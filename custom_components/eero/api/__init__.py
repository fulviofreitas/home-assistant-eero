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
import json
import logging
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import aiohttp

from eero import EeroAPI as EeroSDK
from eero.exceptions import (
    EeroAccessDeniedException,
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

from . import daily as daily_tier
from . import hourly as hourly_tier
from .account import EeroAccount
from .const import DEFAULT_REQUEST_TIMEOUT, REDACT_KEYS
from .throughput import WanTotal, wan_total
from .util import api_url, premium_enabled

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
    "WanTotal",
    "collect_unavailable",
    "premium_enabled",
    "wan_total",
]

_LOGGER = logging.getLogger(__name__)


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

    async def require_token(self) -> str:
        """Return the token the SDK is using now, or raise if there is none.

        For the requests the SDK has no method for and the tier modules send
        through its generic ``get``; async_current_token() answers None
        instead.
        """
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
        await self.save_response(response=data, name=name)
        return data

    async def get(self, path: str, **kwargs: Any) -> Any:
        """GET an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.get(api_url(path), auth_token=await self.require_token(), **kwargs),
            name=path,
        )

    async def put(self, path: str, **kwargs: Any) -> Any:
        """PUT to an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.put(api_url(path), auth_token=await self.require_token(), **kwargs),
            name=path,
        )

    async def post(self, path: str, **kwargs: Any) -> Any:
        """POST to an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.post(api_url(path), auth_token=await self.require_token(), **kwargs),
            name=path,
        )

    async def delete(self, path: str, **kwargs: Any) -> Any:
        """DELETE an endpoint the SDK has no method for."""
        return await self.call(
            self.sdk.networks.delete(
                api_url(path), auth_token=await self.require_token(), **kwargs
            ),
            name=path,
        )

    async def call_optional(
        self,
        request: Awaitable[dict[str, Any]],
        name: str,
        network_id: str,
        feature: str,
    ) -> Any:
        """Like call(), but a feature the network lacks yields None, not a failed poll.

        A premium or unavailable feature also raises a repair issue. A 404 or a
        403 does not: hardware without the feature answers 404, and an admin
        without access to it 403, and neither is something to repair.
        """
        try:
            return await self.call(request, name)
        except EeroPremiumRequiredException:
            unavailable = UnavailableFeature(network_id, feature, True)
        except EeroFeatureUnavailableException:
            unavailable = UnavailableFeature(network_id, feature, False)
        except (EeroNotFoundException, EeroAccessDeniedException):
            _LOGGER.debug("%s not readable on this network", feature)
            return None
        if (found := _UNAVAILABLE.get()) is not None:
            found.append(unavailable)
        return None

    # -- account ---------------------------------------------------------

    async def get_account(self) -> dict[str, Any]:
        """Return the account, with its list of networks."""
        account = await self.call(
            self.sdk.account.get_account(),
            name="/2.2/account",
        )
        if not account or "networks" not in account:
            # A 200 with a null or malformed body would otherwise build an
            # account with no networks: on a cold start that sets the
            # integration up with no entities at all and no reason logged.
            raise EeroException("Account response reported no networks")
        return cast("dict[str, Any]", account)

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

    async def get_devices(self, network_id: str) -> list[Any]:
        """Return a network's device list, read from the API now.

        The SDK's device read has no cache: every call is a request, which
        is what the fast tier and the post-burst read both want.
        """
        devices = await self.call(
            self.sdk.devices.get_devices(network_id),
            name=f"/2.2/networks/{network_id}/devices",
        )
        return cast("list[Any]", devices or [])

    async def request_burst(
        self, network_id: str, network: dict[str, Any] | None = None
    ) -> str | None:
        """Request a live-usage burst and return the API's ``next_burst``.

        About 12 s later the device list carries fresh ``usage`` values (see
        api.throughput). Refusals are raised as they come: the caller maps a
        premium or feature refusal to a repair issue and stops asking.
        """
        data = await self.call(
            self.sdk.burst_reporters.create_burst_reporter(network_id, parent=network),
            name=f"/2.2/networks/{network_id}/burst_reporters",
        )
        if isinstance(data, dict) and (next_burst := data.get("next_burst")) is not None:
            return str(next_burst)
        return None

    async def fetch_fast(
        self, network_id: str, config: EeroUpdateConfig
    ) -> dict[str, Any]:
        """Network, clients, profiles, eeros: what trackers and live sensors read.

        At most four requests per network, usually two or three: the network
        envelope already embeds its eeros, so eeros.get_eeros is only called
        when it does not, and clients and profiles are only fetched when
        something on that network uses them.
        """
        try:
            network = await self.call(
                self.sdk.networks.get_network(network_id),
                name=f"/2.2/networks/{network_id}",
            )
        except (EeroNotFoundException, EeroAccessDeniedException):
            # The network was removed from the account, or this account lost
            # access to it. Skip it, with a repair issue, rather than failing
            # the poll for every other network and keeping the entry from
            # loading (and so from its options flow) for good.
            if (found := _UNAVAILABLE.get()) is not None:
                found.append(UnavailableFeature(network_id, "network", False))
            return {}
        if not isinstance(network, dict):
            raise EeroException(f"Network {network_id} returned no data")
        payload: dict[str, Any] = {"network": network}
        if config.get_devices:
            payload["devices"] = await self.get_devices(network_id)
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
        return await hourly_tier.fetch_hourly(self, network_id, network, config)

    async def update_activity(
        self,
        activity: str,
        network_id: str,
        resource: str,
        timezone: str,
        profile_id: str | None = None,
    ) -> Any:
        """Fetch one activity series."""
        return await hourly_tier.update_activity(
            self, activity, network_id, resource, timezone, profile_id
        )

    # -- daily tier ------------------------------------------------------

    async def fetch_daily(
        self, network_id: str, network: dict[str, Any], config: EeroUpdateConfig
    ) -> dict[str, Any]:
        """The lists, settings, hardware and firmware updates of the daily tier.

        These change when somebody changes them, so they are polled daily and
        refreshed on demand after a setter that touches them. What is read is
        listed in the docstring of api/daily.py.
        """
        return await daily_tier.fetch_daily(self, network_id, network, config)

    async def attach_release_notes(self, updates: dict[str, Any]) -> None:
        """Add the release notes to an updates read, unless fetching them fails.

        Release notes only decorate the update entities. Losing them must not
        take the rest of the tier down with them.
        """
        try:
            updates["release_notes"] = await self.get_release_notes(
                updates.get("manifest_resource")
            )
        except (TimeoutError, aiohttp.ClientError, EeroException) as error:
            _LOGGER.warning("Could not fetch release notes: %s", error)

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
        await self.save_response(response=notes, name="release_notes")
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
            if not payload.get("network"):
                continue
            network = _fast_network(payload, hourly.get(network_id))
            tier = daily.get(network_id) or {}
            _merge_daily_hardware(network, tier)
            _merge_daily_settings(network, tier)
            networks.append(network)
        account = dict(account or {})
        account["networks"] = {"count": len(networks), "data": networks}
        return EeroAccount(self, account)

    # -- helpers ---------------------------------------------------------

    def define_period(
        self, period: str, timezone: str
    ) -> tuple[str | None, str | None, str | None]:
        """Return the (start, end, cadence) of the day, week or month so far."""
        return hourly_tier.define_period(period, timezone)

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

    async def save_response(self, response: Any, name: str = "response") -> None:
        """Save a redacted response for debugging.

        Auth exchanges are never written to disk: their bodies are the session
        token itself. Redaction and serialisation happen here, on the event
        loop, so the caller can go on changing the response afterwards; only
        the file write goes to a thread, because it blocks.
        """
        if not self.save_location or not response:
            return
        if "/login" in name:
            _LOGGER.debug("Not saving response for auth endpoint: %s", name)
            return
        text = json.dumps(
            self.redact(response),
            indent=4,
            default=lambda o: "not-serializable",
            sort_keys=True,
        )
        file_name = f"{name.replace('/', '_').replace('.', '_')}.json"
        _LOGGER.debug("Saving response: %s", file_name)
        await asyncio.to_thread(_write_text, Path(self.save_location), file_name, text)


def _write_text(directory: Path, file_name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / file_name).write_text(text, encoding="utf-8")


def _counted(items: Any) -> dict[str, Any]:
    items = items if isinstance(items, list) else []
    return {"count": len(items), "data": items}


def _fast_network(
    payload: dict[str, Any], activity: dict[str, Any] | None
) -> dict[str, Any]:
    """Return a network envelope with the fast tier's lists and the hourly activity."""
    network = dict(payload["network"])
    for key in ("devices", "profiles", "eeros"):
        if key in payload:
            network[key] = _counted(payload[key])
    network["activity"] = activity or {}
    return network


def _merge_daily_hardware(network: dict[str, Any], tier: dict[str, Any]) -> None:
    """Add the daily tier's Thread, backup and entitlement reads to a network."""
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


def _merge_daily_settings(network: dict[str, Any], tier: dict[str, Any]) -> None:
    """Add the daily tier's lists, settings and firmware updates to a network."""
    if "blacklist" in tier:
        network["blacklist"] = _counted(tier["blacklist"])
    if "schedules" in tier:
        network["schedules"] = tier["schedules"]
    if "reservations" in tier:
        network["reservations"] = _counted(tier["reservations"])
    if "forwards" in tier:
        network["forwards"] = _counted(tier["forwards"])
    if isinstance(tier.get("fast_transition"), dict):
        value = tier["fast_transition"].get("fast_transition")
        if value is not None:
            network["fast_transition_enabled"] = value
    if "connections" in tier:
        network["connections"] = tier["connections"]
    if isinstance(tier.get("updates"), dict):
        # The network envelope's own updates block is re-read every
        # fast poll (preferred_update_hour lives there); the daily
        # read adds the target firmware and release notes.
        network["updates"] = {
            **tier["updates"],
            **(network.get("updates") or {}),
        }


@dataclass(eq=False)
class EeroUpdateConfig:
    """What to fetch for one network.

    Compared and hashed by identity, like a plain class: eq=False.
    """

    activity: dict[str, list[str]] = field(default_factory=dict)
    profiles: list[str] = field(default_factory=list)
    eeros: list[str] = field(default_factory=list)
    get_backup_access_points: bool = False
    get_devices: bool = False
    get_profiles: bool = field(init=False)
    get_release_notes: bool = False
    # Only meaningful (and only ever set) alongside get_devices: the
    # block switch has nothing to read state from without a client list.
    get_blacklist: bool = False
    # Bedtime switch/time entities: one schedules read per configured
    # profile, only when a profile entity is configured.
    get_schedules: bool = False
    # Per-port sensors/buttons: one connections read per configured
    # eero, only when an eero entity is configured.
    get_connections: bool = False

    def __post_init__(self) -> None:
        """Derive get_profiles from the profiles.

        None is still taken for an empty container, as it was when this
        class had a hand-written constructor.
        """
        self.activity = self.activity if self.activity is not None else {}
        self.profiles = self.profiles if self.profiles is not None else []
        self.eeros = self.eeros if self.eeros is not None else []
        self.get_profiles = bool(self.profiles)
