"""Support for Eero event entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from homeassistant.components.event import EventEntity, EventEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import TIER_HOURLY
from .coordinator import EeroConfigEntry
from .entity import (
    KIND_NETWORK,
    EeroEntity,
    EeroEntityDescription,
    build_entities,
)

PARALLEL_UPDATES = 0

#: The one HA event type this entity ever fires. The eero API's own app
#: event schema (field names for a per-event type/category) is not
#: documented by the SDK beyond "raw response", so events are not split
#: into HA event_types by eero's own category -- callers wanting to filter
#: by kind should match on the event_data attributes instead, once the
#: real shape is confirmed against a live network.
EVENT_TYPE_APP_EVENT = "app_event"


@dataclass(frozen=True, kw_only=True)
class EeroEventEntityDescription(EeroEntityDescription, EventEntityDescription):
    """Class to describe an Eero event entity."""

    entity_category: EntityCategory | None = EntityCategory.DIAGNOSTIC


EVENT_DESCRIPTIONS: list[EeroEventEntityDescription] = [
    EeroEventEntityDescription(
        key="app_events",
        translation_key="app_events",
        tier=TIER_HOURLY,
        activity_type=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero event entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            EVENT_DESCRIPTIONS,
            EeroEventEntity,
            (KIND_NETWORK,),
        )
    )


class EeroEventEntity(EeroEntity, EventEntity):
    """Representation of an Eero event entity.

    Fires EVENT_TYPE_APP_EVENT for every app event the network reports that
    this entity has not already seen, carrying the raw eero event as its
    attributes.

    Dedup is in-memory only, by a best-effort identifying key taken from
    the raw event (id/timestamp/created_at/time, or the whole event as a
    last resort): nothing is persisted across a restart. The first poll
    after the entity is added (or after a restart) therefore re-announces
    everything the bounded page then returns as "new" -- a known limitation
    until the real eero app_events schema is confirmed well enough to page
    strictly forward from a stored cursor.
    """

    _attr_event_types: ClassVar[list[str]] = [EVENT_TYPE_APP_EVENT]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        self._seen_events: set[str] = set()

    @staticmethod
    def _event_key(event: dict) -> str:
        """Return a best-effort identifying key for one raw event."""
        for field in ("id", "timestamp", "created_at", "time"):
            if field in event:
                return f"{field}:{event[field]}"
        return repr(sorted(event.items()))

    def _handle_coordinator_update(self) -> None:
        """Fire EVENT_TYPE_APP_EVENT for every event not seen before."""
        if (resource := self.resource) is not None:
            for event in getattr(resource, self.entity_description.key, None) or []:
                if not isinstance(event, dict):
                    continue
                key = self._event_key(event)
                if key in self._seen_events:
                    continue
                self._seen_events.add(key)
                # Redacted defensively: the real app_events shape is not
                # documented, so this is the same safety net every saved
                # response goes through, applied to event attributes too.
                self._trigger_event(
                    EVENT_TYPE_APP_EVENT, self.runtime.hub.redact(event)
                )
        super()._handle_coordinator_update()
