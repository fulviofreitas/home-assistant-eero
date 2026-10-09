"""Support for Eero select entities."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EeroConfigEntry
from .entity import (
    KIND_CLIENTS,
    KIND_EEROS,
    KIND_NETWORK,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroSelectEntityDescription(EeroEntityDescription, SelectEntityDescription):
    """Class to describe an Eero select entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG


SELECT_DESCRIPTIONS: list[EeroSelectEntityDescription] = [
    EeroSelectEntityDescription(
        key="profile_assignment",
        translation_key="profile_assignment",
        options="profile_assignment_options",
        requires_profiles=True,
    ),
    EeroSelectEntityDescription(
        key="nightlight_mode",
        name="Nightlight Mode",
        options="nightlight_mode_options",
    ),
    EeroSelectEntityDescription(
        key="preferred_update_hour",
        name="Preferred Update Time",
        options="preferred_update_hour_options",
    ),
]

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero select entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            SELECT_DESCRIPTIONS,
            EeroSelectEntity,
            (KIND_NETWORK, KIND_EEROS, KIND_CLIENTS),
        )
    )


class EeroSelectEntity(EeroEntity, SelectEntity):
    """Representation of an Eero select entity."""

    entity_description: EeroSelectEntityDescription

    @property
    def options(self) -> list[str]:
        """Return a set of selectable options.

        Read as a capability attribute even while unavailable, so it has to
        cope with a resource that is no longer reported.
        """
        if self.resource is None:
            return []
        return getattr(self.resource, self.entity_description.options)

    @property
    def current_option(self) -> str | None:
        """Return the selected entity option to represent the entity state."""
        return getattr(self.resource, self.entity_description.key)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        await self.async_write(
            f"async_set_{self.entity_description.key}",
            option,
            current=self.current_option,
            target=option,
        )
