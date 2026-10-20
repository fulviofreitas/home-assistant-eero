"""Actions (services) of the Eero integration.

Registered once for every entry from ``async_setup``, whether or not anything
is configured; each handler skips entries that are not loaded.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Home Assistant 2026.10 validates with probatio and aliases voluptuous to it
    # at runtime; before that it is voluptuous itself. Only the type checker
    # needs to be told which one the schemas below are.
    import probatio as vol
else:
    import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .api import EeroAuthenticationException, EeroException
from .api.const import SUPPORTED_APPS
from .api.network import EeroNetwork
from .const import (
    ATTR_AUTOMATIC,
    ATTR_BLOCKED_APPS,
    ATTR_CLIENT_PORT,
    ATTR_DELETE_FORWARDS,
    ATTR_DESCRIPTION,
    ATTR_ENABLED,
    ATTR_FORWARD,
    ATTR_GATEWAY_PORT,
    ATTR_IP,
    ATTR_IPV4,
    ATTR_IPV6,
    ATTR_MAC,
    ATTR_PROTOCOL,
    ATTR_PUBLIC_STATIC_IP,
    ATTR_RESERVATION,
    ATTR_TARGET_NETWORK,
    ATTR_TARGET_PROFILE,
    CONF_PROFILES,
    DOMAIN,
    SERVICE_CREATE_PORT_FORWARD,
    SERVICE_CREATE_RESERVATION,
    SERVICE_DELETE_PORT_FORWARD,
    SERVICE_DELETE_RESERVATION,
    SERVICE_SET_BLOCKED_APPS,
    SERVICE_SET_CUSTOM_DNS,
    TIER_DAILY,
    TIER_FAST,
)
from .coordinator import EeroRuntime

# Names or IDs, each kept as a string: the IDs the targets are compared with
# are strings, so an ID given as a number (12345, or "12345" read back as
# one) must not be turned into an int, and a name made of digits keeps its
# leading zeros.
_TARGETS = vol.All(cv.ensure_list, [cv.string])

SET_BLOCKED_APPS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BLOCKED_APPS): vol.All(
            cv.ensure_list, [vol.In(SUPPORTED_APPS.keys())]
        ),
        vol.Optional(ATTR_TARGET_PROFILE, default=[]): _TARGETS,
        vol.Optional(ATTR_TARGET_NETWORK, default=[]): _TARGETS,
    }
)

_TARGET_NETWORK_REQUIRED = {vol.Required(ATTR_TARGET_NETWORK): _TARGETS}

CREATE_RESERVATION_SCHEMA = vol.Schema(
    {
        **_TARGET_NETWORK_REQUIRED,
        vol.Required(ATTR_IP): cv.string,
        vol.Required(ATTR_MAC): cv.string,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_PUBLIC_STATIC_IP): cv.boolean,
    }
)

DELETE_RESERVATION_SCHEMA = vol.Schema(
    {
        **_TARGET_NETWORK_REQUIRED,
        vol.Required(ATTR_RESERVATION): cv.string,
        vol.Optional(ATTR_DELETE_FORWARDS): cv.boolean,
    }
)

CREATE_PORT_FORWARD_SCHEMA = vol.Schema(
    {
        **_TARGET_NETWORK_REQUIRED,
        vol.Required(ATTR_IP): cv.string,
        vol.Required(ATTR_CLIENT_PORT): cv.positive_int,
        vol.Required(ATTR_GATEWAY_PORT): cv.positive_int,
        vol.Required(ATTR_PROTOCOL): cv.string,
        vol.Optional(ATTR_DESCRIPTION): cv.string,
        vol.Optional(ATTR_ENABLED, default=True): cv.boolean,
    }
)

DELETE_PORT_FORWARD_SCHEMA = vol.Schema(
    {
        **_TARGET_NETWORK_REQUIRED,
        vol.Required(ATTR_FORWARD): cv.string,
    }
)

# DNS writes reboot the entire mesh a few minutes later (dns.py, eero-api):
# never retry a failed call in a loop.
SET_CUSTOM_DNS_SCHEMA = vol.Schema(
    {
        **_TARGET_NETWORK_REQUIRED,
        vol.Optional(ATTR_IPV4): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_IPV6): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_AUTOMATIC, default=False): cv.boolean,
    }
)


class _ActionFailures:
    """Collect the failures of an action that targets several networks.

    One network failing must not stop the action on the others, nor skip
    their refresh; the failures are raised together once every target has
    been tried. An expired session starts reauthentication for its entry.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.errors: list[str] = []
        self.auth_failed = False

    async def run(self, entry: ConfigEntry, request: Awaitable[Any]) -> None:
        try:
            await request
        except EeroAuthenticationException:
            entry.async_start_reauth(self.hass)
            self.auth_failed = True
        except (EeroException, TimeoutError) as error:
            self.errors.append(str(error))

    def raise_if_any(self) -> None:
        if self.auth_failed:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="auth_failed"
            )
        if self.errors:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="api_error",
                translation_placeholders={"error": "; ".join(self.errors)},
            )


async def _async_set_blocked_apps(service: ServiceCall) -> None:
    hass = service.hass
    blocked_apps = service.data[ATTR_BLOCKED_APPS]
    target_profile = service.data[ATTR_TARGET_PROFILE]
    target_network = service.data[ATTR_TARGET_NETWORK]
    failures = _ActionFailures(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime: EeroRuntime = entry.runtime_data
        for network in runtime.account.networks:
            if target_network and not (
                network.id in target_network or network.name in target_network
            ):
                continue
            for profile in network.profiles:
                if profile.id not in runtime.resources[network.known_id][CONF_PROFILES]:
                    continue
                if target_profile and not (
                    profile.id in target_profile or profile.name in target_profile
                ):
                    continue
                await failures.run(
                    entry, profile.async_set_blocked_applications(blocked_apps)
                )
        await runtime.coordinator(TIER_FAST).async_request_refresh()
    failures.raise_if_any()


async def _async_network_action(
    hass: HomeAssistant,
    target_network: list[Any],
    action: Callable[[EeroNetwork], Awaitable[Any]],
) -> None:
    """Run action(network) for every loaded network matching target_network.

    Shared by every reservation/forward/DNS service: all five act on a
    network directly (not a profile), and all five refresh the daily
    tier afterward, since that is where reservations, forwards and DNS
    mode are read from. A failure on one network does not stop the
    others; the failures are reported together at the end.
    """
    failures = _ActionFailures(hass)
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        runtime: EeroRuntime = entry.runtime_data
        for network in runtime.account.networks:
            if target_network and not (
                network.id in target_network or network.name in target_network
            ):
                continue
            await failures.run(entry, action(network))
        await runtime.coordinator(TIER_DAILY).async_request_refresh()
    failures.raise_if_any()


async def _async_create_reservation(service: ServiceCall) -> None:
    data = {ATTR_IP: service.data[ATTR_IP], ATTR_MAC: service.data[ATTR_MAC]}
    if ATTR_DESCRIPTION in service.data:
        data[ATTR_DESCRIPTION] = service.data[ATTR_DESCRIPTION]
    if ATTR_PUBLIC_STATIC_IP in service.data:
        data[ATTR_PUBLIC_STATIC_IP] = service.data[ATTR_PUBLIC_STATIC_IP]
    await _async_network_action(
        service.hass,
        service.data[ATTR_TARGET_NETWORK],
        lambda network: network.async_create_reservation(data),
    )


async def _async_delete_reservation(service: ServiceCall) -> None:
    await _async_network_action(
        service.hass,
        service.data[ATTR_TARGET_NETWORK],
        lambda network: network.async_delete_reservation(
            service.data[ATTR_RESERVATION],
            service.data.get(ATTR_DELETE_FORWARDS),
        ),
    )


async def _async_create_port_forward(service: ServiceCall) -> None:
    data = {
        ATTR_IP: service.data[ATTR_IP],
        ATTR_CLIENT_PORT: service.data[ATTR_CLIENT_PORT],
        ATTR_GATEWAY_PORT: service.data[ATTR_GATEWAY_PORT],
        ATTR_PROTOCOL: service.data[ATTR_PROTOCOL],
        ATTR_ENABLED: service.data[ATTR_ENABLED],
    }
    if ATTR_DESCRIPTION in service.data:
        data[ATTR_DESCRIPTION] = service.data[ATTR_DESCRIPTION]
    await _async_network_action(
        service.hass,
        service.data[ATTR_TARGET_NETWORK],
        lambda network: network.async_create_port_forward(data),
    )


async def _async_delete_port_forward(service: ServiceCall) -> None:
    await _async_network_action(
        service.hass,
        service.data[ATTR_TARGET_NETWORK],
        lambda network: network.async_delete_port_forward(service.data[ATTR_FORWARD]),
    )


async def _async_set_custom_dns(service: ServiceCall) -> None:
    await _async_network_action(
        service.hass,
        service.data[ATTR_TARGET_NETWORK],
        lambda network: network.async_set_custom_dns(
            ipv4=service.data.get(ATTR_IPV4),
            ipv6=service.data.get(ATTR_IPV6),
            automatic=service.data[ATTR_AUTOMATIC],
        ),
    )


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the integration's actions."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BLOCKED_APPS,
        _async_set_blocked_apps,
        schema=SET_BLOCKED_APPS_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_RESERVATION,
        _async_create_reservation,
        schema=CREATE_RESERVATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_RESERVATION,
        _async_delete_reservation,
        schema=DELETE_RESERVATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_CREATE_PORT_FORWARD,
        _async_create_port_forward,
        schema=CREATE_PORT_FORWARD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_PORT_FORWARD,
        _async_delete_port_forward,
        schema=DELETE_PORT_FORWARD_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_CUSTOM_DNS,
        _async_set_custom_dns,
        schema=SET_CUSTOM_DNS_SCHEMA,
    )
