"""Form schemas of the Eero config and options flows, and what a submitted form stores.

The setup flow and the options flow ask the same questions. They differ in what a
form starts out with (everything on offer, or what the entry already has), so each
form is built here from the defaults it is given, and each submitted form is turned
into the dict the entry stores.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    # Home Assistant 2026.10 validates with probatio and aliases voluptuous to
    # it at runtime; before that it is voluptuous itself. Only the type checker
    # needs to be told which one the schemas below are.
    import probatio as vol
else:
    import voluptuous as vol
from homeassistant.const import CONF_SCAN_INTERVAL, UnitOfTime
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api.network import EeroNetwork
from .const import (
    ACTIVITIES_DATA_USAGE_DEFAULT,
    ACTIVITIES_DATA_USAGE_PREMIUM,
    ACTIVITIES_DEFAULT,
    ACTIVITIES_PREMIUM,
    CONF_ACTIVITY_CLIENTS,
    CONF_ACTIVITY_EEROS,
    CONF_ACTIVITY_NETWORK,
    CONF_ACTIVITY_PROFILES,
    CONF_BACKUP_NETWORKS,
    CONF_CODE,
    CONF_CONSIDER_HOME,
    CONF_EEROS,
    CONF_LOGIN,
    CONF_NETWORKS,
    CONF_PREFIX_NETWORK_NAME,
    CONF_PROFILES,
    CONF_SAVE_RESPONSES,
    CONF_SUFFIX_CONNECTION_TYPE,
    CONF_TIMEOUT,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_PREFIX_NETWORK_NAME,
    DEFAULT_SAVE_RESPONSES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUFFIX_CONNECTION_TYPE,
    DEFAULT_TIMEOUT,
    DEFAULT_WIRED_CLIENTS_FILTER,
    DEFAULT_WIRELESS_CLIENTS_FILTER,
    MAX_CONSIDER_HOME,
    MAX_SCAN_INTERVAL,
    MAX_TIMEOUT,
    MIN_CONSIDER_HOME,
    MIN_SCAN_INTERVAL,
    MIN_TIMEOUT,
    STEP_CONSIDER_HOME,
    STEP_SCAN_INTERVAL,
    STEP_TIMEOUT,
    VALUES_CLIENTS_FILTER,
)
from .util import stored_setting

#: The "no default" of a required field, for the callers that decide whether to
#: offer one.
NO_DEFAULT = vol.UNDEFINED


def labels(values: Iterable[str | None]) -> list[str]:
    """Return display names as the str list a selector wants.

    Typing only: the values pass through unchanged.
    """
    return cast("list[str]", list(values))


def _dropdown(options: list[str]) -> SelectSelector:
    """A sorted multi-select dropdown over the given names."""
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
            sort=True,
        )
    )


def _activity_dropdown(options: list[str]) -> SelectSelector:
    """A multi-select dropdown over translated activity names, in their own order."""
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="all",
        )
    )


def _clients_filter() -> SelectSelector:
    """The include/exclude choice for a kind of client."""
    return SelectSelector(
        SelectSelectorConfig(
            options=VALUES_CLIENTS_FILTER,
            translation_key="all",
        )
    )


def login_schema(default: Any = NO_DEFAULT) -> vol.Schema:
    """The account login (an email address or a phone number) to sign in with."""
    return vol.Schema(
        {
            vol.Required(CONF_LOGIN, default=default): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.TEXT,
                )
            ),
        }
    )


def code_schema(default: Any = NO_DEFAULT) -> vol.Schema:
    """The verification code eero sent."""
    return vol.Schema(
        {
            vol.Required(CONF_CODE, default=default): TextSelector(
                TextSelectorConfig(
                    type=TextSelectorType.NUMBER,
                )
            ),
        }
    )


def networks_schema(
    network_names: list[str], default: Sequence[str | None]
) -> vol.Schema:
    """Which of the account's networks to set up."""
    return vol.Schema(
        {vol.Optional(CONF_NETWORKS, default=default): _dropdown(network_names)}
    )


@dataclass
class ResourceDefaults:
    """What the resources form starts out with, by display name."""

    eeros: Sequence[str | None]
    profiles: Sequence[str | None]
    wired_clients: Sequence[str | None]
    wired_clients_filter: str
    wireless_clients: Sequence[str | None]
    wireless_clients_filter: str
    backup_networks: Sequence[str | None] = field(default_factory=list)


def new_resource_defaults(network: EeroNetwork) -> ResourceDefaults:
    """Start a network being set up with every eero, profile and backup network selected."""
    return ResourceDefaults(
        eeros=labels(eero.name for eero in network.eeros),
        profiles=labels(profile.name for profile in network.profiles),
        wired_clients=[],
        wired_clients_filter=DEFAULT_WIRED_CLIENTS_FILTER,
        wireless_clients=[],
        wireless_clients_filter=DEFAULT_WIRELESS_CLIENTS_FILTER,
        backup_networks=(
            labels(backup_network.name for backup_network in network.backup_networks)
            if network.premium_enabled
            else []
        ),
    )


def stored_resource_defaults(
    network: EeroNetwork, stored: Mapping[str, Any]
) -> ResourceDefaults:
    """Start a network with what its entry already selects (`stored`: its resources)."""
    return ResourceDefaults(
        eeros=[
            eero.name for eero in network.eeros if eero.id in stored.get(CONF_EEROS, [])
        ],
        profiles=[
            profile.name
            for profile in network.profiles
            if profile.id in stored.get(CONF_PROFILES, [])
        ],
        wired_clients=[
            client.name_mac
            for client in network.clients
            if client.id in stored.get(CONF_WIRED_CLIENTS, [])
        ],
        wired_clients_filter=stored.get(
            CONF_WIRED_CLIENTS_FILTER, DEFAULT_WIRED_CLIENTS_FILTER
        ),
        wireless_clients=[
            client.name_mac
            for client in network.clients
            if client.id in stored.get(CONF_WIRELESS_CLIENTS, [])
        ],
        wireless_clients_filter=stored.get(
            CONF_WIRELESS_CLIENTS_FILTER, DEFAULT_WIRELESS_CLIENTS_FILTER
        ),
        backup_networks=(
            [
                backup_network.name
                for backup_network in network.backup_networks
                if backup_network.id in stored.get(CONF_BACKUP_NETWORKS, [])
            ]
            if network.premium_enabled
            else []
        ),
    )


def resources_schema(network: EeroNetwork, defaults: ResourceDefaults) -> vol.Schema:
    """Which of a network's eeros, profiles, clients and backup networks to follow."""
    schema = {
        vol.Optional(CONF_EEROS, default=defaults.eeros): _dropdown(
            labels(eero.name for eero in network.eeros)
        ),
        vol.Optional(CONF_PROFILES, default=defaults.profiles): _dropdown(
            labels(profile.name for profile in network.profiles)
        ),
        vol.Optional(CONF_WIRED_CLIENTS, default=defaults.wired_clients): _dropdown(
            labels(client.name_mac for client in network.clients if not client.wireless)
        ),
        vol.Optional(
            CONF_WIRED_CLIENTS_FILTER, default=defaults.wired_clients_filter
        ): _clients_filter(),
        vol.Optional(
            CONF_WIRELESS_CLIENTS, default=defaults.wireless_clients
        ): _dropdown(
            labels(client.name_mac for client in network.clients if client.wireless)
        ),
        vol.Optional(
            CONF_WIRELESS_CLIENTS_FILTER, default=defaults.wireless_clients_filter
        ): _clients_filter(),
    }
    if network.premium_enabled:
        schema[vol.Optional(CONF_BACKUP_NETWORKS, default=defaults.backup_networks)] = (
            _dropdown(
                labels(backup_network.name for backup_network in network.backup_networks)
            )
        )
    return vol.Schema(schema)


def resources_from_input(
    network: EeroNetwork, user_input: dict[str, Any]
) -> dict[str, Any]:
    """The IDs a submitted resources form selected, as the entry stores them."""
    return {
        CONF_BACKUP_NETWORKS: [
            backup_network.id
            for backup_network in network.backup_networks
            if backup_network.name in user_input.get(CONF_BACKUP_NETWORKS, [])
        ],
        CONF_EEROS: [
            eero.id for eero in network.eeros if eero.name in user_input[CONF_EEROS]
        ],
        CONF_PROFILES: [
            profile.id
            for profile in network.profiles
            if profile.name in user_input[CONF_PROFILES]
        ],
        CONF_WIRED_CLIENTS: [
            client.id
            for client in network.clients
            if client.name_mac in user_input[CONF_WIRED_CLIENTS]
        ],
        CONF_WIRED_CLIENTS_FILTER: user_input[CONF_WIRED_CLIENTS_FILTER],
        CONF_WIRELESS_CLIENTS: [
            client.id
            for client in network.clients
            if client.name_mac in user_input[CONF_WIRELESS_CLIENTS]
        ],
        CONF_WIRELESS_CLIENTS_FILTER: user_input[CONF_WIRELESS_CLIENTS_FILTER],
    }


@dataclass
class ActivityDefaults:
    """What the activity form starts out with, per kind of resource."""

    network: list[str] = field(default_factory=list)
    eeros: list[str] = field(default_factory=list)
    profiles: list[str] = field(default_factory=list)
    clients: list[str] = field(default_factory=list)


def stored_activity_defaults(stored: Mapping[str, Any]) -> ActivityDefaults:
    """Start a network with the activity its entry already reads (`stored`: its activity)."""
    return ActivityDefaults(
        network=stored.get(CONF_ACTIVITY_NETWORK, []),
        eeros=stored.get(CONF_ACTIVITY_EEROS, []),
        profiles=stored.get(CONF_ACTIVITY_PROFILES, []),
        clients=stored.get(CONF_ACTIVITY_CLIENTS, []),
    )


def activity_schema(
    network: EeroNetwork, resources: Mapping[str, Any], defaults: ActivityDefaults
) -> vol.Schema:
    """Which activity series to read, for the kinds of resource the network follows."""
    activity_options = ACTIVITIES_DEFAULT
    data_usage_options = ACTIVITIES_DATA_USAGE_DEFAULT
    if network.premium_enabled:
        activity_options = ACTIVITIES_PREMIUM
        data_usage_options = ACTIVITIES_DATA_USAGE_PREMIUM

    schema = {
        vol.Optional(CONF_ACTIVITY_NETWORK, default=defaults.network): (
            _activity_dropdown(activity_options)
        ),
    }
    if resources[CONF_EEROS]:
        schema[vol.Optional(CONF_ACTIVITY_EEROS, default=defaults.eeros)] = (
            _activity_dropdown(data_usage_options)
        )
    if resources[CONF_PROFILES]:
        schema[vol.Optional(CONF_ACTIVITY_PROFILES, default=defaults.profiles)] = (
            _activity_dropdown(activity_options)
        )
    if any([resources[CONF_WIRED_CLIENTS], resources[CONF_WIRELESS_CLIENTS]]):
        schema[vol.Optional(CONF_ACTIVITY_CLIENTS, default=defaults.clients)] = (
            _activity_dropdown(activity_options)
        )
    return vol.Schema(schema)


def activity_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """The activities a submitted activity form selected, as the entry stores them."""
    return {
        CONF_ACTIVITY_NETWORK: user_input[CONF_ACTIVITY_NETWORK],
        CONF_ACTIVITY_EEROS: user_input.get(CONF_ACTIVITY_EEROS, []),
        CONF_ACTIVITY_PROFILES: user_input.get(CONF_ACTIVITY_PROFILES, []),
        CONF_ACTIVITY_CLIENTS: user_input.get(CONF_ACTIVITY_CLIENTS, []),
    }


@dataclass
class MiscellaneousDefaults:
    """What the miscellaneous form starts out with."""

    consider_home: float = DEFAULT_CONSIDER_HOME
    prefix_network_name: bool = DEFAULT_PREFIX_NETWORK_NAME
    suffix_connection_type: bool = DEFAULT_SUFFIX_CONNECTION_TYPE


def stored_miscellaneous_defaults(stored: Mapping[str, Any]) -> MiscellaneousDefaults:
    """Start a network with its entry's choices (`stored`: its miscellaneous settings)."""
    return MiscellaneousDefaults(
        consider_home=stored.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
        prefix_network_name=stored.get(
            CONF_PREFIX_NETWORK_NAME, DEFAULT_PREFIX_NETWORK_NAME
        ),
        suffix_connection_type=stored.get(
            CONF_SUFFIX_CONNECTION_TYPE, DEFAULT_SUFFIX_CONNECTION_TYPE
        ),
    )


def miscellaneous_schema(defaults: MiscellaneousDefaults) -> vol.Schema:
    """The per-network naming and consider-home choices."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_CONSIDER_HOME, default=defaults.consider_home
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_CONSIDER_HOME,
                    max=MAX_CONSIDER_HOME,
                    step=STEP_CONSIDER_HOME,
                    unit_of_measurement=UnitOfTime.MINUTES,
                )
            ),
            vol.Optional(
                CONF_PREFIX_NETWORK_NAME,
                default=defaults.prefix_network_name,
            ): BooleanSelector(),
            vol.Optional(
                CONF_SUFFIX_CONNECTION_TYPE,
                default=defaults.suffix_connection_type,
            ): BooleanSelector(),
        }
    )


def miscellaneous_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """The choices a submitted miscellaneous form made, as the entry stores them."""
    return {
        CONF_CONSIDER_HOME: user_input[CONF_CONSIDER_HOME],
        CONF_PREFIX_NETWORK_NAME: user_input[CONF_PREFIX_NETWORK_NAME],
        CONF_SUFFIX_CONNECTION_TYPE: user_input[CONF_SUFFIX_CONNECTION_TYPE],
    }


@dataclass
class PollingDefaults:
    """What the advanced form starts out with."""

    save_responses: bool = DEFAULT_SAVE_RESPONSES
    scan_interval: float = DEFAULT_SCAN_INTERVAL
    timeout: float = DEFAULT_TIMEOUT


def stored_polling_defaults(
    options: Mapping[str, Any], data: Mapping[str, Any]
) -> PollingDefaults:
    """Start the advanced form with the entry's settings: its options, else its data.

    The polling interval is raised to the floor an older entry may predate; the
    timeout is as stored.
    """
    return PollingDefaults(
        save_responses=stored_setting(
            options, data, CONF_SAVE_RESPONSES, DEFAULT_SAVE_RESPONSES
        ),
        scan_interval=max(
            MIN_SCAN_INTERVAL,
            stored_setting(options, data, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        ),
        timeout=stored_setting(options, data, CONF_TIMEOUT, DEFAULT_TIMEOUT),
    )


def polling_schema(defaults: PollingDefaults) -> vol.Schema:
    """The advanced choices: saving responses, polling interval and request timeout."""
    return vol.Schema(
        {
            vol.Optional(
                CONF_SAVE_RESPONSES, default=defaults.save_responses
            ): BooleanSelector(),
            vol.Optional(
                CONF_SCAN_INTERVAL, default=defaults.scan_interval
            ): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_SCAN_INTERVAL,
                    max=MAX_SCAN_INTERVAL,
                    step=STEP_SCAN_INTERVAL,
                    unit_of_measurement=UnitOfTime.SECONDS,
                )
            ),
            vol.Optional(CONF_TIMEOUT, default=defaults.timeout): NumberSelector(
                NumberSelectorConfig(
                    min=MIN_TIMEOUT,
                    max=MAX_TIMEOUT,
                    step=STEP_TIMEOUT,
                    unit_of_measurement=UnitOfTime.SECONDS,
                )
            ),
        }
    )


def polling_invalid(user_input: dict[str, Any]) -> bool:
    """Whether the polling interval leaves no room for the request timeout."""
    return timedelta(seconds=user_input[CONF_SCAN_INTERVAL]) <= timedelta(
        seconds=user_input[CONF_TIMEOUT]
    )


def polling_from_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """The advanced choices a submitted form made, as the entry stores them."""
    return {
        CONF_SAVE_RESPONSES: user_input[CONF_SAVE_RESPONSES],
        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
        CONF_TIMEOUT: user_input[CONF_TIMEOUT],
    }
