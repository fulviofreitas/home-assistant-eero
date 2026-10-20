"""The hourly tier: the activity and data usage series.

The API aggregates these hourly, so polling them faster only returns the same
numbers again. Every request sends start, end and cadence as query parameters:
the API rejects a GET that carries a body.

Module functions that take the hub, whose SDK client and transport they use.
EeroHub.fetch_hourly, update_activity and define_period delegate here.
"""

from __future__ import annotations

import datetime
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, cast
from zoneinfo import ZoneInfo

from .const import (
    ACTIVITY_APP_EVENTS,
    ACTIVITY_EEROS_DATA_USAGE_SUMMARY_DAY,
    ACTIVITY_MAP,
    ACTIVITY_NOTIFICATIONS_UNREAD,
    ACTIVITY_UNPROFILED_DATA_USAGE_DAY,
    CADENCE_DAILY,
    CADENCE_HOURLY,
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_WEEK,
    RESOURCE_MAP,
)
from .util import api_url

if TYPE_CHECKING:
    from . import EeroHub, EeroUpdateConfig


async def fetch_hourly(
    hub: EeroHub, network_id: str, network: dict[str, Any], config: EeroUpdateConfig
) -> dict[str, Any]:
    """Insights and data usage series for the configured activity metrics."""
    timezone = (network.get("timezone") or {}).get("value") or "UTC"
    activity_data: dict[str, Any] = {}
    for resource, activities in config.activity.items():
        resource = RESOURCE_MAP.get(resource, resource)
        activity_data[resource] = {}
        for activity in activities:
            if resource == "profiles":
                activity_data[resource][activity] = {}
                for profile_id in config.profiles:
                    activity_data[resource][activity][profile_id] = (
                        await hub.update_activity(
                            activity, network_id, resource, timezone, profile_id
                        )
                    )
            else:
                activity_data[resource][activity] = await hub.update_activity(
                    activity, network_id, resource, timezone
                )
    return activity_data


async def update_activity(
    hub: EeroHub,
    activity: str,
    network_id: str,
    resource: str,
    timezone: str,
    profile_id: str | None = None,
) -> Any:
    """Fetch one activity series."""
    request, name = await _activity_request(
        hub, activity, network_id, resource, timezone, profile_id
    )
    data = await hub.call_optional(request, name, network_id, activity)
    return _activity_series(activity, {} if data is None else data)


async def _activity_request(
    hub: EeroHub,
    activity: str,
    network_id: str,
    resource: str,
    timezone: str,
    profile_id: str | None,
) -> tuple[Awaitable[dict[str, Any]], str]:
    """Return the SDK request for one activity series and the name it is saved under."""
    # "{}/insights" or "{}/data_usage": the family is the last segment.
    family: str = str(ACTIVITY_MAP[activity][0]).rsplit("/", 1)[-1]
    insight_type = cast("str", ACTIVITY_MAP[activity][1])
    period = cast("str", ACTIVITY_MAP[activity][2])
    start, end, cadence = hub.define_period(period=period, timezone=timezone)
    window: dict[str, Any] = {"start": start, "end": end, "cadence": cadence}
    if (
        special := _special_activity_request(hub, activity, network_id, timezone, window)
    ) is not None:
        return special
    name = f"/2.2/networks/{network_id}/{family}/{resource}"
    if family == "data_usage":
        return (
            _usage_request(hub, network_id, resource, profile_id, timezone, window),
            name,
        )
    return (
        await _insights_request(
            hub, network_id, resource, profile_id, insight_type, window
        ),
        name,
    )


def _special_activity_request(
    hub: EeroHub,
    activity: str,
    network_id: str,
    timezone: str,
    window: dict[str, Any],
) -> tuple[Awaitable[dict[str, Any]], str] | None:
    """Return the request of an activity with an endpoint of its own, else None."""
    if activity == ACTIVITY_UNPROFILED_DATA_USAGE_DAY:
        return (
            hub.sdk.data_usage.get_unprofiled_summary(
                network_id, timezone=timezone, **window
            ),
            f"/2.2/networks/{network_id}/data_usage/unprofiled/summary",
        )
    if activity == ACTIVITY_EEROS_DATA_USAGE_SUMMARY_DAY:
        return (
            hub.sdk.data_usage.get_eeros_summary(
                network_id, timezone=timezone, **window
            ),
            f"/2.2/networks/{network_id}/data_usage/eeros/summary",
        )
    if activity == ACTIVITY_APP_EVENTS:
        # A bounded page: this is reported as new HA events on every
        # entity not yet seen, so an unbounded page would replay a
        # flood of history the first time the entity is added.
        return (
            hub.sdk.events.get_app_events(network_id, page_size=25),
            f"/2.2/networks/{network_id}/app_events",
        )
    if activity == ACTIVITY_NOTIFICATIONS_UNREAD:
        return (
            hub.sdk.notifications.has_unread(network_id),
            f"/2.2/networks/{network_id}/notifications/has_unread",
        )
    return None


def _usage_request(
    hub: EeroHub,
    network_id: str,
    resource: str,
    profile_id: str | None,
    timezone: str,
    window: dict[str, Any],
) -> Awaitable[dict[str, Any]]:
    """Return the data usage request for a network, its devices, a profile or its eeros."""
    if resource == "network":
        return hub.sdk.data_usage.get_data_usage(
            network_id, timezone=timezone, **window
        )
    if resource == "devices":
        return hub.sdk.data_usage.get_devices_usage(
            network_id, timezone=timezone, **window
        )
    if resource == "profiles":
        return hub.sdk.data_usage.get_profile_usage(
            network_id, str(profile_id), timezone=timezone, **window
        )
    return hub.sdk.data_usage.get_eeros_usage(network_id, timezone=timezone, **window)


async def _insights_request(
    hub: EeroHub,
    network_id: str,
    resource: str,
    profile_id: str | None,
    insight_type: str,
    window: dict[str, Any],
) -> Awaitable[dict[str, Any]]:
    """Return the insights request for a network, its devices, a profile or the rest."""
    if resource == "network":
        return hub.sdk.insights.get_insights(
            network_id, insight_type=insight_type, **window
        )
    if resource == "devices":
        return hub.sdk.insights.get_devices_insights(
            network_id, insight_type=insight_type, **window
        )
    if resource == "profiles":
        return hub.sdk.insights.get_profile_insights(
            network_id, str(profile_id), insight_type=insight_type, **window
        )
    return hub.sdk.insights.get(
        api_url(f"/2.2/networks/{network_id}/insights/{resource}"),
        auth_token=await hub.require_token(),
        params={**window, "insight_type": insight_type},
    )


def _activity_series(activity: str, data: Any) -> Any:
    """Pick the series out of an activity response, whatever shape it came in."""
    if activity == ACTIVITY_NOTIFICATIONS_UNREAD:
        # Always the {"has_unread": bool} shape has_unread's docstring
        # describes; never routed through the insights/series/values
        # extraction below, which would silently discard it (it has no
        # "insights"/"series"/"values" key to find).
        return data if isinstance(data, dict) else {}
    if not isinstance(data, dict):
        return data
    if activity == ACTIVITY_APP_EVENTS:
        # Shape not documented by the SDK beyond "raw response". A bare
        # list (the common shape for this family, see data_usage_day)
        # is already returned above, before this dict-only branch; a
        # dict envelope is assumed to nest the list under "events".
        # Never raises on an unexpected shape: an empty list is safer
        # than guessing wrong.
        events = data.get("events")
        return events if isinstance(events, list) else []
    return data.get("insights", data.get("series", data.get("values")))


def define_period(
    period: str, timezone: str
) -> tuple[str | None, str | None, str | None]:
    """Return the (start, end, cadence) of the day, week or month so far.

    Weeks start on Sunday, as the eero app's do. Standard library only:
    python-dateutil is not a Home Assistant dependency.
    """
    now = datetime.datetime.now(tz=ZoneInfo(timezone))
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == PERIOD_DAY:
        start, cadence = today, CADENCE_HOURLY
        following = start + datetime.timedelta(days=1)
    elif period == PERIOD_WEEK:
        start = today - datetime.timedelta(days=(now.weekday() + 1) % 7)
        following = start + datetime.timedelta(weeks=1)
        cadence = CADENCE_DAILY
    elif period == PERIOD_MONTH:
        start = today.replace(day=1)
        following = (start + datetime.timedelta(days=32)).replace(day=1)
        cadence = CADENCE_DAILY
    else:
        return (None, None, None)
    end = following - datetime.timedelta(seconds=1)
    return (
        f"{start.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z",
        f"{end.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z",
        cadence,
    )
