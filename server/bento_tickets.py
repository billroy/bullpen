"""Bullpen ticket support for Bento packages."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import re
import zipfile

from server import tasks as task_mod
from server.bento_carrier import BentoCarrierError, inspect_bento
from server.bento_workers import BULLPEN_PROFILE_ID, BULLPEN_PROFILE_VERSION, worker_export_name


_VALID_PRIORITIES = {"urgent", "high", "normal", "low"}
_SAFE_IMPORT_STATUS = "backlog"
_ACTIVE_IMPORT_STATUSES = {"assigned", "in_progress", "in-progress"}


def _created_at():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_json(obj):
    return json.dumps(obj, indent=2, sort_keys=True)


def _ticket_export_name(value, fallback="ticket"):
    return worker_export_name(value, fallback=fallback)


def _item_id_for_ticket(ticket, index):
    title = _ticket_export_name(ticket.get("title"), f"ticket-{index + 1}")
    source_id = _ticket_export_name(ticket.get("id"), f"source-{index + 1}")
    return f"ticket.{index + 1}.{source_id}.{title}"


def _ticket_payload_path(item_id):
    return f"payload/tickets/{item_id}.json"


def _read_json_member(zf, path):
    try:
        raw = zf.read(path)
    except KeyError as exc:
        raise BentoCarrierError("Package item payload is missing", "missing-item-path") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BentoCarrierError("Package item payload must be UTF-8 JSON", "invalid-json") from exc


def load_manifest(fileobj):
    fileobj.seek(0)
    with zipfile.ZipFile(fileobj, "r") as zf:
        manifest = _read_json_member(zf, "bento.json")
    fileobj.seek(0)
    return manifest


def _load_ticket_payloads(fileobj, manifest):
    tickets = []
    with zipfile.ZipFile(fileobj, "r") as zf:
        for item in manifest.get("items") or []:
            if not isinstance(item, dict) or item.get("media_type") != "application/json":
                continue
            if item.get("bullpen_type") != "ticket":
                continue
            tickets.append((item, _read_json_member(zf, item.get("path"))))
    fileobj.seek(0)
    return tickets


def _safe_tags(tags):
    if not isinstance(tags, list):
        return []
    clean = []
    for tag in tags[:20]:
        text = str(tag or "").strip()
        if text:
            clean.append(text[:80])
    return clean


def _safe_priority(value):
    value = str(value or "normal").strip().lower()
    return value if value in _VALID_PRIORITIES else "normal"


def _safe_type(value):
    text = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "task").strip().lower()).strip("-")
    return text[:40] or "task"


def _safe_import_status(value):
    status = str(value or _SAFE_IMPORT_STATUS).strip() or _SAFE_IMPORT_STATUS
    normalized = re.sub(r"[\s-]+", "_", status.lower())
    if normalized in _ACTIVE_IMPORT_STATUSES:
        return _SAFE_IMPORT_STATUS
    return status


def sanitize_ticket_for_package(ticket):
    ticket = ticket if isinstance(ticket, dict) else {}
    return {
        "id": str(ticket.get("id") or ""),
        "title": str(ticket.get("title") or "Untitled ticket"),
        "body": str(ticket.get("body") or ""),
        "type": _safe_type(ticket.get("type")),
        "priority": _safe_priority(ticket.get("priority")),
        "tags": _safe_tags(ticket.get("tags")),
        "status": str(ticket.get("status") or "inbox"),
        "created_at": str(ticket.get("created_at") or ""),
        "updated_at": str(ticket.get("updated_at") or ""),
    }


def sanitize_ticket_for_import(ticket, *, target_status=None):
    ticket = sanitize_ticket_for_package(ticket)
    status = _safe_import_status(target_status)
    sanitized = {
        "title": ticket["title"],
        "body": ticket["body"],
        "type": ticket["type"],
        "priority": ticket["priority"],
        "tags": ticket["tags"],
        "status": status,
        "source_task_id": ticket.get("id") or "",
        "source_status": ticket.get("status") or "",
    }
    sanitized_report = []
    if ticket.get("status") != status:
        sanitized_report.append({"field": "status", "from": ticket.get("status") or "", "to": status})
    return sanitized, sanitized_report


def build_ticket_bento(ws, tickets, *, kind, selected_ids=None):
    tickets = [sanitize_ticket_for_package(ticket) for ticket in tickets if isinstance(ticket, dict)]
    if not tickets:
        raise ValueError("No tickets selected")

    selected_ids = list(selected_ids or [])
    created_at = _created_at()
    items = []
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for index, ticket in enumerate(tickets):
            item_id = _item_id_for_ticket(ticket, index)
            path = _ticket_payload_path(item_id)
            item = {
                "id": item_id,
                "media_type": "application/json",
                "path": path,
                "label": ticket.get("title") or "Ticket",
                "bullpen_type": "ticket",
            }
            items.append(item)
            zf.writestr(path, _safe_json(ticket))

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
            "attributes": [
                {
                    "label": "Bullpen preview",
                    "namespace": "org.bullpen.preview",
                    "name": "preview",
                    "version": "1",
                    "data": {
                        "kind": kind,
                        "ticket_count": len(tickets),
                        "badges": [kind],
                    },
                }
            ],
            "bullpen": {
                "kind": kind,
                "created_at": created_at,
                "workspace": {"id": ws.id, "name": ws.name},
                "selection": {
                    "ids": selected_ids,
                    "count": len(tickets),
                },
            },
        }
        zf.writestr("bento.json", _safe_json(manifest))

    mem.seek(0)
    return mem


def preview_ticket_bento(fileobj, *, bp_dir):
    carrier = inspect_bento(fileobj)
    manifest = load_manifest(fileobj)
    profiles = manifest.get("profiles") or []
    profile_ids = {profile.get("id") for profile in profiles if isinstance(profile, dict)}
    if BULLPEN_PROFILE_ID not in profile_ids:
        return carrier

    ticket_payloads = _load_ticket_payloads(fileobj, manifest)
    items = []
    warnings = []
    for item, ticket in ticket_payloads:
        if not isinstance(ticket, dict):
            warnings.append(f"{item.get('id') or 'ticket'} is not a ticket object")
            continue
        sanitized = sanitize_ticket_for_package(ticket)
        item_warnings = []
        if sanitized.get("status") in {"assigned", "in_progress", "in-progress"} or ticket.get("assigned_to"):
            item_warnings.append("ticket will import unassigned into backlog")
        items.append({
            "item_id": item.get("id") or "",
            "type": "ticket",
            "title": sanitized["title"],
            "priority": sanitized["priority"],
            "ticket_type": sanitized["type"],
            "source_status": sanitized["status"],
            "tags": sanitized["tags"],
            "body_length": len(sanitized["body"]),
            "warnings": item_warnings,
        })
        warnings.extend(item_warnings)

    preview = dict(carrier)
    preview["supported_profiles"] = [BULLPEN_PROFILE_ID]
    preview["unsupported_profiles"] = [
        profile["id"]
        for profile in carrier.get("profiles", [])
        if profile.get("id") and profile.get("id") != BULLPEN_PROFILE_ID
    ]
    preview["kind"] = (manifest.get("bullpen") or {}).get("kind") or ("ticket" if len(items) == 1 else "ticket-bundle")
    preview["bullpen"] = {
        "kind": preview["kind"],
        "items": items,
        "import": {
            "target_status": _SAFE_IMPORT_STATUS,
            "new_ids": True,
            "assignments_cleared": True,
        },
        "warnings": warnings,
    }
    return preview


def apply_ticket_fragments(bp_dir, tickets, *, target_status=None, kind="ticket-fragment"):
    tickets = list(tickets or [])
    if not tickets:
        raise BentoCarrierError("Package does not contain tickets", "missing-tickets")

    created = []
    sanitized_reports = []
    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue
        sanitized, reports = sanitize_ticket_for_import(ticket, target_status=target_status)
        task = task_mod.create_task(
            bp_dir,
            sanitized["title"],
            description="",
            task_type=sanitized["type"],
            priority=sanitized["priority"],
            tags=sanitized["tags"],
            status=sanitized["status"],
        )
        update_fields = {
            "body": sanitized["body"],
            "assigned_to": "",
            "source_task_id": sanitized["source_task_id"],
            "source_status": sanitized["source_status"],
        }
        task = task_mod.update_task(bp_dir, task["id"], update_fields)
        created.append(task)
        for report in reports:
            sanitized_reports.append({
                "ticket": sanitized["title"],
                "source_id": sanitized["source_task_id"],
                **report,
            })

    if not created:
        raise BentoCarrierError("Package does not contain valid tickets", "missing-tickets")

    return {
        "ok": True,
        "kind": kind,
        "imported": {
            "tickets": len(created),
        },
        "tickets": created,
        "sanitized": sanitized_reports,
        "target_status": _safe_import_status(target_status),
        "warnings": [],
    }


def apply_ticket_bento(fileobj, *, bp_dir, target_status=None):
    carrier = inspect_bento(fileobj)
    if not any(profile.get("id") == BULLPEN_PROFILE_ID for profile in carrier.get("profiles", [])):
        raise BentoCarrierError("Package does not include the Bullpen share profile", "unsupported-profile")

    manifest = load_manifest(fileobj)
    ticket_payloads = _load_ticket_payloads(fileobj, manifest)
    result = apply_ticket_fragments(
        bp_dir,
        [ticket for _item, ticket in ticket_payloads],
        target_status=target_status,
        kind=(manifest.get("bullpen") or {}).get("kind") or ("ticket" if len(ticket_payloads) == 1 else "ticket-bundle"),
    )
    return result
