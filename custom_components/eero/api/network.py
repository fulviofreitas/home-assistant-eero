"""Eero API."""

from __future__ import annotations

import logging
from functools import cached_property
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any, cast

from eero.api.security import MLO_MODE_DISABLED, MLO_MODE_MULTI, MLO_MODE_SINGLE

from .backup_network import EeroBackupNetwork
from .client import EeroClient
from .const import (
    DEVICE_CATEGORY_COMPUTERS_PERSONAL,
    DEVICE_CATEGORY_ENTERTAINMENT,
    DEVICE_CATEGORY_HOME,
    DEVICE_CATEGORY_OTHER,
    MODEL_BEACON,
    PREFERRED_UPDATE_HOUR_MAP,
    STATE_DISABLED,
    STATE_NETWORK,
    STATE_PROFILE,
)
from .eero import EeroDevice, EeroDeviceBeacon
from .firmware import EeroFirmware
from .profile import EeroProfile
from .resource import EeroResource
from .util import premium_ok

if TYPE_CHECKING:
    from . import EeroHub
    from .account import EeroAccount

_LOGGER = logging.getLogger(__name__)

# The no-SDK-method writes below (DNS-policy settings, hide_5g, preferred
# update hour, ipv6_upstream on its own, the Thread enable path) go through
# the SDK's public put/post/delete with the exact request the integration has
# always sent: eero-api has no reader-verified method for them, or its method
# sends a different request (see CHANGELOG 2.0.0).


def _same_dns_servers(current: list[str], target: list[str]) -> bool:
    """Compare DNS server lists order-insensitively.

    Normalizes through ipaddress so a stored, fully-expanded IPv6 literal
    (``2606:4700:4700:0:0:0:0:1111``) compares equal to the compressed form
    (``2606:4700:4700::1111``) a caller is more likely to supply.
    """

    def _normalize(value: str) -> str:
        try:
            return str(ip_address(value))
        except ValueError:
            return value

    return {_normalize(v) for v in current} == {_normalize(v) for v in target}


class EeroNetwork(EeroResource):
    """EeroNetwork."""

    def __init__(self, api: EeroHub, account: EeroAccount, data: dict[str, Any]) -> None:
        """Initialize."""
        super().__init__(api=api, network=None, data=data)
        self.account = account
        if self.data is None:
            self.data = {}

    @property
    def ad_block(self) -> bool:
        """Ad block."""
        return all(
            [
                self.ad_block_enabled,
                not self.ad_block_profiles,
            ]
        )

    async def async_set_ad_block(self, value: bool) -> None:
        """Set network-wide ad blocking."""
        await self.api.post(f"{self.url_dns_policies}/adblock", json={"enable": value})

    @property
    def ad_block_enabled(self) -> bool | None:
        """Ad block enabled."""
        return (
            cast("bool | None", self.data.get("premium_dns", {}).get("ad_block_settings", {}).get("enabled"))
        )

    @property
    def ad_block_profiles(self) -> list[str | None] | None:
        """Ad block profiles."""
        return (
            cast("list[str | None] | None", self.data.get("premium_dns", {})
            .get("ad_block_settings", {})
            .get("profiles"))
        )

    @property
    def ad_block_status(self) -> str:
        """Ad block status."""
        if self.ad_block:
            return STATE_NETWORK
        if self.ad_block_profiles:
            return STATE_PROFILE
        return STATE_DISABLED

    @property
    def adblock_day(self) -> int | None:
        """Adblock day."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("adblock_day", [])
        ):
            if series["insight_type"] == "adblock":
                return cast("int | None", series["sum"])
        return None

    @property
    def adblock_month(self) -> int | None:
        """Adblock month."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("adblock_month", [])
        ):
            if series["insight_type"] == "adblock":
                return cast("int | None", series["sum"])
        return None

    @property
    def adblock_week(self) -> int | None:
        """Adblock week."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("adblock_week", [])
        ):
            if series["insight_type"] == "adblock":
                return cast("int | None", series["sum"])
        return None

    @property
    def app_events(self) -> list[Any]:
        """Recent app events, newest-fetched call first.

        A bounded page from the hourly tier's activity read
        (events.get_app_events), only populated when the app_events
        activity is configured for this network.
        """
        events = self.data.get("activity", {}).get("network", {}).get("app_events")
        return events if isinstance(events, list) else []

    @property
    def backup_internet_enabled(self) -> bool | None:
        """Backup internet enabled."""
        return self.data.get("backup_internet_enabled")

    async def async_set_backup_internet_enabled(self, value: bool) -> None:
        """Set backup internet."""
        await self.api.call(
            self.api.sdk.backup.set_backup_internet(self.sdk_id, value),
            name=f"{self.url}/backupinternet",
        )

    @property
    def band_steering(self) -> bool | None:
        """Band steering."""
        return self.data.get("band_steering")

    async def async_set_band_steering(self, value: bool) -> None:
        """Set band steering."""
        await self.api.call(
            self.api.sdk.security.set_band_steering(self.sdk_id, value, parent=self.data),
            name=f"{self.url}/settings",
        )

    @property
    def block_malware(self) -> bool | None:
        """Block malware."""
        return (
            cast("bool | None", self.data.get("premium_dns", {})
            .get("dns_policies", {})
            .get("block_malware"))
        )

    async def async_set_block_malware(self, value: bool) -> None:
        """Set Advanced Security malware blocking."""
        await self.api.post(
            f"{self.url_dns_policies}/network", json={"block_malware": value}
        )

    @property
    def blocked_day(self) -> dict[str, int | None]:
        """Blocked day."""
        data: dict[str, int | None] = {
            "blocked": None,
            "botnet": None,
            "domains": None,
            "malware": None,
            "parked": None,
            "phishing": None,
            "spyware": None,
        }
        for series in (
            self.data.get("activity", {}).get("network", {}).get("blocked_day", [])
        ):
            if series["insight_type"] in list(data.keys()):
                data[series["insight_type"]] = series["sum"]
        return data

    @property
    def blocked_month(self) -> dict[str, int | None]:
        """Blocked month."""
        data: dict[str, int | None] = {
            "blocked": None,
            "botnet": None,
            "domains": None,
            "malware": None,
            "parked": None,
            "phishing": None,
            "spyware": None,
        }
        for series in (
            self.data.get("activity", {}).get("network", {}).get("blocked_month", [])
        ):
            if series["insight_type"] in list(data.keys()):
                data[series["insight_type"]] = series["sum"]
        return data

    @property
    def blocked_week(self) -> dict[str, int | None]:
        """Blocked week."""
        data: dict[str, int | None] = {
            "blocked": None,
            "botnet": None,
            "domains": None,
            "malware": None,
            "parked": None,
            "phishing": None,
            "spyware": None,
        }
        for series in (
            self.data.get("activity", {}).get("network", {}).get("blocked_week", [])
        ):
            if series["insight_type"] in list(data.keys()):
                data[series["insight_type"]] = series["sum"]
        return data

    @property
    def city(self) -> str | None:
        """City."""
        return cast("str | None", self.data.get("geo_ip", {}).get("city"))

    @property
    def clients_count(self) -> int | None:
        """Clients count."""
        return cast("int | None", self.data.get("clients", {}).get("count"))

    @property
    def connected_clients_count(self) -> int:
        """Connected clients count."""
        return len([client for client in self.clients if client.connected])

    @property
    def connected_clients_count_computers_personal(self) -> int:
        """Connected clients count computers personal."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.device_category == DEVICE_CATEGORY_COMPUTERS_PERSONAL
            ]
        )

    @property
    def connected_clients_count_entertainment(self) -> int:
        """Connected clients count entertainment."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.device_category == DEVICE_CATEGORY_ENTERTAINMENT
            ]
        )

    @property
    def connected_clients_count_home(self) -> int:
        """Connected clients count home."""
        return len(
            [
                client
                for client in self.clients
                if client.connected and client.device_category == DEVICE_CATEGORY_HOME
            ]
        )

    @property
    def connected_clients_count_other(self) -> int:
        """Connected clients count other."""
        return len(
            [
                client
                for client in self.clients
                if client.connected and client.device_category == DEVICE_CATEGORY_OTHER
            ]
        )

    @property
    def connected_guest_clients_count(self) -> int:
        """Connected guest clients count."""
        return len(
            [client for client in self.clients if client.connected and client.is_guest]
        )

    @property
    def connected_guest_clients_count_computers_personal(self) -> int:
        """Connected guest clients count computers personal."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.is_guest
                and client.device_category == DEVICE_CATEGORY_COMPUTERS_PERSONAL
            ]
        )

    @property
    def connected_guest_clients_count_entertainment(self) -> int:
        """Connected guest clients count entertainment."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.is_guest
                and client.device_category == DEVICE_CATEGORY_ENTERTAINMENT
            ]
        )

    @property
    def connected_guest_clients_count_home(self) -> int:
        """Connected guest clients count home."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.is_guest
                and client.device_category == DEVICE_CATEGORY_HOME
            ]
        )

    @property
    def connected_guest_clients_count_other(self) -> int:
        """Connected guest clients count other."""
        return len(
            [
                client
                for client in self.clients
                if client.connected
                and client.is_guest
                and client.device_category == DEVICE_CATEGORY_OTHER
            ]
        )

    @property
    def country_code(self) -> str | None:
        """Country code."""
        return cast("str | None", self.data.get("geo_ip", {}).get("countryCode"))

    @property
    def country_name(self) -> str | None:
        """Country name."""
        return cast("str | None", self.data.get("geo_ip", {}).get("countryName"))

    @property
    def data_usage_day(self) -> tuple[int | None, int | None]:
        """Data usage day."""
        down, up = None, None
        for series in (
            self.data.get("activity", {}).get("network", {}).get("data_usage_day", [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def data_usage_month(self) -> tuple[int | None, int | None]:
        """Data usage month."""
        down, up = None, None
        for series in (
            self.data.get("activity", {}).get("network", {}).get("data_usage_month", [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def data_usage_week(self) -> tuple[int | None, int | None]:
        """Data usage week."""
        down, up = None, None
        for series in (
            self.data.get("activity", {}).get("network", {}).get("data_usage_week", [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def ddns_enabled(self) -> bool | None:
        """DDNS enabled."""
        return cast("bool | None", self.data.get("ddns", {}).get("enabled"))

    @property
    def eeros_data_usage_summary_day(self) -> tuple[int | None, int | None]:
        """Today's hourly data usage summed across all eeros.

        Shape assumed identical to data_usage_day's list of {"type", "sum"}
        entries: data_usage.get_eeros_summary is not documented as
        live-verified against this shape by the SDK.
        """
        down, up = None, None
        for series in (
            self.data.get("activity", {})
            .get("network", {})
            .get("eeros_data_usage_summary_day", [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    async def async_set_ddns_enabled(self, value: bool) -> None:
        """Set dynamic DNS."""
        ddns = self.api.sdk.ddns
        await self.api.call(
            ddns.enable(self.sdk_id, parent=self.data)
            if value
            else ddns.disable(self.sdk_id, parent=self.data),
            name=f"{self.url}/ddns",
        )

    @property
    def ddns_subdomain(self) -> str | None:
        """DDNS subdomain."""
        return cast("str | None", self.data.get("ddns", {}).get("subdomain"))

    @property
    def dns_caching(self) -> bool | None:
        """DNS caching."""
        return cast("bool | None", self.data.get("dns", {}).get("caching"))

    async def async_set_dns_caching(self, value: bool) -> None:
        """Set local DNS caching. The API reboots every eero after a DNS write."""
        await self.api.call(
            self.api.sdk.dns.set_dns_caching(self.sdk_id, value, parent=self.data),
            name=f"{self.url}/settings",
        )

    @property
    def dns_mode(self) -> str | None:
        """DNS mode ("custom" or "automatic"), the IPv4 selector.

        Already published on the network envelope the fast tier fetches:
        no extra request. The diagnostic sensor reads this, not a fresh
        dns.get_dns_settings call.
        """
        return cast("str | None", self.data.get("dns", {}).get("mode"))

    async def _current_dns(self) -> dict[str, Any]:
        """Return the DNS settings to compare against before a write.

        The network envelope the fast tier fetches already carries these
        (dns.get_dns_settings's own docstring: "DNS settings are part of
        the network resource"), so this only issues a request when that is
        somehow missing -- never unconditionally.
        """
        if "dns" in self.data or "ipv6" in self.data:
            return self.data
        return (
            await self.api.call(
                self.api.sdk.dns.get_dns_settings(self.sdk_id), name=f"{self.url}/settings"
            )
            or {}
        )

    async def async_set_custom_dns(
        self,
        ipv4: list[str] | None = None,
        ipv6: list[str] | None = None,
        automatic: bool = False,
    ) -> None:
        """Set custom DNS servers, or switch back to automatic.

        Every DNS write reboots the entire mesh a few minutes later, so
        read-compare-skip is mandatory here, not just good practice: each
        family's write is skipped when the network already reports the
        target state. The families that change are sent in one write (a
        family not supplied, or already as asked, is left untouched);
        automatic=True switches both back in one write and ignores ipv4/ipv6.
        """
        current = await self._current_dns()
        if automatic:
            ipv4_mode = current.get("dns", {}).get("mode")
            ipv6_mode = current.get("ipv6", {}).get("name_servers", {}).get("mode")
            if ipv4_mode == "automatic" and ipv6_mode == "automatic":
                _LOGGER.debug("Skipping set_custom_dns(automatic): already automatic")
                return
            await self.api.call(
                self.api.sdk.dns.set_dns_mode(self.sdk_id, "automatic", parent=self.data),
                name=f"{self.url}/settings",
            )
            return
        # Both families go in one write: two writes would mean two reboots.
        changed: list[str] = []
        if ipv4:
            dns = current.get("dns", {})
            if dns.get("mode") == "custom" and _same_dns_servers(
                dns.get("custom", {}).get("ips") or [], ipv4
            ):
                _LOGGER.debug("Skipping set_custom_dns ipv4: already set")
            else:
                changed.extend(ipv4)
        if ipv6:
            name_servers = current.get("ipv6", {}).get("name_servers", {})
            if name_servers.get("mode") == "custom" and _same_dns_servers(
                name_servers.get("custom") or [], ipv6
            ):
                _LOGGER.debug("Skipping set_custom_dns ipv6: already set")
            else:
                changed.extend(ipv6)
        if not changed:
            return
        # set_custom_dns leaves a family that is not in the list untouched.
        await self.api.call(
            self.api.sdk.dns.set_custom_dns(self.sdk_id, changed, parent=self.data),
            name=f"{self.url}/settings",
        )

    @property
    def reservation_count(self) -> int | None:
        """Number of DHCP reservations, from the daily-tier reservations read."""
        reservations = self.data.get("reservations")
        if not isinstance(reservations, dict):
            return None
        return reservations.get("count")

    async def async_create_reservation(self, reservation_data: dict[str, Any]) -> None:
        """Create a DHCP reservation. Fields: description, ip, mac, public_static_ip.

        Skipped when the daily-tier reservations read already shows an
        entry with this exact IP and MAC.
        """
        existing = (self.data.get("reservations") or {}).get("data") or []
        for entry in existing:
            if (
                isinstance(entry, dict)
                and entry.get("ip") == reservation_data.get("ip")
                and entry.get("mac") == reservation_data.get("mac")
            ):
                _LOGGER.debug(
                    "Skipping create_reservation: an identical reservation exists"
                )
                return
        await self.api.call(
            self.api.sdk.reservations.create_reservation(self.sdk_id, reservation_data),
            name=f"{self.url}/reservations",
        )

    async def async_delete_reservation(
        self, reservation_id: str, delete_forwards: bool | None = None
    ) -> None:
        """Delete a DHCP reservation, optionally deleting forwards that reference it."""
        kwargs = {} if delete_forwards is None else {"delete_forwards": delete_forwards}
        await self.api.call(
            self.api.sdk.reservations.delete_reservation(
                self.sdk_id, reservation_id, **kwargs
            ),
            name=f"{self.url}/reservations/{reservation_id}",
        )

    @property
    def forward_count(self) -> int | None:
        """Number of port forwards, from the daily-tier forwards read."""
        forwards = self.data.get("forwards")
        if not isinstance(forwards, dict):
            return None
        return forwards.get("count")

    async def async_create_port_forward(self, forward_data: dict[str, Any]) -> None:
        """Create a port forward.

        Fields: client_port, description, enabled, gateway_port, ip,
        protocol.

        Skipped when the daily-tier forwards read already shows an entry
        with this exact IP, client port, gateway port and protocol.
        """
        existing = (self.data.get("forwards") or {}).get("data") or []
        for entry in existing:
            if not isinstance(entry, dict):
                continue
            if all(
                entry.get(field) == forward_data.get(field)
                for field in ("ip", "client_port", "gateway_port", "protocol")
            ):
                _LOGGER.debug(
                    "Skipping create_port_forward: an identical forward exists"
                )
                return
        await self.api.call(
            self.api.sdk.forwards.create_forward(self.sdk_id, forward_data),
            name=f"{self.url}/forwards",
        )

    async def async_delete_port_forward(self, forward_id: str) -> None:
        """Delete a port forward."""
        await self.api.call(
            self.api.sdk.forwards.delete_forward(self.sdk_id, forward_id),
            name=f"{self.url}/forwards/{forward_id}",
        )

    @property
    def _release_notes(self) -> dict[str, Any]:
        """Release notes block, or an empty dict when the network reports none."""
        return self.data.get("updates", {}).get("release_notes") or {}

    @property
    def fast_transition_enabled(self) -> bool | None:
        """802.11r fast transition enabled.

        From a dedicated daily-tier read (security.get_fast_transition,
        the SDK's own "verified read"): not part of the base network
        envelope the way wpa3/upnp/band_steering are.
        """
        return self.data.get("fast_transition_enabled")

    async def async_set_fast_transition_enabled(self, value: bool) -> None:
        """Set 802.11r fast transition. Unconfirmed write: may reboot every eero."""
        await self.api.call(
            self.api.sdk.security.set_fast_transition(self.sdk_id, value, parent=self.data),
            name=f"{self.url}/fast_transition",
        )

    @property
    def firmware_history(self) -> list[EeroFirmware]:
        """Firmware history."""
        return [
            EeroFirmware(firmware)
            for firmware in self._release_notes.get("history") or []
        ]

    @property
    def gateway_ip(self) -> str | None:
        """Gateway IP."""
        return self.data.get("gateway_ip")

    @property
    def gateway_mac_address(self) -> str | None:
        """Gateway MAC address."""
        for eero in self.eeros:
            if eero.is_gateway:
                return eero.mac_address
        return None

    @property
    def gateway_name(self) -> str | None:
        """Gateway name."""
        for eero in self.eeros:
            if eero.is_gateway:
                return eero.name
        return None

    @property
    def guest_network_enabled(self) -> bool | None:
        """Guest network enabled."""
        return cast("bool | None", self.data.get("guest_network", {}).get("enabled"))

    async def async_set_guest_network_enabled(self, value: bool) -> None:
        """Set the guest network."""
        await self.api.call(
            self.api.sdk.networks.set_guest_network(self.sdk_id, enabled=value),
            name=f"{self.url}/guestnetwork",
        )

    @property
    def guest_network_name(self) -> str | None:
        """Guest network name."""
        return cast("str | None", self.data.get("guest_network", {}).get("name"))

    async def async_set_guest_network_name(self, value: str) -> None:
        """Rename the guest network, without changing whether it is enabled."""
        await self.api.call(
            self.api.sdk.networks.set_guest_network(
                self.sdk_id, enabled=bool(self.guest_network_enabled), name=value
            ),
            name=f"{self.url}/guestnetwork",
        )

    @property
    def guest_network_password(self) -> str | None:
        """Guest network password.

        Not read by any entity: the guest password text entity is
        write-only and never reports this value as state.
        """
        return cast("str | None", self.data.get("guest_network", {}).get("password"))

    async def async_set_guest_network_password(self, value: str) -> None:
        """Set the guest network's password."""
        await self.api.call(
            self.api.sdk.networks.set_guest_password(self.sdk_id, value),
            name=f"{self.url}/guestnetwork/password",
        )

    @property
    def health_eero_network_status(self) -> str | None:
        """Health Eero network status."""
        return cast("str | None", self.data.get("health", {}).get("eero_network", {}).get("status"))

    @property
    def health_internet_isp_up(self) -> bool | None:
        """Health internet ISP up."""
        return cast("bool | None", self.data.get("health", {}).get("internet", {}).get("isp_up"))

    @property
    def health_internet_status(self) -> str | None:
        """Health internet status."""
        return cast("str | None", self.data.get("health", {}).get("internet", {}).get("status"))

    @property
    def inspected_day(self) -> int | None:
        """Inspected day."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("inspected_day", [])
        ):
            if series["insight_type"] == "inspected":
                return cast("int | None", series["sum"])
        return None

    @property
    def inspected_month(self) -> int | None:
        """Inspected month."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("inspected_month", [])
        ):
            if series["insight_type"] == "inspected":
                return cast("int | None", series["sum"])
        return None

    @property
    def inspected_week(self) -> int | None:
        """Inspected week."""
        for series in (
            self.data.get("activity", {}).get("network", {}).get("inspected_week", [])
        ):
            if series["insight_type"] == "inspected":
                return cast("int | None", series["sum"])
        return None

    @property
    def ipv6_upstream(self) -> bool | None:
        """IPV6 upstream."""
        return self.data.get("ipv6_upstream")

    async def async_set_ipv6_upstream(self, value: bool) -> None:
        """Set IPv6 upstream only; security.set_ipv6 would set downstream too."""
        await self.api.put(cast("str", self.url_settings), json={"ipv6_upstream": value})

    @property
    def isp(self) -> str | None:
        """ISP."""
        return cast("str | None", self.data.get("geo_ip", {}).get("isp"))

    @property
    def mlo_mode(self) -> str | None:
        """MLO (Multi-Link Operation) mode: "disabled", "single", or "multi".

        Confirmed present on the network envelope by the eero app's own
        observed API schema (``Network.mlo_mode``, typed there as an
        opaque object; eero-api's set_mlo_mode writes/reads it as a plain
        string) -- not live-verified by eero-api itself, so this parses
        defensively: a string in the three known values, or a dict
        carrying one of them under "mode"/"value". Raises AttributeError
        (so the select entity is never created) when the network reports
        itself incapable, or the value does not parse: never a blind
        write with no confirmed state to compare against.
        """
        if not self.data.get("capabilities", {}).get("mlo_mode", {}).get("capable"):
            raise AttributeError("mlo_mode: network is not capable")
        raw = self.data.get("mlo_mode")
        value: Any = None
        if isinstance(raw, str):
            value = raw
        elif isinstance(raw, dict):
            value = raw.get("mode") or raw.get("value")
        if value not in (MLO_MODE_DISABLED, MLO_MODE_SINGLE, MLO_MODE_MULTI):
            raise AttributeError("mlo_mode: value did not parse")
        return cast("str | None", value)

    @property
    def mlo_mode_options(self) -> list[str]:
        """Every selectable MLO mode."""
        return [MLO_MODE_DISABLED, MLO_MODE_SINGLE, MLO_MODE_MULTI]

    async def async_set_mlo_mode(self, value: str) -> None:
        """Set the network's MLO mode. Unconfirmed write: may reboot every eero."""
        await self.api.call(
            self.api.sdk.security.set_mlo_mode(self.sdk_id, value, parent=self.data),
            name=f"{self.url}/mlo_mode",
        )

    @property
    def manifest_resource(self) -> str | None:
        """Manifest resource."""
        return cast("str | None", self.data.get("updates", {}).get("manifest_resource"))

    @property
    def name(self) -> str | None:
        """Name."""
        return self.data.get("name")

    @property
    def nickname(self) -> str | None:
        """Nickname."""
        return self.data.get("nickname_label")

    @property
    def name_unique(self) -> str | None:
        """Human-readable label that distinguishes networks with the same name."""
        label = f'{self.name} "{self.nickname}"' if self.nickname else self.name
        parts = [part for part in (self.city, self.region_name) if part]
        if parts:
            return f"{label} ({', '.join(parts)})"
        return label

    @property
    def notifications_has_unread(self) -> bool | None:
        """Whether this network has unread notifications.

        None until the hourly tier has fetched this (only configured when
        the notifications_has_unread activity is selected for this
        network), not False: the activity reads {"has_unread": bool}
        verbatim, so an unfetched value has no dict to read it from at all.
        """
        data = self.data.get("activity", {}).get("network", {}).get(
            "notifications_has_unread"
        )
        if isinstance(data, dict):
            return bool(data.get("has_unread"))
        return None

    @property
    def password(self) -> str | None:
        """Password."""
        return self.data.get("password")

    @property
    def pause_5g_enabled(self) -> bool | None:
        """Pause 5G enabled."""
        return cast("bool | None", self.data.get("temporary_flags", {}).get("hide_5g", {}).get("value"))

    @property
    def pause_5g_expiration(self) -> str | None:
        """Pause 5G expiration."""
        return cast("str | None", self.data.get("temporary_flags", {}).get("hide_5g", {}).get("expires_on"))

    async def async_set_pause_5g_enabled(self, value: bool) -> None:
        """Pause or resume the 5 GHz band."""
        url = f"{self.url}/temporary_flags/hide_5g"
        if value:
            await self.api.put(url, json={"value": True})
        else:
            await self.api.delete(url)

    @property
    def postal_code(self) -> str | None:
        """Postal code."""
        return cast("str | None", self.data.get("geo_ip", {}).get("postalCode"))

    @property
    def power_saving_enabled(self) -> bool | None:
        """Power saving enabled.

        A plain top-level boolean on the network envelope (confirmed by
        the eero app's own observed API schema: ``Network.power_saving``),
        not nested under a "power_saving" object; no extra request.
        """
        return self.data.get("power_saving")

    async def async_set_power_saving_enabled(self, value: bool) -> None:
        """Turn network-wide power saving on or off. Unconfirmed write."""
        await self.api.call(
            self.api.sdk.power_saving.set_power_saving(
                self.sdk_id, enable=value, parent=self.data
            ),
            name=f"{self.url}/power_saving",
        )

    @property
    def preferred_update_hour(self) -> str | None:
        """Preferred update hour."""
        hour = self.data.get("updates", {}).get("preferred_update_hour")
        if hour is None:
            return hour
        return {value: key for key, value in PREFERRED_UPDATE_HOUR_MAP.items()}.get(
            hour
        )

    async def async_set_preferred_update_hour(self, value: str) -> None:
        """Set the hour firmware updates may install."""
        if value not in self.preferred_update_hour_options:
            return
        await self.api.post(
            f"{self.url}/updates/preferred_update_hour",
            json={"preferred_update_hour": PREFERRED_UPDATE_HOUR_MAP[value]},
        )

    @property
    def preferred_update_hour_options(self) -> list[str]:
        """Preferred update hour options."""
        return list(PREFERRED_UPDATE_HOUR_MAP.keys())

    @property
    def premium_capable(self) -> bool | None:
        """Premium capable."""
        return cast("bool | None", self.data.get("capabilities", {}).get("premium", {}).get("capable"))

    @property
    def premium_status(self) -> str | None:
        """Premium status."""
        return self.data.get("premium_status")

    @property
    def premium_enabled(self) -> bool:
        """Premium enabled.

        From the entitlements read when the daily tier has one; from
        premium_status otherwise.
        """
        features = self.data.get("entitlements")
        if isinstance(features, dict) and isinstance(features.get("features"), list):
            return bool(features["features"])
        return premium_ok(
            capable=self.premium_capable,
            status=self.premium_status,
        )

    @property
    def public_ip(self) -> str | None:
        """Public IP."""
        return cast("str | None", self.data.get("ip_settings", {}).get("public_ip"))

    async def async_reboot(self) -> None:
        """Reboot every eero on the network."""
        await self.api.call(
            self.api.sdk.networks.reboot_network(self.sdk_id), name=f"{self.url}/reboot"
        )

    @property
    def region(self) -> str | None:
        """Region."""
        return cast("str | None", self.data.get("geo_ip", {}).get("region"))

    @property
    def region_name(self) -> str | None:
        """Region name."""
        return cast("str | None", self.data.get("geo_ip", {}).get("regionName"))

    async def async_run_internet_backup_test(self) -> None:
        """Run internet backup test."""
        await self.api.call(
            self.api.sdk.backup_access_points.connectivity_check(self.sdk_id),
            name=f"{self.url}/backup_access_points/connectivity_check",
        )

    async def async_run_speed_test(self) -> None:
        """Run speed test."""
        await self.api.call(
            self.api.sdk.networks.run_speed_test(self.sdk_id), name=f"{self.url}/speedtest"
        )

    @property
    def speed_date(self) -> str | None:
        """Speed date."""
        return cast("str | None", self.data.get("speed", {}).get("date"))

    @property
    def speed_down(self) -> tuple[int | None, str | None]:
        """Speed down."""
        return (
            self.data.get("speed", {}).get("down", {}).get("value"),
            self.data.get("speed", {}).get("down", {}).get("units"),
        )

    @property
    def speed_up(self) -> tuple[int | None, str | None]:
        """Speed up."""
        return (
            self.data.get("speed", {}).get("up", {}).get("value"),
            self.data.get("speed", {}).get("up", {}).get("units"),
        )

    @property
    def sqm(self) -> bool | None:
        """SQM."""
        return self.data.get("sqm")

    async def async_set_sqm(self, value: bool) -> None:
        """Set Smart Queue Management."""
        # Not sqm.set_sqm: it sends the value as a query parameter, a request
        # eero-api has not verified; this is the JSON body 1.x always sent.
        await self.api.put(cast("str", self.url_settings), json={"sqm": value})

    @property
    def ssid(self) -> str | None:
        """SSID."""
        return self.name

    @property
    def status(self) -> str | None:
        """Status."""
        return self.data.get("status")

    @property
    def target_firmware(self) -> EeroFirmware:
        """Target firmware."""
        return EeroFirmware(self._release_notes.get("target") or {})

    @property
    def thread_active_operational_dataset(self) -> str | None:
        """Thread active operational dataset."""
        return cast("str | None", self.data.get("thread", {}).get("active_operational_dataset"))

    @property
    def thread_channel(self) -> int | None:
        """Thread channel."""
        return cast("int | None", self.data.get("thread", {}).get("channel"))

    @property
    def thread_commissioning_credential(self) -> str | None:
        """Thread commissioning credentials."""
        return cast("str | None", self.data.get("thread", {}).get("commissioning_credential"))

    @property
    def thread_enabled(self) -> bool | None:
        """Thread enabled."""
        return cast("bool | None", self.data.get("thread", {}).get("enabled"))

    async def async_set_thread_enabled(self, value: bool) -> None:
        """Set Thread. Keeps the {thread}/enable path the integration has always used."""
        await self.api.put(f"{self.url_thread}/enable", json={"enabled": value})

    @property
    def thread_master_key(self) -> str | None:
        """Thread master key."""
        return cast("str | None", self.data.get("thread", {}).get("master_key"))

    @property
    def thread_name(self) -> str | None:
        """Thread name."""
        return cast("str | None", self.data.get("thread", {}).get("name"))

    @property
    def thread_pan_id(self) -> str | None:
        """Thread PAN ID."""
        return cast("str | None", self.data.get("thread", {}).get("pan_id"))

    @property
    def thread_xpan_id(self) -> str | None:
        """Thread XPAN ID."""
        return cast("str | None", self.data.get("thread", {}).get("xpan_id"))

    @property
    def unprofiled_data_usage_day(self) -> tuple[int | None, int | None]:
        """Today's hourly data usage summed across unprofiled devices.

        Shape assumed identical to data_usage_day's list of {"type", "sum"}
        entries: data_usage.get_unprofiled_summary is not documented as
        live-verified against this shape by the SDK.
        """
        down, up = None, None
        for series in (
            self.data.get("activity", {})
            .get("network", {})
            .get("unprofiled_data_usage_day", [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    async def async_install_firmware_update(self) -> None:
        """Trigger a firmware update for every eero on this network."""
        await self.api.call(
            self.api.sdk.updates.apply_update(self.sdk_id), name=f"{self.url}/updates"
        )

    @property
    def upnp(self) -> bool | None:
        """UPNP."""
        return self.data.get("upnp")

    async def async_set_upnp(self, value: bool) -> None:
        """Set UPnP."""
        await self.api.call(
            self.api.sdk.security.set_upnp(self.sdk_id, value, parent=self.data), name=f"{self.url}/settings"
        )

    @property
    def url_dns_policies(self) -> str:
        """URL DNS Policies."""
        return f"{self.url}/dns_policies"

    @property
    def url_insights(self) -> str | None:
        """URL insights."""
        return cast("str | None", self.data.get("resources", {}).get("insights"))

    @property
    def url_reboot(self) -> str | None:
        """URL reboot."""
        return cast("str | None", self.data.get("resources", {}).get("reboot"))

    @property
    def url_settings(self) -> str | None:
        """URL settings."""
        return cast("str | None", self.data.get("resources", {}).get("settings"))

    @property
    def url_thread(self) -> str | None:
        """URL thread."""
        return cast("str | None", self.data.get("resources", {}).get("thread"))

    @property
    def url_updates(self) -> str | None:
        """URL updates."""
        return cast("str | None", self.data.get("resources", {}).get("updates"))

    @property
    def wan_router_ip(self) -> str | None:
        """WAN router ip."""
        return cast("str | None", self.data.get("lease", {}).get("dhcp", {}).get("router"))

    @property
    def wan_subnet_mask(self) -> str | None:
        """WAN subnet mask."""
        return cast("str | None", self.data.get("lease", {}).get("dhcp", {}).get("mask"))

    @property
    def wpa3(self) -> bool | None:
        """WPA3."""
        return self.data.get("wpa3")

    async def async_set_wpa3(self, value: bool) -> None:
        """Set WPA3."""
        await self.api.call(
            self.api.sdk.security.set_wpa3(self.sdk_id, value, parent=self.data), name=f"{self.url}/settings"
        )

    @cached_property
    def backup_networks(self) -> list[EeroBackupNetwork]:
        """Backup networks."""
        return [
            EeroBackupNetwork(self.api, self, backup_network)
            for backup_network in self.data.get("backup_access_points", {}).get(
                "data", []
            )
        ]

    @cached_property
    def clients(self) -> list[EeroClient]:
        """Clients."""
        return [
            EeroClient(self.api, self, client)
            for client in self.data.get("devices", {}).get("data", [])
        ]

    @cached_property
    def eeros(self) -> list[EeroDevice]:
        """Eeros."""
        eeros: list[EeroDevice] = []
        for eero in self.data.get("eeros", {}).get("data", []):
            if eero["model"] == MODEL_BEACON:
                eeros.append(EeroDeviceBeacon(self.api, self, eero))
            else:
                eeros.append(EeroDevice(self.api, self, eero))
        return eeros

    @cached_property
    def profiles(self) -> list[EeroProfile]:
        """Profiles."""
        return [
            EeroProfile(self.api, self, profile)
            for profile in self.data.get("profiles", {}).get("data", [])
        ]

    @cached_property
    def resources(
        self,
    ) -> list[EeroResource]:
        """Resources."""
        return [*self.backup_networks, *self.eeros, *self.profiles, *self.clients]

    @cached_property
    def resource_by_id(self) -> dict[str, EeroResource]:
        """Resources of this network by ID, built once per tree.

        The first resource wins on a shared ID, as a scan of resources in
        order (backup networks, eeros, profiles, clients) would find it.
        """
        index: dict[str, EeroResource] = {}
        for resource in self.resources:
            if resource.id is not None:
                index.setdefault(resource.id, resource)
        return index
