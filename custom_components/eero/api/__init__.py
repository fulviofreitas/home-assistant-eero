"""Eero API.

The integration's layer over the eero-api SDK (import name ``eero``). The SDK
does the HTTP, the session refresh and the error classification; this module
decides what to fetch for each polling tier, unwraps the ``{"meta", "data"}``
envelopes the SDK returns, and assembles them into the dicts the property
objects in this package (EeroAccount, EeroNetwork, ...) were written against.

Kept free of Home Assistant imports so it can be unit tested on its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import datetime
import json
import logging
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import aiohttp
from eero import EeroAPI as EeroSDK
from eero.const import API_ENDPOINT
from eero.exceptions import (
    EeroAPIException,
    EeroAuthenticationException,
    EeroException,
    EeroFeatureUnavailableException,
    EeroNetworkException,
    EeroNotFoundException,
    EeroPremiumRequiredException,
    EeroRateLimitException,
    EeroTimeoutException,
)

from .account import EeroAccount
from .const import (
    ACTIVITY_APP_EVENTS,
    ACTIVITY_EEROS_DATA_USAGE_SUMMARY_DAY,
    ACTIVITY_MAP,
    ACTIVITY_NOTIFICATIONS_UNREAD,
    ACTIVITY_UNPROFILED_DATA_USAGE_DAY,
    CADENCE_DAILY,
    CADENCE_HOURLY,
    DEFAULT_REQUEST_TIMEOUT,
    PERIOD_DAY,
    PERIOD_MONTH,
    PERIOD_WEEK,
    REDACT_KEYS,
    RESOURCE_MAP,
)
from .util import backup_access_point_ok, premium_ok

__all__ = [
    "EeroAPIException",
    "EeroAccount",
    "EeroAuthenticationException",
    "EeroException",
    "EeroFeatureUnavailableException",
    "EeroHub",
    "EeroNetworkException",
    "EeroPremiumRequiredException",
    "EeroRateLimitException",
    "EeroTimeoutException",
    "EeroUpdateConfig",
    "UnavailableFeature",
    "collect_unavailable",
]

_LOGGER = logging.getLogger(__name__)

# The SDK resolves a relative path against .../2.2, so a path the API itself
# returned ("/2.2/networks/1/...", "/2.3/...") has to be made absolute on the
# same host, or it would become ".../2.2/2.2/networks/1/...". The host has to
# match exactly: the SDK only attaches the session token to its own host.
API_HOST = API_ENDPOINT.rsplit("/2.2", 1)[0]


def api_url(path: str) -> str:
    """Return an absolute API URL for a path the API returned."""
    if path.startswith(("http://", "https://")):
        return path
    return f"{API_HOST}/{path.lstrip('/')}"


class UnavailableFeature(Exception):
    """A tier read that the account is not entitled to, or the network lacks.

    Carried in the tier payload rather than raised, so the rest of the poll
    still lands; the coordinator turns it into a repair issue.
    """

    def __init__(self, network_id: str, feature: str, premium: bool) -> None:
        """Initialize."""
        super().__init__(f"{feature} unavailable on network {network_id}")
        self.network_id = network_id
        self.feature = feature
        self.premium = premium


_UNAVAILABLE: ContextVar[list[UnavailableFeature] | None] = ContextVar(
    "eero_unavailable", default=None
)


@contextmanager
def collect_unavailable() -> Iterator[list[UnavailableFeature]]:
    """Collect the features a fetch found unavailable.

    A context variable rather than an attribute on the hub: the three tiers
    can refresh at the same time, and each must only see its own.
    """
    found: list[UnavailableFeature] = []
    token = _UNAVAILABLE.set(found)
    try:
        yield found
    finally:
        _UNAVAILABLE.reset(token)


class EeroHub:
    """One eero account: the SDK client plus what the integration keeps around it."""

    # Eero's own hosts, including subdomains. eeroassets.com is where the
    # firmware manifest URL in the API response actually points.
    ALLOWED_RELEASE_NOTE_HOSTS = frozenset({"eero.com", "e2ro.com", "eeroassets.com"})

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_token: str | None = None,
        save_location: str | None = None,
        request_timeout: float | None = None,
        sdk: EeroSDK | None = None,
    ) -> None:
        """Initialize.

        use_keyring=False with no cookie_file gives the SDK an in-memory
        credential store: the config entry owns the token, nothing else does.
        """
        self.session = session
        self.sdk = sdk or EeroSDK(session=session, use_keyring=False)
        self.user_token = user_token
        self.save_location = save_location
        self.request_timeout = request_timeout or DEFAULT_REQUEST_TIMEOUT
        self.release_notes_cache: dict[str, dict[str, Any] | None] = {}

    # -- session ---------------------------------------------------------

    async def async_set_token(self, token: str) -> None:
        """Hand a stored session token to the SDK."""
        await self.sdk.auth.set_session_token(token)
        self.user_token = token

    async def async_current_token(self) -> str | None:
        """Return the token the SDK is using now."""
        return await self.sdk.auth.get_auth_token()

    async def login(self, login: str) -> None:
        """Request a verification code; the SDK keeps the pending token."""
        _LOGGER.debug("Requesting login code")
        if not await self.sdk.auth.login(login):
            raise EeroAuthenticationException("Login did not return a session token")

    async def login_verify(self, code: str) -> dict[str, Any]:
        """Verify the code and return the account it signed in to."""
        _LOGGER.debug("Verifying login code")
        if not await self.sdk.auth.verify(code):
            raise EeroAuthenticationException("Verification code was not accepted")
        self.user_token = await self.async_current_token()
        return await self.get_account()

    # -- transport -------------------------------------------------------

    async def _token(self) -> str:
        if not (token := await self.async_current_token()):
            raise EeroAuthenticationException("Not authenticated")
        return token

    async def call(self, request: Awaitable[dict[str, Any]], name: str) -> Any:
        """Await an SDK request under the configured timeout; return its data.

        The SDK sets ClientTimeout(total=30, sock_read=10) on every request and
        does not let a caller change it, so the configured timeout can only
        ever shorten that, which is why the option is capped at 30 seconds.
        """
        async with asyncio.timeout(self.request_timeout):
            envelope = await request
        data = envelope.get("data") if isinstance(envelope, dict) else None
        self.save_response(response=data, name=name)
        return data

    async def get(self, path: str, **kwargs: Any) -> Any:
        """GET an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.get(api_url(path), auth_token=await self._token(), **kwargs),
            name=path,
        )

    async def put(self, path: str, **kwargs: Any) -> Any:
        """PUT to an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.put(api_url(path), auth_token=await self._token(), **kwargs),
            name=path,
        )

    async def post(self, path: str, **kwargs: Any) -> Any:
        """POST to an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.post(api_url(path), auth_token=await self._token(), **kwargs),
            name=path,
        )

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """DELETE an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.delete(
                api_url(path), auth_token=await self._token(), **kwargs
            ),
            name=path,
        )

    async def _optional(
        self,
        request: Awaitable[dict[str, Any]],
        name: str,
        network_id: str,
        feature: str,
    ) -> Any:
        """Like call(), but a feature the network lacks yields None, not a failed poll."""
        try:
            return await self.call(request, name)
        except EeroPremiumRequiredException:
            unavailable = UnavailableFeature(network_id, feature, True)
        except (EeroFeatureUnavailableException, EeroNotFoundException):
            unavailable = UnavailableFeature(network_id, feature, False)
        if (found := _UNAVAILABLE.get()) is not None:
            found.append(unavailable)
        return None

    # -- account ---------------------------------------------------------

    async def get_account(self) -> dict[str, Any]:
        """Return the account, with its list of networks."""
        account = await self.call(
            self.sdk.auth.get("/account", auth_token=await self._token()),
            name="/2.2/account",
        )
        if not account or "networks" not in account:
            # A 200 with a null or malformed body would otherwise build an
            # account with no networks: on a cold start that sets the
            # integration up with no entities at all and no reason logged.
            raise EeroException("Account response reported no networks")
        return account

    @staticmethod
    def network_ids(account: dict[str, Any]) -> list[str]:
        """Return the IDs of the networks the account lists."""
        ids = []
        for network in account.get("networks", {}).get("data", []):
            if url := network.get("url"):
                ids.append(url.rstrip("/").rsplit("/", 1)[-1])
            else:
                _LOGGER.debug("Skipping a network entry that reports no url")
        return ids

    async def snapshot(self, account: dict[str, Any] | None = None) -> EeroAccount:
        """Fetch everything the config and options flows offer for selection."""
        if account is None:
            account = await self.get_account()
        fast: dict[str, dict[str, Any]] = {}
        daily: dict[str, dict[str, Any]] = {}
        for network_id in self.network_ids(account):
            config = EeroUpdateConfig(get_devices=True, profiles=["*"])
            config.get_backup_access_points = True
            fast[network_id] = await self.fetch_fast(network_id, config)
            daily[network_id] = await self.fetch_daily(
                network_id, fast[network_id]["network"], config
            )
        return self.assemble(account, fast, {}, daily)

    # -- fast tier -------------------------------------------------------

    async def fetch_fast(
        self, network_id: str, config: EeroUpdateConfig
    ) -> dict[str, Any]:
        """Network, clients, profiles, eeros: what trackers and live sensors read.

        At most four requests per network, usually two or three: the network
        envelope already embeds its eeros, so eeros.get_eeros is only called
        when it does not, and clients and profiles are only fetched when
        something on that network uses them.
        """
        network = await self.call(
            self.sdk.networks.get_network(network_id), name=f"/2.2/networks/{network_id}"
        )
        if not isinstance(network, dict):
            raise EeroException(f"Network {network_id} returned no data")
        payload: dict[str, Any] = {"network": network}
        if config.get_devices:
            payload["devices"] = (
                await self.call(
                    self.sdk.devices.get_devices(network_id),
                    name=f"/2.2/networks/{network_id}/devices",
                )
                or []
            )
        if config.get_profiles:
            payload["profiles"] = (
                await self.call(
                    self.sdk.profiles.get_profiles(network_id),
                    name=f"/2.2/networks/{network_id}/profiles",
                )
                or []
            )
        if not (network.get("eeros") or {}).get("data"):
            payload["eeros"] = (
                await self.call(
                    self.sdk.eeros.get_eeros(network_id),
                    name=f"/2.2/networks/{network_id}/eeros",
                )
                or []
            )
        return payload

    # -- hourly tier -----------------------------------------------------

    async def fetch_hourly(
        self, network_id: str, network: dict[str, Any], config: EeroUpdateConfig
    ) -> dict[str, Any]:
        """Insights and data usage series for the configured activity metrics.

        The API aggregates these hourly, so polling them faster only returns
        the same numbers again. Every request sends start, end and cadence as
        query parameters: the API rejects a GET that carries a body.
        """
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
                            await self.update_activity(
                                activity, network_id, resource, timezone, profile_id
                            )
                        )
                else:
                    activity_data[resource][activity] = await self.update_activity(
                        activity, network_id, resource, timezone
                    )
        return activity_data

    async def update_activity(
        self,
        activity: str,
        network_id: str,
        resource: str,
        timezone: str,
        profile_id: str | None = None,
    ) -> Any:
        """Fetch one activity series."""
        # "{}/insights" or "{}/data_usage": the family is the last segment.
        family: str = str(ACTIVITY_MAP[activity][0]).rsplit("/", 1)[-1]
        insight_type: str = ACTIVITY_MAP[activity][1]
        period: str = ACTIVITY_MAP[activity][2]
        start, end, cadence = self.define_period(period=period, timezone=timezone)
        window = {"start": start, "end": end, "cadence": cadence}
        name = f"/2.2/networks/{network_id}/{family}/{resource}"
        if activity == ACTIVITY_UNPROFILED_DATA_USAGE_DAY:
            request = self.sdk.data_usage.get_unprofiled_summary(
                network_id, timezone=timezone, **window
            )
            name = f"/2.2/networks/{network_id}/data_usage/unprofiled/summary"
        elif activity == ACTIVITY_EEROS_DATA_USAGE_SUMMARY_DAY:
            request = self.sdk.data_usage.get_eeros_summary(
                network_id, timezone=timezone, **window
            )
            name = f"/2.2/networks/{network_id}/data_usage/eeros/summary"
        elif activity == ACTIVITY_APP_EVENTS:
            # A bounded page: this is reported as new HA events on every
            # entity not yet seen, so an unbounded page would replay a
            # flood of history the first time the entity is added.
            request = self.sdk.events.get_app_events(network_id, page_size=25)
            name = f"/2.2/networks/{network_id}/app_events"
        elif activity == ACTIVITY_NOTIFICATIONS_UNREAD:
            request = self.sdk.notifications.has_unread(network_id)
            name = f"/2.2/networks/{network_id}/notifications/has_unread"
        elif family == "data_usage":
            if resource == "network":
                request = self.sdk.data_usage.get_data_usage(
                    network_id, timezone=timezone, **window
                )
            elif resource == "devices":
                request = self.sdk.data_usage.get_devices_usage(
                    network_id, timezone=timezone, **window
                )
            elif resource == "profiles":
                request = self.sdk.data_usage.get_profile_usage(
                    network_id, str(profile_id), timezone=timezone, **window
                )
            else:
                # Per-eero usage has no SDK reader; same query, same endpoint.
                request = self.sdk.data_usage.get(
                    api_url(f"/2.2/networks/{network_id}/data_usage/{resource}"),
                    auth_token=await self._token(),
                    params={**window, "timezone": timezone},
                )
        elif resource == "network":
            request = self.sdk.insights.get_insights(
                network_id, insight_type=insight_type, **window
            )
        elif resource == "devices":
            request = self.sdk.insights.get_devices_insights(
                network_id, insight_type=insight_type, **window
            )
        elif resource == "profiles":
            request = self.sdk.insights.get_profile_insights(
                network_id, str(profile_id), insight_type=insight_type, **window
            )
        else:
            request = self.sdk.insights.get(
                api_url(f"/2.2/networks/{network_id}/insights/{resource}"),
                auth_token=await self._token(),
                params={**window, "insight_type": insight_type},
            )
        data = await self._optional(request, name, network_id, activity) or {}
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

    # -- daily tier ------------------------------------------------------

    async def fetch_daily(
        self, network_id: str, network: dict[str, Any], config: EeroUpdateConfig
    ) -> dict[str, Any]:
        """Thread, backup access points, backup internet, entitlements, updates.

        These change when somebody changes them, so they are polled daily and
        refreshed on demand after a setter that touches them.
        """
        payload: dict[str, Any] = {}
        resources = network.get("resources") or {}
        if config.get_blacklist:
            payload["blacklist"] = (
                await self._optional(
                    self.sdk.blacklist.get_blacklist(network_id),
                    f"/2.2/networks/{network_id}/blacklist",
                    network_id,
                    "blacklist",
                )
                or []
            )
        if config.get_schedules:
            schedules: dict[str, Any] = {}
            for profile_id in config.profiles:
                if profile_id == "*":
                    # Only ever seen from snapshot(), which has no real
                    # profile IDs to resolve schedules for.
                    continue
                schedules[profile_id] = (
                    await self._optional(
                        self.sdk.schedule.get_schedules(network_id, profile_id),
                        f"/2.2/networks/{network_id}/profiles/{profile_id}/schedules",
                        network_id,
                        "schedules",
                    )
                    or []
                )
            payload["schedules"] = schedules
        payload["reservations"] = (
            await self._optional(
                self.sdk.reservations.get_reservations(network_id),
                f"/2.2/networks/{network_id}/reservations",
                network_id,
                "reservations",
            )
            or []
        )
        payload["forwards"] = (
            await self._optional(
                self.sdk.forwards.get_forwards(network_id),
                f"/2.2/networks/{network_id}/forwards",
                network_id,
                "forwards",
            )
            or []
        )
        if resources.get("thread"):
            payload["thread"] = await self._optional(
                self.sdk.thread.get_thread(network_id),
                f"/2.2/networks/{network_id}/thread",
                network_id,
                "thread",
            )
        payload["features"] = await self._optional(
            self.sdk.entitlements.get_features(network_id),
            f"/2.2/entitlements/networks/{network_id}/features",
            network_id,
            "entitlements",
        )
        capabilities = network.get("capabilities") or {}
        backup_access_point = capabilities.get("backup_access_point") or {}
        if config.get_backup_access_points and backup_access_point_ok(
            capable=backup_access_point.get("capable"),
            requirements=backup_access_point.get("requirements"),
        ):
            if premium_enabled(network, payload["features"]):
                payload["backup_access_points"] = (
                    await self._optional(
                        self.sdk.backup_access_points.list(network_id),
                        f"/2.2/networks/{network_id}/backup_access_points",
                        network_id,
                        "backup_access_points",
                    )
                    or []
                )
                payload["backup_internet"] = await self._optional(
                    self.sdk.backup.get_backup_internet(network_id),
                    f"/2.2/networks/{network_id}/backupinternet",
                    network_id,
                    "backup_internet",
                )
        updates = await self._optional(
            self.sdk.updates.get_updates(network_id),
            f"/2.2/networks/{network_id}/updates",
            network_id,
            "updates",
        )
        if not isinstance(updates, dict):
            updates = dict(network.get("updates") or {})
        if config.get_release_notes:
            try:
                updates["release_notes"] = await self.get_release_notes(
                    updates.get("manifest_resource")
                )
            except (TimeoutError, aiohttp.ClientError, EeroException) as error:
                # Release notes only decorate the update entities. Losing
                # them must not take the rest of the tier down with them.
                _LOGGER.warning("Could not fetch release notes: %s", error)
        payload["updates"] = updates
        return payload

    async def get_release_notes(self, url: str | None) -> dict[str, Any] | None:
        """Get release notes.

        Cached by manifest URL: the manifest changes only when the firmware
        does.
        """
        if not url:
            return None
        if url in self.release_notes_cache:
            return self.release_notes_cache[url]
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if parsed.scheme != "https" or not any(
            host == domain or host.endswith(f".{domain}")
            for domain in self.ALLOWED_RELEASE_NOTE_HOSTS
        ):
            _LOGGER.warning("Refusing to fetch release notes from unexpected host: %s", host)
            # Remember the refusal: the manifest URL does not change between
            # polls, and neither does the answer.
            self.release_notes_cache[url] = None
            return None
        # A plain GET on the shared session: no credentials are attached, the
        # manifest URL comes from the API response, not from this integration.
        async with asyncio.timeout(self.request_timeout):
            async with self.session.get(url) as response:
                if response.status >= 400:
                    raise EeroException(
                        f"Unable to get release notes (status={response.status})"
                    )
                text = await response.text()
        try:
            notes = json.loads(text)
        except json.JSONDecodeError as error:
            raise EeroException("Unable to decode release notes") from error
        if not isinstance(notes, dict):
            raise EeroException("Release notes are not a JSON object")
        self.save_response(response=notes, name="release_notes")
        self.release_notes_cache[url] = notes
        return notes

    # -- assembly --------------------------------------------------------

    def assemble(
        self,
        account: dict[str, Any] | None,
        fast: dict[str, dict[str, Any]],
        hourly: dict[str, dict[str, Any]],
        daily: dict[str, dict[str, Any]],
    ) -> EeroAccount:
        """Build the property-object tree from the three tiers' payloads."""
        networks = []
        for network_id, payload in fast.items():
            network = dict(payload["network"])
            if "devices" in payload:
                network["devices"] = _counted(payload["devices"])
            if "profiles" in payload:
                network["profiles"] = _counted(payload["profiles"])
            if "eeros" in payload:
                network["eeros"] = _counted(payload["eeros"])
            network["activity"] = hourly.get(network_id) or {}
            tier = daily.get(network_id) or {}
            if tier.get("thread") is not None:
                network["thread"] = tier["thread"]
            if "backup_access_points" in tier:
                network["backup_access_points"] = _counted(tier["backup_access_points"])
            if isinstance(tier.get("backup_internet"), dict):
                enabled = tier["backup_internet"].get("backup_internet_enabled")
                if enabled is not None:
                    network["backup_internet_enabled"] = enabled
            if "features" in tier:
                network["entitlements"] = tier["features"]
            if "blacklist" in tier:
                network["blacklist"] = _counted(tier["blacklist"])
            if "schedules" in tier:
                network["schedules"] = tier["schedules"]
            if "reservations" in tier:
                network["reservations"] = _counted(tier["reservations"])
            if "forwards" in tier:
                network["forwards"] = _counted(tier["forwards"])
            if isinstance(tier.get("updates"), dict):
                network["updates"] = tier["updates"]
            networks.append(network)
        account = dict(account or {})
        account["networks"] = {"count": len(networks), "data": networks}
        return EeroAccount(self, account)

    # -- helpers ---------------------------------------------------------

    def define_period(self, period: str, timezone: str) -> tuple:
        """Define period."""
        # Imported here so this package can be imported, and unit tested,
        # without python-dateutil, which arrives with Home Assistant rather
        # than through this integration's requirements.
        from dateutil import relativedelta  # noqa: PLC0415

        start, end, cadence = None, None, None
        now = datetime.datetime.now(tz=ZoneInfo(timezone))
        if period == PERIOD_DAY:
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(days=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_HOURLY
        elif period == PERIOD_WEEK:
            start = now - relativedelta.relativedelta(days=now.weekday() + 1)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(weeks=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_DAILY
        elif period == PERIOD_MONTH:
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = (
                start
                + relativedelta.relativedelta(months=1)
                - datetime.timedelta(seconds=1)
            )
            cadence = CADENCE_DAILY
        else:
            return (start, end, cadence)
        start = f"{start.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z"
        end = f"{end.astimezone(datetime.UTC).replace(tzinfo=None).isoformat()}Z"
        return (start, end, cadence)

    def redact(self, obj: Any) -> Any:
        """Return a copy of obj with every secret value replaced."""
        if isinstance(obj, dict):
            return {
                key: ("**REDACTED**" if key in REDACT_KEYS else self.redact(value))
                for key, value in obj.items()
            }
        if isinstance(obj, list):
            return [self.redact(item) for item in obj]
        return obj

    def save_response(self, response: Any, name: str = "response") -> None:
        """Save a redacted response for debugging.

        Auth exchanges are never written to disk: their bodies are the session
        token itself.
        """
        if not self.save_location or not response:
            return
        if "/login" in name:
            _LOGGER.debug("Not saving response for auth endpoint: %s", name)
            return
        Path(self.save_location).mkdir(parents=True, exist_ok=True)
        name = name.replace("/", "_").replace(".", "_")
        file_path_name = f"{self.save_location}/{name}.json"
        _LOGGER.debug("Saving response: %s", file_path_name)
        with Path(file_path_name).open(mode="w", encoding="utf-8") as file:
            json.dump(
                obj=self.redact(response),
                fp=file,
                indent=4,
                default=lambda o: "not-serializable",
                sort_keys=True,
            )


def _counted(items: Any) -> dict[str, Any]:
    items = items if isinstance(items, list) else []
    return {"count": len(items), "data": items}


def premium_enabled(network: dict[str, Any], features: Any) -> bool:
    """Whether the network is entitled to eero Plus features.

    Decided from the entitlements read when there is one: an empty feature
    list means no subscription. When entitlements could not be read, fall
    back to the premium_status field on the network envelope.
    """
    if isinstance(features, dict) and isinstance(features.get("features"), list):
        return bool(features["features"])
    return premium_ok(
        capable=(network.get("capabilities") or {}).get("premium", {}).get("capable"),
        status=network.get("premium_status"),
    )


class EeroUpdateConfig:
    """What to fetch for one network."""

    def __init__(
        self,
        activity: dict | None = None,
        profiles: list | None = None,
        get_backup_access_points: bool = False,
        get_devices: bool = False,
        get_release_notes: bool = False,
        get_blacklist: bool = False,
        get_schedules: bool = False,
    ) -> None:
        """Initialize."""
        self.activity = activity if activity is not None else {}
        self.profiles = profiles if profiles is not None else []
        self.get_backup_access_points = get_backup_access_points
        self.get_devices = get_devices
        self.get_profiles = bool(self.profiles)
        self.get_release_notes = get_release_notes
        # Only meaningful (and only ever set) alongside get_devices: the
        # block switch has nothing to read state from without a client list.
        self.get_blacklist = get_blacklist
        # Bedtime switch/time entities: one schedules read per configured
        # profile, only when a profile entity is configured.
        self.get_schedules = get_schedules
