"""Shared template rendering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from server.values import find_value_by_ref, value_ref_warning


CONTEXT_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\}")
VALUE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9][A-Za-z0-9 _.\-]{0,127})\}")


@dataclass(frozen=True)
class TemplateRenderResult:
    text: str
    warnings: list[str]


def render_context_template(template, context, *, max_len, single_line=False):
    text = str(template or "")

    def _replace(match):
        path = match.group(1).split(".")
        value = context
        for part in path:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return ""
        return str(value if value is not None else "")

    rendered = CONTEXT_PLACEHOLDER_RE.sub(_replace, text)
    rendered = "".join(ch for ch in rendered if ch in "\n\t" or ord(ch) >= 32)
    if single_line:
        rendered = " ".join(rendered.split())
    else:
        rendered = re.sub(r"[ \t\r\f\v]+", " ", rendered).strip()
    return rendered[:max_len]


def raw_value_text(value):
    return str(value if value is not None else "")


def render_value_template(template, slots, *, context_label="template"):
    text = str(template or "")
    warnings = []

    def _replace(match):
        ref = match.group(1).strip()
        if not ref:
            return match.group(0)
        found = find_value_by_ref(slots, ref)
        if not found:
            warnings.append(f"{context_label}: value '{ref}' not found; leaving placeholder unchanged.")
            return match.group(0)
        warning = value_ref_warning(found)
        if warning:
            warnings.append(f"{context_label}: {warning}")
        return raw_value_text((found.get("slot") or {}).get("value"))

    return TemplateRenderResult(text=VALUE_PLACEHOLDER_RE.sub(_replace, text), warnings=warnings)
