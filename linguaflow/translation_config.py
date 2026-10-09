"""Shared translation context defaults and limits, independent of UI/models."""

DEFAULT_CONTEXT_BEFORE = 5
DEFAULT_CONTEXT_AFTER = 1
DEFAULT_INITIAL_CONTEXT_BEFORE = 1
DEFAULT_INITIAL_CONTEXT_AFTER = 1
MAX_CONTEXT_BEFORE = 10
MAX_CONTEXT_AFTER = 2
MAX_INITIAL_CONTEXT_BEFORE = 2
MAX_CONTEXT_CHARACTERS = 600

CONTEXT_COUNTS = {
    'translation_before': (DEFAULT_CONTEXT_BEFORE, MAX_CONTEXT_BEFORE),
    'translation_after': (DEFAULT_CONTEXT_AFTER, MAX_CONTEXT_AFTER),
    'translation_initial_before': (DEFAULT_INITIAL_CONTEXT_BEFORE, MAX_INITIAL_CONTEXT_BEFORE),
}


def context_count(value, default: int, maximum: int) -> int:
    """Preserve valid stored integers; default corrupt input and bound the range."""
    try:
        if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
            return default
        return max(0, min(maximum, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default
