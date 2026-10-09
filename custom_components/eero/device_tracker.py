"""Support for Eero device tracker entities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.device_tracker import (
    BaseScannerEntity,
    SourceType,
)
from homeassistant.const import ATTR_MANUFACTURER
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import CONF_CONSIDER_HOME
from .coordinator import EeroConfigEntry, EeroRuntime
from .entity import (
    KIND_CLIENTS,
    KIND_PROFILES,
    EeroEntity,
    EeroEntityDescription,
    async_setup_platform_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroDeviceTrackerEntityDescription(EeroEntityDescription):
    """Class to describe an Eero device tracker entity."""

    check_support: bool = False
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    source_type: SourceType = SourceType.ROUTER


DEVICE_TRACKER_DESCRIPTIONS: list[EeroDeviceTrackerEntityDescription] = [
    EeroDeviceTrackerEntityDescription(
        key="device_tracker",
    ),
]


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero device tracker entity based on a config entry."""
    async_setup_platform_entities(
        config_entry,
        DEVICE_TRACKER_DESCRIPTIONS,
        EeroDeviceTrackerEntity,
        (KIND_PROFILES, KIND_CLIENTS),
        async_add_entities,
    )


class EeroDeviceTrackerEntity(EeroEntity, BaseScannerEntity):
    """Representation of an Eero device tracker entity."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        runtime: EeroRuntime,
        network_id: str,
        resource_id: str | None,
        description: EeroDeviceTrackerEntityDescription,
        tier: str | None = None,
    ) -> None:
        """Initialize device."""
        super().__init__(runtime, network_id, resource_id, description, tier)
        self.consider_home: timedelta = timedelta(
            minutes=runtime.miscellaneous[network_id][CONF_CONSIDER_HOME]
        )
        self.last_seen: datetime | None = None

    @property
    def is_connected(self) -> bool | None:
        """Return true if the device is connected to the network."""
        if self.consider_home:
            if not self.resource.connected:
                return bool(
                    self.last_seen
                    and (dt_util.utcnow() - self.last_seen) < self.consider_home
                )
            self.last_seen = dt_util.utcnow()
            return True
        return self.resource.connected

    @property
    def source_type(self) -> SourceType | str:
        """Return the source type, eg gps or router, of the device."""
        return self.entity_description.source_type

    @property
    def ip_address(self) -> str | None:
        """Return the primary ip address of the device."""
        if self.resource.is_client:
            return self.resource.ip
        return None

    @property
    def mac_address(self) -> str | None:
        """Return the mac address of the device."""
        if self.resource.is_client:
            return self.resource.mac
        return None

    @property
    def hostname(self) -> str | None:
        """Return hostname of the device."""
        if self.resource.is_client:
            return self.resource.hostname
        return None

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes.

        Implemented by platform classes. Convention for attribute names
        is lowercase snake_case.
        """
        attrs: dict[str, Any] = {}
        if self.resource is None or self.network is None:
            return attrs
        if self.is_connected and self.resource.is_client:
            attrs["connected_to"] = self.resource.source_location
            attrs["connection_type"] = self.resource.connection_type
            if ip_address := self.ip_address:
                attrs["ip"] = ip_address
            if mac_address := self.mac_address:
                attrs["mac"] = mac_address
            if hostname := self.hostname:
                attrs["host_name"] = hostname
            if manufacturer := self.resource.manufacturer:
                attrs[ATTR_MANUFACTURER] = manufacturer
            attrs["network_name"] = self.network.name
            if self.resource.wireless:
                frequency, frequency_unit = self.resource.interface_frequency
                if frequency:
                    attrs["band"] = (
                        f"{frequency} {frequency_unit}"
                        if frequency_unit
                        else str(frequency)
                    )
                if self.resource.channel is not None:
                    attrs["channel"] = self.resource.channel
                if channel_width_rx := self.resource.channel_width_rx:
                    attrs["channel_width_rx"] = channel_width_rx
        return attrs
