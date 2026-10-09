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

from .api.const import PORT_ACTIONS
from .const import TIER_DAILY
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_EEROS,
    KIND_NETWORK,
    EeroEntity,
    EeroEntityDescription,
    EeroPortEntity,
    async_setup_port_entities,
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
    async_setup_port_entities(
        config_entry,
        lambda runtime, network_id, eero_id, port: [
            EeroPortButtonEntity(
                runtime, network_id, eero_id, port["interface_number"], action
            )
            for action in port.get("actions", [])
            if isinstance(action, dict) and action.get("type") in PORT_ACTIONS
        ],
        async_add_entities,
    )


class EeroButtonEntity(EeroEntity, ButtonEntity):
    """Representation of an Eero button entity."""

    async def async_press(self) -> None:
        """Press the button."""
        await self.async_write(f"async_{self.entity_description.key}")


class EeroPortButtonEntity(EeroPortEntity, ButtonEntity):
    """Representation of one port-level action button on one eero.

    Disruptive (power-cycles the port or disables data/PoE/the port
    itself) and unconfirmed against a live network: disabled by default,
    a CONFIG entity, never auto-enabled.
    """

    _attr_entity_category = EntityCategory.CONFIG
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        runtime,
        network_id: str,
        eero_id: str,
        interface_number: int,
        action: dict,
    ) -> None:
        """Initialize."""
        super().__init__(runtime, network_id, eero_id, interface_number)
        self._action = action["type"]
        self._attr_translation_key = f"port_action_{self._action.lower()}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return (
            f"{self.network_id}-{self.eero_id}-port_{self.interface_number}"
            f"_action_{self._action.lower()}"
        )

    async def async_press(self) -> None:
        """Press the button."""
        if (eero := self.eero) is None:
            return
        await eero.async_port_action(self.interface_number, self._action)
        await self.runtime.coordinator(TIER_DAILY).async_request_refresh()
