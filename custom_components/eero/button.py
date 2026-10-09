"""Support for Eero button entities."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonDeviceClass,
    ButtonEntity,
    ButtonEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    KIND_NETWORK,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)


@dataclass(frozen=True, kw_only=True)
class EeroButtonEntityDescription(EeroEntityDescription, ButtonEntityDescription):
    """Class to describe an Eero button entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG


BUTTON_DESCRIPTIONS: list[EeroButtonEntityDescription] = [
    EeroButtonEntityDescription(
        key="reboot",
        name="Reboot",
        device_class=ButtonDeviceClass.RESTART,
        request_refresh=False,
    ),
    EeroButtonEntityDescription(
        key="run_internet_backup_test",
        name="Run Internet Backup Test",
        icon="mdi:web",
        premium_type=True,
        request_refresh=False,
    ),
    EeroButtonEntityDescription(
        key="run_speed_test",
        name="Run Speed Test",
        icon="mdi:speedometer",
        request_refresh=False,
    ),
]

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero button entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            BUTTON_DESCRIPTIONS,
            EeroButtonEntity,
            (KIND_NETWORK, KIND_EEROS,),
        )
    )


class EeroButtonEntity(EeroEntity, ButtonEntity):
    """Representation of an Eero button entity."""

    async def async_press(self) -> None:
        """Press the button."""
        await self.async_write(f"async_{self.entity_description.key}")
