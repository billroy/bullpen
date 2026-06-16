"""Regression checks for ticket detail usage report controls."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def test_task_detail_time_and_tokens_open_usage_report():
    text = _read("static/components/TaskDetailPanel.js")

    assert "usageReportOpen" in text
    assert "@click=\"openUsageReport\"" in text
    assert "Tokens by Provider" in text
    assert "Time by Run" in text
    assert "Time by Provider" in text
    assert "tokens_by_provider_model" in text
    assert "elapsed_ms" in text


def test_task_detail_usage_report_has_styles():
    text = _read("static/style.css")

    assert ".detail-metric-button" in text
    assert ".usage-report-modal" in text
    assert ".usage-report-table" in text
