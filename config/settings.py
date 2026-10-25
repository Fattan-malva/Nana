"""Central settings for Nana (timeouts, limits, screenshot policy)."""

import os


def _int(name, default):
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


TOOLS_MAX_STEPS = _int("TOOLS_MAX_STEPS", 4)
SCREENSHOT_MAX_AGE_SECONDS = _int("SCREENSHOT_MAX_AGE_SECONDS", 3600)
TASK_TIMEOUT_SECONDS = _int("TASK_TIMEOUT_SECONDS", 120)
ACTION_TIMEOUT_SECONDS = _int("ACTION_TIMEOUT_SECONDS", 30)
