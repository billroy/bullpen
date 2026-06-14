"""Value worker helpers."""

from __future__ import annotations

import re
from math import isfinite


VALUE_WORKER_TYPE = "value"
VALUE_TYPES = {"auto", "number", "string"}
_CELL_REF_RE = re.compile(r"^\s*([A-Za-z]+)\s*(\d+)\s*$")
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?(?:0|[1-9]\d*)(?:\.\d+)?$")


def is_value_worker(slot: dict | None) -> bool:
    return isinstance(slot, dict) and slot.get("type") == VALUE_WORKER_TYPE


def col_label(col: int | float) -> str:
    try:
        col = int(col)
    except (TypeError, ValueError):
        return ""
    if col < 0:
        return ""
    label = ""
    n = col
    while True:
        label = chr(65 + (n % 26)) + label
        n = (n // 26) - 1
        if n < 0:
            break
    return label


def row_label(row: int | float) -> str:
    try:
        row = int(row)
    except (TypeError, ValueError):
        return ""
    if row < 0:
        return ""
    return str(row + 1)


def coord_to_cell_ref(coord: dict | None) -> str:
    if not isinstance(coord, dict):
        return ""
    col = col_label(coord.get("col"))
    row = row_label(coord.get("row"))
    return f"{col}{row}" if col and row else ""


def parse_cell_ref(text: str | None) -> dict[str, int] | None:
    match = _CELL_REF_RE.match(str(text or ""))
    if not match:
        return None
    col = 0
    for ch in match.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    col -= 1
    row = int(match.group(2)) - 1
    if col < 0 or row < 0:
        return None
    return {"col": col, "row": row}


def value_name_key(name: object) -> str:
    return str(name if name is not None else "").strip().casefold()


def value_coord(slot: dict | None, *, index: int | None = None, cols: int = 4) -> dict[str, int] | None:
    if not isinstance(slot, dict):
        return None
    try:
        col = int(slot.get("col"))
        row = int(slot.get("row"))
    except (TypeError, ValueError):
        if index is None:
            return None
        safe_cols = cols if isinstance(cols, int) and cols > 0 else 4
        col = index % safe_cols
        row = index // safe_cols
    if col < 0 or row < 0:
        return None
    return {"col": col, "row": row}


def iter_value_slots(slots: object, *, cols: int = 4):
    if not isinstance(slots, list):
        return
    for index, slot in enumerate(slots):
        if not is_value_worker(slot):
            continue
        coord = value_coord(slot, index=index, cols=cols)
        if coord is None:
            continue
        yield index, slot, coord


def find_value_by_ref(slots: object, ref: object, *, cols: int = 4) -> dict | None:
    """Resolve a value worker by A1 cell reference first, then case-insensitive name."""
    ref_text = str(ref if ref is not None else "").strip()
    if not ref_text:
        return None

    ref_coord = parse_cell_ref(ref_text)
    if ref_coord is not None:
        for index, slot, coord in iter_value_slots(slots, cols=cols):
            if coord == ref_coord:
                return {"index": index, "slot": slot, "coord": coord, "ambiguous": False}

    needle = value_name_key(ref_text)
    matches = []
    for index, slot, coord in iter_value_slots(slots, cols=cols):
        if value_name_key(slot.get("name")) == needle:
            matches.append({"index": index, "slot": slot, "coord": coord})
    if not matches:
        return None
    matches.sort(key=lambda item: (item["coord"]["row"], item["coord"]["col"], item["index"]))
    result = matches[0]
    result["ambiguous"] = len(matches) > 1
    result["matches"] = matches
    return result


def value_ref_warning(match: dict | None) -> str | None:
    if not match or not match.get("ambiguous"):
        return None
    coords = [coord_to_cell_ref(item.get("coord")) for item in match.get("matches") or []]
    coords = [coord for coord in coords if coord]
    if not coords:
        return None
    return f"Duplicate value name matched {coords[0]}; other matches: {', '.join(coords[1:])}"


def normalize_value_type(value_type: object) -> str:
    value_type = str(value_type or "auto").strip().lower()
    return value_type if value_type in VALUE_TYPES else "auto"


def normalize_format(raw: object) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    kind = str(raw.get("kind") or "auto").strip().lower()
    allowed = {"auto", "general", "number", "currency", "string-left", "string-right"}
    if kind not in allowed:
        kind = "auto"
    out = {"kind": kind}
    if kind in {"number", "currency"}:
        try:
            places = int(raw.get("places", 2))
        except (TypeError, ValueError):
            places = 2
        out["places"] = max(0, min(10, places))
    if kind == "currency":
        symbol = str(raw.get("symbol") or "$")[:8]
        out["symbol"] = symbol or "$"
    return out


def format_value(value: object, raw_format: object = None) -> str:
    fmt = normalize_format(raw_format)
    kind = fmt.get("kind")
    if kind in {"number", "currency"}:
        parsed = _parse_plain_number(value)
        if parsed is not None:
            places = int(fmt.get("places", 2))
            rendered = f"{float(parsed):,.{places}f}"
            if isinstance(parsed, int) and places == 0:
                rendered = f"{parsed:,}"
            return f"{fmt.get('symbol', '$')}{rendered}" if kind == "currency" else rendered
    return str(value if value is not None else "")


def _normalize_string(value: object) -> str:
    return str(value if value is not None else "").replace("\r\n", "\n").replace("\r", "\n")


def _parse_plain_number(value: object):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else None
    text = str(value if value is not None else "").strip()
    if not _PLAIN_NUMBER_RE.match(text):
        return None
    if "." in text:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return parsed if isfinite(parsed) else None
    try:
        return int(text)
    except ValueError:
        return None


def is_plain_number(value: object) -> bool:
    return _parse_plain_number(value) is not None


def normalize_value_payload(value: object, value_type: object = "auto") -> dict:
    declared = normalize_value_type(value_type)
    if declared == "string":
        return {
            "value": _normalize_string(value),
            "value_type": declared,
            "resolved_value_type": "string",
        }

    parsed = _parse_plain_number(value)
    if declared == "number":
        if parsed is None:
            parsed = 0
        return {
            "value": parsed,
            "value_type": declared,
            "resolved_value_type": "number",
        }

    if parsed is not None:
        return {
            "value": parsed,
            "value_type": declared,
            "resolved_value_type": "number",
        }
    return {
        "value": _normalize_string(value),
        "value_type": declared,
        "resolved_value_type": "string",
    }
