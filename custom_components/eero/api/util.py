"""Eero API."""

from __future__ import annotations

from typing import Any

from eero.const import API_ENDPOINT

from .const import STATE_ACTIVE, STATE_TRIALING

# The SDK resolves a relative path against .../2.2, so a path the API itself
# returned ("/2.2/networks/1/...", "/2.3/...") has to be made absolute on the
# same host, or it would become ".../2.2/2.2/networks/1/...". The host has to
# match exactly: the SDK only attaches the session token to its own host.
API_HOST = API_ENDPOINT.rsplit("/2.2", 1)[0]


def api_url(path: str) -> str:
    """Return an absolute API URL for a path the API returned."""
    if path.startswith(("http://", "https://")):
        return path
    return f"{API_HOST}/{path.lstrip('/')}"


def sum_data_usage(resource: Any, key: str) -> int | None:
    """Return total bytes for a (download, upload) pair.

    Returns None when neither direction is reported: a period that has just
    rolled over has no series yet, and None + None is not a sum.
    """
    down, up = getattr(resource, key)
    if down is None and up is None:
        return None
    return (down or 0) + (up or 0)


def backup_access_point_ok(capable: bool | None, requirements: dict[str, Any] | None) -> bool:
    """Backup access point OK."""
    return bool(capable) and all(bool(value) for value in (requirements or {}).values())


def premium_ok(capable: bool | None, status: str | None) -> bool:
    """Premium OK."""
    return all(
        [
            capable,
            status in [STATE_ACTIVE, STATE_TRIALING],
        ]
    )


def premium_enabled(network: dict[str, Any], features: Any) -> bool:
    """Whether the network is entitled to eero Plus features.

    Decided from the entitlements read when there is one: an empty feature
    list means no subscription. When entitlements could not be read, fall
    back to the premium_status field on the network envelope.
    """
    if isinstance(features, dict) and isinstance(features.get("features"), list):
        return bool(features["features"])
    return premium_ok(
        capable=(network.get("capabilities") or {}).get("premium", {}).get("capable"),
        status=network.get("premium_status"),
    )
