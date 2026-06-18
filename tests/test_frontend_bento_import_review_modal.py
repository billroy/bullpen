"""Regression checks for the Bento import review modal."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_bento_import_review_modal_is_loaded_and_registered():
    index = _read("static/index.html")
    app = _read("static/app.js")

    assert '<script src="/components/BentoImportReviewModal.js"></script>' in index
    assert "BentoImportReviewModal," in app
    assert ":visible=\"bentoImportReview.visible\"" in app
    assert "@apply=\"applyBentoImportReview\"" in app


def test_bento_import_review_modal_exposes_package_decisions():
    text = _read("static/components/BentoImportReviewModal.js")

    assert "const BentoImportReviewModal = {" in text
    assert "emits: ['close', 'apply']" in text
    assert "value=\"place-right\"" in text
    assert "value=\"place-below\"" in text
    assert "value=\"choose-anchor\"" in text
    assert "decisions.placement = { strategy: this.placementStrategy };" in text
    assert "decisions.approvals = { ...this.approvals };" in text
    assert "decisions.target_status = this.targetStatus;" in text
    assert "new Set(['assigned', 'in_progress', 'in-progress'])" in text
    assert "class=\"modal modal-wide bento-import-modal\"" in text


def test_bento_import_review_styles_exist():
    css = _read("static/style.css")

    assert ".bento-import-modal" in css
    assert ".bento-review-section" in css
    assert ".bento-review-items" in css
    assert ".bento-anchor-grid" in css
