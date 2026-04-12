"""Model alias normalization for provider/model selections."""


_MODEL_ALIASES = {
    "claude": {
        # Legacy/non-existent slug kept in older layouts and docs.
        "claude-haiku-4-6": "claude-haiku-4-5-20250414",
    },
}


def normalize_model(provider, model):
    """Return a canonical model slug for the provider."""
    if not provider or not model:
        return model
    aliases = _MODEL_ALIASES.get(str(provider).lower(), {})
    return aliases.get(model, model)
