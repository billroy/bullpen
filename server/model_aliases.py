"""Model alias normalization for provider/model selections."""


_MODEL_ALIASES = {
    "claude": {
        # Legacy/non-existent slug kept in older layouts and docs.
        "claude-haiku-4-6": "claude-haiku-4-5-20251001",
        "claude-haiku-4-5-20250414": "claude-haiku-4-5-20251001",
    },
    "gemini": {
        # Gemini CLI 0.37.x routes through 2.5/3-era models. Older Bullpen
        # dropdowns exposed 2.0 Flash, which now fails with 404. Auto routing
        # can also stall in headless runs when Pro is exhausted and fallback
        # requires consent, so route stale/auto selections to Flash.
        "auto-gemini-2.5": "gemini-2.5-flash",
        "gemini-2.0-flash": "gemini-2.5-flash",
        "gemini-pro-2.5": "gemini-2.5-pro",
    },
}


def normalize_model(provider, model):
    """Return a canonical model slug for the provider."""
    if not provider or not model:
        return model
    aliases = _MODEL_ALIASES.get(str(provider).lower(), {})
    return aliases.get(model, model)
