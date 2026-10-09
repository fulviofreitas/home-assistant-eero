"""Support for Eero text entities."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.text import TextEntity, TextEntityDescription, TextMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import EeroConfigEntry
from .entity import (
    KIND_NETWORK,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)

PARALLEL_UPDATES = 1


@dataclass(frozen=True, kw_only=True)
class EeroTextEntityDescription(EeroEntityDescription, TextEntityDescription):
    """Class to describe an Eero text entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG
    # The guest password: its state is never reported, in either direction.
    # Reading it back would put a secret in entity state/history; it is
    # accepted on write and nothing else.
    write_only: bool = False


TEXT_DESCRIPTIONS: list[EeroTextEntityDescription] = [
    EeroTextEntityDescription(
        key="guest_network_name",
        translation_key="guest_network_name",
        mode=TextMode.TEXT,
    ),
    EeroTextEntityDescription(
        key="guest_network_password",
        translation_key="guest_network_password",
        mode=TextMode.PASSWORD,
        native_min=8,
        write_only=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero text entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            TEXT_DESCRIPTIONS,
            EeroTextEntity,
            (KIND_NETWORK,),
        )
    )


class EeroTextEntity(EeroEntity, TextEntity):
    """Representation of an Eero text entity."""

    entity_description: EeroTextEntityDescription

    @property
    def native_value(self) -> str | None:
        """Return the entity value.

        A write-only entity (the guest password) never reports its state,
        even though the underlying resource property could in principle be
        read: a secret must never appear as entity state or history.
        """
        if self.entity_description.write_only:
            return None
        return getattr(self.resource, self.entity_description.key, None)

    async def async_set_value(self, value: str) -> None:
        """Change the value.

        A write-only entity has no known current value to compare against,
        so it always writes rather than skipping a redundant write.
        """
        if self.entity_description.write_only:
            # Compared here, not passed to async_write as target: the value
            # is a secret and must not reach a log line. Re-sending the same
            # password still disconnects every guest client.
            if (resource := self.resource) is not None and value == getattr(
                resource, self.entity_description.key, None
            ):
                return
            await self.async_write(f"async_set_{self.entity_description.key}", value)
            return
        await self.async_write(
            f"async_set_{self.entity_description.key}",
            value,
            current=self.native_value,
            target=value,
        )
