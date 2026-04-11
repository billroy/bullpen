"""Cross-workspace worker transfer (copy/move)."""

import os

from server.locks import write_lock
from server.persistence import read_json, write_json
from server.profiles import get_profile, create_profile


# Fields to copy from source worker to destination.
_TRANSFERABLE_FIELDS = (
    "profile", "name", "agent", "model", "activation", "disposition",
    "watch_column", "expertise_prompt", "max_retries", "use_worktree",
    "auto_commit", "auto_pr", "trigger_time", "trigger_interval_minutes",
    "trigger_every_day",
)


class TransferError(Exception):
    """Raised when a transfer cannot proceed."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def transfer_worker(manager, source_workspace_id, source_slot, dest_workspace_id,
                    dest_slot, mode, copy_profile=False):
    """Copy or move a worker between workspaces.

    Returns dict with ``ok``, ``dest_slot``, ``profile_copied``, and ``warnings``.
    Raises ``TransferError`` on validation failure.
    """
    if source_workspace_id == dest_workspace_id:
        raise TransferError("use duplicate for same-workspace copy", 400)

    if mode not in ("copy", "move"):
        raise TransferError("mode must be 'copy' or 'move'", 400)

    # Resolve workspaces — activate from registry if not already loaded
    src_ws = manager.get_or_activate(source_workspace_id)
    if src_ws is None:
        raise TransferError("source workspace not found", 404)

    dst_ws = manager.get_or_activate(dest_workspace_id)
    if dst_ws is None:
        raise TransferError("destination workspace not found", 404)

    warnings = []

    with write_lock:
        # Load source layout
        src_layout = read_json(os.path.join(src_ws.bp_dir, "layout.json"))
        src_slots = src_layout.get("slots", [])

        # Validate source slot
        if source_slot is None or source_slot < 0 or source_slot >= len(src_slots):
            raise TransferError("source slot is empty", 400)

        source_worker = src_slots[source_slot]
        if source_worker is None:
            raise TransferError("source slot is empty", 400)

        # Busy worker cannot be moved
        if mode == "move" and source_worker.get("state") != "idle":
            raise TransferError(
                "worker is busy; copy it instead or wait for it to finish", 409)

        # Load destination layout and config
        dst_layout = read_json(os.path.join(dst_ws.bp_dir, "layout.json"))
        dst_config = read_json(os.path.join(dst_ws.bp_dir, "config.json"))
        dst_slots = dst_layout.get("slots", [])
        dst_rows = dst_config.get("grid", {}).get("rows", 4)
        dst_cols = dst_config.get("grid", {}).get("cols", 6)
        dst_total = dst_rows * dst_cols

        # Extend destination slots array if needed
        while len(dst_slots) < dst_total:
            dst_slots.append(None)
        dst_layout["slots"] = dst_slots

        # Resolve destination slot
        if dest_slot is not None:
            if dest_slot < 0 or dest_slot >= dst_total:
                raise TransferError("destination slot is out of range", 400)
            if dst_slots[dest_slot] is not None:
                raise TransferError("destination slot is occupied", 409)
            target_slot = dest_slot
        else:
            # Auto-assign first empty slot
            target_slot = None
            for i in range(dst_total):
                if dst_slots[i] is None:
                    target_slot = i
                    break
            if target_slot is None:
                raise TransferError("destination grid is full", 409)

        # Generate unique name in destination
        existing_names = {s["name"] for s in dst_slots if s}
        candidate = source_worker["name"]
        if candidate in existing_names:
            base = candidate
            suffix = 2
            candidate = f"{base} copy"
            while candidate in existing_names:
                candidate = f"{base} copy {suffix}"
                suffix += 1

        # Build the cloned worker with runtime fields reset
        clone = {
            "row": target_slot // dst_cols,
            "col": target_slot % dst_cols,
            "state": "idle",
            "task_queue": [],
            "last_trigger_time": None,
            "paused": False,
            "name": candidate,
        }
        for field in _TRANSFERABLE_FIELDS:
            if field == "name":
                continue  # already set with dedup
            if field in source_worker:
                clone[field] = source_worker[field]

        # --- Warnings for workspace-local references ---

        # disposition: worker:<name> may not resolve in destination
        disposition = clone.get("disposition", "")
        if disposition.startswith("worker:") or disposition.startswith("pass:"):
            warnings.append(
                f"disposition '{disposition}' references a workspace-local "
                f"target and may not resolve in the destination"
            )

        # watch_column: check if destination has the column
        watch_col = clone.get("watch_column")
        if watch_col:
            dst_col_keys = {c["key"] for c in dst_config.get("columns", [])}
            if watch_col not in dst_col_keys:
                warnings.append(
                    f"watch_column '{watch_col}' does not exist in destination workspace"
                )

        # --- Profile handling ---
        profile_copied = False
        profile_id = clone.get("profile")
        if profile_id and copy_profile:
            src_profile = get_profile(src_ws.bp_dir, profile_id)
            if src_profile:
                dst_profile = get_profile(dst_ws.bp_dir, profile_id)
                if dst_profile is None:
                    # Copy profile to destination (strip workspaceId if present)
                    profile_data = dict(src_profile)
                    profile_data.pop("workspaceId", None)
                    create_profile(dst_ws.bp_dir, profile_data)
                    profile_copied = True
                else:
                    warnings.append(
                        f"profile '{profile_id}' already exists in destination; skipped"
                    )
            else:
                warnings.append(
                    f"profile '{profile_id}' not found in source workspace"
                )
        elif profile_id and not copy_profile:
            # Check if profile exists in destination; warn if not
            src_profile = get_profile(src_ws.bp_dir, profile_id)
            if src_profile:
                dst_profile = get_profile(dst_ws.bp_dir, profile_id)
                if dst_profile is None:
                    warnings.append(
                        f"profile '{profile_id}' does not exist in destination "
                        f"and was not copied"
                    )

        # --- Write destination first (atomic move safety) ---
        dst_slots[target_slot] = clone
        write_json(os.path.join(dst_ws.bp_dir, "layout.json"), dst_layout)

        # --- Clear source on move ---
        if mode == "move":
            src_slots[source_slot] = None
            write_json(os.path.join(src_ws.bp_dir, "layout.json"), src_layout)

    return {
        "ok": True,
        "dest_slot": target_slot,
        "profile_copied": profile_copied,
        "warnings": warnings,
    }
