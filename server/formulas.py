"""Safe parsing and scalar evaluation for Value worker formulas."""

from __future__ import annotations

import math
import re
import copy
import uuid
import heapq
import calendar
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from server.formula_functions import FORMULA_FUNCTION_NAMES
from server.values import (
    append_value_history,
    coord_to_cell_ref,
    iter_value_slots,
    parse_cell_ref,
    value_name_key,
    value_ref_warning,
)


FORMULA_VERSION = 1
FORMULA_MAX_LENGTH = 8192
FORMULA_MAX_DEPTH = 64
FORMULA_MAX_ARGUMENTS = 255
FORMULA_STATUSES = {"ok", "error", "pending", "stale"}


class FormulaError(Exception):
    """A safe, user-facing formula error."""

    def __init__(self, code: str, message: str, position: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.position = position

    def payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.position is not None:
            payload["position"] = self.position
        return payload


@dataclass(frozen=True)
class Token:
    kind: str
    value: Any
    position: int


@dataclass
class EvaluationResult:
    value: Any
    resolved_value_type: str
    dependencies: list[str]
    warnings: list[str]
    volatile: bool = False


@dataclass
class RangeValue:
    values: list[Any]
    rows: int = 1
    cols: int = 1


class FormulaResolver:
    """Rebuildable in-memory index for one consistent layout snapshot."""

    def __init__(self, slots: list[Any], *, cols: int = 4):
        self.by_coord: dict[tuple[int, int], dict[str, Any]] = {}
        names: dict[str, list[dict[str, Any]]] = {}
        for index, slot, coord in iter_value_slots(slots, cols=cols):
            item = {"index": index, "slot": slot, "coord": coord}
            self.by_coord.setdefault((coord["col"], coord["row"]), item)
            names.setdefault(value_name_key(slot.get("name")), []).append(item)
        self.by_name: dict[str, dict[str, Any]] = {}
        for key, matches in names.items():
            if not key:
                continue
            matches.sort(key=lambda item: (item["coord"]["row"], item["coord"]["col"], item["index"]))
            result = dict(matches[0])
            result["ambiguous"] = len(matches) > 1
            result["matches"] = matches
            self.by_name[key] = result

    def find(self, ref: object) -> dict[str, Any] | None:
        ref_text = str(ref if ref is not None else "").strip()
        if not ref_text:
            return None
        coord = parse_cell_ref(ref_text)
        if coord is not None:
            match = self.by_coord.get((coord["col"], coord["row"]))
            if match is not None:
                return {**match, "ambiguous": False}
        return self.by_name.get(value_name_key(ref_text))


_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_COORD_RE = re.compile(r"\$?[A-Za-z]+\$?\d+")
_COORD_PARTS_RE = re.compile(r"^(\$?)([A-Za-z]+)(\$?)(\d+)$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_OPERATORS = ("<=", ">=", "<>", "+", "-", "*", "/", "%", "^", "&", "=", "<", ">", "(", ")", ",", ":")


def normalize_formula(raw: object) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        source = str(raw.get("source") or "").strip()
        version = raw.get("version", FORMULA_VERSION)
    else:
        source = str(raw).strip()
        version = FORMULA_VERSION
    if not source:
        return None
    if not source.startswith("="):
        source = f"={source}"
    if len(source) > FORMULA_MAX_LENGTH:
        raise FormulaError("#PARSE!", f"Formula exceeds {FORMULA_MAX_LENGTH} characters")
    try:
        version = int(version)
    except (TypeError, ValueError):
        version = FORMULA_VERSION
    if version != FORMULA_VERSION:
        raise FormulaError("#PARSE!", f"Unsupported formula version: {version}")
    return {"source": source, "version": FORMULA_VERSION}


def normalize_formula_state(raw: object) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    status = str(raw.get("status") or "pending").strip().lower()
    if status not in FORMULA_STATUSES:
        status = "pending"
    error_code = raw.get("error_code")
    error_message = raw.get("error_message")
    return {
        "status": status,
        "error_code": str(error_code) if error_code else None,
        "error_message": str(error_message)[:512] if error_message else None,
        "error_position": raw.get("error_position") if isinstance(raw.get("error_position"), int) else None,
        "calculated_at": str(raw.get("calculated_at") or ""),
        "dependencies": [str(item) for item in raw.get("dependencies", []) if isinstance(item, str)][:10000],
        "warnings": [str(item)[:512] for item in raw.get("warnings", []) if isinstance(item, str)][:100],
        "volatile": bool(raw.get("volatile", False)),
    }


def formula_error_state(
    error: FormulaError,
    *,
    calculated_at: str = "",
    dependencies: list[str] | None = None,
    warnings: list[str] | None = None,
    volatile: bool = False,
) -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": error.code,
        "error_message": error.message[:512],
        "error_position": error.position,
        "calculated_at": calculated_at,
        "dependencies": list(dependencies or []),
        "warnings": list(warnings or []),
        "volatile": bool(volatile),
    }


def formula_ok_state(result: EvaluationResult, *, calculated_at: str) -> dict[str, Any]:
    return {
        "status": "ok",
        "error_code": None,
        "error_message": None,
        "error_position": None,
        "calculated_at": calculated_at,
        "dependencies": result.dependencies,
        "warnings": result.warnings,
        "volatile": result.volatile,
    }


def is_formula_stale(slot: object, *, now: datetime | None = None) -> bool:
    if not isinstance(slot, dict) or not slot.get("formula"):
        return False
    state = slot.get("formula_state") if isinstance(slot.get("formula_state"), dict) else {}
    if not state.get("volatile"):
        return state.get("status") == "stale"
    calculated_at = str(state.get("calculated_at") or "")
    try:
        calculated = datetime.fromisoformat(calculated_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    source = str((slot.get("formula") or {}).get("source") or "").upper()
    if "TODAY(" in source and calculated.date() != current.date():
        return True
    return "NOW(" in source and (current - calculated).total_seconds() >= 60


def tokenize(source: str) -> list[Token]:
    source = str(source or "").strip()
    if not source.startswith("="):
        raise FormulaError("#PARSE!", "Formula must begin with =", 0)
    if len(source) > FORMULA_MAX_LENGTH:
        raise FormulaError("#PARSE!", f"Formula exceeds {FORMULA_MAX_LENGTH} characters")
    text = source[1:]
    tokens: list[Token] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        position = i + 1
        if text.startswith("#REF!", i):
            tokens.append(Token("ERROR_REF", "#REF!", position))
            i += 5
            continue
        if ch == '"':
            i += 1
            pieces: list[str] = []
            while i < len(text):
                if text[i] == '"':
                    if i + 1 < len(text) and text[i + 1] == '"':
                        pieces.append('"')
                        i += 2
                        continue
                    i += 1
                    break
                pieces.append(text[i])
                i += 1
            else:
                raise FormulaError("#PARSE!", "Unterminated string literal", position)
            tokens.append(Token("STRING", "".join(pieces), position))
            continue
        if ch == "[":
            i += 1
            pieces = []
            while i < len(text):
                if text[i] == "]":
                    if i + 1 < len(text) and text[i + 1] == "]":
                        pieces.append("]")
                        i += 2
                        continue
                    i += 1
                    break
                pieces.append(text[i])
                i += 1
            else:
                raise FormulaError("#PARSE!", "Unterminated named reference", position)
            name = "".join(pieces).strip()
            if not name:
                raise FormulaError("#NAME?", "Named reference cannot be empty", position)
            tokens.append(Token("NAME", name, position))
            continue
        number = _NUMBER_RE.match(text, i)
        if number:
            raw = number.group(0)
            value = float(raw) if any(c in raw.lower() for c in (".", "e")) else int(raw)
            if isinstance(value, float) and not math.isfinite(value):
                raise FormulaError("#NUM!", "Numeric literal is not finite", position)
            tokens.append(Token("NUMBER", value, position))
            i = number.end()
            continue
        coord = _COORD_RE.match(text, i)
        if coord:
            raw = coord.group(0)
            end = coord.end()
            function_call = end < len(text) and text[end] == "(" and raw.upper() in FORMULA_FUNCTION_NAMES
            if not function_call and (end == len(text) or not (text[end].isalnum() or text[end] in "_.")):
                tokens.append(Token("COORD", raw, position))
                i = end
                continue
        ident = _IDENT_RE.match(text, i)
        if ident:
            tokens.append(Token("IDENT", ident.group(0), position))
            i = ident.end()
            continue
        operator = next((candidate for candidate in _OPERATORS if text.startswith(candidate, i)), None)
        if operator:
            tokens.append(Token(operator, operator, position))
            i += len(operator)
            continue
        raise FormulaError("#PARSE!", f"Unexpected character: {ch}", position)
    tokens.append(Token("EOF", None, len(source)))
    return tokens


def _translate_coord_token(raw: str, delta_col: int, delta_row: int) -> str | None:
    match = _COORD_PARTS_RE.fullmatch(raw)
    parsed = parse_cell_ref(raw.replace("$", ""))
    if not match or not parsed:
        raise FormulaError("#REF!", f"Invalid coordinate reference: {raw}")
    col_absolute, original_col, row_absolute, original_row = match.groups()
    col = parsed["col"] if col_absolute else parsed["col"] + delta_col
    row = parsed["row"] if row_absolute else parsed["row"] + delta_row
    if col < 0 or row < 0:
        return None
    canonical = coord_to_cell_ref({"col": col, "row": row})
    canonical_match = re.fullmatch(r"([A-Z]+)(\d+)", canonical or "")
    if not canonical_match:
        return None
    translated_col = original_col if col_absolute else canonical_match.group(1)
    translated_row = original_row if row_absolute else canonical_match.group(2)
    return f"{col_absolute}{translated_col}{row_absolute}{translated_row}"


def translate_formula_source(
    source: str,
    *,
    source_coord: dict[str, Any],
    destination_coord: dict[str, Any],
) -> str:
    """Translate coordinate-token spans for one structural copy or relocation."""
    source = str(source or "")
    try:
        delta_col = int(destination_coord["col"]) - int(source_coord["col"])
        delta_row = int(destination_coord["row"]) - int(source_coord["row"])
    except (KeyError, TypeError, ValueError) as exc:
        raise FormulaError("#REF!", "Formula translation requires valid source and destination coordinates") from exc
    if delta_col == 0 and delta_row == 0:
        return source

    tokens = tokenize(source)
    replacements: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind != "COORD":
            index += 1
            continue
        if index + 2 < len(tokens) and tokens[index + 1].kind == ":" and tokens[index + 2].kind == "COORD":
            end = tokens[index + 2]
            translated_start = _translate_coord_token(token.value, delta_col, delta_row)
            translated_end = _translate_coord_token(end.value, delta_col, delta_row)
            if translated_start is None or translated_end is None:
                replacements.append((token.position, end.position + len(end.value), "#REF!"))
            else:
                replacements.append((token.position, token.position + len(token.value), translated_start))
                replacements.append((end.position, end.position + len(end.value), translated_end))
            index += 3
            continue
        translated = _translate_coord_token(token.value, delta_col, delta_row)
        replacements.append((token.position, token.position + len(token.value), translated or "#REF!"))
        index += 1

    translated_source = source
    for start, end, value in sorted(replacements, reverse=True):
        translated_source = translated_source[:start] + value + translated_source[end:]
    if len(translated_source) > FORMULA_MAX_LENGTH:
        raise FormulaError("#LIMIT!", f"Translated formula exceeds {FORMULA_MAX_LENGTH} characters")
    return translated_source


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0
        self.depth = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def take(self, kind: str | None = None) -> Token:
        token = self.current
        if kind is not None and token.kind != kind:
            raise FormulaError("#PARSE!", f"Expected {kind}, found {token.kind}", token.position)
        self.index += 1
        return token

    def parse(self):
        node = self.comparison()
        if self.current.kind != "EOF":
            raise FormulaError("#PARSE!", f"Unexpected token: {self.current.kind}", self.current.position)
        return node

    def comparison(self):
        node = self.concat()
        while self.current.kind in {"=", "<>", "<", "<=", ">", ">="}:
            op = self.take().kind
            node = ("binary", op, node, self.concat())
        return node

    def concat(self):
        node = self.additive()
        while self.current.kind == "&":
            self.take()
            node = ("binary", "&", node, self.additive())
        return node

    def additive(self):
        node = self.multiply()
        while self.current.kind in {"+", "-"}:
            op = self.take().kind
            node = ("binary", op, node, self.multiply())
        return node

    def multiply(self):
        node = self.power()
        while self.current.kind in {"*", "/", "%"}:
            op = self.take().kind
            node = ("binary", op, node, self.power())
        return node

    def power(self):
        node = self.unary()
        if self.current.kind == "^":
            self.take()
            node = ("binary", "^", node, self.power())
        return node

    def unary(self):
        if self.current.kind in {"+", "-"}:
            op = self.take().kind
            return ("unary", op, self.unary())
        return self.primary()

    def primary(self):
        token = self.current
        if token.kind in {"NUMBER", "STRING"}:
            self.take()
            return ("literal", token.value)
        if token.kind == "ERROR_REF":
            self.take()
            return ("error", "#REF!", token.position)
        if token.kind == "COORD":
            self.take()
            if self.current.kind == ":":
                self.take(":")
                end = self.take("COORD")
                return ("range", token.value, end.value, token.position)
            return ("reference", token.value, True, token.position)
        if token.kind == "NAME":
            self.take()
            return ("reference", token.value, False, token.position)
        if token.kind == "IDENT":
            self.take()
            upper = token.value.upper()
            if upper in {"TRUE", "FALSE"} and self.current.kind != "(":
                return ("literal", upper == "TRUE")
            if self.current.kind == "(":
                return self.function_call(token)
            return ("reference", token.value, False, token.position)
        if token.kind == "(":
            self.take()
            self.depth += 1
            if self.depth > FORMULA_MAX_DEPTH:
                raise FormulaError("#LIMIT!", "Formula nesting limit exceeded", token.position)
            node = self.comparison()
            self.take(")")
            self.depth -= 1
            return node
        raise FormulaError("#PARSE!", f"Expected expression, found {token.kind}", token.position)

    def function_call(self, token: Token):
        self.take("(")
        self.depth += 1
        if self.depth > FORMULA_MAX_DEPTH:
            raise FormulaError("#LIMIT!", "Function nesting limit exceeded", token.position)
        args = []
        if self.current.kind != ")":
            while True:
                args.append(self.comparison())
                if len(args) > FORMULA_MAX_ARGUMENTS:
                    raise FormulaError("#LIMIT!", "Function argument limit exceeded", token.position)
                if self.current.kind != ",":
                    break
                self.take(",")
        self.take(")")
        self.depth -= 1
        return ("call", token.value.upper(), args, token.position)


def parse_formula(source: str):
    return Parser(tokenize(source)).parse()


def _canonical_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def _number(value: Any, position: int | None = None) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FormulaError("#VALUE!", "Numeric operand required", position)
    if isinstance(value, float) and not math.isfinite(value):
        raise FormulaError("#NUM!", "Numeric result is not finite", position)
    return value


def _result_type(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "number"
    return "string"


def coerce_formula_result(value: Any, value_type: object = "auto") -> tuple[Any, str]:
    """Apply a Value worker's declared result policy to a scalar formula result."""
    declared = str(value_type or "auto").strip().lower()
    if declared not in {"auto", "number", "string"}:
        declared = "auto"
    if isinstance(value, float) and not math.isfinite(value):
        raise FormulaError("#NUM!", "Formula result is not finite")
    if declared == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise FormulaError("#VALUE!", "Formula result must be numeric")
        return value, "number"
    if declared == "string":
        return _canonical_text(value), "string"
    resolved = _result_type(value)
    if resolved == "boolean":
        return _canonical_text(value), "string"
    return value, resolved


def _as_date(value: Any, position: int | None = None) -> date:
    text = _canonical_text(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        raise FormulaError("#VALUE!", "Strict ISO date required", position)


def _as_time(value: Any, position: int | None = None) -> time:
    text = _canonical_text(value).strip()
    candidate = text.split("T", 1)[1] if "T" in text else text
    candidate = candidate.removesuffix("Z")
    try:
        return time.fromisoformat(candidate)
    except (TypeError, ValueError):
        raise FormulaError("#VALUE!", "Strict ISO time or timestamp required", position)


def _add_months(value: date, months: int, *, end_of_month: bool = False) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year, month_zero = divmod(month_index, 12)
    month = month_zero + 1
    last = calendar.monthrange(year, month)[1]
    day = last if end_of_month else min(value.day, last)
    return date(year, month, day)


def _range_items(value: Any) -> list[Any]:
    return list(value.values) if isinstance(value, RangeValue) else [value]


def _numeric_items(value: Any, position: int | None = None) -> list[float | int]:
    return [item for item in _range_items(value)
            if isinstance(item, (int, float)) and not isinstance(item, bool)]


def _equal(left: Any, right: Any) -> bool:
    if isinstance(left, str) and isinstance(right, str):
        return left.casefold() == right.casefold()
    return left == right


def _wildcard_regex(pattern: str) -> re.Pattern[str]:
    pieces: list[str] = []
    escaped = False
    for ch in pattern:
        if escaped:
            pieces.append(re.escape(ch))
            escaped = False
        elif ch == "~":
            escaped = True
        elif ch == "*":
            pieces.append(".*")
        elif ch == "?":
            pieces.append(".")
        else:
            pieces.append(re.escape(ch))
    if escaped:
        pieces.append(re.escape("~"))
    return re.compile("^" + "".join(pieces) + "$", re.IGNORECASE | re.DOTALL)


def _criterion_match(value: Any, criterion: Any) -> bool:
    if not isinstance(criterion, str):
        return _equal(value, criterion)
    match = re.match(r"^(<=|>=|<>|=|<|>)(.*)$", criterion, re.DOTALL)
    op, target_text = (match.group(1), match.group(2)) if match else ("=", criterion)
    target: Any = target_text
    try:
        target = float(target_text) if any(ch in target_text.lower() for ch in ".e") else int(target_text)
    except (TypeError, ValueError):
        pass
    if op in {"=", "<>"} and isinstance(target, str) and any(ch in target for ch in "*?"):
        matched = bool(_wildcard_regex(target).match(_canonical_text(value)))
        return matched if op == "=" else not matched
    if op in {"=", "<>"}:
        matched = _equal(value, target)
        return matched if op == "=" else not matched
    try:
        if isinstance(value, str) and isinstance(target, str):
            left, right = value.casefold(), target.casefold()
        else:
            left, right = value, target
        return {"<": left < right, "<=": left <= right, ">": left > right, ">=": left >= right}[op]
    except TypeError:
        return False


def _percentile(numbers: list[float | int], k: float, position: int) -> float | int:
    if not numbers:
        raise FormulaError("#DIV/0!", "Percentile has no numeric values", position)
    if not 0 <= k <= 1:
        raise FormulaError("#NUM!", "Percentile must be between 0 and 1", position)
    ordered = sorted(numbers)
    rank = (len(ordered) - 1) * k
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


_BASE_INFO = {
    "BIN": (2, 10, -512, 511),
    "OCT": (8, 10, -536870912, 536870911),
    "HEX": (16, 10, -549755813888, 549755813887),
}


def _decode_base(value: Any, source: str, position: int) -> int:
    base, width, _minimum, _maximum = _BASE_INFO[source]
    text = _canonical_text(value).strip().upper()
    if not text or len(text) > width:
        raise FormulaError("#NUM!", f"Invalid {source} value", position)
    try:
        unsigned = int(text, base)
    except ValueError:
        raise FormulaError("#NUM!", f"Invalid {source} value", position)
    bits = {"BIN": 10, "OCT": 30, "HEX": 40}[source]
    if len(text) == width and unsigned & (1 << (bits - 1)):
        return unsigned - (1 << bits)
    if unsigned > _BASE_INFO[source][3]:
        raise FormulaError("#NUM!", f"{source} value is out of range", position)
    return unsigned


def _encode_base(number: int, target: str, places: int | None, position: int) -> str:
    base, width, minimum, maximum = _BASE_INFO[target]
    if number < minimum or number > maximum:
        raise FormulaError("#NUM!", f"Value is out of range for {target}", position)
    bits = {"BIN": 10, "OCT": 30, "HEX": 40}[target]
    unsigned = number if number >= 0 else (1 << bits) + number
    encoded = {2: lambda n: format(n, "b"), 8: lambda n: format(n, "o"), 16: lambda n: format(n, "X")}[base](unsigned)
    if number < 0:
        return encoded.rjust(width, {2: "1", 8: "7", 16: "F"}[base])
    if places is not None:
        if places < len(encoded) or places < 1 or places > width:
            raise FormulaError("#NUM!", "Invalid places argument", position)
        encoded = encoded.rjust(places, "0")
    return encoded


def _bounded_root(function: Callable[[float], float], guess: float, position: int) -> float:
    value = guess
    for _ in range(100):
        current = function(value)
        if abs(current) <= 1e-10:
            return value
        step = max(1e-7, abs(value) * 1e-6)
        try:
            derivative = (function(value + step) - function(value - step)) / (2 * step)
        except (ValueError, ZeroDivisionError, OverflowError):
            derivative = 0
        if not derivative or not math.isfinite(derivative):
            break
        candidate = value - current / derivative
        if candidate <= -0.999999999 or not math.isfinite(candidate):
            candidate = (value - 0.999999999) / 2
        if abs(candidate - value) <= 1e-12:
            return candidate
        value = candidate
    raise FormulaError("#NUM!", "Calculation did not converge", position)


class Evaluator:
    def __init__(self, slots: list[Any], *, current_index: int | None = None, cols: int = 4,
                 now: datetime | None = None, resolver: FormulaResolver | None = None):
        self.slots = slots
        self.current_index = current_index
        self.cols = cols
        self.dependencies: list[str] = []
        self.warnings: list[str] = []
        self.volatile = False
        self.now = now or datetime.now(timezone.utc)
        self.resolver = resolver or FormulaResolver(slots, cols=cols)

    def evaluate(self, node):
        kind = node[0]
        if kind == "literal":
            return node[1]
        if kind == "error":
            raise FormulaError(node[1], "Invalid structural reference", node[2])
        if kind == "reference":
            return self.reference(node[1], node[2], node[3])
        if kind == "range":
            return self.range_value(node[1], node[2], node[3])
        if kind == "unary":
            value = _number(self.evaluate(node[2]))
            return value if node[1] == "+" else -value
        if kind == "binary":
            return self.binary(node[1], node[2], node[3])
        if kind == "call":
            return self.call(node[1], node[2], node[3])
        raise FormulaError("#PARSE!", "Unknown expression node")

    def reference(self, ref: str, coordinate: bool, position: int):
        clean_ref = ref.replace("$", "") if coordinate else ref
        match = self.resolver.find(clean_ref)
        if not match:
            code = "#REF!" if coordinate else "#NAME?"
            raise FormulaError(code, f"Value reference not found: {clean_ref}", position)
        if self.current_index is not None and match.get("index") == self.current_index:
            raise FormulaError("#CYCLE!", "Formula directly references itself", position)
        slot = match.get("slot") or {}
        state = slot.get("formula_state") if isinstance(slot.get("formula_state"), dict) else {}
        if slot.get("formula") and state.get("status") == "error":
            raise FormulaError(str(state.get("error_code") or "#VALUE!"), f"Referenced formula {clean_ref} is in error", position)
        dependency = coord_to_cell_ref(match.get("coord"))
        if dependency and dependency not in self.dependencies:
            self.dependencies.append(dependency)
        warning = value_ref_warning(match)
        if warning and warning not in self.warnings:
            self.warnings.append(warning)
        return slot.get("value", "")

    def range_value(self, start_ref: str, end_ref: str, position: int) -> RangeValue:
        start = parse_cell_ref(start_ref.replace("$", ""))
        end = parse_cell_ref(end_ref.replace("$", ""))
        if not start or not end:
            raise FormulaError("#REF!", "Invalid range reference", position)
        min_col, max_col = sorted((start["col"], end["col"]))
        min_row, max_row = sorted((start["row"], end["row"]))
        count = (max_col - min_col + 1) * (max_row - min_row + 1)
        if count > 10000:
            raise FormulaError("#LIMIT!", "Range exceeds 10000 positions", position)
        values: list[Any] = []
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                ref = coord_to_cell_ref({"col": col, "row": row})
                match = self.resolver.find(ref)
                if not match:
                    values.append(None)
                    continue
                slot = match.get("slot") or {}
                state = slot.get("formula_state") if isinstance(slot.get("formula_state"), dict) else {}
                if slot.get("formula") and state.get("status") == "error":
                    raise FormulaError(str(state.get("error_code") or "#VALUE!"), f"Referenced formula {ref} is in error", position)
                if ref not in self.dependencies:
                    self.dependencies.append(ref)
                values.append(slot.get("value", ""))
        return RangeValue(values, rows=max_row - min_row + 1, cols=max_col - min_col + 1)

    def binary(self, op: str, left_node, right_node):
        left = self.evaluate(left_node)
        right = self.evaluate(right_node)
        if op == "&":
            return _canonical_text(left) + _canonical_text(right)
        if op in {"=", "<>", "<", "<=", ">", ">="}:
            if isinstance(left, str) and isinstance(right, str):
                left, right = left.casefold(), right.casefold()
            elif type(left) is not type(right) and not (
                isinstance(left, (int, float)) and isinstance(right, (int, float))
            ):
                raise FormulaError("#VALUE!", "Comparison operands have incompatible types")
            if op == "=":
                return left == right
            if op == "<>":
                return left != right
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            return left >= right
        left_num, right_num = _number(left), _number(right)
        if op in {"/", "%"} and right_num == 0:
            raise FormulaError("#DIV/0!", "Division by zero")
        try:
            value = {
                "+": lambda: left_num + right_num,
                "-": lambda: left_num - right_num,
                "*": lambda: left_num * right_num,
                "/": lambda: left_num / right_num,
                "%": lambda: left_num % right_num,
                "^": lambda: left_num ** right_num,
            }[op]()
        except (OverflowError, ValueError):
            raise FormulaError("#NUM!", "Invalid numeric result")
        return _number(value)

    def _args(self, args):
        return [self.evaluate(arg) for arg in args]

    @staticmethod
    def _flatten(values: list[Any]) -> list[Any]:
        flattened: list[Any] = []
        for value in values:
            flattened.extend(value.values if isinstance(value, RangeValue) else [value])
        return flattened

    def call(self, name: str, args, position: int):
        if name not in FORMULA_FUNCTION_NAMES:
            raise FormulaError("#NAME?", f"Unknown function: {name}", position)
        if name == "IF":
            if len(args) not in {2, 3}:
                raise FormulaError("#VALUE!", "IF expects 2 or 3 arguments", position)
            condition = self.evaluate(args[0])
            return self.evaluate(args[1] if bool(condition) else (args[2] if len(args) == 3 else ("literal", False)))
        if name == "IFERROR":
            if len(args) != 2:
                raise FormulaError("#VALUE!", "IFERROR expects 2 arguments", position)
            try:
                return self.evaluate(args[0])
            except FormulaError:
                return self.evaluate(args[1])
        if name == "ISERROR":
            if len(args) != 1:
                raise FormulaError("#VALUE!", "ISERROR expects 1 argument", position)
            try:
                self.evaluate(args[0])
                return False
            except FormulaError:
                return True
        if name in {"ISERR", "ISNA"}:
            if len(args) != 1:
                raise FormulaError("#VALUE!", f"{name} expects 1 argument", position)
            try:
                self.evaluate(args[0])
                return False
            except FormulaError as error:
                return error.code != "#N/A" if name == "ISERR" else error.code == "#N/A"
        if name == "IFNA":
            if len(args) != 2:
                raise FormulaError("#VALUE!", "IFNA expects 2 arguments", position)
            try:
                return self.evaluate(args[0])
            except FormulaError as error:
                if error.code != "#N/A":
                    raise
                return self.evaluate(args[1])
        if name == "IFS":
            if not args or len(args) % 2:
                raise FormulaError("#VALUE!", "IFS expects condition/value pairs", position)
            for index in range(0, len(args), 2):
                if bool(self.evaluate(args[index])):
                    return self.evaluate(args[index + 1])
            raise FormulaError("#N/A", "IFS found no true condition", position)
        if name == "SWITCH":
            if len(args) < 3:
                raise FormulaError("#VALUE!", "SWITCH expects an expression and cases", position)
            expression = self.evaluate(args[0])
            pair_end = len(args) if len(args) % 2 else len(args) - 1
            for index in range(1, pair_end, 2):
                if _equal(expression, self.evaluate(args[index])):
                    return self.evaluate(args[index + 1])
            if pair_end < len(args):
                return self.evaluate(args[-1])
            raise FormulaError("#N/A", "SWITCH found no matching case", position)
        if name in {"AND", "OR"}:
            if not args:
                raise FormulaError("#VALUE!", f"{name} expects at least 1 argument", position)
            if name == "AND":
                for arg in args:
                    if not bool(self.evaluate(arg)):
                        return False
                return True
            for arg in args:
                if bool(self.evaluate(arg)):
                    return True
            return False
        if name in {"ROW", "COLUMN"}:
            if len(args) > 1:
                raise FormulaError("#VALUE!", f"{name} expects 0 or 1 arguments", position)
            if args:
                node = args[0]
                if node[0] not in {"reference", "range"} or (node[0] == "reference" and not node[2]):
                    raise FormulaError("#VALUE!", f"{name} requires a coordinate reference", position)
                parsed = parse_cell_ref(node[1].replace("$", ""))
                if not parsed:
                    raise FormulaError("#REF!", "Invalid coordinate reference", position)
                return parsed["row"] + 1 if name == "ROW" else parsed["col"] + 1
            if self.current_index is None:
                raise FormulaError("#VALUE!", f"{name} requires cell context", position)
            return self.current_index // self.cols + 1 if name == "ROW" else self.current_index % self.cols + 1
        values = self._args(args)
        if name in {"SUM", "AVERAGE", "MIN", "MAX", "COUNT"}:
            flat = self._flatten(values)
            numbers = [value for value in flat if isinstance(value, (int, float)) and not isinstance(value, bool)]
            if name == "COUNT":
                return len(numbers)
            if not numbers:
                if name == "SUM":
                    return 0
                raise FormulaError("#DIV/0!" if name == "AVERAGE" else "#VALUE!", f"{name} has no numeric values", position)
            if name == "SUM":
                return sum(numbers)
            if name == "AVERAGE":
                return sum(numbers) / len(numbers)
            return min(numbers) if name == "MIN" else max(numbers)
        if name in {"COUNTA", "COUNTBLANK"}:
            flat = self._flatten(values)
            if name == "COUNTA":
                return sum(item is not None and item != "" for item in flat)
            return sum(item is None or item == "" for item in flat)
        if name in {"COUNTIF", "SUMIF", "AVERAGEIF"}:
            expected = 2 if name == "COUNTIF" else None
            if (expected and len(values) != expected) or (not expected and len(values) not in {2, 3}):
                raise FormulaError("#VALUE!", f"Invalid {name} arguments", position)
            criteria_items = _range_items(values[0])
            selected = [index for index, item in enumerate(criteria_items) if _criterion_match(item, values[1])]
            if name == "COUNTIF":
                return len(selected)
            result_items = _range_items(values[2]) if len(values) == 3 else criteria_items
            if len(result_items) != len(criteria_items):
                raise FormulaError("#VALUE!", "Criteria and result ranges must have equal size", position)
            numbers = [result_items[index] for index in selected
                       if isinstance(result_items[index], (int, float)) and not isinstance(result_items[index], bool)]
            if name == "SUMIF":
                return sum(numbers)
            if not numbers:
                raise FormulaError("#DIV/0!", "AVERAGEIF has no matching numeric values", position)
            return sum(numbers) / len(numbers)
        if name in {"COUNTIFS", "SUMIFS", "AVERAGEIFS", "MAXIFS", "MINIFS"}:
            if name == "COUNTIFS":
                if len(values) < 2 or len(values) % 2:
                    raise FormulaError("#VALUE!", "COUNTIFS expects range/criterion pairs", position)
                result_items = None
                pairs = values
            else:
                if len(values) < 3 or len(values) % 2 == 0:
                    raise FormulaError("#VALUE!", f"{name} expects a result range and range/criterion pairs", position)
                result_items = _range_items(values[0])
                pairs = values[1:]
            ranges = [_range_items(pairs[index]) for index in range(0, len(pairs), 2)]
            size = len(ranges[0])
            if any(len(items) != size for items in ranges) or (result_items is not None and len(result_items) != size):
                raise FormulaError("#VALUE!", "Criteria and result ranges must have equal size", position)
            selected = [index for index in range(size) if all(
                _criterion_match(ranges[pair_index][index], pairs[pair_index * 2 + 1])
                for pair_index in range(len(ranges))
            )]
            if name == "COUNTIFS":
                return len(selected)
            numbers = [result_items[index] for index in selected
                       if isinstance(result_items[index], (int, float)) and not isinstance(result_items[index], bool)]
            if name == "SUMIFS":
                return sum(numbers)
            if not numbers:
                raise FormulaError("#DIV/0!" if name == "AVERAGEIFS" else "#VALUE!",
                                   f"{name} has no matching numeric values", position)
            if name == "AVERAGEIFS":
                return sum(numbers) / len(numbers)
            return max(numbers) if name == "MAXIFS" else min(numbers)
        if name == "SUMPRODUCT":
            if not values:
                raise FormulaError("#VALUE!", "SUMPRODUCT expects at least 1 argument", position)
            arrays = [_range_items(value) for value in values]
            if any(len(items) != len(arrays[0]) for items in arrays):
                raise FormulaError("#VALUE!", "SUMPRODUCT arguments must have equal size", position)
            total = 0
            for index in range(len(arrays[0])):
                product = 1
                for items in arrays:
                    item = items[index]
                    product *= item if isinstance(item, (int, float)) and not isinstance(item, bool) else 0
                total += product
            return total
        if name in {"PRODUCT", "SUMSQ"}:
            numbers = [item for item in self._flatten(values)
                       if isinstance(item, (int, float)) and not isinstance(item, bool)]
            if name == "SUMSQ":
                return sum(item * item for item in numbers)
            product = 1
            for item in numbers:
                product *= item
            return product
        if name in {"MEDIAN", "LARGE", "SMALL", "PERCENTILE.INC", "QUARTILE.INC", "RANK.EQ", "STDEV.P", "STDEV.S"}:
            if not values:
                raise FormulaError("#VALUE!", f"{name} expects arguments", position)
            numbers = _numeric_items(values[0], position)
            if name in {"MEDIAN", "STDEV.P", "STDEV.S"} and len(values) > 1:
                numbers = [item for item in self._flatten(values)
                           if isinstance(item, (int, float)) and not isinstance(item, bool)]
            if name == "MEDIAN":
                if not numbers:
                    raise FormulaError("#DIV/0!", "MEDIAN has no numeric values", position)
                return statistics.median(numbers)
            if name in {"LARGE", "SMALL"}:
                self._arity(name, values, 2, position)
                rank = int(_number(values[1], position))
                if rank < 1 or rank > len(numbers):
                    raise FormulaError("#NUM!", "Rank is out of range", position)
                return sorted(numbers, reverse=name == "LARGE")[rank - 1]
            if name == "PERCENTILE.INC":
                self._arity(name, values, 2, position)
                return _percentile(numbers, float(_number(values[1], position)), position)
            if name == "QUARTILE.INC":
                self._arity(name, values, 2, position)
                quartile = int(_number(values[1], position))
                if quartile not in range(5):
                    raise FormulaError("#NUM!", "Quartile must be 0 through 4", position)
                return _percentile(numbers, quartile / 4, position)
            if name == "RANK.EQ":
                if len(values) not in {2, 3}:
                    raise FormulaError("#VALUE!", "RANK.EQ expects 2 or 3 arguments", position)
                target = _number(values[0], position)
                numbers = _numeric_items(values[1], position)
                ascending = bool(values[2]) if len(values) == 3 else False
                ordered = sorted(numbers, reverse=not ascending)
                try:
                    return ordered.index(target) + 1
                except ValueError:
                    raise FormulaError("#N/A", "Value is not in the ranked range", position)
            if name == "STDEV.P":
                if not numbers:
                    raise FormulaError("#DIV/0!", "STDEV.P has no numeric values", position)
                return statistics.pstdev(numbers)
            if len(numbers) < 2:
                raise FormulaError("#DIV/0!", "STDEV.S requires at least 2 numeric values", position)
            return statistics.stdev(numbers)
        if name == "NOT":
            self._arity(name, values, 1, position)
            return not bool(values[0])
        if name == "ISNUMBER":
            self._arity(name, values, 1, position)
            return isinstance(values[0], (int, float)) and not isinstance(values[0], bool)
        if name == "ISTEXT":
            self._arity(name, values, 1, position)
            return isinstance(values[0], str)
        if name == "ISBLANK":
            self._arity(name, values, 1, position)
            return values[0] == "" or values[0] is None
        if name == "NA":
            self._arity(name, values, 0, position)
            raise FormulaError("#N/A", "Not available", position)
        if name in {"ISEVEN", "ISODD"}:
            self._arity(name, values, 1, position)
            number = math.trunc(_number(values[0], position))
            return number % 2 == (0 if name == "ISEVEN" else 1)
        if name == "ISLOGICAL":
            self._arity(name, values, 1, position)
            return isinstance(values[0], bool)
        if name == "N":
            self._arity(name, values, 1, position)
            if isinstance(values[0], bool):
                return int(values[0])
            return values[0] if isinstance(values[0], (int, float)) else 0
        if name == "TYPE":
            self._arity(name, values, 1, position)
            if isinstance(values[0], RangeValue):
                return 64
            if isinstance(values[0], bool):
                return 4
            if isinstance(values[0], (int, float)):
                return 1
            return 2
        if name == "XOR":
            if not values:
                raise FormulaError("#VALUE!", "XOR expects at least 1 argument", position)
            return sum(bool(item) for item in self._flatten(values)) % 2 == 1
        if name == "CHOOSE":
            if len(values) < 2:
                raise FormulaError("#VALUE!", "CHOOSE expects an index and values", position)
            index = int(_number(values[0], position))
            if index < 1 or index >= len(values):
                raise FormulaError("#VALUE!", "CHOOSE index is out of range", position)
            return values[index]
        if name in {"ROWS", "COLUMNS"}:
            self._arity(name, values, 1, position)
            value = values[0]
            if not isinstance(value, RangeValue):
                return 1
            return value.rows if name == "ROWS" else value.cols
        if name == "INDEX":
            if len(values) not in {2, 3}:
                raise FormulaError("#VALUE!", "INDEX expects 2 or 3 arguments", position)
            source = values[0] if isinstance(values[0], RangeValue) else RangeValue([values[0]])
            row = int(_number(values[1], position))
            col = int(_number(values[2], position)) if len(values) == 3 else 1
            if row < 1 or col < 1 or row > source.rows or col > source.cols:
                raise FormulaError("#REF!", "INDEX position is outside the range", position)
            return source.values[(row - 1) * source.cols + col - 1]
        if name in {"MATCH", "XMATCH"}:
            if len(values) < 2 or len(values) > (4 if name == "XMATCH" else 3):
                raise FormulaError("#VALUE!", f"Invalid {name} arguments", position)
            lookup = values[0]
            items = _range_items(values[1])
            match_mode = int(_number(values[2], position)) if len(values) > 2 else (0 if name == "XMATCH" else 1)
            search_mode = int(_number(values[3], position)) if len(values) > 3 else 1
            allowed_modes = {0, 1, -1, 2} if name == "XMATCH" else {0, 1, -1}
            if match_mode not in allowed_modes or search_mode not in {1, -1}:
                raise FormulaError("#VALUE!", f"Unsupported {name} match or search mode", position)
            order = range(len(items) - 1, -1, -1) if search_mode == -1 else range(len(items))
            for index in order:
                matched = (_wildcard_regex(_canonical_text(lookup)).match(_canonical_text(items[index])) is not None
                           if match_mode == 2 else _equal(items[index], lookup))
                if matched:
                    return index + 1
            comparable = [(index, item) for index, item in enumerate(items)
                          if isinstance(item, (int, float)) and isinstance(lookup, (int, float))]
            if match_mode in {1, -1}:
                candidates = [(index, item) for index, item in comparable
                              if (item >= lookup if match_mode == 1 and name == "XMATCH" else
                                  item <= lookup if match_mode == -1 and name == "XMATCH" else
                                  item <= lookup if match_mode == 1 else item >= lookup)]
                if candidates:
                    chosen = min(candidates, key=lambda pair: pair[1]) if (match_mode == 1 and name == "XMATCH") or (match_mode == -1 and name != "XMATCH") else max(candidates, key=lambda pair: pair[1])
                    return chosen[0] + 1
            raise FormulaError("#N/A", f"{name} did not find a match", position)
        if name == "XLOOKUP":
            if len(values) < 3 or len(values) > 6:
                raise FormulaError("#VALUE!", "XLOOKUP expects 3 to 6 arguments", position)
            lookup_items, return_items = _range_items(values[1]), _range_items(values[2])
            if len(lookup_items) != len(return_items):
                raise FormulaError("#VALUE!", "Lookup and return ranges must have equal size", position)
            match_mode = int(_number(values[4], position)) if len(values) > 4 else 0
            search_mode = int(_number(values[5], position)) if len(values) > 5 else 1
            if match_mode not in {0, 1, -1, 2} or search_mode not in {1, -1}:
                raise FormulaError("#VALUE!", "Unsupported XLOOKUP match or search mode", position)
            order = range(len(lookup_items) - 1, -1, -1) if search_mode == -1 else range(len(lookup_items))
            for index in order:
                matched = (_wildcard_regex(_canonical_text(values[0])).match(_canonical_text(lookup_items[index])) is not None
                           if match_mode == 2 else _equal(values[0], lookup_items[index]))
                if matched:
                    return return_items[index]
            if match_mode in {1, -1} and isinstance(values[0], (int, float)):
                candidates = [(index, item) for index, item in enumerate(lookup_items)
                              if isinstance(item, (int, float)) and
                              (item >= values[0] if match_mode == 1 else item <= values[0])]
                if candidates:
                    chosen = min(candidates, key=lambda pair: pair[1]) if match_mode == 1 else max(candidates, key=lambda pair: pair[1])
                    return return_items[chosen[0]]
            if len(values) > 3:
                return values[3]
            raise FormulaError("#N/A", "XLOOKUP did not find a match", position)
        if name == "ABS":
            self._arity(name, values, 1, position)
            return abs(_number(values[0], position))
        if name in {"EXP", "LN", "LOG", "LOG10", "SQRT", "POWER", "PI", "SIGN", "INT", "TRUNC", "CEILING.MATH", "FLOOR.MATH", "QUOTIENT"}:
            if name == "PI":
                self._arity(name, values, 0, position)
                return math.pi
            if name == "POWER":
                self._arity(name, values, 2, position)
                operands = (_number(values[0], position), _number(values[1], position))
                try:
                    return _number(math.pow(*operands), position)
                except (ValueError, OverflowError):
                    raise FormulaError("#NUM!", "Invalid POWER result", position)
            if name == "LOG":
                if len(values) not in {1, 2}:
                    raise FormulaError("#VALUE!", "LOG expects 1 or 2 arguments", position)
                number = _number(values[0], position)
                base = _number(values[1], position) if len(values) == 2 else 10
                if number <= 0 or base <= 0 or base == 1:
                    raise FormulaError("#NUM!", "Invalid LOG domain", position)
                return math.log(number, base)
            if name in {"CEILING.MATH", "FLOOR.MATH"}:
                if len(values) not in {1, 2, 3}:
                    raise FormulaError("#VALUE!", f"{name} expects 1 to 3 arguments", position)
                number = _number(values[0], position)
                significance = abs(_number(values[1], position)) if len(values) > 1 else 1
                mode = bool(values[2]) if len(values) > 2 else False
                if significance == 0:
                    return 0
                scaled = number / significance
                if name == "CEILING.MATH":
                    rounded = math.floor(scaled) if number < 0 and mode else math.ceil(scaled)
                else:
                    rounded = math.ceil(scaled) if number < 0 and mode else math.floor(scaled)
                return rounded * significance
            if name == "QUOTIENT":
                self._arity(name, values, 2, position)
                divisor = _number(values[1], position)
                if divisor == 0:
                    raise FormulaError("#DIV/0!", "Division by zero", position)
                return math.trunc(_number(values[0], position) / divisor)
            self._arity(name, values, 1, position)
            number = _number(values[0], position)
            try:
                if name == "EXP": return _number(math.exp(number), position)
                if name == "LN": return _number(math.log(number), position)
                if name == "LOG10": return _number(math.log10(number), position)
                if name == "SQRT": return _number(math.sqrt(number), position)
                if name == "SIGN": return 0 if number == 0 else (1 if number > 0 else -1)
                if name == "INT": return math.floor(number)
                return math.trunc(number)
            except (ValueError, OverflowError):
                raise FormulaError("#NUM!", f"Invalid {name} result", position)
        if name in {"ACOS", "ACOSH", "ASIN", "ASINH", "ATAN", "ATANH", "COS", "COSH", "SIN", "SINH", "TAN", "TANH", "DEGREES", "RADIANS"}:
            self._arity(name, values, 1, position)
            number = _number(values[0], position)
            functions = {"ACOS": math.acos, "ACOSH": math.acosh, "ASIN": math.asin,
                         "ASINH": math.asinh, "ATAN": math.atan, "ATANH": math.atanh,
                         "COS": math.cos, "COSH": math.cosh, "SIN": math.sin,
                         "SINH": math.sinh, "TAN": math.tan, "TANH": math.tanh,
                         "DEGREES": math.degrees, "RADIANS": math.radians}
            try:
                return _number(functions[name](number), position)
            except (ValueError, OverflowError):
                raise FormulaError("#NUM!", f"Invalid {name} result", position)
        if name == "ATAN2":
            self._arity(name, values, 2, position)
            x, y = _number(values[0], position), _number(values[1], position)
            if x == 0 and y == 0:
                raise FormulaError("#DIV/0!", "ATAN2 arguments cannot both be zero", position)
            return math.atan2(y, x)
        if name in {"COMBIN", "FACT", "GCD", "LCM"}:
            numbers = [math.trunc(_number(item, position)) for item in values]
            if any(item < 0 for item in numbers):
                raise FormulaError("#NUM!", f"{name} requires non-negative integers", position)
            try:
                if name == "FACT":
                    self._arity(name, values, 1, position)
                    if numbers[0] > 170:
                        raise FormulaError("#NUM!", "FACT result would overflow", position)
                    return math.factorial(numbers[0])
                if name == "COMBIN":
                    self._arity(name, values, 2, position)
                    if numbers[0] > 10000:
                        raise FormulaError("#LIMIT!", "COMBIN input is too large", position)
                    return math.comb(numbers[0], numbers[1])
                if not numbers:
                    raise FormulaError("#VALUE!", f"{name} expects arguments", position)
                return math.gcd(*numbers) if name == "GCD" else math.lcm(*numbers)
            except ValueError:
                raise FormulaError("#NUM!", f"Invalid {name} arguments", position)
        if name in {"ROUND", "ROUNDUP", "ROUNDDOWN"}:
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            number = _number(values[0], position)
            digits = int(_number(values[1], position)) if len(values) == 2 else 0
            factor = 10 ** digits
            if name == "ROUND":
                try:
                    quantum = Decimal(1).scaleb(-digits)
                    rounded = Decimal(str(number)).quantize(quantum, rounding=ROUND_HALF_UP)
                    return int(rounded) if digits <= 0 and rounded == rounded.to_integral() else float(rounded)
                except (InvalidOperation, ValueError, OverflowError):
                    raise FormulaError("#NUM!", "Invalid rounding result", position)
            scaled = number * factor
            rounded = math.ceil(abs(scaled)) if name == "ROUNDUP" else math.floor(abs(scaled))
            return math.copysign(rounded / factor, number)
        if name == "MOD":
            self._arity(name, values, 2, position)
            left, right = _number(values[0], position), _number(values[1], position)
            if right == 0:
                raise FormulaError("#DIV/0!", "Division by zero", position)
            return left % right
        if name in {"CONCAT", "TEXTJOIN"}:
            if name == "CONCAT":
                return "".join(_canonical_text(value) for value in self._flatten(values) if value is not None)
            if len(values) < 3:
                raise FormulaError("#VALUE!", "TEXTJOIN expects at least 3 arguments", position)
            delimiter = _canonical_text(values[0])
            ignore_empty = bool(values[1])
            items = self._flatten(values[2:])
            return delimiter.join(_canonical_text(value) for value in items if not (ignore_empty and (value is None or value == "")))
        if name in {"LEFT", "RIGHT"}:
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            text = _canonical_text(values[0])
            count = int(_number(values[1], position)) if len(values) == 2 else 1
            if count < 0:
                raise FormulaError("#VALUE!", "Character count cannot be negative", position)
            return text[:count] if name == "LEFT" else text[-count:] if count else ""
        if name == "MID":
            self._arity(name, values, 3, position)
            text, start, count = _canonical_text(values[0]), int(_number(values[1], position)), int(_number(values[2], position))
            if start < 1 or count < 0:
                raise FormulaError("#VALUE!", "MID indices are invalid", position)
            return text[start - 1:start - 1 + count]
        if name in {"LEN", "TRIM", "UPPER", "LOWER"}:
            self._arity(name, values, 1, position)
            text = _canonical_text(values[0])
            return {"LEN": len(text), "TRIM": " ".join(text.split()), "UPPER": text.upper(), "LOWER": text.lower()}[name]
        if name == "SUBSTITUTE":
            if len(values) not in {3, 4}:
                raise FormulaError("#VALUE!", "SUBSTITUTE expects 3 or 4 arguments", position)
            text, old, new = map(_canonical_text, values[:3])
            if len(values) == 3:
                return text.replace(old, new)
            occurrence = int(_number(values[3], position))
            if occurrence < 1:
                raise FormulaError("#VALUE!", "SUBSTITUTE occurrence must be positive", position)
            parts = text.split(old)
            return old.join(parts[:occurrence]) + (new + old.join(parts[occurrence:]) if len(parts) > occurrence else "")
        if name in {"CLEAN", "PROPER", "CHAR", "CODE", "UNICODE", "UNICHAR", "REPT", "EXACT"}:
            if name == "EXACT":
                self._arity(name, values, 2, position)
                return _canonical_text(values[0]) == _canonical_text(values[1])
            if name == "REPT":
                self._arity(name, values, 2, position)
                count = math.trunc(_number(values[1], position))
                if count < 0:
                    raise FormulaError("#VALUE!", "REPT count cannot be negative", position)
                result = _canonical_text(values[0]) * count
                if len(result) > FORMULA_MAX_LENGTH:
                    raise FormulaError("#LIMIT!", "REPT result is too long", position)
                return result
            self._arity(name, values, 1, position)
            if name == "CLEAN":
                return "".join(ch for ch in _canonical_text(values[0]) if ord(ch) >= 32)
            if name == "PROPER":
                return _canonical_text(values[0]).title()
            if name in {"CODE", "UNICODE"}:
                text = _canonical_text(values[0])
                if not text:
                    raise FormulaError("#VALUE!", f"{name} requires non-empty text", position)
                return ord(text[0])
            codepoint = math.trunc(_number(values[0], position))
            if name == "CHAR" and not 1 <= codepoint <= 255:
                raise FormulaError("#VALUE!", "CHAR code must be 1 through 255", position)
            try:
                return chr(codepoint)
            except (ValueError, OverflowError):
                raise FormulaError("#VALUE!", "Invalid Unicode code point", position)
        if name in {"FIND", "SEARCH"}:
            if len(values) not in {2, 3}:
                raise FormulaError("#VALUE!", f"{name} expects 2 or 3 arguments", position)
            needle, haystack = _canonical_text(values[0]), _canonical_text(values[1])
            start = math.trunc(_number(values[2], position)) if len(values) == 3 else 1
            if start < 1 or start > len(haystack) + 1:
                raise FormulaError("#VALUE!", "Search start is out of range", position)
            if name == "SEARCH":
                needle, haystack = needle.casefold(), haystack.casefold()
            found = haystack.find(needle, start - 1)
            if found < 0:
                raise FormulaError("#VALUE!", f"{name} text was not found", position)
            return found + 1
        if name == "REPLACE":
            self._arity(name, values, 4, position)
            text = _canonical_text(values[0])
            start = math.trunc(_number(values[1], position))
            count = math.trunc(_number(values[2], position))
            if start < 1 or count < 0:
                raise FormulaError("#VALUE!", "REPLACE indices are invalid", position)
            return text[:start - 1] + _canonical_text(values[3]) + text[start - 1 + count:]
        if name in {"TEXTBEFORE", "TEXTAFTER"}:
            if len(values) not in {2, 3}:
                raise FormulaError("#VALUE!", f"{name} expects 2 or 3 arguments", position)
            text, delimiter = _canonical_text(values[0]), _canonical_text(values[1])
            instance = math.trunc(_number(values[2], position)) if len(values) == 3 else 1
            if not delimiter or instance == 0:
                raise FormulaError("#VALUE!", "Delimiter and instance are invalid", position)
            positions = [match.start() for match in re.finditer(re.escape(delimiter), text)]
            selected = instance - 1 if instance > 0 else len(positions) + instance
            if selected < 0 or selected >= len(positions):
                raise FormulaError("#N/A", "Delimiter occurrence was not found", position)
            cut = positions[selected]
            return text[:cut] if name == "TEXTBEFORE" else text[cut + len(delimiter):]
        if name in {"VALUE", "NUMBERVALUE"}:
            if name == "VALUE":
                self._arity(name, values, 1, position)
                decimal, group = ".", ","
            else:
                if len(values) not in {1, 2, 3}:
                    raise FormulaError("#VALUE!", "NUMBERVALUE expects 1 to 3 arguments", position)
                decimal = _canonical_text(values[1]) if len(values) > 1 else "."
                group = _canonical_text(values[2]) if len(values) > 2 else ","
            text = _canonical_text(values[0]).strip()
            if decimal == group or len(decimal) != 1 or len(group) > 1:
                raise FormulaError("#VALUE!", "Invalid numeric separators", position)
            percent = text.endswith("%")
            if percent:
                text = text[:-1].strip()
            if group:
                text = text.replace(group, "")
            if decimal != ".":
                text = text.replace(decimal, ".")
            try:
                result = float(text)
            except ValueError:
                raise FormulaError("#VALUE!", "Text is not a number", position)
            result = result / 100 if percent else result
            return int(result) if result.is_integer() else result
        if name == "TEXT":
            self._arity(name, values, 2, position)
            value, pattern = values[0], _canonical_text(values[1])
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                percent = "%" in pattern
                number = value * 100 if percent else value
                decimals = len(pattern.split(".", 1)[1].replace("%", "")) if "." in pattern else 0
                grouping = "," in pattern.split(".", 1)[0]
                rendered = f"{number:,.{decimals}f}" if grouping else f"{number:.{decimals}f}"
                return rendered + ("%" if percent else "")
            return _canonical_text(value)
        if name == "DATE":
            self._arity(name, values, 3, position)
            try:
                return date(int(values[0]), int(values[1]), int(values[2])).isoformat()
            except (TypeError, ValueError):
                raise FormulaError("#NUM!", "Invalid date", position)
        if name in {"YEAR", "MONTH", "DAY"}:
            self._arity(name, values, 1, position)
            try:
                parsed = date.fromisoformat(_canonical_text(values[0])[:10])
            except ValueError:
                raise FormulaError("#VALUE!", "Strict ISO date required", position)
            return {"YEAR": parsed.year, "MONTH": parsed.month, "DAY": parsed.day}[name]
        if name == "DAYS":
            self._arity(name, values, 2, position)
            try:
                end = date.fromisoformat(_canonical_text(values[0])[:10])
                start = date.fromisoformat(_canonical_text(values[1])[:10])
            except ValueError:
                raise FormulaError("#VALUE!", "Strict ISO dates required", position)
            return (end - start).days
        if name in {"DATEVALUE", "TIMEVALUE", "HOUR", "MINUTE", "SECOND"}:
            self._arity(name, values, 1, position)
            if name == "DATEVALUE":
                return _as_date(values[0], position).isoformat()
            parsed = _as_time(values[0], position)
            if name == "TIMEVALUE":
                return parsed.replace(microsecond=0).isoformat()
            return {"HOUR": parsed.hour, "MINUTE": parsed.minute, "SECOND": parsed.second}[name]
        if name == "TIME":
            self._arity(name, values, 3, position)
            parts = [math.trunc(_number(value, position)) for value in values]
            total = parts[0] * 3600 + parts[1] * 60 + parts[2]
            if total < 0:
                raise FormulaError("#NUM!", "TIME cannot be negative", position)
            total %= 86400
            return time(total // 3600, (total % 3600) // 60, total % 60).isoformat()
        if name in {"EDATE", "EOMONTH"}:
            self._arity(name, values, 2, position)
            start = _as_date(values[0], position)
            months = math.trunc(_number(values[1], position))
            return _add_months(start, months, end_of_month=name == "EOMONTH").isoformat()
        if name in {"WEEKDAY", "WEEKNUM", "ISOWEEKNUM"}:
            if name == "ISOWEEKNUM":
                self._arity(name, values, 1, position)
                return _as_date(values[0], position).isocalendar().week
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            parsed = _as_date(values[0], position)
            mode = math.trunc(_number(values[1], position)) if len(values) == 2 else 1
            weekday = parsed.weekday()
            if name == "WEEKDAY":
                if mode == 1: return (weekday + 1) % 7 + 1
                if mode == 2: return weekday + 1
                if mode == 3: return weekday
                starts = {11: 0, 12: 1, 13: 2, 14: 3, 15: 4, 16: 5, 17: 6}
                if mode in starts: return (weekday - starts[mode]) % 7 + 1
                raise FormulaError("#NUM!", "Unsupported WEEKDAY return type", position)
            if mode == 21:
                return parsed.isocalendar().week
            starts = {1: 6, 2: 0, 11: 0, 12: 1, 13: 2, 14: 3, 15: 4, 16: 5, 17: 6}
            if mode not in starts:
                raise FormulaError("#NUM!", "Unsupported WEEKNUM return type", position)
            year_start = date(parsed.year, 1, 1)
            offset = (year_start.weekday() - starts[mode]) % 7
            return ((parsed - year_start).days + offset) // 7 + 1
        if name == "DATEDIF":
            self._arity(name, values, 3, position)
            start, end = _as_date(values[0], position), _as_date(values[1], position)
            unit = _canonical_text(values[2]).upper()
            if end < start:
                raise FormulaError("#NUM!", "DATEDIF end precedes start", position)
            years = end.year - start.year - ((end.month, end.day) < (start.month, start.day))
            months = (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)
            if unit == "Y": return years
            if unit == "M": return months
            if unit == "D": return (end - start).days
            if unit == "YM": return months - years * 12
            if unit == "MD":
                anchor = _add_months(start, months)
                return (end - anchor).days
            if unit == "YD":
                anchor = date(end.year, start.month, min(start.day, calendar.monthrange(end.year, start.month)[1]))
                if anchor > end: anchor = date(end.year - 1, start.month, min(start.day, calendar.monthrange(end.year - 1, start.month)[1]))
                return (end - anchor).days
            raise FormulaError("#VALUE!", "Unsupported DATEDIF unit", position)
        if name in {"NETWORKDAYS", "NETWORKDAYS.INTL", "WORKDAY", "WORKDAY.INTL"}:
            international = name.endswith(".INTL")
            workday = name.startswith("WORKDAY")
            minimum, maximum = (2, 4) if international else (2, 3)
            if len(values) < minimum or len(values) > maximum:
                raise FormulaError("#VALUE!", f"Invalid {name} arguments", position)
            weekend_arg_index = 2 if international else None
            holiday_index = 3 if international else 2
            weekend_value = values[weekend_arg_index] if weekend_arg_index is not None and len(values) > weekend_arg_index else 1
            weekend_codes = {1:{5,6},2:{6,0},3:{0,1},4:{1,2},5:{2,3},6:{3,4},7:{4,5},11:{6},12:{0},13:{1},14:{2},15:{3},16:{4},17:{5}}
            if isinstance(weekend_value, str) and len(weekend_value) == 7 and set(weekend_value) <= {"0","1"}:
                weekends = {index for index, flag in enumerate(weekend_value) if flag == "1"}
            else:
                code = math.trunc(_number(weekend_value, position))
                if code not in weekend_codes:
                    raise FormulaError("#NUM!", "Invalid weekend code", position)
                weekends = weekend_codes[code]
            holidays = {_as_date(item, position) for item in _range_items(values[holiday_index]) if item not in {None, ""}} if len(values) > holiday_index else set()
            is_workday = lambda day: day.weekday() not in weekends and day not in holidays
            if workday:
                current = _as_date(values[0], position)
                remaining = abs(math.trunc(_number(values[1], position)))
                if remaining > 1000000:
                    raise FormulaError("#LIMIT!", "WORKDAY span is too large", position)
                direction = 1 if _number(values[1], position) >= 0 else -1
                while remaining:
                    current += timedelta(days=direction)
                    if is_workday(current): remaining -= 1
                return current.isoformat()
            start, end = _as_date(values[0], position), _as_date(values[1], position)
            if abs((end - start).days) > 1000000:
                raise FormulaError("#LIMIT!", "NETWORKDAYS span is too large", position)
            direction = 1 if end >= start else -1
            count, current = 0, start
            while True:
                if is_workday(current): count += direction
                if current == end: break
                current += timedelta(days=direction)
            return count
        if name == "YEARFRAC":
            if len(values) not in {2, 3}:
                raise FormulaError("#VALUE!", "YEARFRAC expects 2 or 3 arguments", position)
            start, end = _as_date(values[0], position), _as_date(values[1], position)
            basis = math.trunc(_number(values[2], position)) if len(values) == 3 else 0
            sign = 1
            if end < start: start, end, sign = end, start, -1
            if basis == 2: result = (end - start).days / 360
            elif basis == 3: result = (end - start).days / 365
            elif basis in {0, 4}:
                d1 = min(start.day, 30)
                d2 = min(end.day, 30) if basis == 4 or d1 == 30 else end.day
                result = ((end.year-start.year)*360 + (end.month-start.month)*30 + d2-d1) / 360
            elif basis == 1:
                if start.year == end.year:
                    result = (end-start).days / (366 if calendar.isleap(start.year) else 365)
                else:
                    result = (date(start.year+1,1,1)-start).days/(366 if calendar.isleap(start.year) else 365)
                    result += sum(1 for _year in range(start.year+1,end.year))
                    result += (end-date(end.year,1,1)).days/(366 if calendar.isleap(end.year) else 365)
            else: raise FormulaError("#NUM!", "YEARFRAC basis must be 0 through 4", position)
            return sign * result
        if name in {"DELTA", "GESTEP"}:
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            left = _number(values[0], position)
            right = _number(values[1], position) if len(values) == 2 else 0
            return 1 if (left == right if name == "DELTA" else left >= right) else 0
        if name in {"BIN2DEC", "BIN2HEX", "BIN2OCT", "DEC2BIN", "DEC2HEX", "DEC2OCT", "HEX2BIN", "HEX2DEC", "HEX2OCT", "OCT2BIN", "OCT2DEC", "OCT2HEX"}:
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            source, target = name.split("2")
            if target == "DEC" and len(values) != 1:
                raise FormulaError("#VALUE!", f"{name} does not accept places", position)
            number = math.trunc(_number(values[0], position)) if source == "DEC" and isinstance(values[0], (int, float)) and not isinstance(values[0], bool) else (_decode_base(values[0], source, position) if source != "DEC" else None)
            if source == "DEC" and number is None:
                raise FormulaError("#VALUE!", f"{name} requires a decimal number", position)
            if target == "DEC":
                return number
            places = math.trunc(_number(values[1], position)) if len(values) == 2 else None
            return _encode_base(number, target, places, position)
        if name in {"BITAND", "BITOR", "BITXOR", "BITLSHIFT", "BITRSHIFT"}:
            self._arity(name, values, 2, position)
            left, right = (_number(values[0], position), _number(values[1], position))
            if left != math.trunc(left) or right != math.trunc(right):
                raise FormulaError("#NUM!", "Bitwise arguments must be integers", position)
            left, right = int(left), int(right)
            limit = (1 << 48) - 1
            if left < 0 or left > limit or (name in {"BITAND","BITOR","BITXOR"} and (right < 0 or right > limit)):
                raise FormulaError("#NUM!", "Bitwise argument is outside the 48-bit range", position)
            if name == "BITAND": result = left & right
            elif name == "BITOR": result = left | right
            elif name == "BITXOR": result = left ^ right
            else:
                shift = right if name == "BITLSHIFT" else -right
                result = left << shift if shift >= 0 else left >> -shift
            if result < 0 or result > limit:
                raise FormulaError("#NUM!", "Bitwise result is outside the 48-bit range", position)
            return result
        if name == "CONVERT":
            self._arity(name, values, 3, position)
            value = _number(values[0], position)
            source, target = _canonical_text(values[1]).lower(), _canonical_text(values[2]).lower()
            factors = {"m": 1.0, "km": 1000.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344, "g": 1.0, "kg": 1000.0, "lb": 453.59237, "oz": 28.349523125}
            if source not in factors or target not in factors:
                raise FormulaError("#VALUE!", "Unsupported or incompatible conversion units", position)
            length = {"m", "km", "cm", "mm", "in", "ft", "yd", "mi"}
            if (source in length) != (target in length):
                raise FormulaError("#VALUE!", "Incompatible conversion units", position)
            return value * factors[source] / factors[target]
        if name in {"IRR", "MIRR", "NPER", "RATE", "XIRR", "XNPV"}:
            if name == "IRR":
                if not values:
                    raise FormulaError("#VALUE!", "IRR expects cash flows", position)
                flows = [_number(item, position) for item in self._flatten(values)]
                if not any(item < 0 for item in flows) or not any(item > 0 for item in flows):
                    raise FormulaError("#NUM!", "IRR requires positive and negative cash flows", position)
                return _bounded_root(lambda rate: sum(flow / ((1 + rate) ** index) for index, flow in enumerate(flows)), 0.1, position)
            if name == "MIRR":
                if len(values) < 3:
                    raise FormulaError("#VALUE!", "MIRR expects cash flows and two rates", position)
                finance_rate = _number(values[-2], position)
                reinvest_rate = _number(values[-1], position)
                flows = [_number(item, position) for item in self._flatten(values[:-2])]
                if len(flows) < 2 or not any(item < 0 for item in flows) or not any(item > 0 for item in flows):
                    raise FormulaError("#NUM!", "MIRR requires positive and negative cash flows", position)
                periods = len(flows) - 1
                present_negative = sum(flow / ((1 + finance_rate) ** index) for index, flow in enumerate(flows) if flow < 0)
                future_positive = sum(flow * ((1 + reinvest_rate) ** (periods - index)) for index, flow in enumerate(flows) if flow > 0)
                return (future_positive / -present_negative) ** (1 / periods) - 1
            if name == "NPER":
                if len(values) not in {3,4,5}:
                    raise FormulaError("#VALUE!", "NPER expects 3 to 5 arguments", position)
                rate, payment, present = map(lambda item: _number(item, position), values[:3])
                future = _number(values[3], position) if len(values)>3 else 0
                due = _number(values[4], position) if len(values)>4 else 0
                try:
                    return -(present + future) / payment if rate == 0 else math.log((payment*(1+rate*due)-future*rate)/(present*rate+payment*(1+rate*due))) / math.log(1+rate)
                except (ValueError, ZeroDivisionError):
                    raise FormulaError("#NUM!", "Invalid NPER inputs", position)
            if name == "RATE":
                if len(values) not in {3,4,5,6}:
                    raise FormulaError("#VALUE!", "RATE expects 3 to 6 arguments", position)
                nper, payment, present = map(lambda item: _number(item, position), values[:3])
                future = _number(values[3], position) if len(values)>3 else 0
                due = _number(values[4], position) if len(values)>4 else 0
                guess = _number(values[5], position) if len(values)>5 else 0.1
                def balance(rate):
                    factor=(1+rate)**nper
                    return present*factor + payment*(1+rate*due)*(factor-1)/rate + future if rate else present+payment*nper+future
                return _bounded_root(balance, guess, position)
            if name == "XNPV":
                self._arity(name, values, 3, position)
                rate = _number(values[0], position)
                flows = [_number(item, position) for item in _range_items(values[1])]
                date_values = values[2]
            else:
                if len(values) not in {2, 3}:
                    raise FormulaError("#VALUE!", "XIRR expects 2 or 3 arguments", position)
                flows = [_number(item, position) for item in _range_items(values[0])]
                date_values = values[1]
                guess = _number(values[2], position) if len(values) == 3 else 0.1
            dates = [_as_date(item, position) for item in _range_items(date_values)]
            if len(flows) != len(dates) or not flows:
                raise FormulaError("#VALUE!", "Cash-flow and date ranges must have equal size", position)
            if not any(item < 0 for item in flows) or not any(item > 0 for item in flows):
                raise FormulaError("#NUM!", f"{name} requires positive and negative cash flows", position)
            origin = dates[0]
            value_at = lambda rate: sum(flow / ((1+rate) ** ((day-origin).days/365)) for flow,day in zip(flows,dates))
            return value_at(rate) if name == "XNPV" else _bounded_root(value_at, guess, position)
        if name in {"PV", "FV", "PMT"}:
            if len(values) not in {3, 4, 5}:
                raise FormulaError("#VALUE!", f"{name} expects 3 to 5 arguments", position)
            rate, nper = _number(values[0], position), _number(values[1], position)
            third = _number(values[2], position)
            fourth = _number(values[3], position) if len(values) > 3 else 0
            due = _number(values[4], position) if len(values) > 4 else 0
            factor = (1 + rate) ** nper
            if name == "FV":
                return -(fourth * factor + third * (1 + rate * due) * (factor - 1) / rate) if rate else -(fourth + third * nper)
            if name == "PV":
                return -(fourth + third * (1 + rate * due) * (factor - 1) / rate) / factor if rate else -(fourth + third * nper)
            if factor == 1:
                return -(third + fourth) / nper
            return -(third * factor + fourth) * rate / ((1 + rate * due) * (factor - 1))
        if name == "NPV":
            if len(values) < 2:
                raise FormulaError("#VALUE!", "NPV expects a rate and cash flows", position)
            rate = _number(values[0], position)
            flows = [_number(value, position) for value in self._flatten(values[1:]) if value is not None and value != ""]
            return sum(flow / ((1 + rate) ** (index + 1)) for index, flow in enumerate(flows))
        if name in {"NOW", "TODAY"}:
            self._arity(name, values, 0, position)
            self.volatile = True
            current = self.now.astimezone(timezone.utc)
            if name == "TODAY":
                return current.date().isoformat()
            return current.isoformat(timespec="seconds").replace("+00:00", "Z")
        raise FormulaError("#NAME?", f"Unknown function: {name}", position)

    @staticmethod
    def _arity(name: str, values: list[Any], expected: int, position: int):
        if len(values) != expected:
            raise FormulaError("#VALUE!", f"{name} expects {expected} arguments", position)


def evaluate_formula(source: str, slots: list[Any], *, current_index: int | None = None, cols: int = 4,
                     now: datetime | None = None, resolver: FormulaResolver | None = None) -> EvaluationResult:
    ast = parse_formula(source)
    evaluator = Evaluator(slots, current_index=current_index, cols=cols, now=now, resolver=resolver)
    value = evaluator.evaluate(ast)
    if isinstance(value, RangeValue):
        raise FormulaError("#VALUE!", "A range cannot be a top-level formula result")
    if isinstance(value, float) and not math.isfinite(value):
        raise FormulaError("#NUM!", "Formula result is not finite")
    return EvaluationResult(
        value=value,
        resolved_value_type=_result_type(value),
        dependencies=evaluator.dependencies,
        warnings=evaluator.warnings,
        volatile=evaluator.volatile,
    )


def _walk_references(node, refs: list[tuple[str, bool, int, bool]], calls: set[str]) -> None:
    kind = node[0]
    if kind in {"literal", "error"}:
        return
    if kind == "reference":
        refs.append((node[1], node[2], node[3], False))
        return
    if kind == "range":
        start = parse_cell_ref(node[1].replace("$", ""))
        end = parse_cell_ref(node[2].replace("$", ""))
        if not start or not end:
            raise FormulaError("#REF!", "Invalid range reference", node[3])
        min_col, max_col = sorted((start["col"], end["col"]))
        min_row, max_row = sorted((start["row"], end["row"]))
        if (max_col - min_col + 1) * (max_row - min_row + 1) > 10000:
            raise FormulaError("#LIMIT!", "Range exceeds 10000 positions", node[3])
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                refs.append((coord_to_cell_ref({"col": col, "row": row}), True, node[3], True))
        return
    if kind == "call":
        calls.add(node[1])
        for arg in node[2]:
            _walk_references(arg, refs, calls)
        return
    if kind == "unary":
        _walk_references(node[2], refs, calls)
        return
    if kind == "binary":
        _walk_references(node[2], refs, calls)
        _walk_references(node[3], refs, calls)


def analyze_formula(source: str, slots: list[Any], *, current_index: int | None = None, cols: int = 4,
                    resolver: FormulaResolver | None = None) -> dict[str, Any]:
    """Parse formula source and resolve direct scalar dependencies without evaluating."""
    ast = parse_formula(source)
    refs: list[tuple[str, bool, int, bool]] = []
    calls: set[str] = set()
    _walk_references(ast, refs, calls)
    dependency_indices: list[int] = []
    dependencies: list[str] = []
    warnings: list[str] = []
    resolver = resolver or FormulaResolver(slots, cols=cols)
    for ref, coordinate, position, allow_missing in refs:
        clean_ref = ref.replace("$", "") if coordinate else ref
        match = resolver.find(clean_ref)
        if not match:
            if allow_missing:
                continue
            code = "#REF!" if coordinate else "#NAME?"
            raise FormulaError(code, f"Value reference not found: {clean_ref}", position)
        index = int(match["index"])
        dependency = coord_to_cell_ref(match.get("coord"))
        if index not in dependency_indices:
            dependency_indices.append(index)
        if dependency and dependency not in dependencies:
            dependencies.append(dependency)
        warning = value_ref_warning(match)
        if warning and warning not in warnings:
            warnings.append(warning)
    return {
        "ast": ast,
        "dependency_indices": dependency_indices,
        "dependencies": dependencies,
        "warnings": warnings,
        "volatile": bool(calls & {"NOW", "TODAY"}),
    }


def _slot_sort_key(slots: list[Any], index: int) -> tuple[int, int, int]:
    slot = slots[index] if 0 <= index < len(slots) and isinstance(slots[index], dict) else {}
    try:
        row = int(slot.get("row", 0))
        col = int(slot.get("col", 0))
    except (TypeError, ValueError):
        row, col = 0, 0
    return row, col, index


def _cycle_nodes(nodes: set[int], edges: dict[int, set[int]]) -> set[int]:
    """Return nodes in strongly connected components that are actual cycles."""
    index_counter = [0]
    indices: dict[int, int] = {}
    lowlinks: dict[int, int] = {}
    stack: list[int] = []
    on_stack: set[int] = set()
    cycles: set[int] = set()

    def strong_connect(node: int) -> None:
        indices[node] = index_counter[0]
        lowlinks[node] = index_counter[0]
        index_counter[0] += 1
        stack.append(node)
        on_stack.add(node)
        for dependency in edges.get(node, set()):
            if dependency not in nodes:
                continue
            if dependency not in indices:
                strong_connect(dependency)
                lowlinks[node] = min(lowlinks[node], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[dependency])
        if lowlinks[node] != indices[node]:
            return
        component: list[int] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == node:
                break
        if len(component) > 1 or (len(component) == 1 and component[0] in edges.get(component[0], set())):
            cycles.update(component)

    for node in sorted(nodes):
        if node not in indices:
            strong_connect(node)
    return cycles


def recalculate_layout(
    layout: dict[str, Any],
    *,
    root_indices: set[int] | None = None,
    cols: int = 4,
    calculated_at: str,
    now: datetime | None = None,
    calculation_id: str | None = None,
    record_history: bool = True,
) -> dict[str, Any]:
    """Recalculate one affected formula generation in place without persistence or events."""
    slots = layout.get("slots", []) if isinstance(layout, dict) else []
    formula_indices = {
        index for index, slot in enumerate(slots)
        if isinstance(slot, dict) and isinstance(slot.get("formula"), dict) and slot["formula"].get("source")
    }
    analyses: dict[int, dict[str, Any]] = {}
    analysis_errors: dict[int, FormulaError] = {}
    edges: dict[int, set[int]] = {index: set() for index in formula_indices}
    reverse: dict[int, set[int]] = {}
    resolver = FormulaResolver(slots, cols=cols)
    for index in formula_indices:
        source = slots[index]["formula"]["source"]
        try:
            analysis = analyze_formula(source, slots, current_index=index, cols=cols, resolver=resolver)
            analyses[index] = analysis
            for dependency_index in analysis["dependency_indices"]:
                reverse.setdefault(dependency_index, set()).add(index)
                if dependency_index in formula_indices:
                    edges[index].add(dependency_index)
        except FormulaError as exc:
            analysis_errors[index] = exc

    if root_indices is None:
        affected = set(formula_indices)
    else:
        affected = {index for index in root_indices if index in formula_indices}
        pending = list(root_indices)
        while pending:
            root = pending.pop(0)
            for dependent in reverse.get(root, set()):
                if dependent not in affected:
                    affected.add(dependent)
                    pending.append(dependent)

    old_slots = {index: copy.deepcopy(slots[index]) for index in affected}
    cycles = _cycle_nodes(affected, edges)
    changed: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index in sorted(cycles, key=lambda item: _slot_sort_key(slots, item)):
        error = FormulaError("#CYCLE!", "Circular formula dependency detected")
        analysis = analyses.get(index, {})
        slots[index]["formula_state"] = formula_error_state(
            error,
            calculated_at=calculated_at,
            dependencies=analysis.get("dependencies"),
            warnings=analysis.get("warnings"),
            volatile=analysis.get("volatile", False),
        )
        errors.append({"index": index, **error.payload()})

    remaining = affected - cycles
    indegree = {
        index: len({dep for dep in edges.get(index, set()) if dep in remaining})
        for index in remaining
    }
    ready = [(_slot_sort_key(slots, index), index) for index, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        _key, index = heapq.heappop(ready)
        order.append(index)
        for dependent in reverse.get(index, set()):
            if dependent not in indegree:
                continue
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(ready, (_slot_sort_key(slots, dependent), dependent))

    for index in order:
        slot = slots[index]
        old_slot = old_slots[index]
        analysis = analyses.get(index, {})
        try:
            if index in analysis_errors:
                raise analysis_errors[index]
            source = slot["formula"]["source"]
            result = evaluate_formula(source, slots, current_index=None, cols=cols, now=now, resolver=resolver)
            value, resolved_type = coerce_formula_result(result.value, slot.get("value_type", "auto"))
            slot["value"] = value
            slot["resolved_value_type"] = resolved_type
            slot["formula_state"] = formula_ok_state(result, calculated_at=calculated_at)
            slot["formula_updated_at"] = calculated_at
            value_changed = (
                old_slot.get("value") != value
                or old_slot.get("resolved_value_type") != resolved_type
            )
            if value_changed:
                slot["updated_at"] = calculated_at
                if record_history:
                    append_value_history(slot, calculated_at)
                changed.append({"index": index, "old_slot": old_slot, "new_slot": copy.deepcopy(slot)})
        except FormulaError as exc:
            slot["formula_state"] = formula_error_state(
                exc,
                calculated_at=calculated_at,
                dependencies=analysis.get("dependencies"),
                warnings=analysis.get("warnings"),
                volatile=analysis.get("volatile", False),
            )
            slot["formula_updated_at"] = calculated_at
            errors.append({"index": index, **exc.payload()})

    calculation_id = calculation_id or str(uuid.uuid4())
    return {
        "calculation_id": calculation_id,
        "evaluated_count": len(affected),
        "changed_count": len(changed),
        "error_count": len(errors),
        "changed": changed,
        "errors": errors,
        "affected_indices": sorted(affected, key=lambda item: _slot_sort_key(slots, item)),
    }
