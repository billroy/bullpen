"""Monotonic sequencing for full-layout replacement events."""

from __future__ import annotations

from typing import Any


def next_revision(value: object) -> int:
    try:
        current = int(value)
    except (TypeError, ValueError):
        current = 0
    return max(0, current) + 1


def bump_layout_revision(layout: dict[str, Any]) -> int:
    """Advance and store the sequence for one durable layout mutation."""
    revision = next_revision(layout.get("workspace_revision"))
    layout["workspace_revision"] = revision
    return revision
