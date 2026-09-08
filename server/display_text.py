"""Normalize process output for Bullpen's plain-text worker displays."""

import re


# Worker focus mode is deliberately a plain-text view, not a PTY. Remove the
# terminal protocols that would otherwise leak fragments such as ``[31m`` into
# the UI. This covers CSI controls, OSC strings (including hyperlinks), DCS/APC
# strings, two-byte ESC controls, and their 8-bit CSI equivalent.
_ANSI_ESCAPE_RE = re.compile(
    r"(?:"
    r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[P^_].*?\x1b\\"
    r"|\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b[@-_]"
    r"|\x9b[0-?]*[ -/]*[@-~]"
    r")",
    re.DOTALL,
)
_SINGLE_ESCAPED_LAYOUT_RE = re.compile(r"(?<!\\)\\(r\\n|n|r|t)")


def decode_escaped_layout(text):
    """Decode one layer of escaped layout in a known serialized-output field.

    This is intentionally separate from general normalization: arbitrary agent
    prose and source code may legitimately contain a literal ``\\n``. Adapters
    should opt in only for fields documented as command or tool output.
    """
    if not isinstance(text, str) or not text:
        return text
    if "\n" in text or "\r" in text:
        return text
    if "\\n" not in text and "\\r\\n" not in text and "\\r" not in text:
        return text

    replacements = {"r\\n": "\n", "n": "\n", "r": "\r", "t": "\t"}
    return _SINGLE_ESCAPED_LAYOUT_RE.sub(lambda match: replacements[match.group(1)], text)


def normalize_display_text(text):
    """Return safe, readable plain text while preserving ordinary content."""
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)

    text = _ANSI_ESCAPE_RE.sub("", text)
    rendered_lines = []

    # Approximate the useful parts of terminal line editing. Carriage return
    # moves to column zero and backspace moves left; subsequent text overwrites
    # what was there. Other C0/C1 controls have no useful plain-text rendering.
    for raw_line in text.split("\n"):
        cells = []
        cursor = 0
        for char in raw_line:
            if char == "\r":
                cursor = 0
            elif char == "\b":
                cursor = max(0, cursor - 1)
            elif char == "\t":
                cells.append(char)
                cursor = len(cells)
            elif ord(char) < 32 or 0x7F <= ord(char) <= 0x9F:
                continue
            elif cursor < len(cells):
                cells[cursor] = char
                cursor += 1
            else:
                cells.append(char)
                cursor += 1
        rendered_lines.append("".join(cells))

    return "\n".join(rendered_lines)
