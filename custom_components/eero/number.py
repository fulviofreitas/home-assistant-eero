"""Support for Eero number entities."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroNumberEntityDescription(EeroEntityDescription, NumberEntityDescription):
    """Class to describe an Eero number entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG


NUMBER_DESCRIPTIONS: list[EeroNumberEntityDescription] = [
    EeroNumberEntityDescription(
        key="nightlight_brightness_percentage",
        translation_key="nightlight_brightness_percentage",
        native_unit_of_measurement=PERCENTAGE,
    ),
]

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero number entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            NUMBER_DESCRIPTIONS,
            EeroNumberEntity,
            (KIND_EEROS,),
        )
    )


class EeroNumberEntity(EeroEntity, NumberEntity):
    """Representation of an Eero number entity."""

    entity_description: EeroNumberEntityDescription

    @property
    def native_value(self) -> float | None:
        """Return the value reported by the number."""
        return getattr(self.resource, self.entity_description.key, None)

    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        await self.async_write(
            f"async_set_{self.entity_description.key}",
            value,
            current=self.native_value,
            target=value,
        )
