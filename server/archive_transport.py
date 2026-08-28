"""Workspace archive import/export helpers."""

import json
import os
import re
import shutil
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from server.init import init_workspace
from server.persistence import ensure_within, read_json, write_json


MAX_IMPORT_ARCHIVE_BYTES = 200 * 1024 * 1024
MAX_IMPORT_ARCHIVE_FILES = 1000
MAX_IMPORT_COMPRESSION_RATIO = 100
NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".tar.gz",
    ".tbz",
    ".tbz2",
    ".tar.bz2",
    ".txz",
    ".tar.xz",
    ".gz",
    ".bz2",
    ".xz",
    ".7z",
    ".rar",
)


def portable_config(config):
    safe = dict(config or {})
    for key in ("server_host", "server_port", "mcp_token", "deploy_label"):
        safe.pop(key, None)
    return safe


def workspace_export_meta(ws):
    # Do not expose host filesystem paths in export manifests.
    return {"id": ws.id, "name": ws.name}


def export_workspace_zip_bytes(ws):
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if os.path.isdir(ws.bp_dir):
            for root, _dirs, files in os.walk(ws.bp_dir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, ws.path).replace(os.sep, "/")
                    if rel_path == ".bullpen/config.json":
                        config = portable_config(read_json(full_path))
                        zf.writestr(rel_path, json.dumps(config, indent=2))
                        continue
                    zf.write(full_path, rel_path)
    mem.seek(0)
    return mem


def export_all_zip_bytes(manager):
    mem = BytesIO()
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for ws in manager.all_workspaces():
            if not os.path.isdir(ws.bp_dir):
                continue
            for root, _dirs, files in os.walk(ws.bp_dir):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, ws.bp_dir).replace(os.sep, "/")
                    arcname = f"workspaces/{ws.id}/.bullpen/{rel_path}"
                    if rel_path == "config.json":
                        config = portable_config(read_json(full_path))
                        zf.writestr(arcname, json.dumps(config, indent=2))
                        continue
                    zf.write(full_path, arcname)
        manifest = {
            "schema": "bullpen-export-all-v1",
            "created_at": created_at,
            "workspaces": [workspace_export_meta(ws) for ws in manager.all_workspaces()],
        }
        zf.writestr("bullpen-export.json", json.dumps(manifest, indent=2))
    mem.seek(0)
    return mem


def _normalized_zip_names(zf):
    return {
        (info.filename or "").replace("\\", "/")
        for info in zf.infolist()
        if info.filename and not info.filename.endswith("/")
    }


def detect_import_archive_type(fileobj):
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            names = _normalized_zip_names(zf)
            if "bento.json" in names:
                return {"ok": True, "type": "bento"}
            if "bullpen-export.json" in names:
                try:
                    manifest = json.loads(zf.read("bullpen-export.json"))
                except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                    raise ValueError("Archive contains invalid Bullpen export manifest") from exc
                if isinstance(manifest, dict) and manifest.get("schema") == "bullpen-export-all-v1":
                    return {"ok": True, "type": "all", "schema": manifest.get("schema")}
                raise ValueError("Archive contains unsupported Bullpen export manifest")
            if any(name.startswith("workspaces/") and "/.bullpen/" in name for name in names):
                return {"ok": True, "type": "all", "legacy": True}
            if any(name.startswith(".bullpen/") for name in names) or "config.json" in names:
                return {"ok": True, "type": "workspace"}
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip file") from exc
    finally:
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)
    raise ValueError("Archive type could not be detected")


def safe_extract_zip(zf, target_dir):
    total_size = 0
    total_compressed_size = 0
    file_count = 0
    for info in zf.infolist():
        name = (info.filename or "").replace("\\", "/")
        if not name or name.endswith("/"):
            continue
        file_count += 1
        if file_count > MAX_IMPORT_ARCHIVE_FILES:
            raise ValueError("Archive contains too many files")
        parts = [p for p in name.split("/") if p not in ("", ".")]
        if any(p == ".." for p in parts):
            raise ValueError("Archive contains invalid relative paths")
        if parts and parts[0].endswith(":"):
            raise ValueError("Archive contains invalid absolute paths")
        lower_name = "/".join(parts).lower()
        if any(lower_name.endswith(suffix) for suffix in NESTED_ARCHIVE_SUFFIXES):
            raise ValueError("Archive contains nested archive files")
        compressed_size = max(0, int(info.compress_size or 0))
        total_compressed_size += max(1, compressed_size)
        total_size += max(0, int(info.file_size or 0))
        if total_size > MAX_IMPORT_ARCHIVE_BYTES:
            raise ValueError("Archive is too large")
        if info.file_size > max(1, compressed_size) * MAX_IMPORT_COMPRESSION_RATIO:
            raise ValueError("Archive contains highly compressed entries")
        if total_size > total_compressed_size * MAX_IMPORT_COMPRESSION_RATIO:
            raise ValueError("Archive compression ratio is too high")
        dest_path = os.path.join(target_dir, *parts)
        ensure_within(dest_path, target_dir)
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with zf.open(info, "r") as src, open(dest_path, "wb") as dst:
            shutil.copyfileobj(src, dst)


def workspace_payload_root(extracted_root):
    explicit = os.path.join(extracted_root, ".bullpen")
    if os.path.isdir(explicit):
        return explicit
    if os.path.exists(os.path.join(extracted_root, "config.json")):
        return extracted_root
    return None


def _read_workspace_json_object(payload_root, filename, *, required=True):
    path = os.path.join(payload_root, filename)
    if not os.path.isfile(path):
        if required:
            raise ValueError(f"Workspace archive is missing {filename}")
        return {}
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Workspace archive contains invalid {filename}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Workspace archive contains invalid {filename}")
    return value


def _workspace_archive_summary(payload_root):
    config = _read_workspace_json_object(payload_root, "config.json")
    layout = _read_workspace_json_object(payload_root, "layout.json", required=False)
    slots = layout.get("slots") or []
    if not isinstance(slots, list):
        raise ValueError("Workspace archive contains invalid layout.json")
    tasks_dir = os.path.join(payload_root, "tasks")
    archive_dir = os.path.join(tasks_dir, "archive")
    profiles_dir = os.path.join(payload_root, "profiles")

    def _count_files(directory, suffix):
        if not os.path.isdir(directory):
            return 0
        return sum(
            1
            for name in os.listdir(directory)
            if name.endswith(suffix) and os.path.isfile(os.path.join(directory, name))
        )

    proposed_name = str(config.get("name") or "Imported project").strip() or "Imported project"
    return {
        "proposed_name": proposed_name,
        "proposed_slug": project_slug(proposed_name),
        "workers": sum(1 for slot in (slots or []) if isinstance(slot, dict)),
        "tickets": _count_files(tasks_dir, ".md"),
        "archived_tickets": _count_files(archive_dir, ".md"),
        "profiles": _count_files(profiles_dir, ".json"),
        "includes_project_files": False,
    }


def preview_workspace_archive(fileobj):
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            with tempfile.TemporaryDirectory(prefix="bullpen_import_preview_") as tmp_dir:
                safe_extract_zip(zf, tmp_dir)
                payload_root = workspace_payload_root(tmp_dir)
                if not payload_root:
                    raise ValueError("Archive does not contain a workspace .bullpen payload")
                return _workspace_archive_summary(payload_root)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip file") from exc
    finally:
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)


def validate_project_name(name):
    value = str(name or "").strip()
    if not value:
        raise ValueError("Project name is required")
    if len(value) > 100:
        raise ValueError("Project name must be 100 characters or fewer")
    if any(ord(char) < 32 for char in value) or any(char in value for char in ("/", "\\")):
        raise ValueError("Project name contains invalid characters")
    return value


def project_slug(name):
    value = unicodedata.normalize("NFKD", validate_project_name(name))
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:80].rstrip("-") or "imported-project"


def _quarantine_imported_workspace(bp_dir, display_name):
    config_path = os.path.join(bp_dir, "config.json")
    config = portable_config(_read_workspace_json_object(bp_dir, "config.json"))
    config["name"] = display_name
    config["worker_automation_paused"] = True
    write_json(config_path, config)

    layout_path = os.path.join(bp_dir, "layout.json")
    layout = _read_workspace_json_object(bp_dir, "layout.json", required=False)
    slots = layout.get("slots")
    if slots is not None and not isinstance(slots, list):
        raise ValueError("Workspace archive contains invalid layout.json")
    if isinstance(slots, list):
        for worker in slots:
            if not isinstance(worker, dict):
                continue
            worker["state"] = "idle"
            worker["task_queue"] = []
            worker["paused"] = True
            worker.pop("started_at", None)
        write_json(layout_path, layout)


def import_workspace_archive_create(app, fileobj, *, name, parent_dir):
    manager = app.config["manager"]
    display_name = validate_project_name(name)
    slug = project_slug(display_name)
    destination = os.path.join(os.path.realpath(parent_dir), slug)
    existing_names = {
        str(project.get("name") or "").strip().casefold()
        for project in manager.list_projects()
    }
    if display_name.casefold() in existing_names:
        raise ValueError(f'A project named "{display_name}" already exists. Choose a different name.')
    if os.path.exists(destination):
        raise ValueError(f"The destination {destination} already exists. Choose a different project name.")

    staging = tempfile.mkdtemp(prefix=f".{slug}.import-", dir=parent_dir)
    created_destination = False
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            with tempfile.TemporaryDirectory(prefix="bullpen_import_create_") as tmp_dir:
                safe_extract_zip(zf, tmp_dir)
                payload_root = workspace_payload_root(tmp_dir)
                if not payload_root:
                    raise ValueError("Archive does not contain a workspace .bullpen payload")
                shutil.copytree(payload_root, os.path.join(staging, ".bullpen"))
        _quarantine_imported_workspace(os.path.join(staging, ".bullpen"), display_name)
        init_workspace(staging)
        os.rename(staging, destination)
        created_destination = True
        workspace_id = manager.register_project(destination, name=display_name)
        return {
            "ok": True,
            "imported": 1,
            "workspaceId": workspace_id,
            "name": display_name,
            "path": destination,
        }
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip file") from exc
    except Exception:
        if created_destination and os.path.isdir(destination):
            shutil.rmtree(destination)
        raise
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        if hasattr(fileobj, "seek"):
            fileobj.seek(0)


def import_workspace_archive(app, socketio, ws, fileobj):
    raise ValueError("Workspace archives can only create new projects")


def import_all_archive(app, socketio, fileobj):
    raise ValueError("Multi-project imports are not currently supported")
