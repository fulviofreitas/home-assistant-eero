"""Support for Eero light entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from homeassistant.components.light import LightEntity, LightEntityDescription
from homeassistant.components.light.const import ColorMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .api.eero import EeroDevice
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)

if TYPE_CHECKING:
    # Moved to .const in Home Assistant 2026.10; still defined in the package
    # itself before that, which is what runs on both.
    from homeassistant.components.light.const import ATTR_BRIGHTNESS
else:
    from homeassistant.components.light import ATTR_BRIGHTNESS


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
        return bool(getattr(self.resource, self.entity_description.key, False))

    @property
    def brightness(self) -> int | None:
        """Return the brightness of this light between 0..255."""
        if not isinstance(resource := self.resource, EeroDevice):
            return None
        if (brightness := resource.status_light_brightness) is None:
            return None
        return cast("int | None", round(brightness * 255 / 100))

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
                resource.status_light_brightness
                if isinstance(resource := self.resource, EeroDevice) and self.is_on
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
