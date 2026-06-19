"""Shared template rendering helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass

from server.values import find_value_by_ref, value_ref_warning


CONTEXT_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)\}")
VALUE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9][A-Za-z0-9 _.\-_]{0,127})\}")


@dataclass(frozen=True)
class TemplateRenderResult:
    text: str
    warnings: list[str]


def render_context_template(template, context, *, max_len, single_line=False):
    text = str(template or "")

    def _replace(match):
        found, value = resolve_context_path(context, match.group(1))
        if not found:
            return ""
        return str(value if value is not None else "")

    return normalize_template_text(CONTEXT_PLACEHOLDER_RE.sub(_replace, text), max_len=max_len, single_line=single_line)


def resolve_context_path(context, ref):
    path = str(ref or "").split(".")
    value = context
    for part in path:
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return False, None
    return True, value


def normalize_template_text(text, *, max_len, single_line=False):
    rendered = str(text or "")
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


def render_context_value_template(template, context, slots, *, max_len, single_line=False, context_label="template"):
    text = str(template or "")
    warnings = []

    def _replace(match):
        ref = match.group(1).strip()
        found_context, context_value = resolve_context_path(context, ref)
        if found_context:
            return str(context_value if context_value is not None else "")

        found_value = find_value_by_ref(slots, ref)
        if found_value:
            warning = value_ref_warning(found_value)
            if warning:
                warnings.append(f"{context_label}: {warning}")
            return raw_value_text((found_value.get("slot") or {}).get("value"))

        if CONTEXT_PLACEHOLDER_RE.fullmatch(match.group(0)):
            return ""
        warnings.append(f"{context_label}: value '{ref}' not found; leaving placeholder unchanged.")
        return match.group(0)

    rendered = normalize_template_text(VALUE_PLACEHOLDER_RE.sub(_replace, text), max_len=max_len, single_line=single_line)
    return TemplateRenderResult(text=rendered, warnings=warnings)
