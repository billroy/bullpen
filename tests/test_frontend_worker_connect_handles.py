"""Regression checks for draggable pass-direction connection handles on worker cards."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_bullpen_tab_computes_neighbor_slots_and_passes_them_to_card():
    text = _read("static/components/BullpenTab.js")
    assert "neighborSlotsMap()" in text
    assert ":neighbor-slots=\"neighborSlotsMap[i - 1]\"" in text
    # Edge and empty-cell detection logic must be present
    assert "r > 0" in text and "r < rows - 1" in text
    assert "c > 0" in text and "c < cols - 1" in text
    # Neighbor is null when the cell is empty
    assert "slots[up] ? up : null" in text
    assert "slots[down] ? down : null" in text


def test_worker_card_accepts_neighbor_slots_prop():
    text = _read("static/components/WorkerCard.js")
    assert "'neighborSlots'" in text
    assert "canConnect(dir)" in text
    assert "passConnectsToNeighbor" in text


def test_worker_card_renders_drag_handles_only_for_existing_neighbors():
    text = _read("static/components/WorkerCard.js")
    assert "v-for=\"dir in ['up','down','left','right']\"" in text
    assert "v-if=\"canConnect(dir)\"" in text
    assert "class=\"connect-handle\"" in text
    assert "@dragstart.stop=\"onHandleDragStart(dir, $event)\"" in text
    assert "@dragend.stop=\"onHandleDragEnd\"" in text


def test_worker_card_handle_dragstart_sets_connect_mime_and_target():
    text = _read("static/components/WorkerCard.js")
    assert "onHandleDragStart(dir, e)" in text
    assert "'application/x-worker-connect'" in text
    # Payload must include target slot so dragover handlers can identify the
    # intended drop destination without reading dataTransfer (restricted).
    assert "target: this.neighborSlots[dir]" in text
    assert "window._bullpenConnectDrag" in text


def test_worker_card_onDragOver_highlights_only_intended_target():
    text = _read("static/components/WorkerCard.js")
    # Only preventDefault on the intended neighbor slot so non-targets show
    # a "no-drop" cursor.
    assert "drag.target === this.slotIndex" in text
    assert "this.connectTarget = true" in text
    assert "dropEffect = 'none'" in text


def test_worker_card_onDrop_updates_disposition_for_source_slot():
    text = _read("static/components/WorkerCard.js")
    assert "'application/x-worker-connect'" in text
    assert "saveWorkerConfig" in text
    assert "'pass:' + payload.direction" in text
    assert "slot: payload.source" in text


def test_worker_card_connect_target_class_toggled_on_card():
    text = _read("static/components/WorkerCard.js")
    assert "'connect-target': connectTarget" in text


def test_pass_indicator_gets_connected_class_when_neighbor_exists():
    text = _read("static/components/WorkerCard.js")
    assert "'pass-connected': passConnectsToNeighbor" in text


def test_connect_handle_and_target_styles_exist():
    text = _read("static/style.css")
    assert ".connect-handle {" in text
    assert ".connect-handle-up {" in text
    assert ".connect-handle-down {" in text
    assert ".connect-handle-left {" in text
    assert ".connect-handle-right {" in text
    # Hover-reveal: handles are invisible until the card is hovered
    assert ".worker-card:hover .connect-handle" in text
    # Connect-target highlight on the adjacent card during drag
    assert ".worker-card.connect-target {" in text


def test_pass_connected_pill_renders_in_gutter():
    text = _read("static/style.css")
    assert ".pass-indicator.pass-connected {" in text
    # Pills sit outside the card footprint (negative offsets = gutter).
    assert ".pass-up.pass-connected {" in text
    assert ".pass-down.pass-connected {" in text
    assert ".pass-left.pass-connected {" in text
    assert ".pass-right.pass-connected {" in text
    # Card must allow children to render into the gutter
    assert "overflow: visible;" in text


def test_worker_config_modal_disables_pass_options_without_neighbor():
    text = _read("static/components/WorkerConfigModal.js")
    assert "'gridRows'" in text and "'gridCols'" in text
    assert "passAvailability()" in text
    assert ":disabled=\"!passAvailability.up\"" in text
    assert ":disabled=\"!passAvailability.down\"" in text
    assert ":disabled=\"!passAvailability.left\"" in text
    assert ":disabled=\"!passAvailability.right\"" in text


def test_app_wires_grid_rows_cols_into_worker_config_modal():
    text = _read("static/app.js")
    assert ":grid-rows=\"state.config.grid?.rows || 4\"" in text
    assert ":grid-cols=\"state.config.grid?.cols || 6\"" in text
