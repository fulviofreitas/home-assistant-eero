"""Support for Eero time entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time

from homeassistant.components.time import TimeEntity, TimeEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TIER_DAILY
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    KIND_PROFILES,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroTimeEntityDescription(EeroEntityDescription, TimeEntityDescription):
    """Class to describe an Eero time entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG


TIME_DESCRIPTIONS: list[EeroTimeEntityDescription] = [
    EeroTimeEntityDescription(
        key="nightlight_schedule_on",
        translation_key="nightlight_schedule_on",
    ),
    EeroTimeEntityDescription(
        key="nightlight_schedule_off",
        translation_key="nightlight_schedule_off",
    ),
    EeroTimeEntityDescription(
        key="bedtime_weekday_start",
        translation_key="bedtime_weekday_start",
        tier=TIER_DAILY,
    ),
    EeroTimeEntityDescription(
        key="bedtime_weekday_end",
        translation_key="bedtime_weekday_end",
        tier=TIER_DAILY,
    ),
    EeroTimeEntityDescription(
        key="bedtime_weekend_start",
        translation_key="bedtime_weekend_start",
        tier=TIER_DAILY,
    ),
    EeroTimeEntityDescription(
        key="bedtime_weekend_end",
        translation_key="bedtime_weekend_end",
        tier=TIER_DAILY,
    ),
]

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero time entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            TIME_DESCRIPTIONS,
            EeroTimeEntity,
            (KIND_EEROS, KIND_PROFILES),
        )
    )


class EeroTimeEntity(EeroEntity, TimeEntity):
    """Representation of an Eero time entity."""

    entity_description: EeroTimeEntityDescription

    @property
    def native_value(self) -> time | None:
        """Return the value reported by the time."""
        return getattr(self.resource, self.entity_description.key, None)

    async def async_set_value(self, value: time) -> None:
        """Change the time."""
        await self.async_write(
            f"async_set_{self.entity_description.key}",
            value,
            current=self.native_value,
            target=value,
        )
