"""Regression checks for worker-group drag/drop and clipboard operations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_exposes_group_worker_socket_events():
    text = _read("static/app.js")
    assert "function moveWorkerGroup(moves)" in text
    assert "socket.emit('worker:move_group'" in text
    assert "function pasteWorkerGroup(items)" in text
    assert "socket.emit('worker:paste_group'" in text


def test_bullpen_tab_builds_pass_reachable_groups_for_drag_and_copy():
    text = _read("static/components/BullpenTab.js")
    assert "workerGroupSlots(startSlot)" in text
    assert "passTargetsForSlot(slotIndex)" in text
    assert "buildGroupMovePlan(sourceSlot, destinationCoord," in text
    assert "canDropWorkerAtSlot(sourceSlot, targetSlot, e)" in text
    assert "moveWorkerGroupToCoord(sourceSlot, coord)" in text
    assert "this.$root.moveWorkerGroup(plan.moves)" in text
    assert "Copied worker group (" in text


def test_bullpen_tab_group_detection_includes_inbound_pass_links():
    text = _read("static/components/BullpenTab.js")
    assert "passSourcesForSlot(slotIndex)" in text
    assert "this.passTargetsForSlot(item.slotIndex).includes(target)" in text
    assert "new Set([...this.passTargetsForSlot(slot), ...this.passSourcesForSlot(slot)])" in text


def test_bullpen_tab_pastes_group_workers_with_relative_offsets():
    text = _read("static/components/BullpenTab.js")
    assert "clipboardTargetsForCoord(coord)" in text
    assert "this.$root.pasteWorkerGroup(targets)" in text
    assert "Cannot paste worker group here" in text


def test_bullpen_tab_worker_clipboard_preserves_shell_fields():
    text = _read("static/components/BullpenTab.js")
    assert "workerFieldsForClipboard(worker)" in text
    assert "'type', 'profile'" in text
    assert "'command', 'cwd', 'timeout_seconds', 'ticket_delivery', 'env'" in text
    assert "copy[key] = JSON.parse(JSON.stringify(worker[key]));" in text


def test_worker_card_uses_group_drag_payload_and_delegates_drop_validation():
    text = _read("static/components/WorkerCard.js")
    assert "'buildWorkerDragPayload'" in text
    assert "'buildWorkerDragImage'" in text
    assert "'canDropWorkerAtSlot'" in text
    assert "'dropWorkerOnSlot'" in text
    assert "'updateSingletonWorkerDrag'" in text
    assert "'endSingletonWorkerDrag'" in text
    assert "'cancelSingletonWorkerDrag'" in text
    assert "'application/x-worker-group'" in text
    assert "@pointerdown=\"onPointerDown\"" in text
    assert "@pointermove=\"onPointerMove\"" in text
    assert "@lostpointercapture=\"onPointerLostCapture\"" in text
    assert "pointerWorkerDrag" in text
    assert "shiftDragIntent" in text
    assert "const singleton = !!(e.shiftKey || this.shiftDragIntent)" in text
    assert "window._bullpenWorkerDrag = payload" in text
    assert "this.buildWorkerDragPayload(this.slotIndex, {" in text
    assert "clientX: e.clientX" in text
    assert "clientY: e.clientY" in text
    assert "this.buildWorkerDragImage(this.slotIndex" in text
    assert "e.dataTransfer.setDragImage(dragImage.element, offsetX, offsetY)" in text
    assert "removeDragImage()" in text
    assert "this.canDropWorkerAtSlot(source, this.slotIndex, e)" in text
    assert "const handled = this.dropWorkerOnSlot(dragSource, this.slotIndex, e)" in text
    assert "if (handled) {" in text


def test_bullpen_tab_builds_composite_drag_image_for_worker_groups():
    text = _read("static/components/BullpenTab.js")
    assert ":build-worker-drag-image=\"buildWorkerDragImage\"" in text
    assert "buildWorkerDragImage(slotIndex, pointer = {}," in text
    assert "worker-group-drag-image" in text
    assert "workerElementForSlot(slotIndex)" in text
    assert "cardEl ? cardEl.cloneNode(true)" in text


def test_worker_drag_uses_pointer_projected_drop_coordinates():
    text = _read("static/components/BullpenTab.js")
    assert "pointerOffset" in text
    assert "singleton: true" in text
    assert "_workerDragPointerOffset(slotIndex, pointer = {})" in text
    assert "_workerDragCoordFromEvent(e)" in text
    assert "const x = e.clientX - rect.left - this.headerWidth - offsetX" in text
    assert "const y = e.clientY - rect.top - this.headerHeight - offsetY" in text
    assert "canDropWorkerAtSlot(sourceSlot, targetSlot, e)" in text
    assert "dropWorkerOnSlot(sourceSlot, targetSlot, e)" in text
    assert "const dropCoord = this._workerDragCoordFromEvent(e) || coord" in text
    assert "const coord = this._workerDragCoordFromEvent(e)" in text


def test_shift_worker_drag_uses_single_card_move_or_swap_semantics():
    text = _read("static/components/BullpenTab.js")
    assert "_isSingletonWorkerDrag()" in text
    assert "return !!window._bullpenWorkerDrag || types.includes('application/x-worker-slot')" in text
    assert "moveWorkerDragToCoord(sourceSlot, coord)" in text
    assert "moveSingleWorkerToCoord(sourceSlot, coord)" in text
    assert "updateSingletonWorkerDrag(sourceSlot, e)" in text
    assert "endSingletonWorkerDrag(sourceSlot, e)" in text
    assert "cancelSingletonWorkerDrag()" in text
    assert "if (this._isSingletonWorkerDrag()) {" in text
    assert "this.$root.moveWorker(source, occupied.slotIndex)" in text
    assert "this.$root.moveWorker(source, coord)" in text
    assert ":update-singleton-worker-drag=\"updateSingletonWorkerDrag\"" in text
    assert ":end-singleton-worker-drag=\"endSingletonWorkerDrag\"" in text
    assert ":cancel-singleton-worker-drag=\"cancelSingletonWorkerDrag\"" in text
