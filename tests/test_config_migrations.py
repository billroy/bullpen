"""Tests for versioned workspace config migration and its CLI."""

import json

import bullpen
from server.config_migrations import (
    CURRENT_CONFIG_SCHEMA_VERSION,
    migrate_workspace_configs,
    plan_config_migration,
)
from server.init import DEFAULT_AGENT_TIMEOUT_SECONDS


def _write_config(workspace, config):
    bp_dir = workspace / ".bullpen"
    bp_dir.mkdir(parents=True)
    path = bp_dir / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_plan_removes_legacy_default_and_uses_inheritance():
    plan = plan_config_migration(
        {"name": "legacy", "agent_timeout_seconds": 600},
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert plan["needs_migration"] is True
    assert plan["from_version"] == 0
    assert plan["to_version"] == CURRENT_CONFIG_SCHEMA_VERSION
    assert "agent_timeout_seconds" not in plan["updated_config"]
    assert plan["updated_config"]["config_schema_version"] == 1
    assert plan["changes"][0]["effective"] == 1200


def test_plan_preserves_custom_legacy_override():
    plan = plan_config_migration(
        {"agent_timeout_seconds": 900},
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert plan["updated_config"]["agent_timeout_seconds"] == 900
    assert plan["updated_config"]["config_schema_version"] == 1


def test_plan_preserves_missing_timeout_as_inheritance():
    plan = plan_config_migration(
        {"name": "already inherited"},
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert "agent_timeout_seconds" not in plan["updated_config"]
    assert plan["updated_config"]["config_schema_version"] == 1


def test_current_schema_preserves_explicit_600_override():
    config = {
        "config_schema_version": CURRENT_CONFIG_SCHEMA_VERSION,
        "agent_timeout_seconds": 600,
    }
    plan = plan_config_migration(
        config,
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert plan["needs_migration"] is False
    assert plan["updated_config"] == config


def test_multi_workspace_dry_run_and_apply_are_idempotent(tmp_path):
    registered = tmp_path / "projects" / "registered"
    discovered = tmp_path / "projects" / "unregistered"
    registered_path = _write_config(registered, {"agent_timeout_seconds": 600})
    discovered_path = _write_config(discovered, {"agent_timeout_seconds": 600})

    registry = tmp_path / "global" / "projects.json"
    registry.parent.mkdir()
    registry.write_text(json.dumps({
        "version": 1,
        "projects": [{"id": "one", "path": str(registered), "name": "one"}],
    }))

    dry_run = migrate_workspace_configs(
        registry_path=str(registry),
        scan_roots=[str(tmp_path / "projects")],
        apply=False,
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert dry_run["summary"] == {
        "total": 2,
        "would_migrate": 2,
        "migrated": 0,
        "current": 0,
        "errors": 0,
    }
    assert json.loads(registered_path.read_text())["agent_timeout_seconds"] == 600
    assert json.loads(discovered_path.read_text())["agent_timeout_seconds"] == 600

    applied = migrate_workspace_configs(
        registry_path=str(registry),
        scan_roots=[str(tmp_path / "projects")],
        apply=True,
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )

    assert applied["summary"]["migrated"] == 2
    for path in (registered_path, discovered_path):
        config = json.loads(path.read_text())
        assert config["config_schema_version"] == 1
        assert "agent_timeout_seconds" not in config

    repeated = migrate_workspace_configs(
        registry_path=str(registry),
        scan_roots=[str(tmp_path / "projects")],
        apply=True,
        default_agent_timeout_seconds=DEFAULT_AGENT_TIMEOUT_SECONDS,
    )
    assert repeated["summary"]["current"] == 2
    assert repeated["summary"]["migrated"] == 0


def test_config_migrate_cli_defaults_to_dry_run(tmp_path, capsys):
    workspace = tmp_path / "project"
    config_path = _write_config(workspace, {"agent_timeout_seconds": 600})
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps([
        {"id": "one", "path": str(workspace), "name": "one"},
    ]))

    args = bullpen.parse_args([
        "config-migrate",
        "--registry", str(registry),
        "--output", "json",
    ])
    assert bullpen.run_config_migrate_cli(args) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run"
    assert report["summary"]["would_migrate"] == 1
    assert json.loads(config_path.read_text())["agent_timeout_seconds"] == 600


def test_config_migrate_cli_apply_updates_config(tmp_path, capsys):
    workspace = tmp_path / "project"
    config_path = _write_config(workspace, {"agent_timeout_seconds": 600})
    registry = tmp_path / "projects.json"
    registry.write_text(json.dumps([
        {"id": "one", "path": str(workspace), "name": "one"},
    ]))

    args = bullpen.parse_args([
        "config-migrate",
        "--registry", str(registry),
        "--apply",
        "--output", "json",
    ])
    assert bullpen.run_config_migrate_cli(args) == 0

    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "apply"
    assert report["summary"]["migrated"] == 1
    config = json.loads(config_path.read_text())
    assert config["config_schema_version"] == 1
    assert "agent_timeout_seconds" not in config
