"""Regression checks for worker grid row height resizing."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_card_accepts_selected_card_height_and_resize_props():
    text = _read("static/components/WorkerCard.js")
    assert "'cardHeight'" in text
    assert "'isSelected'" in text
    assert "'isVerticalResizing'" in text
    assert "'workspaceId'" in text
    assert "'requestOutputCatchup'" in text
    assert "'vertical-resize-start'" in text
    assert "effectiveLayoutMode()" in text
    assert "this.ensureOutputCatchup();" in text
    assert "outputRequestToken()" in text
    assert "this.requestOutputCatchup(this.slotIndex, {" in text


def test_worker_card_bottom_hover_prefers_vertical_resize_outside_pass_down_zone():
    text = _read("static/components/WorkerCard.js")
    assert "v-if=\"showsVerticalResizeControl\"" in text
    assert "hasExpandableCardContent()" in text
    assert "return this.isPaused || this.taskQueueCount > 0 || this.workerState !== 'idle';" in text
    assert "showsVerticalResizeControl()" in text
    assert "return this.isSelected && this.hasExpandableCardContent;" in text
    assert "updateCardHoverState(e)" in text
    assert "onCardMouseMove(e)" in text
    assert "this.updateCardHoverState(e);" in text
    assert "onPointerMove(e)" in text
    assert "const downHandleZone = this.canConnect('down') && Math.abs(x - (rect.width / 2)) <= 18;" in text
    assert "if (this.showsVerticalResizeControl && y >= rect.height - threshold && !downHandleZone) {" in text
    assert "this.hoveredVerticalResize = true;" in text
    assert "this.hoveredHandle = null;" in text
    assert "if (!this.showsVerticalResizeControl || e.button !== 0) return;" in text


def test_bullpen_tab_tracks_sparse_row_height_overrides():
    text = _read("static/components/BullpenTab.js")
    assert "pendingRowHeights: null" in text
    assert "rowHeightOverrides()" in text
    assert "normalizeRowHeights(value, baseHeight = this.rowHeight)" in text
    assert "rowHeightForRow(row)" in text
    assert "rowPixelTop(row)" in text
    assert "rowFromPixel(y)" in text
    assert "persistSingleRowHeight(row, height)" in text


def test_bullpen_tab_toolbar_can_reset_all_rows_small():
    text = _read("static/components/BullpenTab.js")
    assert '<button class="btn btn-sm" @click="jumpHome">Home</button>' in text
    assert '<button class="btn btn-sm" @click="resetRowsSmall" title="Reset all row heights to small">Small Rows</button>' in text
    assert "resetRowsSmall()" in text
    assert "this.pendingRowHeight = 32;" in text
    assert "this.pendingRowHeights = {};" in text
    assert "this.persistGrid({ rowHeight: 32, rowHeights: {} });" in text


def test_bullpen_tab_wires_unshifted_single_row_and_shift_global_resize():
    text = _read("static/components/BullpenTab.js")
    app = _read("static/app.js")
    assert "@pointerdown=\"onRowResizeDown(r.row, $event)\"" in text
    assert "title=\"Drag to resize this row; hold Shift for all rows\"" in text
    assert "const mode = e.shiftKey ? 'global' : 'single';" in text
    assert "const startHeight = mode === 'global' ? this.rowHeight : this.rowHeightForRow(rowIndex);" in text
    assert "this.persistGrid({ rowHeight: final, rowHeights });" in text
    assert "this.persistSingleRowHeight(resize.row, final);" in text
    assert "safe.grid = {" in app
    assert "rowHeights," in app


def test_bullpen_tab_positions_cards_and_overlays_with_effective_row_height():
    text = _read("static/components/BullpenTab.js")
    assert ":card-height=\"cardHeightForSlot(item.slotIndex)\"" in text
    assert ":is-vertical-resizing=\"cardVerticalResize && cardVerticalResize.slotIndex === item.slotIndex\"" in text
    assert ":output-lines=\"$root.outputLinesForSlot(item.slotIndex, workspaceId)\"" in text
    assert ":workspace-id=\"workspaceId\"" in text
    assert ":request-output-catchup=\"$root.requestOutputCatchup\"" in text
    assert "@vertical-resize-start=\"onCardVerticalResizeStart(item, $event)\"" in text
    assert ":style=\"{ top: r.y + 'px', height: r.height + 'px' }\"" in text
    assert "const p = this.coordPixel(item.coord);" in text
    assert "return this.insetBoxStyle(p.x, p.y, this.columnWidth, this.rowHeightForRow(this.ghostCell.row));" in text
    assert "row: this.rowFromPixel(y)," in text


def test_card_vertical_resize_styles_exist():
    text = _read("static/style.css")
    assert ".card-height-resize-handle {" in text
    assert "cursor: row-resize;" in text
    assert ".card-height-resize-handle.card-height-resize-handle-active {" in text
