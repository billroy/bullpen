"""Regression checks for worker header menu viewport-safe positioning."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_worker_menu_measures_rendered_dimensions_and_clamps_to_viewport():
    text = _read("static/components/WorkerCard.js")
    assert "ref=\"menu\"" in text
    assert "const menuEl = this.$refs.menu;" in text
    assert "const menuWidth = menuEl?.offsetWidth || 160;" in text
    assert "const viewportWidth = window.innerWidth || document.documentElement.clientWidth || 0;" in text
    assert "const maxLeft = Math.max(gutter, viewportWidth - menuWidth - gutter);" in text
    assert "const maxTop = viewportHeight - menuHeight - gutter;" in text

