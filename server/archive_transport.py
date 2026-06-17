"""Workspace archive import/export helpers."""

import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from io import BytesIO

from server import mcp_auth
from server.global_settings import load_global_settings
from server.init import init_workspace
from server.persistence import ensure_within, read_json


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


def write_runtime_config(app, ws, preferred_token=None):
    manager = app.config["manager"]
    token = mcp_auth.ensure_workspace_runtime_config(
        ws.bp_dir,
        host=app.config.get("host", "127.0.0.1"),
        port=app.config.get("port", 5000),
        disallowed_tokens=mcp_auth.workspace_token_set(manager.all_workspaces(), exclude_bp_dir=ws.bp_dir),
        preferred_token=preferred_token,
    )
    app.config.setdefault("mcp_tokens_by_workspace", {})
    app.config["mcp_tokens_by_workspace"][ws.id] = token


def replace_workspace_bp_dir(app, socketio, ws, source_bp_dir):
    manager = app.config["manager"]
    bp_dir = ws.bp_dir
    previous_token = mcp_auth.read_workspace_mcp_token(bp_dir)
    if os.path.exists(bp_dir):
        shutil.rmtree(bp_dir)
    shutil.copytree(source_bp_dir, bp_dir)
    init_workspace(ws.path)
    write_runtime_config(app, ws, preferred_token=previous_token)
    from server.app import load_state, reconcile

    reconcile(bp_dir)
    state = load_state(bp_dir, ws.path, workspace_display=ws.name)
    state["workspaceId"] = ws.id
    state["globalSettings"] = load_global_settings(manager.global_dir)
    socketio.emit("state:init", state, to=ws.id)
    socketio.emit("files:changed", {"workspaceId": ws.id}, to=ws.id)


def import_workspace_archive(app, socketio, ws, fileobj):
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            with tempfile.TemporaryDirectory(prefix="bullpen_import_") as tmp_dir:
                safe_extract_zip(zf, tmp_dir)
                payload_root = workspace_payload_root(tmp_dir)
                if not payload_root:
                    raise ValueError("Archive does not contain a workspace .bullpen payload")
                replace_workspace_bp_dir(app, socketio, ws, payload_root)
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip file") from exc
    return {"ok": True, "imported": 1, "workspaceId": ws.id}


def import_all_archive(app, socketio, fileobj):
    manager = app.config["manager"]
    imported = 0
    try:
        with zipfile.ZipFile(fileobj, "r") as zf:
            with tempfile.TemporaryDirectory(prefix="bullpen_import_all_") as tmp_dir:
                safe_extract_zip(zf, tmp_dir)
                workspaces_dir = os.path.join(tmp_dir, "workspaces")
                if not os.path.isdir(workspaces_dir):
                    raise ValueError("Archive does not contain a workspaces/ directory")
                for ws in manager.all_workspaces():
                    candidate = os.path.join(workspaces_dir, ws.id)
                    if not os.path.isdir(candidate):
                        continue
                    payload_root = workspace_payload_root(candidate)
                    if not payload_root:
                        continue
                    replace_workspace_bp_dir(app, socketio, ws, payload_root)
                    imported += 1
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid zip file") from exc
    if imported == 0:
        raise ValueError("No matching workspaces found in archive")
    return {"ok": True, "imported": imported}
