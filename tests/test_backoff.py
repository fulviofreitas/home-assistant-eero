"""The poll interval stretches while rate limited and never past 15 minutes."""

from __future__ import annotations

from datetime import timedelta
import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "custom_components" / "eero" / "backoff.py"
spec = importlib.util.spec_from_file_location("eero_backoff", MODULE)
backoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backoff)

BASE = timedelta(seconds=300)


def test_first_rate_limit_doubles_the_scan_interval():
    assert backoff.backoff_interval(BASE, BASE) == timedelta(seconds=600)


def test_repeated_rate_limits_keep_doubling_up_to_the_cap():
    interval = BASE
    seen = []
    for _ in range(5):
        interval = backoff.backoff_interval(interval, BASE)
        seen.append(interval)
    assert seen == [
        timedelta(seconds=600),
        timedelta(minutes=15),
        timedelta(minutes=15),
        timedelta(minutes=15),
        timedelta(minutes=15),
    ]


def test_missing_interval_starts_from_the_base():
    assert backoff.backoff_interval(None, timedelta(seconds=60)) == timedelta(seconds=120)


def test_base_above_the_cap_is_never_shortened():
    base = timedelta(minutes=20)
    assert backoff.backoff_interval(base, base) == base


def test_retry_after_longer_than_the_backoff_wins():
    assert backoff.respect_retry_after(timedelta(minutes=10), 1800) == timedelta(minutes=30)


def test_retry_after_shorter_than_the_backoff_is_ignored():
    assert backoff.respect_retry_after(timedelta(minutes=10), 60) == timedelta(minutes=10)


def test_retry_after_is_capped_at_an_hour():
    assert backoff.respect_retry_after(timedelta(minutes=10), 86400) == timedelta(hours=1)


def test_missing_or_nonsense_retry_after_changes_nothing():
    for value in (None, 0, -5):
        assert backoff.respect_retry_after(timedelta(minutes=10), value) == timedelta(minutes=10)
