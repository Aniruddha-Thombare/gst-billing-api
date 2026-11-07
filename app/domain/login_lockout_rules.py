from __future__ import annotations

MAX_FAILED_ATTEMPTS = 5
WINDOW_MINUTES = 15


def is_locked(recent_failures: int) -> bool:
    return recent_failures >= MAX_FAILED_ATTEMPTS 