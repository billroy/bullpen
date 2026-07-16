"""Representative acceptance benchmark for server-owned formula generations."""

from time import perf_counter

from server.formulas import recalculate_layout


def _value(col, row, value=1):
    return {
        "type": "value",
        "name": "",
        "col": col,
        "row": row,
        "value": value,
        "value_type": "auto",
        "resolved_value_type": "number",
        "save_history": False,
    }


def _formula(col, row, source):
    slot = _value(col, row, 0)
    slot["formula"] = {"source": source, "version": 1}
    slot["formula_state"] = {"status": "pending"}
    return slot


def test_acceptance_dataset_generation_stays_within_two_second_budget():
    """5,000 cells / 1,000 formulas / depth 500 / sparse 100x100 range."""
    slots = [_value(0, 0, 1)]

    # A 500-deep chain rooted at A1.
    for row in range(1, 501):
        slots.append(_formula(0, row, f"=A{row}+1"))

    # Another 499 formulas affected directly by the same root.
    for row in range(499):
        slots.append(_formula(1, row, "=$A$1+1"))

    # The maximum-size sparse rectangular range from the acceptance dataset.
    slots.append(_formula(1, 499, "=SUM(C1:CX100)"))

    # Fill the workspace to 5,000 Value cells outside the sparse range.
    for index in range(3999):
        slots.append(_value(200 + (index % 100), index // 100, index))

    layout = {"slots": slots}
    started = perf_counter()
    result = recalculate_layout(
        layout,
        root_indices={0},
        calculated_at="2026-07-16T12:00:00Z",
        record_history=False,
    )
    elapsed = perf_counter() - started

    assert len(slots) == 5000
    assert sum(1 for slot in slots if slot.get("formula")) == 1000
    assert result["evaluated_count"] == 999
    assert result["error_count"] == 0
    assert layout["slots"][500]["value"] == 501
    assert elapsed < 2.0, f"acceptance generation took {elapsed:.3f}s"
