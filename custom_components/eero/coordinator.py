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
from homeassistant.helpers import issue_registry as ir
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
            self.update_interval = backoff_interval(
                self.update_interval, self.base_interval
            )
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="rate_limited",
                translation_placeholders={
                    "seconds": str(int(self.update_interval.total_seconds()))
                },
            ) from error
        except TimeoutError as error:
            raise UpdateFailed(
                translation_domain=DOMAIN, translation_key="timeout"
            ) from error
        except EeroException as error:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": str(error)},
            ) from error
        self.update_interval = self.base_interval
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
    _account_key: tuple[int, int, int] | None = None
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
        """Refresh the fast tier first: the other two read its network payload."""
        await self.coordinators[TIER_FAST].async_config_entry_first_refresh()
        await self.coordinators[TIER_DAILY].async_config_entry_first_refresh()
        await self.coordinators[TIER_HOURLY].async_config_entry_first_refresh()

    def previous(self, tier: str, network_id: str) -> dict[str, Any]:
        """Return a tier's last data for a network.

        Used when the fast tier has no envelope for the network to build on:
        keeping the last good data beats replacing it with an empty one.
        """
        return dict((self.coordinators[tier].data or {}).get(network_id) or {})

    def network_payload(self, network_id: str) -> dict[str, Any]:
        """Return the latest raw network envelope from the fast tier."""
        data = self.coordinators[TIER_FAST].data or {}
        return (data.get(network_id) or {}).get("network") or {}

    @property
    def account(self) -> EeroAccount:
        """Return the property-object tree, rebuilt when any tier has new data."""
        fast, hourly, daily = (
            self.coordinators[tier].data or {}
            for tier in (TIER_FAST, TIER_HOURLY, TIER_DAILY)
        )
        key = (id(fast), id(hourly), id(daily))
        if self._account is None or key != self._account_key:
            self._account = self.hub.assemble(None, fast, hourly, daily)
            self._account_key = key
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
                    "premium_required" if item.premium else "feature_unavailable"
                ),
                translation_placeholders={
                    "feature": item.feature,
                    "network": item.network_id,
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
