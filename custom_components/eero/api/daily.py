"""The daily tier: the lists, settings and hardware that rarely change.

It reads the block list, the profiles' schedules, the DHCP reservations, the
port forwards, fast transition, the eeros' ports (connections), Thread, the
entitlements, the backup access points and backup internet, and the firmware
updates with their release notes. Which of them are read follows the update
config, the network's resources and capabilities, and the premium plan.

These change when somebody changes them, so they are polled daily and
refreshed on demand after a setter that touches them.

Module functions that take the hub, whose SDK client and transport they use.
EeroHub.fetch_daily delegates here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .util import backup_access_point_ok, premium_enabled

if TYPE_CHECKING:
    from . import EeroHub, EeroUpdateConfig


async def fetch_daily(
    hub: EeroHub, network_id: str, network: dict[str, Any], config: EeroUpdateConfig
) -> dict[str, Any]:
    """Everything the daily tier reads, as one payload (see the module docstring)."""
    payload: dict[str, Any] = {}
    resources = network.get("resources") or {}
    await _read_clients(hub, network_id, config, payload)
    await _read_network_settings(hub, network_id, payload)
    await _read_hardware(hub, network_id, resources, config, payload)
    await _read_backup(hub, network_id, network, config, payload)
    await _read_updates(hub, network_id, network, config, payload)
    return payload


async def _read_clients(
    hub: EeroHub, network_id: str, config: EeroUpdateConfig, payload: dict[str, Any]
) -> None:
    """Read what the client entities need: the block list and bedtime schedules."""
    if config.get_blacklist:
        payload["blacklist"] = (
            await hub.call_optional(
                hub.sdk.blacklist.get_blacklist(network_id),
                f"/2.2/networks/{network_id}/blacklist",
                network_id,
                "blacklist",
            )
            or []
        )
    if config.get_schedules:
        schedules: dict[str, Any] = {}
        for profile_id in config.profiles:
            if profile_id == "*":
                # Only ever seen from snapshot(), which has no real
                # profile IDs to resolve schedules for.
                continue
            schedules[profile_id] = (
                await hub.call_optional(
                    hub.sdk.schedule.get_schedules(network_id, profile_id),
                    f"/2.2/networks/{network_id}/profiles/{profile_id}/schedules",
                    network_id,
                    "schedules",
                )
                or []
            )
        payload["schedules"] = schedules


async def _read_network_settings(
    hub: EeroHub, network_id: str, payload: dict[str, Any]
) -> None:
    """Read the network's reservations, port forwards and fast transition."""
    payload["reservations"] = (
        await hub.call_optional(
            hub.sdk.reservations.get_reservations(network_id),
            f"/2.2/networks/{network_id}/reservations",
            network_id,
            "reservations",
        )
        or []
    )
    payload["forwards"] = (
        await hub.call_optional(
            hub.sdk.forwards.get_forwards(network_id),
            f"/2.2/networks/{network_id}/forwards",
            network_id,
            "forwards",
        )
        or []
    )
    payload["fast_transition"] = await hub.call_optional(
        hub.sdk.security.get_fast_transition(network_id),
        f"/2.2/networks/{network_id}/fast_transition",
        network_id,
        "fast_transition",
    )


async def _read_hardware(
    hub: EeroHub,
    network_id: str,
    resources: dict[str, Any],
    config: EeroUpdateConfig,
    payload: dict[str, Any],
) -> None:
    """Read the eeros' ports, the Thread network and the entitlements."""
    if config.get_connections:
        connections: dict[str, Any] = {}
        for eero_id in config.eeros:
            connections[eero_id] = (
                await hub.call_optional(
                    hub.sdk.eeros.get_connections(network_id, eero_id),
                    f"/2.2/eeros/{eero_id}/connections",
                    network_id,
                    "connections",
                )
                or {}
            )
        payload["connections"] = connections
    if resources.get("thread"):
        payload["thread"] = await hub.call_optional(
            hub.sdk.thread.get_thread(network_id),
            f"/2.2/networks/{network_id}/thread",
            network_id,
            "thread",
        )
    payload["features"] = await hub.call_optional(
        hub.sdk.entitlements.get_features(network_id),
        f"/2.2/entitlements/networks/{network_id}/features",
        network_id,
        "entitlements",
    )


async def _read_backup(
    hub: EeroHub,
    network_id: str,
    network: dict[str, Any],
    config: EeroUpdateConfig,
    payload: dict[str, Any],
) -> None:
    """Read the backup access points and backup internet, where offered.

    Needs the entitlements read before it, to know whether the network has
    the premium plan.
    """
    capabilities = network.get("capabilities") or {}
    backup_access_point = capabilities.get("backup_access_point") or {}
    if config.get_backup_access_points and backup_access_point_ok(
        capable=backup_access_point.get("capable"),
        requirements=backup_access_point.get("requirements"),
    ):
        if premium_enabled(network, payload["features"]):
            payload["backup_access_points"] = (
                await hub.call_optional(
                    hub.sdk.backup_access_points.list(network_id),
                    f"/2.2/networks/{network_id}/backup_access_points",
                    network_id,
                    "backup_access_points",
                )
                or []
            )
            payload["backup_internet"] = await hub.call_optional(
                hub.sdk.backup.get_backup_internet(network_id),
                f"/2.2/networks/{network_id}/backupinternet",
                network_id,
                "backup_internet",
            )


async def _read_updates(
    hub: EeroHub,
    network_id: str,
    network: dict[str, Any],
    config: EeroUpdateConfig,
    payload: dict[str, Any],
) -> None:
    """Read the firmware updates and, if wanted, their release notes."""
    updates = await hub.call_optional(
        hub.sdk.updates.get_updates(network_id),
        f"/2.2/networks/{network_id}/updates",
        network_id,
        "updates",
    )
    if not isinstance(updates, dict):
        updates = dict(network.get("updates") or {})
    if config.get_release_notes:
        await hub.attach_release_notes(updates)
    payload["updates"] = updates
