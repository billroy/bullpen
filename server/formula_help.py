"""Lazy, read-only formula handbook data derived from checked-in sources."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import re
from typing import Any

from server.formula_functions import FORMULA_FUNCTIONS, FORMULA_FUNCTIONS_BY_NAME


_REFERENCE_PATH = Path(__file__).resolve().parents[1] / "docs" / "function-reference.md"
_FUNCTION_HEADING_RE = re.compile(r"^### `([^`]+)`\s*$", re.MULTILINE)
_SYNTAX_RE = re.compile(r"^\*\*Syntax:\*\*\s*`([^`]+)`\s*$", re.MULTILINE)
_EXAMPLE_RE = re.compile(r"^\*\*Example:\*\*\s*`([^`]+)`\s*$", re.MULTILINE)


def formula_help_index() -> list[dict[str, Any]]:
    """Return the compact catalog needed by the client-side search view."""
    return [
        {
            "name": item["name"],
            "category": item["category"],
            "signature": item["signature"],
            "summary": item["summary"],
        }
        for item in FORMULA_FUNCTIONS
    ]


@lru_cache(maxsize=1)
def _reference_sections() -> dict[str, str]:
    """Read and split the long-form reference only when detail is requested."""
    text = _REFERENCE_PATH.read_text(encoding="utf-8")
    matches = list(_FUNCTION_HEADING_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1).upper()] = text[match.end():end].strip()
    return sections


def _description_markdown(section: str) -> str:
    """Remove fields rendered separately by the compact reference card."""
    description = _SYNTAX_RE.sub("", section)
    description = _EXAMPLE_RE.sub("", description)
    return re.sub(r"\n{3,}", "\n\n", description).strip()


def formula_function_help(name: object) -> dict[str, Any] | None:
    """Return one function's detail without loading other detail on the client."""
    normalized = str(name or "").strip().upper()
    entry = FORMULA_FUNCTIONS_BY_NAME.get(normalized)
    if entry is None:
        return None

    section = _reference_sections().get(normalized, "")
    syntax_match = _SYNTAX_RE.search(section)
    example_match = _EXAMPLE_RE.search(section)
    examples = [example_match.group(1)] if example_match else list(entry.get("examples") or [])

    return {
        "name": entry["name"],
        "category": entry["category"],
        "signature": syntax_match.group(1) if syntax_match else entry["signature"],
        "summary": entry["summary"],
        "accepts_ranges": bool(entry.get("accepts_ranges")),
        "documentation": _description_markdown(section) or entry["summary"],
        "examples": examples,
    }


def reference_function_names() -> frozenset[str]:
    """Expose reference coverage for validation tests."""
    return frozenset(_reference_sections())
