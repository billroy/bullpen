"""Workspace file browsing helpers."""

import mimetypes
import os
import subprocess

from server.persistence import atomic_write, ensure_within

MAX_BINARY_FILE_BYTES = 50 * 1024 * 1024


class FileBrowserError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def is_textual_mime(mime):
    if not mime:
        return True
    if mime.startswith("text/"):
        return True
    textual_application_prefixes = (
        "application/json",
        "application/ld+json",
        "application/xml",
        "application/javascript",
        "application/x-javascript",
        "application/ecmascript",
        "application/x-sh",
        "application/x-shellscript",
    )
    return any(
        mime == prefix or mime.startswith(prefix + ";")
        for prefix in textual_application_prefixes
    )


def workspace_file_path(workspace, filepath):
    full_path = os.path.join(workspace, filepath)
    try:
        return ensure_within(full_path, workspace)
    except ValueError as e:
        raise FileBrowserError(str(e), status=403)


def build_file_tree(workspace):
    """Build file tree excluding .git, node_modules, gitignored paths."""
    excluded = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", "venv"}

    gitignored = set()
    try:
        result = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
            capture_output=True, text=True, cwd=workspace, timeout=5,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if line:
                    gitignored.add(line.rstrip("/"))
        gitignored.discard(".bullpen")
    except Exception:
        pass

    max_depth = 20
    max_nodes = 10_000
    node_count = [0]

    def walk(path, rel="", depth=0):
        entries = []
        if depth >= max_depth or node_count[0] >= max_nodes:
            return entries
        try:
            items = sorted(os.listdir(path))
        except PermissionError:
            return entries

        for name in items:
            if node_count[0] >= max_nodes:
                break
            if name.startswith(".") and name in excluded:
                continue
            rel_path = os.path.join(rel, name) if rel else name
            if rel_path in gitignored or name in excluded:
                continue
            full = os.path.join(path, name)
            node_count[0] += 1
            if os.path.islink(full):
                if os.path.isdir(full):
                    continue
                entries.append({"name": name, "path": rel_path, "type": "file"})
            elif os.path.isdir(full):
                children = walk(full, rel_path, depth + 1)
                entries.append({"name": name, "path": rel_path, "type": "dir", "children": children})
            else:
                entries.append({"name": name, "path": rel_path, "type": "file"})
        return entries

    return walk(workspace)


def read_text_file(workspace, filepath):
    full_path = workspace_file_path(workspace, filepath)
    if not os.path.isfile(full_path):
        raise FileBrowserError("File not found", status=404)
    mime, _ = mimetypes.guess_type(full_path)
    if mime and not is_textual_mime(mime):
        raise FileBrowserError("File is not text", status=415)
    with open(full_path, "r", errors="replace") as handle:
        content = handle.read()
    return {"path": filepath, "content": content, "mime": mime or "text/plain"}


def read_binary_file(workspace, filepath):
    full_path = workspace_file_path(workspace, filepath)
    if not os.path.isfile(full_path):
        raise FileBrowserError("File not found", status=404)
    size = os.path.getsize(full_path)
    if size > MAX_BINARY_FILE_BYTES:
        raise FileBrowserError("File too large for socket transfer", status=413)
    mime, _ = mimetypes.guess_type(full_path)
    with open(full_path, "rb") as handle:
        content = handle.read()
    return {
        "path": filepath,
        "data": content,
        "mime": mime or "application/octet-stream",
        "size": size,
    }


def file_exists(workspace, filepath):
    full_path = workspace_file_path(workspace, filepath)
    return os.path.exists(full_path)


def create_directory(workspace, dirpath):
    normalized = str(dirpath or "").strip().strip("/\\")
    if not normalized:
        raise FileBrowserError("Folder path is required", status=400)
    full_path = workspace_file_path(workspace, normalized)
    if os.path.exists(full_path):
        message = "Folder already exists" if os.path.isdir(full_path) else "Path already exists"
        raise FileBrowserError(message, status=409)
    try:
        os.makedirs(full_path, exist_ok=False)
    except OSError as e:
        raise FileBrowserError(f"Failed to create folder: {e}", status=400)
    return {"ok": True, "path": normalized}


def write_text_file(workspace, filepath, content, *, create=False):
    full_path = workspace_file_path(workspace, filepath)
    if len(content) > 1_000_000:
        raise FileBrowserError("File too large (max 1MB)", status=400)
    if create and os.path.exists(full_path):
        raise FileBrowserError("File already exists", status=409)
    try:
        content.encode("utf-8")
    except UnicodeEncodeError:
        raise FileBrowserError("Binary files cannot be edited", status=400)
    atomic_write(full_path, content)
    return {"ok": True, "path": filepath}
