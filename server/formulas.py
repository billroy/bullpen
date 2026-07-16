"""Safe parsing and scalar evaluation for Value worker formulas."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable

from server.values import coord_to_cell_ref, find_value_by_ref, value_ref_warning


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


def formula_error_state(error: FormulaError, *, calculated_at: str = "") -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": error.code,
        "error_message": error.message[:512],
        "error_position": error.position,
        "calculated_at": calculated_at,
        "dependencies": [],
        "warnings": [],
        "volatile": False,
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
                raise FormulaError("#PARSE!", "Ranges are introduced in formula tranche 3", token.position)
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
    if isinstance(value, float) and not math.isfinite(value):
        raise FormulaError("#NUM!", "Formula result is not finite")
    return EvaluationResult(
        value=value,
        resolved_value_type=_result_type(value),
        dependencies=evaluator.dependencies,
        warnings=evaluator.warnings,
        volatile=evaluator.volatile,
    )
