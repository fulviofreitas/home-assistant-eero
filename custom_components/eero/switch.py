"""Support for Eero switch entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
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
    async_setup_platform_entities,
)

if TYPE_CHECKING:
    # Moved to .const in Home Assistant 2026.10; still defined in the package
    # itself before that, which is what runs on both.
    from homeassistant.components.switch.const import SwitchDeviceClass
else:
    from homeassistant.components.switch import SwitchDeviceClass

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EeroSwitchEntityDescription(EeroEntityDescription, SwitchEntityDescription):
    """Class to describe an Eero switch entity."""

    device_class: SwitchDeviceClass | None = SwitchDeviceClass.SWITCH
    entity_category: EntityCategory | None = EntityCategory.CONFIG


SWITCH_DESCRIPTIONS: list[EeroSwitchEntityDescription] = [
    EeroSwitchEntityDescription(
        key="ad_block",
        translation_key="ad_block",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="auto_join_enabled",
        translation_key="auto_join_enabled",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="backup_internet_enabled",
        translation_key="backup_internet_enabled",
        premium_type=True,
        extra_tiers=(TIER_DAILY,),
        refresh_tiers=(TIER_FAST, TIER_DAILY),
    ),
    EeroSwitchEntityDescription(
        key="band_steering",
        translation_key="band_steering",
    ),
    EeroSwitchEntityDescription(
        key="bedtime_enabled",
        translation_key="bedtime_enabled",
        tier=TIER_DAILY,
        requires_value=True,
    ),
    EeroSwitchEntityDescription(
        key="blocked",
        translation_key="blocked",
        tier=TIER_DAILY,
        # Blocking removes the device from the network entirely: the fast
        # tier's device list changes too, not just the daily-tier blacklist.
        refresh_tiers=(TIER_FAST, TIER_DAILY),
        requires_value=True,
    ),
    EeroSwitchEntityDescription(
        key="block_gaming_content",
        translation_key="block_gaming_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_illegal_content",
        translation_key="block_illegal_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_malware",
        translation_key="block_malware",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_messaging_content",
        translation_key="block_messaging_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_pornographic_content",
        translation_key="block_pornographic_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_shopping_content",
        translation_key="block_shopping_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_social_content",
        translation_key="block_social_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_streaming_content",
        translation_key="block_streaming_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="block_violent_content",
        translation_key="block_violent_content",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="ddns_enabled",
        translation_key="ddns_enabled",
        premium_type=True,
        extra_attrs={
            "domain": lambda resource: resource.ddns_subdomain,
        },
    ),
    EeroSwitchEntityDescription(
        key="dns_caching",
        translation_key="dns_caching",
        # A DNS write reboots every eero on the network a few minutes later.
        request_refresh=False,
    ),
    EeroSwitchEntityDescription(
        key="fast_transition_enabled",
        translation_key="fast_transition_enabled",
        tier=TIER_DAILY,
        # Unconfirmed write: may reboot every eero. Re-reading the daily
        # tier afterwards is a GET, and without it the switch would show
        # the old state for a day and read-compare-skip would compare
        # against it.
        refresh_tiers=(TIER_DAILY,),
        requires_value=True,
    ),
    EeroSwitchEntityDescription(
        key="guest_network_enabled",
        translation_key="guest_network_enabled",
        extra_attrs={
            "guest_network_name": lambda resource: resource.guest_network_name,
            "connected_guest_clients": lambda resource: resource.connected_guest_clients_count,
        },
    ),
    EeroSwitchEntityDescription(
        key="ipv6_upstream",
        translation_key="ipv6_upstream",
        request_refresh=False,
    ),
    EeroSwitchEntityDescription(
        key="pause_5g_enabled",
        translation_key="pause_5g_enabled",
        extra_attrs={
            "expiration": lambda resource: resource.pause_5g_expiration,
        },
    ),
    EeroSwitchEntityDescription(
        key="paused",
        translation_key="paused",
    ),
    EeroSwitchEntityDescription(
        key="power_saving_enabled",
        translation_key="power_saving_enabled",
        # Unconfirmed write: may reboot every eero. Re-read afterwards (a
        # GET) so the state, and read-compare-skip, are not left stale.
        requires_value=True,
    ),
    EeroSwitchEntityDescription(
        key="safe_search_enabled",
        translation_key="safe_search_enabled",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="secondary_wan_allow_access",
        translation_key="secondary_wan_allow_access",
        premium_type=True,
    ),
    EeroSwitchEntityDescription(
        key="sqm",
        translation_key="sqm",
    ),
    EeroSwitchEntityDescription(
        key="thread_enabled",
        translation_key="thread_enabled",
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
        translation_key="upnp",
    ),
    EeroSwitchEntityDescription(
        key="wpa3",
        translation_key="wpa3",
    ),
    EeroSwitchEntityDescription(
        key="youtube_restricted",
        translation_key="youtube_restricted",
        premium_type=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero switch entity based on a config entry."""
    async_setup_platform_entities(
        config_entry,
        SWITCH_DESCRIPTIONS,
        EeroSwitchEntity,
        (KIND_NETWORK, KIND_BACKUP_NETWORKS, KIND_PROFILES, KIND_CLIENTS),
        async_add_entities,
    )


class EeroSwitchEntity(EeroEntity, SwitchEntity):
    """Representation of an Eero switch entity."""

    entity_description: EeroSwitchEntityDescription

    @property
    def is_on(self) -> bool | None:
        """Return True if entity is on; None when the state is not known."""
        if (value := getattr(self.resource, self.entity_description.key, None)) is None:
            return None
        return bool(value)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes."""
        attrs: dict[str, Any] = {}
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
