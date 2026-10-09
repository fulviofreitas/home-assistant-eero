"""Eero API."""

from __future__ import annotations

from datetime import datetime, time
from functools import cached_property
from typing import TYPE_CHECKING, Any, cast

from eero.api.schedule import WEEKDAYS, WEEKEND

from .client import EeroClient
from .resource import EeroResource

if TYPE_CHECKING:
    from .network import EeroNetwork

#: Scheduled pauses this integration manages are always named "Bedtime";
#: the SDK has no separate "is this a bedtime pause" flag, so a weekday/
#: weekend pause is identified by its day set, not by an ID it keeps.
_BEDTIME_NAME = "bedtime"
_WEEKDAYS = frozenset(WEEKDAYS)
_WEEKEND = frozenset(WEEKEND)
_DEFAULT_BEDTIME_START = "22:00"
_DEFAULT_BEDTIME_END = "07:00"


def _parse_hhmm(value: str | None) -> time | None:
    """Parse an "HH:MM" schedule time into a time object."""
    if not value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return time(int(hour), int(minute))
    except (ValueError, TypeError):
        return None


def _insight_sum(
    network: EeroNetwork, activity: str, profile_id: str | None, insight_type: str
) -> int | None:
    """Return the period total from one profile's insights series."""
    series = network.data.get("activity", {}).get("profiles", {}).get(activity, {})
    if not isinstance(series, dict):
        return None
    for entry in series.get(profile_id) or []:
        if isinstance(entry, dict) and entry.get("insight_type") == insight_type:
            return entry.get("sum")
    return None


class EeroProfile(EeroResource):
    """EeroProfile."""

    network: EeroNetwork

    @property
    def ad_block(self) -> bool:
        """Ad block."""
        return bool(
            self.network.ad_block_enabled
            and self.url in (self.network.ad_block_profiles or [])
        )

    async def async_set_ad_block(self, value: bool) -> None:
        """Add this profile to, or remove it from, the network's ad blocking."""
        profiles = list(self.network.ad_block_profiles or [])
        if value:
            if self.url not in profiles:
                profiles.append(self.url)
        elif self.url in profiles:
            profiles.remove(self.url)
        await self.api.post(
            f"{self.network.url_dns_policies}/adblock",
            json={"enable": bool(value or profiles), "profiles": profiles},
        )

    @property
    def adblock_day(self) -> int | None:
        """Adblock day."""
        return _insight_sum(self.network, "adblock_day", self.id, "adblock")

    @property
    def adblock_month(self) -> int | None:
        """Adblock month."""
        return _insight_sum(self.network, "adblock_month", self.id, "adblock")

    @property
    def adblock_week(self) -> int | None:
        """Adblock week."""
        return _insight_sum(self.network, "adblock_week", self.id, "adblock")

    def _bedtime_entries(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Return (weekday, weekend) bedtime schedule entries, if any exist."""
        schedules = self.network.data.get("schedules")
        weekday: dict[str, Any] | None = None
        weekend: dict[str, Any] | None = None
        if not isinstance(schedules, dict):
            return (weekday, weekend)
        for entry in schedules.get(self.id) or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("name", "")).strip().lower() != _BEDTIME_NAME:
                continue
            days = frozenset(entry.get("days") or [])
            if days == _WEEKDAYS:
                weekday = entry
            elif days == _WEEKEND:
                weekend = entry
        return (weekday, weekend)

    @property
    def bedtime_enabled(self) -> bool | None:
        """Whether a weekday or weekend bedtime schedule is active.

        None until the daily tier has fetched this profile's schedules.
        """
        schedules = self.network.data.get("schedules")
        if not isinstance(schedules, dict) or self.id not in schedules:
            return None
        weekday, weekend = self._bedtime_entries()
        return bool((weekday or {}).get("enabled") or (weekend or {}).get("enabled"))

    async def async_set_bedtime_enabled(self, value: bool) -> None:
        """Turn the bedtime schedule(s) on or off.

        Turning on creates a schedule (default 22:00-07:00) for whichever of
        weekday/weekend has none yet, and re-enables the other(s). Turning
        off disables rather than deletes, so times already set survive being
        turned off and back on.
        """
        weekday, weekend = self._bedtime_entries()
        for entry, setter in (
            (weekday, self.api.sdk.schedule.set_weekday_bedtime),
            (weekend, self.api.sdk.schedule.set_weekend_bedtime),
        ):
            if value:
                if entry is None:
                    await self.api.call(
                        setter(
                            self.network.sdk_id,
                            self.sdk_id,
                            _DEFAULT_BEDTIME_START,
                            _DEFAULT_BEDTIME_END,
                        ),
                        name=f"{self.url}/schedules",
                    )
                elif not entry.get("enabled"):
                    await self.api.call(
                        self.api.sdk.schedule.update_schedule(entry, enabled=True),
                        name=f"{self.url}/schedules",
                    )
            elif entry is not None and entry.get("enabled"):
                await self.api.call(
                    self.api.sdk.schedule.update_schedule(entry, enabled=False),
                    name=f"{self.url}/schedules",
                )

    async def _async_set_bedtime_time(self, weekday: bool, field: str, value: time) -> None:
        """Set one start/end field of the weekday or weekend bedtime schedule."""
        entry = self._bedtime_entries()[0 if weekday else 1]
        hhmm = value.strftime("%H:%M")
        if entry is not None:
            fields: dict[str, Any] = {field: hhmm}
            await self.api.call(
                self.api.sdk.schedule.update_schedule(entry, **fields),
                name=f"{self.url}/schedules",
            )
            return
        start = hhmm if field == "start" else _DEFAULT_BEDTIME_START
        end = hhmm if field == "end" else _DEFAULT_BEDTIME_END
        setter = (
            self.api.sdk.schedule.set_weekday_bedtime
            if weekday
            else self.api.sdk.schedule.set_weekend_bedtime
        )
        await self.api.call(
            setter(self.network.sdk_id, self.sdk_id, start, end),
            name=f"{self.url}/schedules",
        )

    @property
    def bedtime_weekday_start(self) -> time | None:
        """Weekday bedtime start."""
        return _parse_hhmm((self._bedtime_entries()[0] or {}).get("start"))

    async def async_set_bedtime_weekday_start(self, value: time) -> None:
        """Set weekday bedtime start."""
        await self._async_set_bedtime_time(True, "start", value)

    @property
    def bedtime_weekday_end(self) -> time | None:
        """Weekday bedtime end."""
        return _parse_hhmm((self._bedtime_entries()[0] or {}).get("end"))

    async def async_set_bedtime_weekday_end(self, value: time) -> None:
        """Set weekday bedtime end."""
        await self._async_set_bedtime_time(True, "end", value)

    @property
    def bedtime_weekend_start(self) -> time | None:
        """Weekend bedtime start."""
        return _parse_hhmm((self._bedtime_entries()[1] or {}).get("start"))

    async def async_set_bedtime_weekend_start(self, value: time) -> None:
        """Set weekend bedtime start."""
        await self._async_set_bedtime_time(False, "start", value)

    @property
    def bedtime_weekend_end(self) -> time | None:
        """Weekend bedtime end."""
        return _parse_hhmm((self._bedtime_entries()[1] or {}).get("end"))

    async def async_set_bedtime_weekend_end(self, value: time) -> None:
        """Set weekend bedtime end."""
        await self._async_set_bedtime_time(False, "end", value)

    @property
    def block_apps_enabled(self) -> bool:
        """Block apps enabled."""
        return bool(self.blocked_applications)

    @property
    def block_gaming_content(self) -> bool | None:
        """Block gaming content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_gaming_content"))
        )

    async def async_set_block_gaming_content(self, value: bool) -> None:
        """Set block gaming content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_gaming_content": value})

    @property
    def block_illegal_content(self) -> bool | None:
        """Block illegal content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_illegal_content"))
        )

    async def async_set_block_illegal_content(self, value: bool) -> None:
        """Set block illegal content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_illegal_content": value})

    @property
    def block_messaging_content(self) -> bool | None:
        """Block messaging content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_messaging_content"))
        )

    async def async_set_block_messaging_content(self, value: bool) -> None:
        """Set block messaging content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_messaging_content": value})

    @property
    def block_pornographic_content(self) -> bool | None:
        """Block pornographic content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_pornographic_content"))
        )

    async def async_set_block_pornographic_content(self, value: bool) -> None:
        """Set block pornographic content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_pornographic_content": value})

    @property
    def block_shopping_content(self) -> bool | None:
        """Block shopping content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_shopping_content"))
        )

    async def async_set_block_shopping_content(self, value: bool) -> None:
        """Set block shopping content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_shopping_content": value})

    @property
    def block_social_content(self) -> bool | None:
        """Block social content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_social_content"))
        )

    async def async_set_block_social_content(self, value: bool) -> None:
        """Set block social content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_social_content": value})

    @property
    def block_streaming_content(self) -> bool | None:
        """Block streaming content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_streaming_content"))
        )

    async def async_set_block_streaming_content(self, value: bool) -> None:
        """Set block streaming content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_streaming_content": value})

    @property
    def block_violent_content(self) -> bool | None:
        """Block violent content."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("block_violent_content"))
        )

    async def async_set_block_violent_content(self, value: bool) -> None:
        """Set block violent content."""
        await self.api.post(cast("str", self.url_dns_policies), json={"block_violent_content": value})

    @property
    def blocked_applications(self) -> list[str]:
        """Blocked applications."""
        return cast("list[str]", self.data.get("premium_dns", {}).get("blocked_applications", []))

    @property
    def blocked_applications_count(self) -> int:
        """Blocked applications count."""
        return len(self.blocked_applications)

    async def async_set_blocked_applications(self, blocked_applications: list[str]) -> None:
        """Set blocked applications."""
        await self.api.call(
            self.api.sdk.dns_policies.set_profile_blocked_applications(
                self.network.sdk_id, self.sdk_id, list(blocked_applications)
            ),
            name=f"{self.url_dns_policies}/applications/blocked",
        )

    @property
    def blocked_day(self) -> int | None:
        """Blocked day."""
        return _insight_sum(self.network, "blocked_day", self.id, "blocked")

    @property
    def blocked_month(self) -> int | None:
        """Blocked month."""
        return _insight_sum(self.network, "blocked_month", self.id, "blocked")

    @property
    def blocked_week(self) -> int | None:
        """Blocked week."""
        return _insight_sum(self.network, "blocked_week", self.id, "blocked")

    @property
    def connected(self) -> bool:
        """Connected."""
        return bool(self.connected_clients_count != 0)

    @property
    def connected_clients_count(self) -> int:
        """Connected clients count."""
        return len(self.connected_clients_names)

    @property
    def connected_clients_names(self) -> list[str]:
        """Connected clients names."""
        return cast(
            "list[str]", [client.name for client in self.clients if client.connected]
        )

    @property
    def data_usage_day(self) -> tuple[int | None, int | None]:
        """Data usage day."""
        down, up = None, None
        for series in (
            self.network.data.get("activity", {})
            .get("profiles", {})
            .get("data_usage_day", {})
            .get(self.id, [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def data_usage_month(self) -> tuple[int | None, int | None]:
        """Data usage month."""
        down, up = None, None
        for series in (
            self.network.data.get("activity", {})
            .get("profiles", {})
            .get("data_usage_month", {})
            .get(self.id, [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def data_usage_week(self) -> tuple[int | None, int | None]:
        """Data usage week."""
        down, up = None, None
        for series in (
            self.network.data.get("activity", {})
            .get("profiles", {})
            .get("data_usage_week", {})
            .get(self.id, [])
        ):
            if series["type"] == "download":
                down = series["sum"]
            elif series["type"] == "upload":
                up = series["sum"]
        return (down, up)

    @property
    def inspected_day(self) -> int | None:
        """Inspected day."""
        return _insight_sum(self.network, "inspected_day", self.id, "inspected")

    @property
    def inspected_month(self) -> int | None:
        """Inspected month."""
        return _insight_sum(self.network, "inspected_month", self.id, "inspected")

    @property
    def inspected_week(self) -> int | None:
        """Inspected week."""
        return _insight_sum(self.network, "inspected_week", self.id, "inspected")

    @property
    def last_active(self) -> datetime | None:
        """Last active."""
        if last_active := [
            client.last_active
            for client in self.clients
            if client.last_active is not None
        ]:
            return max(last_active)
        return None

    @property
    def name(self) -> str | None:
        """Name."""
        return self.data.get("name")

    @property
    def name_long(self) -> str:
        """Name long."""
        return f"{self.name} Profile"

    @property
    def paused(self) -> bool | None:
        """Paused."""
        return self.data.get("paused")

    async def async_set_paused(self, value: bool) -> None:
        """Pause or resume the profile."""
        await self.api.call(
            self.api.sdk.profiles.pause_profile(self.network.sdk_id, self.sdk_id, value),
            name=self.sdk_url,
        )

    @property
    def safe_search_enabled(self) -> bool | None:
        """Safe search enabled."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("safe_search_enabled"))
        )

    async def async_set_safe_search_enabled(self, value: bool) -> None:
        """Set safe search enabled."""
        await self.api.post(cast("str", self.url_dns_policies), json={"safe_search_enabled": value})

    @property
    def url_dns_policies(self) -> str | None:
        """URL DNS policies."""
        return f"{self.network.url}/dns_policies/profiles/{self.id}"

    @property
    def url_insights(self) -> str | None:
        """URL insights."""
        return f"{self.network.url_insights}/profiles/{self.id}"

    @property
    def youtube_restricted(self) -> bool | None:
        """YouTube restricted."""
        return (
            cast("bool | None", self.data.get("unified_content_filters", {})
            .get("dns_policies", {})
            .get("youtube_restricted"))
        )

    async def async_set_youtube_restricted(self, value: bool) -> None:
        """Set youtube restricted."""
        await self.api.post(cast("str", self.url_dns_policies), json={"youtube_restricted": value})

    @cached_property
    def clients(self) -> list[EeroClient]:
        """Clients assigned to this profile."""
        return [
            EeroClient(self.api, self.network, client)
            for client in self.data.get("devices", [])
        ]
