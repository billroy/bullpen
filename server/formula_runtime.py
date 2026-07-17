"""Shared formula-generation lifecycle helpers.

This module owns the calculation/revision contract. Callers remain responsible
for persisting the returned layout and for delivering any post-commit effects.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable

from server import formulas
from server.layout_runtime import next_revision


@dataclass
class FormulaGeneration:
    calculation: dict[str, Any]
    event_layout: dict[str, Any]
    revision: int


def calculate_generation(
    layout: dict[str, Any],
    *,
    root_indices: Iterable[int],
    cols: int,
    calculated_at: str,
    now=None,
    timezone_name: str | None = "UTC",
    calculation_id: str | None = None,
    record_history: bool = True,
) -> FormulaGeneration:
    """Calculate one generation and attach its monotonic sequence in place."""
    calculation = formulas.recalculate_layout(
        layout,
        root_indices=set(root_indices),
        cols=cols,
        calculated_at=calculated_at,
        now=now,
        timezone_name=timezone_name,
        calculation_id=calculation_id,
        record_history=record_history,
    )
    formula_revision = next_revision(layout.get("formula_revision"))
    workspace_revision = next_revision(layout.get("workspace_revision"))
    layout["formula_revision"] = formula_revision
    layout["workspace_revision"] = workspace_revision
    event_layout = copy.deepcopy(layout)
    event_layout["calculation"] = {
        "formula_revision": formula_revision,
        "workspace_revision": workspace_revision,
        "calculation_id": calculation["calculation_id"],
        "evaluated_count": calculation["evaluated_count"],
        "changed_count": calculation["changed_count"],
        "error_count": calculation["error_count"],
        "errors": calculation["errors"][:100],
    }
    return FormulaGeneration(
        calculation=calculation,
        event_layout=event_layout,
        revision=workspace_revision,
    )
