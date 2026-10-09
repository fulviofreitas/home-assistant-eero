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
    this entity instance has not already seen, carrying the raw eero event
    as its attributes.

    Dedup is in-memory only, by a best-effort identifying key taken from
    the raw event (id/timestamp/created_at/time, or the whole event as a
    last resort): nothing is persisted across a restart. The data already
    present when the entity is added is recorded as seen without firing
    (async_added_to_hass), so events that happened before this entity was
    added -- including before HA started -- are never replayed as live HA
    events; only an event that appears in a later poll fires. The seen-set
    is replaced (not accumulated) on every update, bounded by the page the
    SDK call requests, so memory never grows across polls -- an event that
    scrolls off that page cannot reappear as "new" either.
    """

    _attr_event_types: ClassVar[list[str]] = [EVENT_TYPE_APP_EVENT]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize."""
        super().__init__(*args, **kwargs)
        # None until primed (async_added_to_hass): _handle_coordinator_update
        # must never fire anything before that has happened.
        self._seen_events: set[str] | None = None

    @staticmethod
    def _event_key(event: dict) -> str:
        """Return a best-effort identifying key for one raw event."""
        for field in ("id", "timestamp", "created_at", "time"):
            if field in event:
                return f"{field}:{event[field]}"
        return repr(sorted(event.items()))

    def _current_events(self) -> list[dict]:
        """Return the resource's current raw event list, defensively typed."""
        if (resource := self.resource) is None:
            return []
        events = getattr(resource, self.entity_description.key, None) or []
        return [event for event in events if isinstance(event, dict)]

    async def async_added_to_hass(self) -> None:
        """Record the data already fetched as seen, without firing it."""
        await super().async_added_to_hass()
        self._seen_events = {self._event_key(event) for event in self._current_events()}

    def _handle_coordinator_update(self) -> None:
        """Fire EVENT_TYPE_APP_EVENT for every event not seen before."""
        if self._seen_events is not None:
            events = self._current_events()
            for event in events:
                key = self._event_key(event)
                if key in self._seen_events:
                    continue
                # Redacted defensively: the real app_events shape is not
                # documented, so this is the same safety net every saved
                # response goes through, applied to event attributes too.
                self._trigger_event(
                    EVENT_TYPE_APP_EVENT, self.runtime.hub.redact(event)
                )
            self._seen_events = {self._event_key(event) for event in events}
        super()._handle_coordinator_update()
