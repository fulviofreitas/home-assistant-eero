"""Live WAN throughput from a usage burst.

The eero API has no network-level throughput field. After a burst request
(``POST .../burst_reporters``) and a settle of about 12 s, every device in
the device list carries fresh ``usage.down_mbps`` / ``usage.up_mbps`` values;
the network's live throughput is their sum over the connected devices.

Pure functions, no Home Assistant: tested standalone.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import math
from typing import Any

USAGE_DOWN = "down_mbps"
USAGE_UP = "up_mbps"


@dataclass(frozen=True)
class WanTotal:
    """Summed throughput over the connected devices, in Mbit/s.

    ``down`` and ``up`` are None when any connected device lacked a usable
    usage pair: an unknown total, which is not a zero one. ``devices`` is the
    number of connected devices the sum ran over either way.
    """

    down: float | None
    up: float | None
    devices: int


def _mbps(usage: Any, key: str) -> float | None:
    """Return a finite, non-negative rate, or None when it is missing or unusable."""
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _device_key(device: dict[str, Any]) -> str | None:
    """Return the key a device is deduplicated by: its MAC, else its URL."""
    mac = device.get("mac")
    if isinstance(mac, str) and mac:
        return mac.lower()
    url = device.get("url")
    if isinstance(url, str) and url:
        return url
    return None


def wan_total(devices: Iterable[Any]) -> WanTotal:
    """Sum the live usage of the connected devices in a device list.

    Devices are deduplicated by lower-cased MAC (URL when there is no MAC;
    an entry with neither is skipped), the first occurrence winning. Only
    devices whose ``connected`` is exactly True count. If any of them lacks a
    numeric, finite, non-negative down/up pair the whole total is unknown.
    """
    seen: set[str] = set()
    connected: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, dict):
            continue
        if (key := _device_key(device)) is None or key in seen:
            continue
        seen.add(key)
        if device.get("connected") is True:
            connected.append(device)

    down = up = 0.0
    for device in connected:
        usage = device.get("usage")
        device_down = _mbps(usage, USAGE_DOWN)
        device_up = _mbps(usage, USAGE_UP)
        if device_down is None or device_up is None:
            return WanTotal(None, None, len(connected))
        down += device_down
        up += device_up
    return WanTotal(down, up, len(connected))
