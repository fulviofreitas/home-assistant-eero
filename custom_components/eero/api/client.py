"""Eero API."""

from __future__ import annotations

from datetime import datetime
import logging

from eero.exceptions import EeroException

from .const import DEVICE_CATEGORY_TYPE_MAP
from .resource import EeroResource

_LOGGER = logging.getLogger(__name__)

#: The select option meaning "not assigned to any profile". Chosen so it
#: cannot collide with a real eero profile name in practice; a profile
#: actually named this would be indistinguishable from unassigned.
UNASSIGNED_PROFILE = "Unassigned"


def _same_client(a: EeroClient, b: EeroClient) -> bool:
    """Whether two EeroClient views (network-level, profile-level) are the same device."""
    if a.url and b.url and a.url == b.url:
        return True
    return bool(a.mac and b.mac and a.mac == b.mac)


class EeroClient(EeroResource):
    """EeroClient."""

    @property
    def adblock_day(self) -> int | None:
        """Adblock day."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("adblock_day", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def adblock_month(self) -> int | None:
        """Adblock month."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("adblock_month", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def adblock_week(self) -> int | None:
        """Adblock week."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("adblock_week", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def blocked_day(self) -> int | None:
        """Blocked day."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("blocked_day", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def blocked_month(self) -> int | None:
        """Blocked month."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("blocked_month", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def blocked_week(self) -> int | None:
        """Blocked week."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("blocked_week", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def blocked(self) -> bool | None:
        """Whether this client is on the network's block list.

        Read from the daily-tier blacklist, matched by MAC: a blocked device
        is removed from the network entirely, so the device envelope itself
        carries no reliable flag for this (unlike paused). None until the
        daily tier has been fetched at least once.
        """
        if (network := self.network) is None or "blacklist" not in network.data:
            return None
        mac = (self.mac or "").replace(":", "").lower()
        for entry in network.data["blacklist"].get("data", []):
            entry_mac = str(entry.get("mac") or entry.get("device_id") or "")
            if entry_mac.replace(":", "").lower() == mac:
                return True
        return False

    async def async_set_blocked(self, value: bool) -> None:
        """Add or remove this client from the network's block list."""
        if value:
            await self.api.call(
                self.api.sdk.blacklist.add_to_blacklist(self.network.id, self.mac),
                name=f"/2.2/networks/{self.network.id}/blacklist",
            )
        else:
            await self.api.call(
                self.api.sdk.blacklist.remove_from_blacklist(self.network.id, self.mac),
                name=f"/2.2/networks/{self.network.id}/blacklist",
            )

    @property
    def channel(self) -> int | None:
        """Channel."""
        return self.data.get("channel")

    @property
    def channel_width_rx(self) -> str | None:
        """Channel width RX."""
        return (
            self.data.get("connectivity", {})
            .get("rx_rate_info", {})
            .get("channel_width")
        )

    @property
    def channel_width_tx(self) -> str | None:
        """Channel width TX."""
        return (
            self.data.get("connectivity", {})
            .get("tx_rate_info", {})
            .get("channel_width")
        )

    @property
    def connected(self) -> bool | None:
        """Connected."""
        return self.data.get("connected")

    @property
    def connection_type(self) -> str | None:
        """Connection type."""
        return self.data.get("connection_type")

    @property
    def data_usage_day(self) -> tuple[int | None, int | None]:
        """Data usage day."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("data_usage_day", [])
        ):
            if device["url"] == self.url:
                return (device["download"], device["upload"])
        return (None, None)

    @property
    def data_usage_month(self) -> tuple[int | None, int | None]:
        """Data usage month."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("data_usage_month", [])
        ):
            if device["url"] == self.url:
                return (device["download"], device["upload"])
        return (None, None)

    @property
    def data_usage_week(self) -> tuple[int | None, int | None]:
        """Data usage week."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("data_usage_week", [])
        ):
            if device["url"] == self.url:
                return (device["download"], device["upload"])
        return (None, None)

    @property
    def device_category(self) -> str | None:
        """Device category."""
        return DEVICE_CATEGORY_TYPE_MAP.get(self.device_type)

    @property
    def device_type(self) -> str | None:
        """Device type."""
        return self.data.get("device_type")

    @property
    def hostname(self) -> str | None:
        """Hostname."""
        return self.data.get("hostname")

    @property
    def inspected_day(self) -> int | None:
        """Inspected day."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("inspected_day", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def inspected_month(self) -> int | None:
        """Inspected month."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("inspected_month", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def inspected_week(self) -> int | None:
        """Inspected week."""
        for device in (
            self.network.data.get("activity", {})
            .get("devices", {})
            .get("inspected_week", [])
        ):
            if device["insights_url"] == self.url_insights:
                return device["sum"]
        return None

    @property
    def interface_frequency(self) -> tuple[str | None, str | None]:
        """Interface frequency."""
        return (
            self.data.get("interface", {}).get("frequency"),
            self.data.get("interface", {}).get("frequency_unit"),
        )

    @property
    def ip(self) -> str | None:
        """IP."""
        return self.data.get("ip")

    @property
    def is_guest(self) -> bool | None:
        """Is guest."""
        return self.data.get("is_guest")

    @property
    def is_private(self) -> bool | None:
        """Is private."""
        return self.data.get("is_private")

    @property
    def last_active(self) -> datetime | None:
        """Last active."""
        if last_active := self.data.get("last_active"):
            return datetime.fromisoformat(last_active)
        return None

    @property
    def mac(self) -> str | None:
        """MAC."""
        return self.data.get("mac")

    @property
    def manufacturer(self) -> str | None:
        """Manufacturer."""
        return self.data.get("manufacturer")

    @property
    def name(self) -> str | None:
        """Name."""
        if self.nickname:
            return self.nickname
        if self.hostname:
            return self.hostname
        return self.mac

    @property
    def name_connection_type(self) -> str | None:
        """Name connection type."""
        if self.connection_type:
            return f"{self.name} ({self.connection_type.title()})"
        return f"{self.name} (Unknown)"

    @property
    def name_mac(self) -> str | None:
        """Name MAC."""
        return f"{self.name} ({self.mac})"

    @property
    def nickname(self) -> str | None:
        """Nickname."""
        return self.data.get("nickname")

    @property
    def paused(self) -> bool | None:
        """Paused."""
        return self.data.get("paused")

    async def async_set_paused(self, value: bool) -> None:
        """Pause or resume the client."""
        await self.api.call(
            self.api.sdk.devices.pause_device(self.network.id, self.mac, value),
            name=f"/2.3/networks/{self.network.id}/devices",
        )

    @property
    def profile_assignment(self) -> str | None:
        """Name of the profile this client is currently assigned to.

        Resolved by scanning the network's profiles for one whose device
        list includes this client: the device envelope itself carries no
        reliable profile reference. UNASSIGNED_PROFILE when none does, or
        None if the network's profiles were never fetched (no profile
        configured on this network -- the entity is not created in that
        case, but the property stays honest if ever called anyway).
        """
        if "profiles" not in self.network.data:
            return None
        for profile in self.network.profiles:
            if any(_same_client(self, assigned) for assigned in profile.clients):
                return profile.name or UNASSIGNED_PROFILE
        return UNASSIGNED_PROFILE

    @property
    def profile_assignment_options(self) -> list[str]:
        """Every selectable profile name, plus the unassigned sentinel."""
        if "profiles" not in self.network.data:
            return []
        return [
            UNASSIGNED_PROFILE,
            *[profile.name for profile in self.network.profiles if profile.name],
        ]

    async def async_set_profile_assignment(self, value: str) -> None:
        """Move this client to a different profile (or unassign it).

        profiles.set_profile_devices replaces a profile's whole device
        list, so this reads both the losing and gaining profile's current
        list and rewrites each exactly once.
        """
        current = None
        target = None
        for profile in self.network.profiles:
            if any(_same_client(self, assigned) for assigned in profile.clients):
                current = profile
            if value != UNASSIGNED_PROFILE and profile.name == value:
                target = profile
        for profile in (current, target):
            if profile is not None and not isinstance(profile.data.get("devices"), list):
                # set_profile_devices replaces the whole list: without the
                # profile's current list, writing would drop its other clients.
                raise EeroException(
                    "The profile's current device list is unknown; not changing it"
                )
        if current is not None and current is not target:
            urls = [
                assigned.url
                for assigned in current.clients
                if not _same_client(self, assigned) and assigned.url
            ]
            await self.api.call(
                self.api.sdk.profiles.set_profile_devices(self.network.id, current.id, urls),
                name=current.url,
            )
        if target is not None and target is not current:
            urls = [
                assigned.url for assigned in target.clients if assigned.url
            ] + ([self.url] if self.url else [])
            await self.api.call(
                self.api.sdk.profiles.set_profile_devices(self.network.id, target.id, urls),
                name=target.url,
            )

    @property
    def secondary_wan_allow_access(self) -> bool | None:
        """Whether this client may use the internet backup connection."""
        return not self.data.get("secondary_wan_deny_access")

    async def async_set_secondary_wan_allow_access(self, value: bool) -> None:
        """Allow or deny this client the internet backup connection."""
        await self.api.put(
            f"/2.3/networks/{self.network.id}/devices/{self.mac}",
            json={"secondary_wan_deny_access": not value},
        )

    @property
    def signal(self) -> tuple[int | None, str | None]:
        """Signal."""
        if signal := self.data.get("connectivity", {}).get("signal"):
            parts = signal.split()
            try:
                return (int(parts[0]), parts[1])
            except (IndexError, ValueError):
                _LOGGER.debug("Unexpected signal format: %s", signal)
        return (None, None)

    @property
    def source_location(self) -> str | None:
        """Source location."""
        return self.data.get("source", {}).get("location")

    @property
    def url_insights(self) -> str | None:
        """URL insights."""
        return f"{self.network.url_insights}/devices/{self.id}"

    @property
    def usage_down(self) -> float:
        """Usage down."""
        if usage := self.data.get("usage"):
            return usage.get("down_mbps", 0)
        return 0

    @property
    def usage_up(self) -> float:
        """Usage up."""
        if usage := self.data.get("usage"):
            return usage.get("up_mbps", 0)
        return 0

    @property
    def wireless(self) -> bool | None:
        """Wireless."""
        return self.data.get("wireless")
