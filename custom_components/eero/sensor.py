"""Support for Eero sensor entities."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
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
    STATE_DISABLED,
    STATE_FAILURE,
    STATE_NETWORK,
    STATE_PROFILE,
)
from .api.util import sum_data_usage
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
from .util import resource_supports

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
        name="Ad Blocking Status",
        device_class=SensorDeviceClass.ENUM,
        options=[STATE_DISABLED, STATE_NETWORK, STATE_PROFILE],
        premium_type=True,
    ),
    EeroSensorEntityDescription(
        key="adblock_day",
        name="Ad Blocks Day",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="adblock_week",
        name="Ad Blocks Week",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="adblock_month",
        name="Ad Blocks Month",
        native_unit_of_measurement="ads",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="blocked_day",
        name="Threat Blocks Day",
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
        name="Threat Blocks Week",
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
        name="Threat Blocks Month",
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
        name="Connected Clients",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="clients",
    ),
    EeroSensorEntityDescription(
        key="connected_guest_clients_count",
        name="Connected Guest Clients",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="clients",
    ),
    EeroSensorEntityDescription(
        key="data_usage_day",
        name="Data Usage Day",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="data_usage_week",
        name="Data Usage Week",
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
        name="Data Usage Month",
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_value=sum_data_usage,
        native_unit_of_measurement=UnitOfInformation.BYTES,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="gateway_ip",
        name="Gateway IP",
        extra_attrs={
            "mac_address": lambda resource: resource.gateway_mac_address,
            "name": lambda resource: resource.gateway_name,
        },
    ),
    EeroSensorEntityDescription(
        key="inspected_day",
        name="Scans Day",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="inspected_week",
        name="Scans Week",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="inspected_month",
        name="Scans Month",
        native_unit_of_measurement="scans",
        state_class=SensorStateClass.TOTAL_INCREASING,
        activity_type=True,
        tier=TIER_HOURLY,
    ),
    EeroSensorEntityDescription(
        key="ip",
        name="IP Address",
    ),
    EeroSensorEntityDescription(
        key="last_active",
        name="Last Active",
        device_class=SensorDeviceClass.TIMESTAMP,
    ),
    EeroSensorEntityDescription(
        key="public_ip",
        name="Public IP",
    ),
    EeroSensorEntityDescription(
        key="signal",
        name="Signal Strength",
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
        name="Download Speed",
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
        name="Upload Speed",
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
        name="Status",
    ),
    EeroSensorEntityDescription(
        key="usage_down",
        name="Download Rate",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    ),
    EeroSensorEntityDescription(
        key="usage_up",
        name="Upload Rate",
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
    ),
    EeroSensorEntityDescription(
        key="wan_router_ip",
        name="WAN Router IP",
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


class EeroSensorEntity(EeroEntity, SensorEntity):
    """Representation of an Eero sensor entity."""

    @property
    def native_value(self) -> StateType | datetime:
        """Return the value reported by the sensor."""
        return self.entity_description.native_value(
            self.resource, self.entity_description.key
        )

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
            return self.entity_description.native_unit_of_measurement(
                self.resource, self.entity_description.key
            )
        return self.entity_description.native_unit_of_measurement

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
