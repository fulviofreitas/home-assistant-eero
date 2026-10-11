"""How far to stretch the poll interval while the Eero API is rate limiting.

Kept free of Home Assistant and package imports so it can be tested on its own,
like device_removal.py.

Each rate-limited poll doubles the interval, up to MAX_BACKOFF, and the first
successful poll puts it back to the configured scan interval. When the API
says how long to wait (Retry-After, reported by eero-api since 8.1.2), the
next poll waits at least that long, capped at MAX_RETRY_AFTER so a malformed
or extreme header cannot leave the device trackers blind for a day.
"""

from __future__ import annotations

from datetime import timedelta

MAX_BACKOFF = timedelta(minutes=15)
MAX_RETRY_AFTER = timedelta(hours=1)


def backoff_interval(current: timedelta | None, base: timedelta) -> timedelta:
    """Return the interval to use after a rate-limited poll."""
    current = max(current or base, base)
    return max(base, min(current * 2, MAX_BACKOFF))


def respect_retry_after(interval: timedelta, retry_after: float | None) -> timedelta:
    """Return interval, stretched to the server's Retry-After when it asks for longer."""
    if retry_after is None or retry_after <= 0:
        return interval
    return max(interval, min(timedelta(seconds=retry_after), MAX_RETRY_AFTER))
