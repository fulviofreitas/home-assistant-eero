"""Support for Eero sensor entities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    UnitOfDataRate,
    UnitOfInformation,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .api.const import (
    DEVICE_CATEGORY_COMPUTERS_PERSONAL,
    DEVICE_CATEGORY_ENTERTAINMENT,
    DEVICE_CATEGORY_HOME,
    DEVICE_CATEGORY_OTHER,
    PERIOD_DAY,
    STATE_AUTOMATIC,
    STATE_CUSTOM,
    STATE_DISABLED,
    STATE_FAILURE,
    STATE_NETWORK,
    STATE_PROFILE,
)
from .api.util import sum_data_usage
from .const import TIER_DAILY, TIER_HOURLY
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_BACKUP_NETWORKS,
    KIND_CLIENTS,
    KIND_EEROS,
    KIND_NETWORK,
    KIND_PROFILES,
    EeroEntity,
    EeroEntityDescription,
    EeroPortEntity,
    async_setup_platform_entities,
    async_setup_port_entities,
)
from .util import resource_supports

#: PhyRate enum (eero app's observed API schema) -> Mbit/s. Not documented
#: or live-verified by eero-api itself, which has no reader for a port's
#: speed at all.
_PHY_RATE_MBPS = {
    "P10": 10,
    "P100": 100,
    "P1000": 1000,
    "P2500": 2500,
    "P5000": 5000,
    "P10000": 10000,
    "P25000": 25000,
}


def _port_negotiated_speed(port: dict) -> int | None:
    """Return a port's negotiated speed in Mbit/s, or None if unrecognised."""
    return _PHY_RATE_MBPS.get(port.get("negotiated_speed"))


def _port_connection_status(port: dict) -> str | None:
    """Return a port's connection status.

    PortConnectionStatus is an opaque object in the observed schema; this
    stays defensive about it being a plain string in practice (as
    PortConnectionPower/WirelessConnectionStatus siblings suggest for this
    whole family) or a dict carrying the real value under "status"/"value".
    """
    status = port.get("connection_status")
    if isinstance(status, dict):
        return status.get("status") or status.get("value")
    if isinstance(status, str):
        return status
    return None


@dataclass(frozen=True, kw_only=True)
class EeroPortSensorEntityDescription(SensorEntityDescription):
    """Class to describe one per-port sensor field."""

    value_fn: Callable[[dict], Any]
    translation_key: str | None = None
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC


PORT_SENSOR_DESCRIPTIONS: tuple[EeroPortSensorEntityDescription, ...] = (
    EeroPortSensorEntityDescription(
        key="connection_status",
        translation_key="port_connection_status",
        value_fn=_port_connection_status,
    ),
    EeroPortSensorEntityDescription(
        key="negotiated_speed",
        translation_key="port_negotiated_speed",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_port_negotiated_speed,
    ),
)

DEVICE_CATEGORIES = [
    DEVICE_CATEGORY_COMPUTERS_PERSONAL,
    DEVICE_CATEGORY_ENTERTAINMENT,
    DEVICE_CATEGORY_HOME,
    DEVICE_CATEGORY_OTHER,
]

SIGNAL_STRENGTH_UNIT_MAP = {
    "dBm": SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
}

SPEED_UNIT_MAP = {
    "Kbps": UnitOfDataRate.KILOBITS_PER_SECOND,
    "Mbps": UnitOfDataRate.MEGABITS_PER_SECOND,
    "Gbps": UnitOfDataRate.GIGABITS_PER_SECOND,
}


@dataclass(frozen=True, kw_only=True)
class EeroSensorEntityDescription(EeroEntityDescription, SensorEntityDescription):
    """Class to describe an Eero sensor entity."""

    native_value: Callable = lambda resource, key: getattr(resource, key)
    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC
    # Only set for a SensorStateClass.TOTAL sensor: the period its value
    # resets at the start of, in the network's own timezone. A resource
    # with a known, well-defined start (the current day) can use TOTAL
    # instead of TOTAL_INCREASING, which has no reset point at all.
    last_reset_period: str | None = None


SENSOR_DESCRIPTIONS: list[EeroSensorEntityDescription] = [
    EeroSensorEntityDescription(
        key="ad_block_status",
        translation_key="ad_block_status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_DISABLED, STATE_NETWORK, STATE_PROFILE],
        premium_type=True,
    ),
    EeroSensorEntityDescription(
        key="adblock_day",
        translation_key="adblock_day",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="adblock_week",
        translation_key="adblock_week",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="adblock_month",
        translation_key="adblock_month",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="blocked_day",
        translation_key="blocked_day",
        native_unit_of_measurement="threats",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=lambda resource, key: getattr(resource, key)["blocked"]
        if resource.is_network
        else getattr(resource, key),
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="blocked_week",
        translation_key="blocked_week",
        native_unit_of_measurement="threats",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=lambda resource, key: getattr(resource, key)["blocked"]
        if resource.is_network
        else getattr(resource, key),
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="blocked_month",
        translation_key="blocked_month",
        native_unit_of_measurement="threats",
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=lambda resource, key: getattr(resource, key)["blocked"]
        if resource.is_network
        else getattr(resource, key),
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="connected_clients_count",
        translation_key="connected_clients_count",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="clients",
    ),
    EeroSensorEntityDescription(
        key="connected_guest_clients_count",
        translation_key="connected_guest_clients_count",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="clients",
    ),
    EeroSensorEntityDescription(
        key="data_usage_day",
        translation_key="data_usage_day",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="data_usage_week",
        translation_key="data_usage_week",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="unprofiled_data_usage_day",
        translation_key="unprofiled_data_usage_day",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        last_reset_period=PERIOD_DAY,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="eeros_data_usage_summary_day",
        translation_key="eeros_data_usage_summary_day",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL,
        last_reset_period=PERIOD_DAY,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="data_usage_month",
        translation_key="data_usage_month",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="dns_mode",
        translation_key="dns_mode",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_CUSTOM, STATE_AUTOMATIC],
    ),
    EeroSensorEntityDescription(
        key="forward_count",
        translation_key="forward_count",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="forwards",
        tier=TIER_DAILY,
    ),
    EeroSensorEntityDescription(
        key="gateway_ip",
        translation_key="gateway_ip",
        extra_attrs={
            "mac_address": lambda resource: resource.gateway_mac_address,
            "name": lambda resource: resource.gateway_name,
        },
    ),
    EeroSensorEntityDescription(
        key="inspected_day",
        translation_key="inspected_day",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="inspected_week",
        translation_key="inspected_week",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="inspected_month",
        translation_key="inspected_month",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="ip",
        translation_key="ip",
    ),
    EeroSensorEntityDescription(
        key="last_active",
        translation_key="last_active",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    EeroSensorEntityDescription(
        key="public_ip",
        translation_key="public_ip",
    ),
    EeroSensorEntityDescription(
        key="reservation_count",
        translation_key="reservation_count",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="reservations",
        tier=TIER_DAILY,
    ),
    EeroSensorEntityDescription(
        key="signal",
        translation_key="signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        state_class=SensorStateClass.MEASUREMENT,
        native_value=lambda resource, key: getattr(resource, key)[0],
        native_unit_of_measurement=lambda resource, key: SIGNAL_STRENGTH_UNIT_MAP.get(
            getattr(resource, key)[1], getattr(resource, key)[1]
        ),
        wireless_only=True,
    ),
    EeroSensorEntityDescription(
        key="speed_down",
        translation_key="speed_down",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_value=lambda resource, key: getattr(resource, key)[0],
        native_unit_of_measurement=lambda resource, key: SPEED_UNIT_MAP.get(
            getattr(resource, key)[1], getattr(resource, key)[1]
        ),
        extra_attrs={
            "last_updated": lambda resource: resource.speed_date,
        },
    ),
    EeroSensorEntityDescription(
        key="speed_up",
        translation_key="speed_up",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_value=lambda resource, key: getattr(resource, key)[0],
        native_unit_of_measurement=lambda resource, key: SPEED_UNIT_MAP.get(
            getattr(resource, key)[1], getattr(resource, key)[1]
        ),
        extra_attrs={
            "last_updated": lambda resource: resource.speed_date,
        },
    ),
    EeroSensorEntityDescription(
        key="status",
        translation_key="status",
    ),
    EeroSensorEntityDescription(
        key="usage_down",
        translation_key="usage_down",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    ),
    EeroSensorEntityDescription(
        key="usage_up",
        translation_key="usage_up",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    ),
    EeroSensorEntityDescription(
        key="wan_router_ip",
        translation_key="wan_router_ip",
        extra_attrs={
            "subnet_mask": lambda resource: resource.wan_subnet_mask,
        },
    ),
]


PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero sensor entity based on a config entry."""
    async_setup_platform_entities(
        config_entry,
        SENSOR_DESCRIPTIONS,
        EeroSensorEntity,
        (KIND_NETWORK, KIND_BACKUP_NETWORKS, KIND_EEROS, KIND_PROFILES, KIND_CLIENTS),
        async_add_entities,
    )
    async_setup_port_entities(
        config_entry,
        lambda runtime, network_id, eero_id, port: [
            EeroPortSensorEntity(
                runtime, network_id, eero_id, port["interface_number"], description
            )
            for description in PORT_SENSOR_DESCRIPTIONS
        ],
        async_add_entities,
    )


class EeroSensorEntity(EeroEntity, SensorEntity):
    """Representation of an Eero sensor entity."""

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value reported by the sensor."""
        return cast("StateType | datetime", self.entity_description.native_value(
            self.resource, self.entity_description.key
        ))

    @property
    def last_reset(self) -> datetime | None:
        """Return when this TOTAL sensor's value last reset.

        Only meaningful for a description that names its reset period: the
        start of that period (today, midnight) in the network's own
        timezone, the same window EeroHub.define_period(PERIOD_DAY) fetches
        the value over.
        """
        if not self.entity_description.last_reset_period or self.resource is None:
            return None
        timezone = (self.resource.data.get("timezone") or {}).get("value") or "UTC"
        now = datetime.now(tz=ZoneInfo(timezone))
        return now.replace(hour=0, minute=0, second=0, microsecond=0)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement of the sensor, if any.

        Home Assistant reads this even while the entity is unavailable, so it
        has to cope with a resource that is no longer reported.
        """
        if callable(self.entity_description.native_unit_of_measurement):
            if self.resource is None:
                return None
            return cast("str | None", self.entity_description.native_unit_of_measurement(
                self.resource, self.entity_description.key
            ))
        return cast("str | None", self.entity_description.native_unit_of_measurement)

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return entity specific state attributes.

        Implemented by platform classes. Convention for attribute names
        is lowercase snake_case.
        """
        attrs: dict[str, Any] = {}
        if self.resource is None:
            return attrs
        if self.entity_description.extra_attrs:
            for key, func in self.entity_description.extra_attrs.items():
                attrs[key] = func(self.resource)
        if (
            self.entity_description.key.startswith("blocked")
            and self.resource.is_network
        ):
            data = getattr(self.resource, self.entity_description.key)
            if isinstance(data, dict):
                attrs = {key: value for key, value in data.items() if key != "blocked"}
        if self.entity_description.key.startswith("data_usage"):
            attrs["download"], attrs["upload"] = getattr(
                self.resource, self.entity_description.key
            )
        if self.entity_description.key.endswith("clients_count"):
            if self.resource.is_eero or self.resource.is_profile:
                attrs["clients"] = sorted(self.resource.connected_clients_names)
            for category in DEVICE_CATEGORIES:
                attr = f"{self.entity_description.key}_{category}"
                if resource_supports(self.resource, attr):
                    attrs[category] = getattr(self.resource, attr)
        if self.entity_description.key == "status" and self.resource.is_backup_network:
            attrs["checked"] = self.resource.checked
            if all(
                [
                    self.state == STATE_FAILURE,
                    failure_reason := self.resource.failure_reason,
                ]
            ):
                attrs["failure_reason"] = failure_reason.lower()
        return attrs


class EeroPortSensorEntity(EeroPortEntity, SensorEntity):
    """Representation of one field of one eero's port."""

    entity_description: EeroPortSensorEntityDescription

    def __init__(
        self,
        runtime,
        network_id: str,
        eero_id: str,
        interface_number: int,
        description: EeroPortSensorEntityDescription,
    ) -> None:
        """Initialize."""
        super().__init__(runtime, network_id, eero_id, interface_number)
        self.entity_description = description

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return (
            f"{self.network_id}-{self.eero_id}-port_{self.interface_number}"
            f"_{self.entity_description.key}"
        )

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        if (port := self.port) is None:
            return None
        return cast("StateType", self.entity_description.value_fn(port))
