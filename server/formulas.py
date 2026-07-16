"""Safe parsing and scalar evaluation for Value worker formulas."""

from __future__ import annotations

import math
import re
import copy
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from server.values import append_value_history, coord_to_cell_ref, find_value_by_ref, parse_cell_ref, value_ref_warning


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


_NUMBER_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_COORD_RE = re.compile(r"\$?[A-Za-z]+\$?\d+")
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
            if end == len(text) or not (text[end].isalnum() or text[end] in "_."):
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


class Evaluator:
    def __init__(self, slots: list[Any], *, current_index: int | None = None, cols: int = 4, now: datetime | None = None):
        self.slots = slots
        self.current_index = current_index
        self.cols = cols
        self.dependencies: list[str] = []
        self.warnings: list[str] = []
        self.volatile = False
        self.now = now or datetime.now(timezone.utc)

    def evaluate(self, node):
        kind = node[0]
        if kind == "literal":
            return node[1]
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
        match = find_value_by_ref(self.slots, clean_ref, cols=self.cols)
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
                match = find_value_by_ref(self.slots, ref, cols=self.cols)
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
        return RangeValue(values)

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
        if name == "ABS":
            self._arity(name, values, 1, position)
            return abs(_number(values[0], position))
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
        if name in {"DELTA", "GESTEP"}:
            if len(values) not in {1, 2}:
                raise FormulaError("#VALUE!", f"{name} expects 1 or 2 arguments", position)
            left = _number(values[0], position)
            right = _number(values[1], position) if len(values) == 2 else 0
            return 1 if (left == right if name == "DELTA" else left >= right) else 0
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


def evaluate_formula(source: str, slots: list[Any], *, current_index: int | None = None, cols: int = 4, now: datetime | None = None) -> EvaluationResult:
    ast = parse_formula(source)
    evaluator = Evaluator(slots, current_index=current_index, cols=cols, now=now)
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


def analyze_formula(source: str, slots: list[Any], *, current_index: int | None = None, cols: int = 4) -> dict[str, Any]:
    """Parse formula source and resolve direct scalar dependencies without evaluating."""
    ast = parse_formula(source)
    refs: list[tuple[str, bool, int, bool]] = []
    calls: set[str] = set()
    _walk_references(ast, refs, calls)
    dependency_indices: list[int] = []
    dependencies: list[str] = []
    warnings: list[str] = []
    for ref, coordinate, position, allow_missing in refs:
        clean_ref = ref.replace("$", "") if coordinate else ref
        match = find_value_by_ref(slots, clean_ref, cols=cols)
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
    for index in formula_indices:
        source = slots[index]["formula"]["source"]
        try:
            analysis = analyze_formula(source, slots, current_index=index, cols=cols)
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
    ready = sorted((index for index, degree in indegree.items() if degree == 0), key=lambda item: _slot_sort_key(slots, item))
    order: list[int] = []
    while ready:
        index = ready.pop(0)
        order.append(index)
        for dependent in reverse.get(index, set()):
            if dependent not in indegree:
                continue
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
                ready.sort(key=lambda item: _slot_sort_key(slots, item))

    for index in order:
        slot = slots[index]
        old_slot = old_slots[index]
        analysis = analyses.get(index, {})
        try:
            if index in analysis_errors:
                raise analysis_errors[index]
            source = slot["formula"]["source"]
            result = evaluate_formula(source, slots, current_index=None, cols=cols, now=now)
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
