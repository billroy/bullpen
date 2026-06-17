"""Bullpen worker support for Bento packages."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
import os
import re
import zipfile

from server.bento_carrier import BentoCarrierError, inspect_bento
from server.persistence import read_json, write_json
from server.profiles import create_profile, get_profile
from server.worker_types import copy_worker_slot, normalize_layout


BULLPEN_PROFILE_ID = "org.bullpen.share"
BULLPEN_PROFILE_VERSION = "1"
BULLPEN_BENTO_MIMETYPE = "application/vnd.bullpen.bento+zip"


_RUNTIME_FIELDS = {
    "task_queue",
    "state",
    "started_at",
    "last_trigger_time",
    "service_state",
    "output",
    "output_buffer",
    "pid",
    "process_id",
}

_COMMAND_FIELDS = {"command", "cwd", "pre_start", "health_command", "health_url"}
_ENV_FIELDS = {"env"}
_GIT_FIELDS = {"use_worktree", "auto_commit", "auto_pr"}
_NOTIFICATION_FIELDS = {"notification"}
_SERVICE_FIELDS = {
    "command_source",
    "procfile_process",
    "port",
    "ticket_action",
    "startup_grace_seconds",
    "startup_timeout_seconds",
    "health_type",
    "health_interval_seconds",
    "health_timeout_seconds",
    "health_failure_threshold",
    "on_crash",
    "stop_timeout_seconds",
    "log_max_bytes",
}


def worker_export_name(value, fallback="worker"):
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip(" .-_")
    return text[:80] or fallback


def _created_at():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _item_id_for_worker(worker, index):
    name = worker_export_name(worker.get("name"), f"worker-{index + 1}")
    return f"worker.{index + 1}.{name}"


def _worker_payload_path(item_id):
    return f"payload/workers/{item_id}.json"


def _profile_payload_path(profile_id):
    return f"payload/profiles/{worker_export_name(profile_id, 'profile')}.json"


def sanitize_worker_for_package(worker):
    """Return a worker object safe to store in a share package."""
    sanitized = copy_worker_slot(worker, reset_runtime=True)
    for key in _RUNTIME_FIELDS:
        sanitized.pop(key, None)
    if sanitized.get("type") != "value":
        sanitized["task_queue"] = []
        sanitized["state"] = "idle"
    return sanitized


def _approved(approvals, capability):
    if isinstance(approvals, dict):
        return bool(approvals.get(capability))
    if isinstance(approvals, (list, tuple, set)):
        return capability in approvals
    return False


def _strip_fields(worker, fields):
    stripped = []
    for field in sorted(fields):
        if field in worker:
            worker.pop(field, None)
            stripped.append(field)
    return stripped


def sanitize_worker_for_import(worker, *, approvals=None):
    """Return an import-safe worker and a report of stripped capability fields."""
    original = worker if isinstance(worker, dict) else {}
    sanitized = sanitize_worker_for_package(original)
    reports = []

    runtime_fields = sorted(field for field in _RUNTIME_FIELDS if field in original)
    if runtime_fields:
        reports.append({"capability": "runtime", "fields": runtime_fields})

    command_fields = _strip_fields(sanitized, _COMMAND_FIELDS) if not _approved(approvals, "commands") else []
    if command_fields:
        reports.append({"capability": "commands", "fields": command_fields})

    env_fields = _strip_fields(sanitized, _ENV_FIELDS) if not _approved(approvals, "env") else []
    if env_fields:
        reports.append({"capability": "env", "fields": env_fields})

    if sanitized.get("type") == "service" and not _approved(approvals, "services"):
        service_fields = _strip_fields(sanitized, _SERVICE_FIELDS)
        sanitized["activation"] = "manual"
        if service_fields:
            reports.append({"capability": "services", "fields": service_fields})

    notification_fields = (
        _strip_fields(sanitized, _NOTIFICATION_FIELDS)
        if sanitized.get("type") == "notification" and not _approved(approvals, "notifications")
        else []
    )
    if notification_fields:
        reports.append({"capability": "notifications", "fields": notification_fields})

    git_fields = []
    if not _approved(approvals, "git"):
        for field in sorted(_GIT_FIELDS):
            if sanitized.get(field):
                sanitized[field] = False
                git_fields.append(field)
    if git_fields:
        reports.append({"capability": "git", "fields": git_fields})

    return sanitized, reports


def _safe_json(obj):
    return json.dumps(obj, indent=2, sort_keys=True)


def _profile_ids(workers):
    ids = set()
    for worker in workers:
        profile_id = worker.get("profile")
        if isinstance(profile_id, str) and profile_id.strip():
            ids.add(profile_id.strip())
    return sorted(ids)


def build_worker_bento(ws, workers, *, kind, selected_slots=None):
    """Build a Bento package for one worker or a selected worker group."""
    workers = [sanitize_worker_for_package(worker) for worker in workers if isinstance(worker, dict)]
    if not workers:
        raise ValueError("No workers selected")

    selected_slots = list(selected_slots or [])
    created_at = _created_at()
    items = []
    worker_items = []
    attributes = [
        {
            "label": "Bullpen preview",
            "namespace": "org.bullpen.preview",
            "name": "preview",
            "version": "1",
            "data": {
                "kind": kind,
                "worker_count": len(workers),
                "badges": [kind],
            },
        }
    ]

    profile_ids = _profile_ids(workers)
    profiles_written = []
    profile_items = []
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for index, worker in enumerate(workers):
            item_id = _item_id_for_worker(worker, index)
            path = _worker_payload_path(item_id)
            item = {
                "id": item_id,
                "media_type": "application/json",
                "path": path,
                "label": worker.get("name") or "Worker",
                "bullpen_type": "worker",
            }
            items.append(item)
            worker_items.append(item)
            zf.writestr(path, _safe_json(worker))

        for profile_id in profile_ids:
            profile_path = os.path.join(ws.bp_dir, "profiles", f"{profile_id}.json")
            if not os.path.exists(profile_path):
                continue
            payload_path = _profile_payload_path(profile_id)
            profile = read_json(profile_path)
            profile.pop("workspaceId", None)
            item = {
                "id": f"profile.{worker_export_name(profile_id, 'profile')}",
                "media_type": "application/json",
                "path": payload_path,
                "label": profile.get("name") or profile_id,
                "bullpen_type": "profile",
                "profile_id": profile_id,
            }
            items.append(item)
            profile_items.append(item)
            profiles_written.append(profile_id)
            zf.writestr(payload_path, _safe_json(profile))

        manifest = {
            "format": "bento",
            "version": "1",
            "profiles": [
                {
                    "id": BULLPEN_PROFILE_ID,
                    "version": BULLPEN_PROFILE_VERSION,
                    "label": "Bullpen Share",
                }
            ],
            "items": items,
            "attributes": attributes,
            "bullpen": {
                "kind": kind,
                "created_at": created_at,
                "workspace": {"id": ws.id, "name": ws.name},
                "selection": {
                    "slots": selected_slots,
                    "count": len(workers),
                },
                "profiles": {
                    "referenced": profile_ids,
                    "included": profiles_written,
                },
            },
        }
        zf.writestr("bento.json", _safe_json(manifest))

    mem.seek(0)
    return mem


def _read_json_member(zf, path):
    try:
        raw = zf.read(path)
    except KeyError as exc:
        raise BentoCarrierError("Package item payload is missing", "missing-item-path") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BentoCarrierError("Package item payload must be UTF-8 JSON", "invalid-json") from exc


def _load_manifest(fileobj):
    fileobj.seek(0)
    with zipfile.ZipFile(fileobj, "r") as zf:
        manifest = _read_json_member(zf, "bento.json")
    fileobj.seek(0)
    return manifest


def _load_worker_payloads(fileobj, manifest):
    worker_payloads = []
    profile_payloads = []
    with zipfile.ZipFile(fileobj, "r") as zf:
        for item in manifest.get("items") or []:
            if not isinstance(item, dict) or item.get("media_type") != "application/json":
                continue
            item_type = item.get("bullpen_type")
            path = item.get("path")
            if item_type == "worker":
                payload = _read_json_member(zf, path)
                worker_payloads.append((item, payload))
            elif item_type == "profile":
                profile_payloads.append((item, _read_json_member(zf, path)))
    fileobj.seek(0)
    return worker_payloads, profile_payloads


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _worker_capabilities(worker):
    caps = set()
    worker_type = str(worker.get("type") or "ai")
    if worker_type == "shell":
        if worker.get("command"):
            caps.add("commands")
        if worker.get("env"):
            caps.add("env")
        if worker.get("cwd"):
            caps.add("commands")
    elif worker_type == "service":
        for key in ("command", "pre_start", "health_command"):
            if worker.get(key):
                caps.add("commands")
        if worker.get("env"):
            caps.add("env")
        caps.add("services")
    elif worker_type == "notification":
        notification = worker.get("notification")
        if notification:
            caps.add("notifications")
    if worker.get("auto_commit") or worker.get("auto_pr") or worker.get("use_worktree"):
        caps.add("git")
    if worker.get("task_queue") or str(worker.get("state") or "idle") != "idle" or worker.get("started_at"):
        caps.add("queues")
    return sorted(caps)


def _binding_for(worker, package_names, workspace_names, columns):
    bindings = []
    warnings = []

    disposition = str(worker.get("disposition") or "").strip()
    if disposition.startswith("worker:"):
        name = disposition[len("worker:"):].strip()
        bindings.append(_name_binding("disposition", disposition, name, package_names, workspace_names))
    elif disposition.startswith("random:"):
        name = disposition[len("random:"):].strip()
        if name:
            bindings.append(_name_binding("disposition", disposition, name, package_names, workspace_names))
        else:
            bindings.append({"field": "disposition", "value": disposition, "status": "wildcard"})
    elif disposition.startswith("pass:"):
        bindings.append({"field": "disposition", "value": disposition, "status": "directional"})
    elif disposition and disposition not in columns:
        warnings.append(f"disposition '{disposition}' does not match a destination column")

    watch_column = worker.get("watch_column")
    if watch_column and watch_column not in columns:
        warnings.append(f"watch_column '{watch_column}' does not match a destination column")

    return bindings, warnings


def _name_binding(field, value, name, package_names, workspace_names):
    package_matches = package_names.get(name, 0)
    workspace_matches = workspace_names.get(name, 0)
    if package_matches == 1:
        status = "package-local"
    elif package_matches > 1:
        status = "ambiguous-package"
    elif workspace_matches == 1:
        status = "workspace"
    elif workspace_matches > 1:
        status = "ambiguous-workspace"
    else:
        status = "missing"
    return {"field": field, "value": value, "name": name, "status": status}


def _safe_cols(config):
    grid = config.get("grid", {}) if isinstance(config, dict) else {}
    return max(_safe_int(grid.get("cols"), 4), 1)


def _coord_occupied(slots, col, row, *, cols):
    for index, worker in enumerate(slots):
        if not isinstance(worker, dict):
            continue
        worker_col = _safe_int(worker.get("col"), index % cols)
        worker_row = _safe_int(worker.get("row"), index // cols)
        if worker_col == col and worker_row == row:
            return index, worker
    return None


def _placement_state(entries):
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _placement_preview(workers, existing_slots, *, cols):
    requested = []
    conflicts = []
    state_entries = []
    seen = set()
    duplicate_targets = []
    for item_id, worker in workers:
        coord = {"col": _safe_int(worker.get("col"), 0), "row": _safe_int(worker.get("row"), 0)}
        key = (coord["col"], coord["row"])
        if key in seen:
            duplicate_targets.append(coord)
        seen.add(key)
        requested.append({"item_id": item_id, "coord": coord})
        existing = _coord_occupied(existing_slots, coord["col"], coord["row"], cols=cols)
        if existing:
            existing_index, existing_worker = existing
            conflicts.append({"coord": coord, "existing_name": existing_worker.get("name") or "Worker"})
            state_existing = {
                "slot": existing_index,
                "name": str(existing_worker.get("name") or "Worker"),
                "type": str(existing_worker.get("type") or "ai"),
            }
        else:
            state_existing = None
        state_entries.append({
            "item_id": item_id,
            "coord": coord,
            "existing": state_existing,
        })
    status = "conflict" if conflicts or duplicate_targets else "available"
    options = ["preserve"] if status == "available" else ["choose-anchor", "place-right", "place-below", "cancel"]
    return {
        "status": status,
        "state": _placement_state(state_entries),
        "requested": requested,
        "conflicts": conflicts,
        "duplicate_targets": duplicate_targets,
        "options": options,
    }


def _slot_coords(workers):
    coords = []
    for worker in workers:
        coords.append((_safe_int(worker.get("col"), 0), _safe_int(worker.get("row"), 0)))
    if not coords:
        raise BentoCarrierError("Package does not contain workers", "missing-workers")
    return coords


def _occupied_coords(slots, *, cols):
    occupied = set()
    for index, worker in enumerate(slots):
        if not isinstance(worker, dict):
            continue
        occupied.add((
            _safe_int(worker.get("col"), index % cols),
            _safe_int(worker.get("row"), index // cols),
        ))
    return occupied


def _unique_worker_name(base, existing_names, *, allow_blank=False):
    if allow_blank and str(base or "") == "":
        return ""
    base = str(base or "Worker").strip() or "Worker"
    if base not in existing_names:
        existing_names.add(base)
        return base
    candidate = f"{base} copy"
    suffix = 2
    while candidate in existing_names:
        candidate = f"{base} copy {suffix}"
        suffix += 1
    existing_names.add(candidate)
    return candidate


def _candidate_positions(workers, anchor_col, anchor_row):
    coords = _slot_coords(workers)
    min_col = min(col for col, _row in coords)
    min_row = min(row for _col, row in coords)
    positions = []
    for worker in workers:
        col = anchor_col + (_safe_int(worker.get("col"), 0) - min_col)
        row = anchor_row + (_safe_int(worker.get("row"), 0) - min_row)
        positions.append((worker, col, row))
    return positions


def _positions_available(positions, occupied):
    seen = set()
    for _worker, col, row in positions:
        if col < 0 or row < 0:
            return False
        key = (col, row)
        if key in seen or key in occupied:
            return False
        seen.add(key)
    return True


def _resolve_import_positions(workers, existing_slots, *, cols, placement):
    placement = placement if isinstance(placement, dict) else {}
    strategy = str(placement.get("strategy") or "preserve")
    if strategy not in {"preserve", "choose-anchor", "place-right", "place-below"}:
        raise BentoCarrierError("Unsupported worker import placement strategy", "invalid-placement")

    occupied = _occupied_coords(existing_slots, cols=cols)
    coords = _slot_coords(workers)
    min_col = min(col for col, _row in coords)
    min_row = min(row for _col, row in coords)

    if strategy == "preserve":
        positions = [(worker, _safe_int(worker.get("col"), 0), _safe_int(worker.get("row"), 0)) for worker in workers]
        if not _positions_available(positions, occupied):
            raise BentoCarrierError("Placement conflicts with existing workers", "placement-conflict")
        return positions, {"strategy": "preserve", "anchor": {"col": min_col, "row": min_row}}

    if strategy == "choose-anchor":
        anchor = placement.get("anchor") if isinstance(placement.get("anchor"), dict) else {}
        anchor_col = _safe_int(anchor.get("col"), min_col)
        anchor_row = _safe_int(anchor.get("row"), min_row)
        positions = _candidate_positions(workers, anchor_col, anchor_row)
        if not _positions_available(positions, occupied):
            raise BentoCarrierError("Placement conflicts with existing workers", "placement-conflict")
        return positions, {"strategy": strategy, "anchor": {"col": anchor_col, "row": anchor_row}}

    if occupied:
        max_col = max(col for col, _row in occupied)
        max_row = max(row for _col, row in occupied)
        occupied_min_col = min(col for col, _row in occupied)
        occupied_min_row = min(row for _col, row in occupied)
    else:
        max_col = max_row = -1
        occupied_min_col = occupied_min_row = 0

    if strategy == "place-right":
        anchor_col = max_col + 1
        anchor_row = occupied_min_row
        while True:
            positions = _candidate_positions(workers, anchor_col, anchor_row)
            if _positions_available(positions, occupied):
                return positions, {"strategy": strategy, "anchor": {"col": anchor_col, "row": anchor_row}}
            anchor_col += 1

    anchor_col = occupied_min_col
    anchor_row = max_row + 1
    while True:
        positions = _candidate_positions(workers, anchor_col, anchor_row)
        if _positions_available(positions, occupied):
            return positions, {"strategy": strategy, "anchor": {"col": anchor_col, "row": anchor_row}}
        anchor_row += 1


def _local_name_rewrites(workers, rename_map, package_name_counts):
    rewritten = []
    for worker in workers:
        disposition = str(worker.get("disposition") or "")
        for prefix in ("worker:", "random:"):
            if not disposition.startswith(prefix):
                continue
            target = disposition[len(prefix):].strip()
            if package_name_counts.get(target) == 1 and target in rename_map:
                worker["disposition"] = f"{prefix}{rename_map[target]}"
                rewritten.append({
                    "worker": worker.get("name") or "Worker",
                    "field": "disposition",
                    "from": disposition,
                    "to": worker["disposition"],
                })
            break
    return rewritten


def copy_worker_for_fragment(source):
    """Return a pasted/fragment worker copy with runtime state reset."""
    source = source if isinstance(source, dict) else {}
    source_type = str(source.get("type") or "").strip()
    if not source_type and "command" in source:
        source_type = "shell"
    if (source_type or "ai") == "ai":
        worker = {
            key: value
            for key, value in source.items()
            if key in {
                "type", "row", "col", "profile", "name", "agent", "model", "activation",
                "disposition", "watch_column", "expertise_prompt", "trust_mode", "max_retries",
                "use_worktree", "auto_commit", "auto_pr", "trigger_time",
                "trigger_interval_minutes", "trigger_every_day", "last_trigger_time",
                "paused", "task_queue", "state", "color", "avatar",
            }
        }
    else:
        worker = {**source, "type": source_type}
    return copy_worker_slot(worker, reset_runtime=True)


def apply_worker_fragments_to_layout(layout, fragments, *, config, replace=False):
    """Apply worker fragments to a normalized layout and return import metadata."""
    layout = normalize_layout(layout, config=config)
    slots = layout.setdefault("slots", [])
    cols = _safe_cols(config)
    fragments = list(fragments or [])
    if not fragments:
        raise BentoCarrierError("Worker fragment requires at least one worker", "missing-workers")

    seen_targets = set()
    prepared = []
    for fragment in fragments:
        worker = fragment.get("worker") if isinstance(fragment, dict) else None
        coord = fragment.get("coord") if isinstance(fragment, dict) else None
        if not isinstance(worker, dict) or not isinstance(coord, dict):
            raise BentoCarrierError("Worker fragment item is invalid", "invalid-worker-fragment")
        col = _safe_int(coord.get("col"), 0)
        row = _safe_int(coord.get("row"), 0)
        target = (col, row)
        if target in seen_targets:
            raise BentoCarrierError("Worker fragment has duplicate target coordinates", "coordinate_collision")
        seen_targets.add(target)
        occupied = _coord_occupied(slots, col, row, cols=cols)
        if occupied:
            if replace:
                slot_index, _existing = occupied
                slots[slot_index] = None
            else:
                raise BentoCarrierError("Coordinate already occupied", "coordinate_collision")
        prepared.append((worker, col, row))

    existing_names = {
        worker.get("name")
        for worker in slots
        if isinstance(worker, dict) and worker.get("name")
    }
    package_name_counts = {}
    for worker, _col, _row in prepared:
        name = worker.get("name")
        if name:
            package_name_counts[name] = package_name_counts.get(name, 0) + 1

    rename_map = {}
    renamed = []
    workers = []
    for worker, col, row in prepared:
        worker = copy_worker_slot(worker, reset_runtime=True)
        original = worker.get("name") or ""
        allow_blank = worker.get("type") == "value" and original == ""
        final = _unique_worker_name(original, existing_names, allow_blank=allow_blank)
        if final != original:
            rename_map[original or "Worker"] = final
            renamed.append({"from": original or "Worker", "to": final})
        worker["name"] = final
        worker["col"] = col
        worker["row"] = row
        workers.append(worker)

    rewritten = _local_name_rewrites(workers, rename_map, package_name_counts)
    added_slots = []
    for worker in workers:
        while len(slots) and slots[-1] is None:
            slots.pop()
        slot_index = None
        for index, existing in enumerate(slots):
            if existing is None:
                slot_index = index
                break
        if slot_index is None:
            slot_index = len(slots)
            slots.append(None)
        slots[slot_index] = worker
        added_slots.append(slot_index)

    layout = normalize_layout(layout, config=config)
    return {
        "layout": layout,
        "slots": added_slots,
        "renamed": renamed,
        "rewritten_bindings": rewritten,
    }


def apply_worker_bento(fileobj, *, bp_dir, placement=None, mode="merge", approvals=None):
    """Import sanitized workers from a Bullpen Bento package into a workspace."""
    if mode not in {"merge", "add-only"}:
        raise BentoCarrierError("Unsupported worker import mode", "invalid-import-mode")

    carrier = inspect_bento(fileobj)
    if not any(profile.get("id") == BULLPEN_PROFILE_ID for profile in carrier.get("profiles", [])):
        raise BentoCarrierError("Package does not include the Bullpen share profile", "unsupported-profile")

    manifest = _load_manifest(fileobj)
    worker_payloads, profile_payloads = _load_worker_payloads(fileobj, manifest)
    workers = []
    placement_workers = []
    sanitized_reports = []
    warnings = []
    for item, worker in worker_payloads:
        if not isinstance(worker, dict):
            warnings.append(f"{item.get('id') or 'worker'} is not a worker object")
            continue
        sanitized, worker_reports = sanitize_worker_for_import(worker, approvals=approvals)
        for report in worker_reports:
            sanitized_reports.append({
                "worker": sanitized.get("name") or "Worker",
                **report,
            })
        workers.append(sanitized)
        placement_workers.append((item.get("id") or "", sanitized))
    if not workers:
        raise BentoCarrierError("Package does not contain workers", "missing-workers")

    config = read_json(os.path.join(bp_dir, "config.json"))
    layout = normalize_layout(read_json(os.path.join(bp_dir, "layout.json")), config=config)
    slots = layout.setdefault("slots", [])
    cols = _safe_cols(config)
    placement = placement if isinstance(placement, dict) else {}
    expected_state = placement.get("expected_state") or placement.get("state")
    if expected_state:
        current_state = _placement_preview(placement_workers, slots, cols=cols).get("state")
        if current_state != expected_state:
            raise BentoCarrierError("Import preview is stale; preview the package again", "stale-preview")
    positions, placement_result = _resolve_import_positions(workers, slots, cols=cols, placement=placement)

    imported_profiles = []
    skipped_profiles = []
    for item, profile in profile_payloads:
        if not isinstance(profile, dict):
            continue
        profile_id = item.get("profile_id") or profile.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            continue
        profile_id = profile_id.strip()
        try:
            existing_profile = get_profile(bp_dir, profile_id)
        except ValueError as exc:
            raise BentoCarrierError("Package profile id is invalid", "invalid-profile-id") from exc
        if existing_profile:
            skipped_profiles.append(profile_id)
            continue
        profile = dict(profile)
        profile["id"] = profile_id
        profile.pop("workspaceId", None)
        create_profile(bp_dir, profile)
        imported_profiles.append(profile_id)

    fragment_result = apply_worker_fragments_to_layout(
        layout,
        [
            {"worker": worker, "coord": {"col": col, "row": row}}
            for worker, col, row in positions
        ],
        config=config,
    )
    layout = fragment_result["layout"]
    write_json(os.path.join(bp_dir, "layout.json"), layout)
    for profile_id in skipped_profiles:
        warnings.append(f"profile '{profile_id}' already exists and was kept")

    return {
        "ok": True,
        "kind": (manifest.get("bullpen") or {}).get("kind") or ("worker" if len(workers) == 1 else "worker-group"),
        "layout": layout,
        "imported": {
            "workers": len(workers),
            "profiles": len(imported_profiles),
        },
        "slots": fragment_result["slots"],
        "profiles": {
            "imported": sorted(imported_profiles),
            "skipped": sorted(skipped_profiles),
        },
        "renamed": fragment_result["renamed"],
        "rewritten_bindings": fragment_result["rewritten_bindings"],
        "sanitized": sanitized_reports,
        "placement": placement_result,
        "warnings": warnings,
    }


def preview_worker_bento(fileobj, *, bp_dir):
    """Return a worker-aware preview for a validated Bullpen Bento package."""
    carrier = inspect_bento(fileobj)
    manifest = _load_manifest(fileobj)
    profiles = manifest.get("profiles") or []
    profile_ids = {profile.get("id") for profile in profiles if isinstance(profile, dict)}
    if BULLPEN_PROFILE_ID not in profile_ids:
        return carrier

    worker_payloads, profile_payloads = _load_worker_payloads(fileobj, manifest)
    config = read_json(os.path.join(bp_dir, "config.json"))
    layout = normalize_layout(read_json(os.path.join(bp_dir, "layout.json")), config=config)
    existing_slots = layout.get("slots", [])
    cols = _safe_cols(config)
    columns = {column.get("key") for column in config.get("columns", []) if isinstance(column, dict)}
    workspace_names = {}
    for worker in existing_slots:
        if isinstance(worker, dict) and worker.get("name"):
            name = worker["name"]
            workspace_names[name] = workspace_names.get(name, 0) + 1
    package_names = {}
    for _item, worker in worker_payloads:
        if isinstance(worker, dict) and worker.get("name"):
            name = worker["name"]
            package_names[name] = package_names.get(name, 0) + 1

    items = []
    capability_counts = {"commands": 0, "env": 0, "services": 0, "notifications": 0, "git": 0, "queues": 0}
    warnings = []
    placement_workers = []
    for item, worker in worker_payloads:
        if not isinstance(worker, dict):
            warnings.append(f"{item.get('id') or 'worker'} is not a worker object")
            continue
        capabilities = _worker_capabilities(worker)
        for capability in capabilities:
            capability_counts[capability] = capability_counts.get(capability, 0) + 1
        bindings, binding_warnings = _binding_for(worker, package_names, workspace_names, columns)
        warnings.extend(binding_warnings)
        item_id = item.get("id") or ""
        placement_workers.append((item_id, worker))
        items.append({
            "item_id": item_id,
            "type": "worker",
            "name": str(worker.get("name") or "Worker"),
            "worker_type": str(worker.get("type") or "ai"),
            "profile": str(worker.get("profile") or ""),
            "coord": {"col": _safe_int(worker.get("col"), 0), "row": _safe_int(worker.get("row"), 0)},
            "capabilities": capabilities,
            "bindings": bindings,
            "warnings": binding_warnings,
        })

    included_profile_ids = []
    for item, profile in profile_payloads:
        profile_id = item.get("profile_id") or (profile.get("id") if isinstance(profile, dict) else "")
        if profile_id:
            included_profile_ids.append(str(profile_id))
    referenced_profile_ids = sorted({
        worker.get("profile")
        for _item, worker in worker_payloads
        if isinstance(worker, dict) and isinstance(worker.get("profile"), str) and worker.get("profile")
    })
    preview = dict(carrier)
    preview["supported_profiles"] = [BULLPEN_PROFILE_ID]
    preview["unsupported_profiles"] = [
        profile["id"]
        for profile in carrier.get("profiles", [])
        if profile.get("id") and profile.get("id") != BULLPEN_PROFILE_ID
    ]
    preview["kind"] = (manifest.get("bullpen") or {}).get("kind") or ("worker" if len(items) == 1 else "worker-group")
    preview["bullpen"] = {
        "kind": preview["kind"],
        "items": items,
        "profiles": {
            "referenced": referenced_profile_ids,
            "included": sorted(included_profile_ids),
            "missing": sorted(set(referenced_profile_ids) - set(included_profile_ids)),
        },
        "placement": _placement_preview(placement_workers, existing_slots, cols=cols),
        "capabilities": capability_counts,
        "warnings": warnings,
    }
    return preview
