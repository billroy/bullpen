"""Versioned, inspectable migrations for workspace ``config.json`` files."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Iterable

from server.persistence import read_json, write_json


CONFIG_SCHEMA_VERSION_KEY = "config_schema_version"
CURRENT_CONFIG_SCHEMA_VERSION = 1
LEGACY_AGENT_TIMEOUT_SECONDS = 600

_SCAN_PRUNE_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}


class ConfigMigrationError(ValueError):
    """Raised when a workspace config cannot be migrated safely."""


def _config_version(config):
    raw = config.get(CONFIG_SCHEMA_VERSION_KEY, 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ConfigMigrationError(
            f"{CONFIG_SCHEMA_VERSION_KEY} must be a non-negative integer"
        )
    if raw > CURRENT_CONFIG_SCHEMA_VERSION:
        raise ConfigMigrationError(
            f"config schema version {raw} is newer than supported "
            f"({CURRENT_CONFIG_SCHEMA_VERSION})"
        )
    return raw


def plan_config_migration(config, *, default_agent_timeout_seconds):
    """Return the deterministic migration plan for one parsed config.

    Schema version 0 persisted the then-global 600-second agent timeout into
    every workspace. Version 1 removes that legacy value so the workspace
    inherits the application default. Non-600 values are treated as
    intentional overrides and preserved. Once a config is at version 1, an
    explicit 600-second value is likewise preserved.
    """
    if not isinstance(config, dict):
        raise ConfigMigrationError("workspace config must be a JSON object")

    from_version = _config_version(config)
    updated = copy.deepcopy(config)
    changes = []
    version = from_version

    if version == 0:
        if updated.get("agent_timeout_seconds") == LEGACY_AGENT_TIMEOUT_SECONDS:
            updated.pop("agent_timeout_seconds")
            changes.append(
                {
                    "key": "agent_timeout_seconds",
                    "from": LEGACY_AGENT_TIMEOUT_SECONDS,
                    "to": None,
                    "effective": default_agent_timeout_seconds,
                    "reason": (
                        "remove persisted legacy default and inherit "
                        "application default"
                    ),
                }
            )

        updated[CONFIG_SCHEMA_VERSION_KEY] = 1
        changes.append(
            {
                "key": CONFIG_SCHEMA_VERSION_KEY,
                "from": None,
                "to": 1,
                "reason": "record completed workspace config migrations",
            }
        )
        version = 1

    return {
        "from_version": from_version,
        "to_version": version,
        "needs_migration": updated != config,
        "changes": changes,
        "updated_config": updated,
    }


def migrate_workspace_config(
    config_path,
    *,
    apply,
    default_agent_timeout_seconds,
):
    """Plan or apply migrations for one workspace config path."""
    config = read_json(config_path)
    plan = plan_config_migration(
        config,
        default_agent_timeout_seconds=default_agent_timeout_seconds,
    )
    if apply and plan["needs_migration"]:
        write_json(config_path, plan["updated_config"])
    return plan


def _load_registry_paths(registry_path):
    if not registry_path or not os.path.exists(registry_path):
        return []
    with open(registry_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        projects = data.get("projects", [])
    elif isinstance(data, list):
        projects = data
    else:
        raise ConfigMigrationError("workspace registry must be a JSON object or list")
    if not isinstance(projects, list):
        raise ConfigMigrationError("workspace registry projects must be a list")
    return [
        item.get("path")
        for item in projects
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]


def _discover_scan_root(scan_root):
    root = os.path.realpath(os.path.abspath(os.path.expanduser(scan_root)))
    if not os.path.isdir(root):
        raise ConfigMigrationError(f"scan root directory not found: {root}")

    workspaces = []
    for current, dirnames, _filenames in os.walk(root, followlinks=False):
        bp_dir = os.path.join(current, ".bullpen")
        if os.path.isfile(os.path.join(bp_dir, "config.json")):
            workspaces.append(current)
            if ".bullpen" in dirnames:
                dirnames.remove(".bullpen")
        dirnames[:] = [name for name in dirnames if name not in _SCAN_PRUNE_DIRS]
    return workspaces


def discover_workspace_configs(*, registry_path=None, scan_roots: Iterable[str] = ()):
    """Discover unique workspace config paths and record their sources."""
    candidates = {}

    def _add(workspace, source):
        if not workspace:
            return
        resolved = os.path.realpath(os.path.abspath(os.path.expanduser(workspace)))
        candidates.setdefault(resolved, set()).add(source)

    for workspace in _load_registry_paths(registry_path):
        _add(workspace, "registry")
    for scan_root in scan_roots:
        source = f"scan:{os.path.realpath(os.path.abspath(os.path.expanduser(scan_root)))}"
        for workspace in _discover_scan_root(scan_root):
            _add(workspace, source)

    return [
        {
            "workspace": workspace,
            "config_path": os.path.join(workspace, ".bullpen", "config.json"),
            "sources": sorted(sources),
        }
        for workspace, sources in sorted(candidates.items())
    ]


def migrate_workspace_configs(
    *,
    registry_path=None,
    scan_roots: Iterable[str] = (),
    apply=False,
    default_agent_timeout_seconds,
):
    """Plan or apply config migrations across discovered workspaces."""
    scan_roots = list(scan_roots)
    records = []
    discovery_error = None
    try:
        discovered = discover_workspace_configs(
            registry_path=registry_path,
            scan_roots=scan_roots,
        )
    except (ConfigMigrationError, json.JSONDecodeError, OSError) as exc:
        discovered = []
        discovery_error = str(exc)

    for item in discovered:
        record = dict(item)
        workspace = item["workspace"]
        config_path = item["config_path"]
        if not os.path.isdir(workspace):
            record.update(
                {
                    "status": "missing_workspace",
                    "error": "workspace directory not found",
                }
            )
        elif not os.path.isfile(config_path):
            record.update(
                {"status": "missing_config", "error": "config.json not found"}
            )
        else:
            try:
                plan = migrate_workspace_config(
                    config_path,
                    apply=apply,
                    default_agent_timeout_seconds=default_agent_timeout_seconds,
                )
                if not plan["needs_migration"]:
                    status = "current"
                elif apply:
                    status = "migrated"
                else:
                    status = "would_migrate"
                record.update(
                    {
                        "status": status,
                        "from_version": plan["from_version"],
                        "to_version": plan["to_version"],
                        "changes": plan["changes"],
                    }
                )
            except (ConfigMigrationError, json.JSONDecodeError, OSError) as exc:
                record.update({"status": "error", "error": str(exc)})
        records.append(record)

    summary = {
        "total": len(records),
        "would_migrate": sum(item["status"] == "would_migrate" for item in records),
        "migrated": sum(item["status"] == "migrated" for item in records),
        "current": sum(item["status"] == "current" for item in records),
        "errors": sum(
            item["status"] in {"error", "missing_workspace", "missing_config"}
            for item in records
        ),
    }
    return {
        "mode": "apply" if apply else "dry-run",
        "config_schema_version": CURRENT_CONFIG_SCHEMA_VERSION,
        "default_agent_timeout_seconds": default_agent_timeout_seconds,
        "registry_path": registry_path,
        "scan_roots": list(scan_roots),
        "discovery_error": discovery_error,
        "summary": summary,
        "workspaces": records,
    }


def format_migration_report(report):
    """Render a concise, human-readable migration report."""
    summary = report["summary"]
    lines = [
        f"Workspace config migration ({report['mode']})",
        f"Schema: {report['config_schema_version']}",
        f"Inherited agent timeout: {report['default_agent_timeout_seconds']} seconds",
        (
            "Summary: "
            f"{summary['total']} total, "
            f"{summary['would_migrate']} would migrate, "
            f"{summary['migrated']} migrated, "
            f"{summary['current']} current, "
            f"{summary['errors']} errors"
        ),
    ]
    if report.get("discovery_error"):
        lines.append(f"Discovery error: {report['discovery_error']}")
    for item in report["workspaces"]:
        lines.append(f"[{item['status']}] {item['workspace']}")
        for change in item.get("changes", []):
            destination = change["to"]
            if change["key"] == "agent_timeout_seconds" and destination is None:
                destination = f"inherited ({change['effective']})"
            lines.append(f"  {change['key']}: {change['from']} -> {destination}")
        if item.get("error"):
            lines.append(f"  error: {item['error']}")
    return "\n".join(lines)
