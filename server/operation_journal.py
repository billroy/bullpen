"""Recoverable journal for compound JSON-file mutations.

Prepared operations roll back to their recorded snapshots after an exception or
process restart. Committed operations are only awaiting journal cleanup and are
never rolled back.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import uuid
from typing import Any, Iterable

from server.persistence import ensure_within, read_json, write_json


OPERATIONS_DIRNAME = "operations"


def _operations_dir(owner_bp_dir: str) -> str:
    return os.path.join(owner_bp_dir, OPERATIONS_DIRNAME)


def _allowed_path(path: str, allowed_roots: Iterable[str]) -> str:
    last_error = None
    for root in allowed_roots:
        try:
            return ensure_within(path, root)
        except ValueError as exc:
            last_error = exc
    raise ValueError(f"Operation path is outside registered workspaces: {path}") from last_error


def begin_operation(
    owner_bp_dir: str,
    *,
    kind: str,
    restore_files: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Persist rollback snapshots before the first compound mutation."""
    operation_id = str(uuid.uuid4())
    path = os.path.join(_operations_dir(owner_bp_dir), f"{operation_id}.json")
    write_json(path, {
        "id": operation_id,
        "kind": str(kind),
        "status": "prepared",
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "restore_files": restore_files,
        "metadata": metadata or {},
    })
    return path


def mark_operation_committed(path: str) -> None:
    """Durably mark an operation complete before removing its journal."""
    record = read_json(path)
    record["status"] = "committed"
    record["committed_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    write_json(path, record)


def finish_operation(path: str) -> None:
    """Best-effort cleanup after the committed marker is durable."""
    try:
        os.unlink(path)
    except OSError:
        pass


def rollback_operation(path: str, allowed_roots: Iterable[str]) -> None:
    """Restore a prepared operation. The journal remains if restoration fails."""
    record = read_json(path)
    if record.get("status") == "committed":
        finish_operation(path)
        return
    roots = [os.path.abspath(root) for root in allowed_roots]
    for entry in record.get("restore_files", []):
        if not isinstance(entry, dict):
            continue
        target = _allowed_path(str(entry.get("path") or ""), roots)
        content = entry.get("content")
        if content is None:
            try:
                os.unlink(target)
            except FileNotFoundError:
                pass
        else:
            write_json(target, content)
    finish_operation(path)


def recover_pending_operations(bp_dirs: Iterable[str]) -> list[str]:
    """Recover every registered workspace journal, newest first.

    Newest-first ordering makes nested member journals settle before an older
    enclosing group journal restores its all-or-nothing snapshot.
    """
    roots = [os.path.abspath(bp_dir) for bp_dir in bp_dirs]
    journals = []
    for bp_dir in roots:
        directory = _operations_dir(bp_dir)
        if not os.path.isdir(directory):
            continue
        for name in os.listdir(directory):
            if not name.endswith(".json"):
                continue
            path = os.path.join(directory, name)
            try:
                modified = os.path.getmtime(path)
            except OSError:
                continue
            journals.append((modified, path))
    recovered = []
    for _modified, path in sorted(journals, reverse=True):
        rollback_operation(path, roots)
        recovered.append(path)
    return recovered
