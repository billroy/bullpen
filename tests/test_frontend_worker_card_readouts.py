"""Regression checks for worker card task timer and token readouts."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_card_shows_elapsed_and_tokens_for_current_task():
    text = _read("static/components/WorkerCard.js")
    assert 'statusLabel()' in text
    assert 'return `WORKING ${this.elapsed}`' in text
    assert 'class="worker-card-token-meta"' in text
    assert 'worker-card-agent' not in text
    assert '{{ worker.model }}' not in text
    assert '{{ worker.agent }}/{{ worker.model }}' not in text
    assert 'title="Total tokens so far for current task"' in text
    assert 'currentTaskTokens' in text
    assert 'formatTokens(currentTaskTokens)' in text
    assert 'this.outputLines.slice(-5)' in text
    assert 'updateElapsed()' in text


def test_worker_card_readouts_have_styles():
    text = _read("static/style.css")
    assert '.worker-card-token-meta {' in text
    assert 'margin-left: auto;' in text
    assert 'text-overflow: ellipsis;' in text
    assert '.worker-card-output {' in text
    assert 'flex: 1 1 auto;' in text
    assert 'max-height: none;' in text
