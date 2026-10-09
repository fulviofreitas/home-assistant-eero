"""Support for Eero light entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ColorMode,
    LightEntity,
    LightEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroLightEntityDescription(EeroEntityDescription, LightEntityDescription):
    """Class to describe an Eero light entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG
    color_mode: ColorMode = ColorMode.BRIGHTNESS
    supported_color_modes: set[ColorMode] = field(
        default_factory=lambda: {ColorMode.BRIGHTNESS}
    )


LIGHT_DESCRIPTIONS: list[EeroLightEntityDescription] = [
    EeroLightEntityDescription(
        key="status_light_enabled",
        translation_key="status_light_enabled",
    ),
]

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero light entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            LIGHT_DESCRIPTIONS,
            EeroLightEntity,
            (KIND_EEROS,),
        )
    )


class EeroLightEntity(EeroEntity, LightEntity):
    """Representation of an Eero light entity."""

    entity_description: EeroLightEntityDescription

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return bool(getattr(self.resource, self.entity_description.key))

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if self.resource is None:
            return None
        if (brightness := self.resource.status_light_brightness) is None:
            return None
        return round(brightness * 255 / 100)

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self.entity_description.color_mode

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Flag supported color modes."""
        return self.entity_description.supported_color_modes

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        if ATTR_BRIGHTNESS in kwargs:
            # A brightness of 0 switches the light off, so clamp to 1: turn_on
            # must not turn the light off.
            brightness = max(1, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255))
            current = (
                self.resource.status_light_brightness
                if self.resource is not None and self.is_on
                else None
            )
            await self.async_write(
                "async_set_status_light_brightness",
                brightness,
                current=current,
                target=brightness,
            )
        else:
            await self.async_write(
                "async_set_status_light", True, current=self.is_on, target=True
            )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        await self.async_write(
            "async_set_status_light", False, current=self.is_on, target=False
        )
