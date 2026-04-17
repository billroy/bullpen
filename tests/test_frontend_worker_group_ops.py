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
    assert "buildGroupMovePlan(sourceSlot, destinationCoord)" in text
    assert "canDropWorkerAtSlot(sourceSlot, targetSlot)" in text
    assert "moveWorkerGroupToCoord(sourceSlot, coord)" in text
    assert "this.$root.moveWorkerGroup(plan.moves)" in text
    assert "Copied worker group (" in text


def test_bullpen_tab_pastes_group_workers_with_relative_offsets():
    text = _read("static/components/BullpenTab.js")
    assert "clipboardTargetsForCoord(coord)" in text
    assert "this.$root.pasteWorkerGroup(targets)" in text
    assert "Cannot paste worker group here" in text


def test_worker_card_uses_group_drag_payload_and_delegates_drop_validation():
    text = _read("static/components/WorkerCard.js")
    assert "'buildWorkerDragPayload'" in text
    assert "'canDropWorkerAtSlot'" in text
    assert "'dropWorkerOnSlot'" in text
    assert "'application/x-worker-group'" in text
    assert "window._bullpenWorkerDrag = payload" in text
    assert "this.canDropWorkerAtSlot(source, this.slotIndex)" in text
    assert "this.dropWorkerOnSlot(dragSource, this.slotIndex)" in text
