"""Tests for plain-text normalization of worker and service output."""

from server.display_text import decode_escaped_layout, normalize_display_text


def test_normalize_display_text_strips_ansi_and_osc_sequences():
    text = "\x1b[31mred\x1b[0m \x1b]8;;https://example.com\x07link\x1b]8;;\x07"
    assert normalize_display_text(text) == "red link"


def test_normalize_display_text_applies_terminal_line_editing():
    assert normalize_display_text("progress 10%\rprogress 90%") == "progress 90%"
    assert normalize_display_text("abc\b\bXY") == "aXY"


def test_normalize_display_text_removes_other_control_characters():
    assert normalize_display_text("safe\x00\x01 text\nnext\tcell") == "safe text\nnext\tcell"


def test_decode_escaped_layout_decodes_one_layer_only():
    assert decode_escaped_layout(r"one\ntwo\r\nthree\tcell") == "one\ntwo\nthree\tcell"
    assert decode_escaped_layout(r"keep\\nquoted") == r"keep\\nquoted"
    assert decode_escaped_layout(r"C:\temp\tools") == r"C:\temp\tools"
    assert decode_escaped_layout("real\nline with literal \\n") == "real\nline with literal \\n"
