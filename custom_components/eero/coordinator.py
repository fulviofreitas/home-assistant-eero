"""Polling tiers for the Eero integration.

One DataUpdateCoordinator per cadence, each owning its own eero-api calls:

- fast (the scan interval option): network, clients, profiles, eeros.
- hourly: insights and data usage series, which the API aggregates hourly.
- daily, and on demand after a setter that touches it: Thread, backup access
  points, backup internet, entitlements, firmware updates.

Entities subscribe to the coordinator of their tier. The property objects
they read (EeroNetwork, EeroClient, ...) are assembled from all three tiers'
data by EeroRuntime.account.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr, issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    EeroAccount,
    EeroAuthenticationException,
    EeroException,
    EeroHub,
    EeroRateLimitException,
    EeroUpdateConfig,
    UnavailableFeature,
    collect_unavailable,
)
from .backoff import backoff_interval
from .const import CONF_USER_TOKEN, DOMAIN, TIER_DAILY, TIER_FAST, TIER_HOURLY

_LOGGER = logging.getLogger(__name__)

HOURLY_INTERVAL = timedelta(hours=1)
DAILY_INTERVAL = timedelta(days=1)
# After a failed poll, the hourly and daily tiers retry this soon, doubling
# up to backoff.MAX_BACKOFF, instead of waiting out a whole hour or day with
# their entities unavailable.
SLOW_TIER_RETRY = timedelta(minutes=5)

type EeroConfigEntry = ConfigEntry[EeroRuntime]


class EeroTierCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One polling tier: fetch every configured network, map SDK failures."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        runtime: EeroRuntime,
        tier: str,
        interval: timedelta,
        fetch: Callable[[str, EeroUpdateConfig], Awaitable[dict[str, Any]]],
    ) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{DOMAIN} {tier} ({config_entry.title})",
            update_interval=interval,
        )
        self.runtime = runtime
        self.tier = tier
        self.base_interval = interval
        self._fetch = fetch
        self._retrying = False

    def _after_failure(self, rate_limited: bool) -> None:
        """Pick the interval to the next attempt after a failed poll.

        The fast tier keeps its interval, stretched only by a rate limit. The
        hourly and daily tiers retry within minutes, never later than their
        normal cadence.
        """
        if self.tier == TIER_FAST:
            if rate_limited:
                self.update_interval = backoff_interval(
                    self.update_interval, self.base_interval
                )
            return
        retry = (
            backoff_interval(self.update_interval, SLOW_TIER_RETRY)
            if self._retrying
            else SLOW_TIER_RETRY
        )
        self.update_interval = min(retry, self.base_interval)
        self._retrying = True

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch this tier for every configured network.

        EeroAuthenticationException starts reauth. A rate limit stretches the
        interval (doubling, up to 15 minutes) until the next success, because
        the API's 429 carries no usable Retry-After. Timeouts and transport
        errors fail the poll, which makes this tier's entities unavailable.
        """
        data: dict[str, Any] = {}
        try:
            with collect_unavailable() as unavailable:
                for network_id, config in self.runtime.update_config.items():
                    data[network_id] = await self._fetch(network_id, config)
        except EeroAuthenticationException as error:
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from error
        except EeroRateLimitException as error:
            self._after_failure(rate_limited=True)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={
                    "seconds": str(int(self.update_interval.total_seconds()))
                },
            ) from error
        except TimeoutError as error:
            self._after_failure(rate_limited=False)
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="timeout"
            ) from error
        except EeroException as error:
            self._after_failure(rate_limited=False)
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(error)},
            ) from error
        self.update_interval = self.base_interval
        self._retrying = False
        self.runtime.report_unavailable(self.tier, unavailable)
        if self.tier == TIER_FAST:
            await self.runtime.async_persist_token()
        return data


@dataclass
class EeroRuntime:
    """Everything a loaded config entry holds: the hub, the tiers, the options."""

    hass: HomeAssistant
    entry: ConfigEntry
    hub: EeroHub
    update_config: dict[str, EeroUpdateConfig]
    networks: list[str]
    resources: dict[str, Any]
    activity: dict[str, Any]
    miscellaneous: dict[str, Any]
    options: dict[str, Any]
    coordinators: dict[str, EeroTierCoordinator] = field(default_factory=dict)
    _account: EeroAccount | None = None
    _account_sources: tuple[Any, Any, Any] | None = None
    _issues: dict[str, set[str]] = field(default_factory=dict)

    def setup_coordinators(self, scan_interval: timedelta) -> None:
        """Create one coordinator per tier."""
        hub = self.hub

        async def fast(network_id: str, config: EeroUpdateConfig) -> dict[str, Any]:
            return await hub.fetch_fast(network_id, config)

        async def hourly(network_id: str, config: EeroUpdateConfig) -> dict[str, Any]:
            if not config.activity:
                return {}
            if not (network := self.network_payload(network_id)):
                return self.previous(TIER_HOURLY, network_id)
            return await hub.fetch_hourly(network_id, network, config)

        async def daily(network_id: str, config: EeroUpdateConfig) -> dict[str, Any]:
            if not (network := self.network_payload(network_id)):
                return self.previous(TIER_DAILY, network_id)
            return await hub.fetch_daily(network_id, network, config)

        for tier, interval, fetch in (
            (TIER_FAST, scan_interval, fast),
            (TIER_HOURLY, HOURLY_INTERVAL, hourly),
            (TIER_DAILY, DAILY_INTERVAL, daily),
        ):
            self.coordinators[tier] = EeroTierCoordinator(
                self.hass, self.entry, self, tier, interval, fetch
            )

    async def async_first_refresh(self) -> None:
        """Refresh the fast tier first: the other two read its network payload.

        Only the fast tier gates setup. A failure in the hourly or daily tier
        makes that tier's entities unavailable until its next poll; it does
        not hold the whole entry in setup-retry.
        """
        await self.coordinators[TIER_FAST].async_config_entry_first_refresh()
        await self.coordinators[TIER_DAILY].async_refresh()
        await self.coordinators[TIER_HOURLY].async_refresh()

    def previous(self, tier: str, network_id: str) -> dict[str, Any]:
        """Return a tier's last data for a network.

        Used when the fast tier has no envelope for the network to build on:
        keeping the last good data beats replacing it with an empty one.
        """
        return dict((self.coordinators[tier].data or {}).get(network_id) or {})

    def network_name(self, network_id: str) -> str:
        """Return a network's name for messages, or its ID when not known.

        A network the API no longer returns still has its device, and the
        device keeps the name.
        """
        if name := self.network_payload(network_id).get("name"):
            return str(name)
        device = dr.async_get(self.hass).async_get_device_by_identifier(
            (DOMAIN, network_id), self.entry.entry_id
        )
        if device is not None and (device.name_by_user or device.name):
            return str(device.name_by_user or device.name)
        return network_id

    def network_payload(self, network_id: str) -> dict[str, Any]:
        """Return the latest raw network envelope from the fast tier."""
        data = self.coordinators[TIER_FAST].data or {}
        return (data.get(network_id) or {}).get("network") or {}

    @property
    def account(self) -> EeroAccount:
        """Return the property-object tree, rebuilt when any tier has new data."""
        sources = tuple(
            self.coordinators[tier].data for tier in (TIER_FAST, TIER_HOURLY, TIER_DAILY)
        )
        # Compared by identity, holding references: a coordinator replaces
        # its data dict on every refresh, and an id() of a freed dict could be
        # reused by the next one.
        previous = self._account_sources
        if (
            self._account is None
            or previous is None
            or any(a is not b for a, b in zip(sources, previous, strict=True))
        ):
            fast, hourly, daily = (data or {} for data in sources)
            self._account = self.hub.assemble(None, fast, hourly, daily)
            self._account_sources = sources
        return self._account

    def coordinator(self, tier: str) -> EeroTierCoordinator:
        """Return the coordinator of a tier."""
        return self.coordinators[tier]

    async def async_refresh_tiers(self, tiers: tuple[str, ...]) -> None:
        """Ask the given tiers for a refresh, after a setter."""
        await asyncio.gather(
            *(self.coordinators[tier].async_request_refresh() for tier in tiers)
        )

    async def async_persist_token(self) -> None:
        """Write the SDK's current session token to the entry if it changed.

        The running hub already holds the token it persists, so the update
        listener sees no difference and does not reload the entry for it.
        """
        token = await self.hub.async_current_token()
        if token and token != self.entry.data.get(CONF_USER_TOKEN):
            self.hub.user_token = token
            self.hass.config_entries.async_update_entry(
                self.entry, data={**self.entry.data, CONF_USER_TOKEN: token}
            )

    @callback
    def report_unavailable(
        self, tier: str, unavailable: list[UnavailableFeature]
    ) -> None:
        """Raise a repair issue per feature the account cannot read; clear the rest."""
        current: set[str] = set()
        for item in unavailable:
            issue_id = f"{self.entry.entry_id}_{item.network_id}_{item.feature}"
            current.add(issue_id)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=(
                    "network_unavailable"
                    if item.feature == "network"
                    else "premium_required"
                    if item.premium
                    else "feature_unavailable"
                ),
                translation_placeholders={
                    "feature": item.feature,
                    "network": self.network_name(item.network_id),
                },
            )
        for issue_id in self._issues.get(tier, set()) - current:
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issues[tier] = current

    @callback
    def clear_issues(self) -> None:
        """Delete every repair issue this entry raised."""
        for issue_ids in self._issues.values():
            for issue_id in issue_ids:
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
        self._issues.clear()
