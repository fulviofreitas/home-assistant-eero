"""Support for Eero binary sensor entities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TIER_HOURLY
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_BACKUP_NETWORKS,
    KIND_CLIENTS,
    KIND_EEROS,
    KIND_NETWORK,
    KIND_PROFILES,
    EeroEntity,
    EeroEntityDescription,
    async_setup_platform_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroBinarySensorEntityDescription(
    EeroEntityDescription, BinarySensorEntityDescription
):
    """Class to describe an Eero binary sensor entity."""

    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    extra_attrs_wireless_only: dict[str, Callable] | None = None


BINARY_SENSOR_DESCRIPTIONS: list[EeroBinarySensorEntityDescription] = [
    EeroBinarySensorEntityDescription(
        key="block_apps_enabled",
        translation_key="block_apps_enabled",
        extra_attrs={
            "blocked_apps": lambda resource: sorted(resource.blocked_applications),
        },
    ),
    EeroBinarySensorEntityDescription(
        key="connected",
        translation_key="connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        extra_attrs_wireless_only={
            "bandwidth_receive": lambda resource: resource.channel_width_rx,
            "bandwidth_transmit": lambda resource: resource.channel_width_tx,
            "channel": lambda resource: resource.channel,
            "operating_band": lambda resource: f"{resource.interface_frequency[0]} {resource.interface_frequency[1]}",
        },
    ),
    EeroBinarySensorEntityDescription(
        key="notifications_has_unread",
        translation_key="notifications_has_unread",
        activity_type=True,
        tier=TIER_HOURLY,
    ),
]


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero binary sensor entity based on a config entry."""
    async_setup_platform_entities(
        config_entry,
        BINARY_SENSOR_DESCRIPTIONS,
        EeroBinarySensorEntity,
        (KIND_NETWORK, KIND_BACKUP_NETWORKS, KIND_EEROS, KIND_PROFILES, KIND_CLIENTS),
        async_add_entities,
    )


class EeroBinarySensorEntity(EeroEntity, BinarySensorEntity):
    """Representation of an Eero binary sensor entity."""

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return getattr(self.resource, self.entity_description.key)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes.

        Implemented by platform classes. Convention for attribute names
        is lowercase snake_case.
        """
        attrs: dict[str, Any] = {}
        if self.resource is not None and self.is_on:
            if self.entity_description.extra_attrs:
                for key, func in self.entity_description.extra_attrs.items():
                    attrs[key] = func(self.resource)
            if (
                self.entity_description.extra_attrs_wireless_only
                and self.resource.is_client
                and self.resource.wireless
            ):
                for (
                    key,
                    func,
                ) in self.entity_description.extra_attrs_wireless_only.items():
                    attrs[key] = func(self.resource)
        return attrs
