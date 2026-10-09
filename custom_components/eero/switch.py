"""Support for Eero switch entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TIER_DAILY, TIER_FAST
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_BACKUP_NETWORKS,
    KIND_CLIENTS,
    KIND_NETWORK,
    KIND_PROFILES,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EeroSwitchEntityDescription(EeroEntityDescription, SwitchEntityDescription):
    """Class to describe an Eero switch entity."""

    device_class: SwitchDeviceClass | None = SwitchDeviceClass.SWITCH
    entity_category: EntityCategory | None = EntityCategory.CONFIG


SWITCH_DESCRIPTIONS: list[EeroSwitchEntityDescription] = [
    EeroSwitchEntityDescription(
        key="ad_block",
        name="Ad Blocking",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="auto_join_enabled",
        name="Auto-Join Enabled",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="backup_internet_enabled",
        name="Backup Internet Enabled",
        premium_type=True,
        extra_tiers=(TIER_DAILY,),
        refresh_tiers=(TIER_FAST, TIER_DAILY),
    ),
    EeroSwitchEntityDescription(
        key="band_steering",
        name="Band Steering",
    ),
    EeroSwitchEntityDescription(
        key="block_gaming_content",
        name="Gaming Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_illegal_content",
        name="Illegal or Criminal Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_malware",
        name="Advanced Security",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_messaging_content",
        name="Chat and Messaging Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_pornographic_content",
        name="Adult Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_shopping_content",
        name="Shopping Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_social_content",
        name="Social Media Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_streaming_content",
        name="Streaming Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_violent_content",
        name="Violent Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="ddns_enabled",
        name="Dynamic DNS",
        premium_type=True,
        extra_attrs={
            "domain": lambda resource: resource.ddns_subdomain,
        },
    ),
    EeroSwitchEntityDescription(
        key="dns_caching",
        name="Local DNS Caching",
        # A DNS write reboots every eero on the network a few minutes later.
        request_refresh=False,
    ),
    EeroSwitchEntityDescription(
        key="guest_network_enabled",
        name="Guest Network",
        extra_attrs={
            "guest_network_name": lambda resource: resource.guest_network_name,
            "connected_guest_clients": lambda resource: resource.connected_guest_clients_count,
        },
    ),
    EeroSwitchEntityDescription(
        key="ipv6_upstream",
        name="IPv6 Enabled",
        request_refresh=False,
    ),
    EeroSwitchEntityDescription(
        key="pause_5g_enabled",
        name="5 GHz Band Paused",
        extra_attrs={
            "expiration": lambda resource: resource.pause_5g_expiration,
        },
    ),
    EeroSwitchEntityDescription(
        key="paused",
        name="Paused",
    ),
    EeroSwitchEntityDescription(
        key="safe_search_enabled",
        name="SafeSearch Content Filter",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="secondary_wan_allow_access",
        name="Allow Internet Backup",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="sqm",
        name="Smart Queue Management",
    ),
    EeroSwitchEntityDescription(
        key="thread_enabled",
        name="Thread Enabled",
        tier=TIER_DAILY,
        extra_attrs={
            "thread_network_name": lambda resource: resource.thread_name,
            "channel": lambda resource: resource.thread_channel,
            "pan_id": lambda resource: resource.thread_pan_id,
            "extended_pan_id": lambda resource: resource.thread_xpan_id,
        },
    ),
    EeroSwitchEntityDescription(
        key="upnp",
        name="UPnP",
    ),
    EeroSwitchEntityDescription(
        key="wpa3",
        name="WPA3",
    ),
    EeroSwitchEntityDescription(
        key="youtube_restricted",
        name="YouTube Restricted Content Filter",
        premium_type=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero switch entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            SWITCH_DESCRIPTIONS,
            EeroSwitchEntity,
            (KIND_NETWORK, KIND_BACKUP_NETWORKS, KIND_PROFILES, KIND_CLIENTS),
        )
    )


class EeroSwitchEntity(EeroEntity, SwitchEntity):
    """Representation of an Eero switch entity."""

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on."""
        return bool(getattr(self.resource, self.entity_description.key))

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        attrs = {}
        if self.entity_description.extra_attrs and self.is_on:
            for key, func in self.entity_description.extra_attrs.items():
                attrs[key] = func(self.resource)
        return attrs

    async def _async_set(self, value: bool) -> None:
        await self.async_write(
            f"async_set_{self.entity_description.key}",
            value,
            current=self.is_on,
            target=value,
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self._async_set(False)
