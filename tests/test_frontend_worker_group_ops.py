"""Regression checks for worker-group drag/drop and clipboard operations."""

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_app_exposes_group_worker_socket_events():
    text = _read("static/app.js")
    assert "function moveWorkerGroup(moves)" in text
    assert "socket.emit('worker:move_group'" in text
    assert "function pasteWorkerGroup(items)" in text
    assert "socket.emit('worker:paste_group'" in text
    assert "function saveWorkersConfig({ slots, fields })" in text
    assert "socket.emit('worker:configure_many'" in text
    assert "function stopWorkerSlots(slots)" in text
    assert "socket.emit('worker:stop_many'" in text
    assert "function duplicateWorkers(slots)" in text
    assert "socket.emit('worker:duplicate_group'" in text
    assert "function exportWorkerGroup(slots)" in text
    assert "await _downloadBentoExport({ kind: 'worker-group', slots: validSlots }, 'bullpen-worker-group.bento');" in text
    assert "socket.emit('bento:export', _wsData({ ...payload, request_id: requestId }));" in text


def test_bullpen_tab_builds_pass_reachable_groups_for_drag_and_copy():
    text = _read("static/components/BullpenTab.js")
    assert "workerGroupSlots(startSlot)" in text
    assert "selectedWorkerSlots: []" in text
    assert "selectedWorkerScope: 'none'" in text
    assert "isExplicitSelectionActive()" in text
    assert "workerMenuContext(slotIndex)" in text
    assert "slotsForMenuScope(slotIndex, scope)" in text
    assert "expandSelectionSlots(slots)" in text
    assert "passTargetsForSlot(slotIndex)" in text
    assert "buildGroupMovePlan(sourceSlot, destinationCoord," in text
    assert "canDropWorkerAtSlot(sourceSlot, targetSlot, e)" in text
    assert "moveWorkerGroupToCoord(sourceSlot, coord)" in text
    assert "this.$root.moveWorkerGroup(plan.moves)" in text
    assert "Copied worker group (" in text


def test_bullpen_tab_supports_range_multiple_selection():
    text = _read("static/components/BullpenTab.js")
    assert "selectionAnchor: null" in text
    assert "isMultipleSelectionActive()" in text
    assert "slotsInRange(a, b)" in text
    assert "updateRangeSelection(anchor, active)" in text
    assert "if (e.shiftKey) {" in text
    assert "this.updateRangeSelection(anchor, next);" in text
    assert "selectionMoved: false" in text
    assert "this.dragStart.selectionMoved = true;" in text
    assert ":multiple-selection-active=\"isMultipleSelectionActive\"" in text


def test_bullpen_tab_group_detection_includes_inbound_pass_links():
    text = _read("static/components/BullpenTab.js")
    assert "passTargetsBySlot()" in text
    assert "passSourcesBySlot()" in text
    assert "passSourcesForSlot(slotIndex)" in text
    assert "return this.passSourcesBySlot[target] || [];" in text
    assert "new Set([...this.passTargetsForSlot(slot), ...this.passSourcesForSlot(slot)])" in text


def test_bullpen_tab_worker_drop_reuses_expanded_move_plan():
    text = _read("static/components/BullpenTab.js")
    assert "this.selectedWorkerSlots = plan.slots.slice();" in text
    assert "this.selectedWorkerSlots = this.expandSelectionSlots(plan.slots);" not in text


def test_worker_grid_avoids_broad_icon_rerenders_on_layout_updates():
    app = _read("static/app.js")
    tab = _read("static/components/BullpenTab.js")
    assert "updated() {\n    renderLucideIcons(this.$el);" not in app
    assert "updated() {\n    renderLucideIcons(this.$el);" not in tab
    assert "this.$nextTick(() => renderLucideIcons(this.$el));" in app
    assert "this.$nextTick(() => renderLucideIcons(this.$el));" in tab


def test_worker_grid_caches_dragover_drop_target_and_viewport_rect():
    text = _read("static/components/BullpenTab.js")
    assert "dragViewportRect: null" in text
    assert "lastDropTargetKey: ''" in text
    assert "const rect = this.dragViewportRect || this.$refs.viewport.getBoundingClientRect();" in text
    assert "if (coord && this.lastDropTargetKey === key) return true;" in text
    assert "this.lastDropTargetKey = key;" in text
    assert "this.dragViewportRect = null;" in text


def test_worker_cards_use_parent_task_lookup_map():
    app = _read("static/app.js")
    tab = _read("static/components/BullpenTab.js")
    card = _read("static/components/WorkerCard.js")
    assert "const taskById = computed(() => {" in app
    assert ":task-by-id=\"taskById\"" in app
    assert ":task-by-id=\"taskById\"" in tab
    assert "'taskById'" in card
    assert "lookupTask(id)" in card
    assert "this.taskById && this.taskById[id]" in card
    assert "const t = this.lookupTask(id);" in card
    assert "const task = this.lookupTask(this.worker.task_queue[0]);" in card


def test_worker_card_avoids_menu_icon_render_on_every_update():
    text = _read("static/components/WorkerCard.js")
    assert "updated() {\n    if (this.$refs.menu) renderLucideIcons(this.$refs.menu);" not in text
    assert "menuIconToken()" in text
    assert "if (this.showMenu) this.$nextTick(() => renderLucideIcons(this.$refs.menu));" in text


def test_mounted_surfaces_avoid_generic_updated_icon_rerenders():
    for rel_path in [
        "static/components/LeftPane.js",
        "static/components/KanbanTab.js",
        "static/components/TaskDetailPanel.js",
        "static/components/StatsTab.js",
    ]:
      text = _read(rel_path)
      assert "updated() {\n    renderLucideIcons(this.$el);" not in text


def test_worker_card_only_runs_elapsed_timer_when_status_needs_it():
    text = _read("static/components/WorkerCard.js")
    assert "needsElapsedTimer()" in text
    assert "this.syncElapsedTimer();" in text
    assert "setInterval(() => this.updateElapsed(), 1000)" in text
    assert "this._timer = setInterval(() => this.updateElapsed(), 1000);\n    this.updateElapsed();" not in text


def test_worker_card_icon_refreshes_when_reused_slot_changes_type_in_browser():
    browser_cache = Path("/Users/bill/Library/Caches/ms-playwright")
    if browser_cache.exists() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browser_cache)
    playwright = pytest.importorskip("playwright.sync_api")

    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            message = str(exc)
            if (
                "Executable doesn't exist" in message
                or "MachPortRendezvousServer" in message
                or "Permission denied" in message
            ):
                pytest.skip("Playwright browser launch is unavailable in this environment")
            raise
        page = browser.new_page()
        page.set_content(
            """<!doctype html>
            <html>
              <body>
                <div id="app"></div>
                <script src="https://unpkg.com/vue@3.5.33/dist/vue.global.prod.js"></script>
                <script src="https://unpkg.com/lucide@latest/dist/umd/lucide.min.js"></script>
              </body>
            </html>""",
            wait_until="networkidle",
            timeout=15000,
        )
        page.add_script_tag(path=str(ROOT / "static" / "utils.js"))
        page.add_script_tag(path=str(ROOT / "static" / "components" / "WorkerCard.js"))
        page.add_script_tag(content="""
            const { createApp, reactive } = Vue;
            const state = reactive({
              worker: {
                type: 'shell',
                name: 'Start',
                command: 'echo start',
                state: 'idle',
                task_queue: [],
                activation: 'manual',
                color: 'shell',
              },
            });
            window.__workerState = state;
            createApp({
              components: { WorkerCard },
              data() { return { state }; },
              methods: {
                outputLinesForSlot() { return []; },
                startWorkerSlot() {},
                stopWorkerSlot() {},
                restartServiceSlot() {},
                openFocusTab() {},
              },
              template: `<WorkerCard
                :key="0"
                :worker="state.worker"
                :slot-index="0"
                :tasks="[]"
                :task-by-id="{}"
                :output-lines="[]"
                :multiple-workspaces="false"
                :neighbor-slots="{}"
                :all-workers="[state.worker]"
                :menu-context="{}"
                layout-mode="medium"
                :card-height="140"
                :is-selected="false"
                :multiple-selection-active="false"
                :is-vertical-resizing="false"
                workspace-id="ws-a"
              />`,
            }).mount('#app');
        """)
        page.wait_for_timeout(300)
        assert page.locator(".worker-type-icon--card").get_attribute("data-lucide") == "terminal"

        page.evaluate("""
            window.__workerState.worker = {
              type: 'value',
              name: 'Move',
              value: 'rock',
              value_type: 'auto',
              resolved_value_type: 'string',
              color: 'value',
              task_queue: [],
            };
        """)
        page.wait_for_timeout(300)

        assert page.locator(".worker-card-name").first.inner_text() == "Move"
        assert page.locator(".worker-type-icon--card").get_attribute("data-lucide") == "equal"
        browser.close()


def test_server_worker_group_move_uses_coordinate_occupancy_map():
    text = _read("server/events.py")
    assert "def _coord_occupancy_map(layout, cols=4):" in text
    assert "occupied_by_coord = _coord_occupancy_map(layout, cols=cols)" in text
    assert "occupied_slot = occupied_by_coord.get((coord[\"col\"], coord[\"row\"]))" in text
    assert "occupied_slot = _coord_occupied(layout, move[\"to_coord\"], cols=cols)" not in text


def test_bullpen_tab_pastes_group_workers_with_relative_offsets():
    text = _read("static/components/BullpenTab.js")
    assert "clipboardTargetsForCoord(coord)" in text
    assert "this.$root.pasteWorkerGroup(targets)" in text
    assert "Cannot paste worker group here" in text
    assert "if (!this.clipboardWorker || !coord || !this.isWritableCoord(coord)) return false;" in text
    assert "if (this.itemAtCoord(target.coord)) return false;" in text


def test_bullpen_tab_worker_clipboard_preserves_shell_fields():
    text = _read("static/components/BullpenTab.js")
    assert "workerFieldsForClipboard(worker)" in text
    assert "'type', 'profile'" in text
    assert "'command', 'cwd', 'timeout_seconds', 'ticket_delivery', 'env'" in text
    assert "'pre_start', 'ticket_action', 'startup_grace_seconds', 'startup_timeout_seconds'" in text
    assert "'health_type', 'health_url', 'health_command', 'health_interval_seconds'" in text
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


def test_worker_card_keeps_per_worker_menu_items_enabled_during_group_selection():
    text = _read("static/components/WorkerCard.js")
    assert "'multipleSelectionActive'" in text
    assert "'delete-worker'" in text
    assert "This Worker" in text
    assert "class=\"worker-menu-item\" @click=\"menuEdit\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuRun\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuRestart\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuWatch\"" in text
    assert "class=\"worker-menu-item\" :disabled=\"!serviceSiteUrl\" @click=\"menuOpenSite\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuStop\"" in text
    assert "if (this.multipleSelectionActive) return;\n      this.closeMenuAndRestoreFocus();\n      this.$emit('configure', this.slotIndex);" not in text
    assert "if (this.multipleSelectionActive) return;\n      this.closeMenuAndRestoreFocus();\n      this.$root.startWorkerSlot(this.slotIndex);" not in text


def test_worker_card_exposes_explicit_group_and_selection_menu_items():
    text = _read("static/components/WorkerCard.js")
    assert "v-if=\"canPauseWorker && !isPaused\"" in text
    assert "v-if=\"canPauseWorker && isPaused\"" in text
    assert "Pause Worker" in text
    assert "Unpause Worker" in text
    assert "class=\"worker-menu-item\" @click=\"menuDuplicate\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuCopyWorker\"" in text
    assert "class=\"worker-menu-item\" @click=\"menuExportWorker\"" in text
    assert "Connected Group: {{ connectedGroupCount }} Workers" in text
    assert "Selected Workers: {{ selectionCount }}" in text
    assert "menuScoped('pause', 'connected-group')" in text
    assert "menuScoped('copy', 'connected-group')" in text
    assert "menuScoped('duplicate', 'connected-group')" in text
    assert "menuScoped('export', 'connected-group')" in text
    assert "menuScoped('copy-to', 'connected-group')" in text
    assert "menuScoped('delete', 'connected-group')" in text
    assert "menuScoped('pause', 'selection')" in text
    assert "menuScoped('copy', 'selection')" in text
    assert "menuScoped('duplicate', 'selection')" in text
    assert "menuScoped('export', 'selection')" in text
    assert "menuScoped('copy-to', 'selection')" in text
    assert "menuScoped(action, scope)" in text
    assert "if (this.multipleSelectionActive) return;" not in text
    assert "this.$emit('delete-worker', this.slotIndex);" in text


def test_worker_card_keeps_run_visible_during_automation_pause():
    text = _read("static/components/WorkerCard.js")
    assert "automationPausedForWorker()" in text
    assert "this.$root?.state?.config?.worker_automation_paused === true" in text
    assert "canStart && !isPaused\" class=\"worker-menu-item\" @click=\"menuRun\"" in text
    assert "canStart && !isPaused && !automationPausedForWorker" not in text


def test_bullpen_tab_deletes_selected_worker_group_from_menu():
    text = _read("static/components/BullpenTab.js")
    assert "@delete-worker=\"deleteWorkerFromMenu\"" in text
    assert "@worker-scope-action=\"handleWorkerScopeAction\"" in text
    assert "handleWorkerScopeAction(payload)" in text
    assert "this.$root.saveWorkersConfig({ slots, fields: { paused } });" in text
    assert "this.$root.stopWorkerSlots(slots);" in text
    assert "this.$root.duplicateWorkers(slots);" in text
    assert "this.$root.exportWorkerGroup(slots);" in text
    assert "deleteWorkerFromMenu(slot, scope = 'item')" in text
    assert "const slots = this.slotsForMenuScope(source, scope);" in text
    assert "this.$root.removeWorkers(slots)" in text
    assert "this.$root.removeWorker(source)" in text


def test_worker_transfer_modal_supports_group_payloads():
    app_text = _read("static/app.js")
    modal_text = _read("static/components/WorkerTransferModal.js")
    assert "const transferSlots = ref([]);" in app_text
    assert ":slot-indices=\"transferSlots\"" in app_text
    assert "socket.emit('worker:transfer', _wsData(payload));" in app_text
    assert "socket.on('worker:transferred', onTransferred);" in app_text
    assert "socket.on('worker:transfer:error', onError);" in app_text
    assert "/api/worker/transfer" not in app_text
    assert "props: ['visible', 'worker', 'slotIndex', 'slotIndices'" in modal_text
    assert "source_slots: this.resolvedSlots" in modal_text
    assert "transferSubject()" in modal_text


def test_keyboard_worker_commands_use_explicit_selection_scope_only():
    text = _read("static/components/BullpenTab.js")
    assert "this.copyWorker(item.slotIndex, this.isExplicitSelectionActive ? 'selection' : 'item');" in text
    assert "const slots = this.selectedWorkerSlots.slice();" in text
    assert "if (this.$root.removeWorkers(slots) === true) this.moveCursorToDeletedWorkerRegion(slots);" in text
    assert "if (this.isExplicitSelectionActive) {" in text
    assert "this.copyWorker(item.slotIndex, 'connected-group');" not in text


def test_worker_group_delete_moves_cursor_to_deleted_region_top_left():
    text = _read("static/components/BullpenTab.js")
    assert "topLeftCoordForSlots(slots)" in text
    assert "moveCursorToDeletedWorkerRegion(slots)" in text
    assert "col: Math.min(coord.col, item.coord.col)" in text
    assert "row: Math.min(coord.row, item.coord.row)" in text
    assert "this.selectedCell = { ...coord };" in text
    assert "this.selectedWorkerSlots = [];" in text
    assert "this.selectedWorkerScope = 'none';" in text
    assert "if (deleted) this.moveCursorToDeletedWorkerRegion(slots.length ? slots : [source]);" in text


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
