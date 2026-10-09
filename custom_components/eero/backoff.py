"""How far to stretch the poll interval while the Eero API is rate limiting.

Kept free of Home Assistant and package imports so it can be tested on its own,
like device_removal.py.

The API's 429 carries no usable Retry-After, so the coordinator backs off on
its own: each rate-limited poll doubles the interval, up to MAX_BACKOFF, and
the first successful poll puts it back to the configured scan interval.
"""

from __future__ import annotations

from datetime import timedelta

MAX_BACKOFF = timedelta(minutes=15)


def backoff_interval(current: timedelta | None, base: timedelta) -> timedelta:
    """Return the interval to use after a rate-limited poll."""
    current = max(current or base, base)
    return max(base, min(current * 2, MAX_BACKOFF))
