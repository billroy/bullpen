"""Regression checks for worker card task timer and token readouts."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_card_shows_elapsed_and_tokens_for_current_task():
    text = _read("static/components/WorkerCard.js")
    assert 'statusLabel()' in text
    assert 'return `BUSY ${this.elapsed}`' in text
    assert 'return `RETRY${this.retryAttemptLabel}${this.retryCountdownLabel}`' in text
    assert 'worker-card-agent' not in text
    assert '{{ worker.model }}' not in text
    assert '{{ worker.agent }}/{{ worker.model }}' not in text
    assert 'this.outputLines.slice(-5)' in text
    assert 'updateElapsed()' in text


def test_worker_card_explains_held_manual_queues():
    text = _read("static/components/WorkerCard.js")
    assert "isHeldQueue()" in text
    assert "WAITING FOR RUN" in text
    assert "Run next (${this.taskQueueCount})" in text


def test_worker_card_shows_idle_prompt_and_interpolated_shell_command():
    card = _read("static/components/WorkerCard.js")
    tab = _read("static/components/BullpenTab.js")
    style = _read("static/style.css")

    assert 'v-else-if="idleDetail"' in card
    assert 'class="worker-card-idle-detail worker-card-idle-detail--clickable"' in card
    assert '@click.stop="openConfigFromIdleDetail"' in card
    assert "openConfigFromIdleDetail()" in card
    assert "this.$emit('configure', this.slotIndex);" in card
    assert "idleDetail()" in card
    assert "this.workerState !== 'idle' || this.isHeldQueue || this.isPaused" not in card
    assert "this.workerState !== 'idle' || this.isHeldQueue" in card
    assert "if (this.isShell) return this.interpolateValuePlaceholders(this.worker?.command);" in card
    assert "return String(this.worker?.expertise_prompt || '').trim();" in card
    assert "findValueWorkerForRef(rawRef)" in card
    assert ":all-workers=\"layout.slots\"" in tab
    assert ".worker-card-idle-detail {" in style
    assert ".worker-card-idle-detail--clickable {" in style


def test_worker_card_readouts_have_styles():
    text = _read("static/style.css")
    assert '.worker-card-output {' in text
    assert 'flex: 1 1 0;' in text
    assert 'max-height: none;' in text


def test_worker_card_prioritizes_live_output_while_busy():
    text = _read("static/components/WorkerCard.js")
    output_idx = text.index('class="worker-card-output"')
    queue_idx = text.index('class="worker-card-queue"')
    assert output_idx < queue_idx
    assert "v-else-if=\"effectiveLayoutMode !== 'small' && visibleQueuedTasks.length\"" in text
    assert "visibleQueuedTasks()" in text
    assert "return this.queuedTasks.slice(1);" in text
