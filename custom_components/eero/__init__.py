"""The Eero integration."""

from __future__ import annotations

from datetime import timedelta
import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EeroAuthenticationException, EeroException, EeroHub, EeroUpdateConfig
from .api.const import SUPPORTED_APPS
from .config_flow import EeroConfigFlow
from .const import (
    ACTIVITIES_PREMIUM,
    ATTR_BLOCKED_APPS,
    ATTR_TARGET_NETWORK,
    ATTR_TARGET_PROFILE,
    CONF_ACTIVITY,
    CONF_ACTIVITY_CLIENTS,
    CONF_ACTIVITY_EEROS,
    CONF_ACTIVITY_NETWORK,
    CONF_ACTIVITY_PROFILES,
    CONF_BACKUP_NETWORKS,
    CONF_CONSIDER_HOME,
    CONF_EEROS,
    CONF_FILTER_EXCLUDE,
    CONF_FILTER_INCLUDE,
    CONF_MISCELLANEOUS,
    CONF_NETWORKS,
    CONF_PREFIX_NETWORK_NAME,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_SAVE_RESPONSES,
    CONF_SUFFIX_CONNECTION_TYPE,
    CONF_TIMEOUT,
    CONF_USER_TOKEN,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DEFAULT_CONSIDER_HOME,
    DEFAULT_PREFIX_NETWORK_NAME,
    DEFAULT_SAVE_DIRECTORY,
    DEFAULT_SAVE_RESPONSES,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SUFFIX_CONNECTION_TYPE,
    DEFAULT_TIMEOUT,
    DEFAULT_WIRED_CLIENTS_FILTER,
    DEFAULT_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
    MANUFACTURER,
    MAX_TIMEOUT,
    MIN_SCAN_INTERVAL,
    MODEL_CLIENT_WIRED,
    MODEL_CLIENT_WIRELESS,
    MODEL_NETWORK,
    MODEL_PROFILE,
    SERVICE_SET_BLOCKED_APPS,
    TIER_FAST,
)
from .coordinator import EeroConfigEntry, EeroRuntime
from .device_removal import can_remove_device
from .entity import EeroEntity, EeroEntityDescription

__all__ = ["EeroEntity", "EeroEntityDescription"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SET_BLOCKED_APPS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BLOCKED_APPS): vol.All(
            cv.ensure_list, [vol.In(SUPPORTED_APPS.keys())]
        ),
        vol.Optional(ATTR_TARGET_PROFILE, default=[]): vol.All(
            cv.ensure_list, [vol.Any(cv.positive_int, cv.string)]
        ),
        vol.Optional(ATTR_TARGET_NETWORK, default=[]): vol.All(
            cv.ensure_list, [vol.Any(cv.positive_int, cv.string)]
        ),
    }
)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
    Platform.UPDATE,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions once, for every entry."""

    async def async_set_blocked_apps(service: ServiceCall) -> None:
        blocked_apps = service.data[ATTR_BLOCKED_APPS]
        target_profile = service.data[ATTR_TARGET_PROFILE]
        target_network = service.data[ATTR_TARGET_NETWORK]
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
                    if profile.id not in runtime.resources[network.id][CONF_PROFILES]:
                        continue
                    if target_profile and not (
                        profile.id in target_profile or profile.name in target_profile
                    ):
                        continue
                    try:
                        await profile.async_set_blocked_applications(blocked_apps)
                    except EeroAuthenticationException as error:
                        entry.async_start_reauth(hass)
                        raise HomeAssistantError(
                            translation_domain=DOMAIN, translation_key="auth_failed"
                        ) from error
                    except (EeroException, TimeoutError) as error:
                        raise HomeAssistantError(
                            translation_domain=DOMAIN,
                            translation_key="api_error",
                            translation_placeholders={"error": str(error)},
                        ) from error
            await runtime.coordinator(TIER_FAST).async_request_refresh()

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_BLOCKED_APPS,
        async_set_blocked_apps,
        schema=SET_BLOCKED_APPS_SCHEMA,
    )
    return True



async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    if config_entry.version > EeroConfigFlow.VERSION:
        return False

    _LOGGER.info(
        "Migrating configuration from version: %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version < EeroConfigFlow.VERSION:
        data = dict(config_entry.data)
        _LOGGER.debug("Initial data keys: %s", sorted(data))

        options = dict(config_entry.options)
        _LOGGER.debug("Initial options:\n%s", options)

        if config_entry.version <= 1:
            resources = {}
            for network_id in options.get(CONF_NETWORKS, data.get(CONF_NETWORKS, [])):
                _LOGGER.info("Migrating resources for network: %s", network_id)
                resources[network_id] = {
                    CONF_BACKUP_NETWORKS: [],
                    CONF_EEROS: [],
                    CONF_PROFILES: [],
                    CONF_WIRED_CLIENTS: [],
                    CONF_WIRED_CLIENTS_FILTER: DEFAULT_WIRED_CLIENTS_FILTER,
                    CONF_WIRELESS_CLIENTS: [],
                    CONF_WIRELESS_CLIENTS_FILTER: DEFAULT_WIRELESS_CLIENTS_FILTER,
                }

            device_registry = dr.async_get(hass)
            for conf in [
                CONF_BACKUP_NETWORKS,
                CONF_EEROS,
                CONF_PROFILES,
                CONF_WIRED_CLIENTS,
                CONF_WIRELESS_CLIENTS,
            ]:
                for device_entry in dr.async_entries_for_config_entry(
                    device_registry, config_entry.entry_id
                ):
                    if network_device_id := device_entry.via_device_id:
                        network_id = list(
                            device_registry.async_get(network_device_id).identifiers
                        )[0][1]
                        network_name = device_registry.async_get(network_device_id).name
                        resource_id = list(device_entry.identifiers)[0][1]
                        if any(
                            [
                                resource_id in options.get(conf, data.get(conf, [])),
                                resource_id
                                in data.get(CONF_RESOURCES, {})
                                .get(network_id, {})
                                .get(conf, []),
                                resource_id
                                in options.get(CONF_RESOURCES, {})
                                .get(network_id, {})
                                .get(conf, []),
                            ]
                        ):
                            _LOGGER.info(
                                "Migrating resource: %s in network: %s\n- Name: %s\n- Type: %s\n- Network: %s",
                                resource_id,
                                network_id,
                                device_entry.name,
                                device_entry.model,
                                network_name,
                            )
                            resources[network_id][conf].append(resource_id)

            data[CONF_RESOURCES] = resources
            options[CONF_RESOURCES] = resources

        if config_entry.version <= 2:
            miscellaneous = {}
            for network_id in options.get(CONF_NETWORKS, data.get(CONF_NETWORKS, [])):
                _LOGGER.info(
                    "Migrating miscellaneous options for network: %s", network_id
                )
                miscellaneous[network_id] = {
                    CONF_CONSIDER_HOME: options.get(
                        CONF_CONSIDER_HOME,
                        data.get(CONF_CONSIDER_HOME, DEFAULT_CONSIDER_HOME),
                    ),
                    CONF_PREFIX_NETWORK_NAME: options.get(
                        CONF_PREFIX_NETWORK_NAME,
                        data.get(CONF_PREFIX_NETWORK_NAME, DEFAULT_PREFIX_NETWORK_NAME),
                    ),
                    CONF_SUFFIX_CONNECTION_TYPE: options.get(
                        CONF_SUFFIX_CONNECTION_TYPE,
                        data.get(
                            CONF_SUFFIX_CONNECTION_TYPE, DEFAULT_SUFFIX_CONNECTION_TYPE
                        ),
                    ),
                }

            data[CONF_MISCELLANEOUS] = miscellaneous
            options[CONF_MISCELLANEOUS] = miscellaneous

        _LOGGER.debug("Migrated data keys: %s", sorted(data))
        _LOGGER.debug("Migrated options:\n%s", options)

        hass.config_entries.async_update_entry(
            entry=config_entry,
            data=data,
            options=options,
            version=EeroConfigFlow.VERSION,
            minor_version=EeroConfigFlow.MINOR_VERSION,
        )

    _LOGGER.info(
        "Successfully migrated configuration to version: %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    return True


def _update_config(
    conf_resources: dict, conf_activity: dict
) -> dict[str, EeroUpdateConfig]:
    """Work out what each configured network needs fetched."""
    conf_update = {}
    for network_id, resources in conf_resources.items():
        get_devices = any(
            [
                resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_EXCLUDE,
                resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_INCLUDE
                and bool(resources[CONF_WIRED_CLIENTS]),
                resources[CONF_WIRELESS_CLIENTS_FILTER] == CONF_FILTER_EXCLUDE,
                resources[CONF_WIRELESS_CLIENTS_FILTER] == CONF_FILTER_INCLUDE
                and bool(resources[CONF_WIRELESS_CLIENTS]),
            ]
        )
        conf_update[network_id] = EeroUpdateConfig(
            activity=conf_activity.get(network_id, {}),
            profiles=resources[CONF_PROFILES],
            get_backup_access_points=bool(resources[CONF_BACKUP_NETWORKS]),
            get_devices=get_devices,
            get_release_notes=bool(resources[CONF_EEROS]),
            # The block switch's state has nothing else to read: gated on
            # the same condition as get_devices, so networks with no client
            # entities configured never pay for this daily-tier request.
            get_blacklist=get_devices,
        )
    return conf_update


async def async_setup_entry(hass: HomeAssistant, config_entry: EeroConfigEntry) -> bool:
    """Set up a config entry."""
    data = config_entry.data
    options = config_entry.options

    conf_networks = options.get(CONF_NETWORKS, data.get(CONF_NETWORKS, []))
    conf_resources = options.get(CONF_RESOURCES, data.get(CONF_RESOURCES, {}))
    conf_activity = options.get(CONF_ACTIVITY, data.get(CONF_ACTIVITY, {}))
    conf_miscellaneous = options.get(
        CONF_MISCELLANEOUS, data.get(CONF_MISCELLANEOUS, {})
    )
    conf_save_responses = options.get(
        CONF_SAVE_RESPONSES, data.get(CONF_SAVE_RESPONSES, DEFAULT_SAVE_RESPONSES)
    )
    # Clamped: an entry stored before the floor was raised would otherwise
    # poll faster than the integration now allows, and would fail validation
    # the moment the advanced options form was submitted.
    conf_scan_interval = max(
        MIN_SCAN_INTERVAL,
        options.get(
            CONF_SCAN_INTERVAL, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        ),
    )
    # Clamped too: eero-api gives every request ClientTimeout(total=30), so a
    # longer timeout stored by 1.x could never take effect.
    conf_timeout = min(
        MAX_TIMEOUT, options.get(CONF_TIMEOUT, data.get(CONF_TIMEOUT, DEFAULT_TIMEOUT))
    )

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    for device_entry in dr.async_entries_for_config_entry(
        device_registry, config_entry.entry_id
    ):
        _LOGGER.debug(
            "Checking entries for device: %s - %s",
            device_entry.name,
            device_entry.model,
        )
        for network_id, resources in conf_resources.items():
            conf_identifiers = [
                (DOMAIN, resource_id)
                for resource_id in [network_id]
                + resources[CONF_BACKUP_NETWORKS]
                + resources[CONF_EEROS]
                + resources[CONF_PROFILES]
            ]
            conf_wired_client_identifiers = [
                (DOMAIN, resource_id) for resource_id in resources[CONF_WIRED_CLIENTS]
            ]
            conf_wireless_client_identifiers = [
                (DOMAIN, resource_id)
                for resource_id in resources[CONF_WIRELESS_CLIENTS]
            ]

            if any(
                [
                    all(
                        [
                            device_entry.model
                            not in [MODEL_CLIENT_WIRED, MODEL_CLIENT_WIRELESS],
                            all(
                                bool(identifier not in conf_identifiers)
                                for identifier in device_entry.identifiers
                            ),
                        ]
                    ),
                    all(
                        [
                            device_entry.model == MODEL_CLIENT_WIRED,
                            all(
                                bool(identifier in conf_wired_client_identifiers)
                                for identifier in device_entry.identifiers
                            ),
                            resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_EXCLUDE,
                        ]
                    ),
                    all(
                        [
                            device_entry.model == MODEL_CLIENT_WIRED,
                            all(
                                bool(identifier not in conf_wired_client_identifiers)
                                for identifier in device_entry.identifiers
                            ),
                            resources[CONF_WIRED_CLIENTS_FILTER] == CONF_FILTER_INCLUDE,
                        ]
                    ),
                    all(
                        [
                            device_entry.model == MODEL_CLIENT_WIRELESS,
                            all(
                                bool(identifier in conf_wireless_client_identifiers)
                                for identifier in device_entry.identifiers
                            ),
                            resources[CONF_WIRELESS_CLIENTS_FILTER]
                            == CONF_FILTER_EXCLUDE,
                        ]
                    ),
                    all(
                        [
                            device_entry.model == MODEL_CLIENT_WIRELESS,
                            all(
                                bool(identifier not in conf_wireless_client_identifiers)
                                for identifier in device_entry.identifiers
                            ),
                            resources[CONF_WIRELESS_CLIENTS_FILTER]
                            == CONF_FILTER_INCLUDE,
                        ]
                    ),
                ]
            ):
                _LOGGER.debug(
                    "Removing device entry: %s - %s",
                    device_entry.name,
                    device_entry.model,
                )
                try:
                    device_registry.async_remove_device(device_entry.id)
                except KeyError:
                    # This loop iterates a snapshot of the registry, so a device
                    # already removed as a side effect of removing its
                    # via_device parent is reached a second time.
                    _LOGGER.debug(
                        "Device entry %s was already removed", device_entry.id
                    )
            else:
                for entity_entry in er.async_entries_for_device(
                    entity_registry, device_entry.id
                ):
                    unique_id = entity_entry.unique_id.split("-")
                    activity = conf_activity.get(unique_id[0], {})
                    if all(
                        [
                            unique_id[-1] in ACTIVITIES_PREMIUM,
                            any(
                                [
                                    device_entry.model == MODEL_NETWORK
                                    and unique_id[-1]
                                    not in activity.get(CONF_ACTIVITY_NETWORK, []),
                                    MANUFACTURER in device_entry.model
                                    and unique_id[-1]
                                    not in activity.get(CONF_ACTIVITY_EEROS, []),
                                    device_entry.model == MODEL_PROFILE
                                    and unique_id[-1]
                                    not in activity.get(CONF_ACTIVITY_PROFILES, []),
                                    device_entry.model
                                    in [MODEL_CLIENT_WIRED, MODEL_CLIENT_WIRELESS]
                                    and unique_id[-1]
                                    not in activity.get(CONF_ACTIVITY_CLIENTS, []),
                                ]
                            ),
                        ]
                    ):
                        _LOGGER.debug(
                            "Removing entity: %s from device entry: %s - %s",
                            entity_entry.name,
                            device_entry.name,
                            device_entry.model,
                        )
                        entity_registry.async_remove(entity_entry.entity_id)

    hub = EeroHub(
        session=async_get_clientsession(hass),
        save_location=hass.config.path(".storage", DEFAULT_SAVE_DIRECTORY)
        if conf_save_responses
        else None,
        request_timeout=conf_timeout,
    )
    await hub.async_set_token(data[CONF_USER_TOKEN])

    runtime = EeroRuntime(
        hass=hass,
        entry=config_entry,
        hub=hub,
        update_config=_update_config(conf_resources, conf_activity),
        networks=conf_networks,
        resources=conf_resources,
        activity=conf_activity,
        miscellaneous=conf_miscellaneous,
        options=dict(config_entry.options),
    )
    runtime.setup_coordinators(timedelta(seconds=conf_scan_interval))
    await runtime.async_first_refresh()

    for network in runtime.account.networks:
        if conf_miscellaneous_network := conf_miscellaneous.get(network.id):
            conf_consider_home = conf_miscellaneous_network[CONF_CONSIDER_HOME]
            if conf_consider_home and timedelta(
                minutes=conf_consider_home
            ) <= timedelta(seconds=conf_scan_interval):
                _LOGGER.info(
                    "For network: %s - Consider home interval, %s minute(s), should be set larger than polling interval, %s seconds, otherwise it has no functionality",
                    network.name_unique,
                    int(conf_consider_home),
                    int(conf_scan_interval),
                )

    config_entry.runtime_data = runtime
    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))

    for network in runtime.account.networks:
        if network.id in conf_networks:
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, network.id)},
                manufacturer=MANUFACTURER,
                name=network.name,
                model=MODEL_NETWORK,
            )

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: EeroConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Let Home Assistant delete a client device from its device page.

    Without this hook the delete button is refused ("Config entry does not
    support device removal"), and dead clients (a box whose wifi was turned
    off, a phone that never came back) stay forever with their 8 entities each,
    logged by the recorder every poll. The rule itself is in device_removal.py.
    """
    if config_entry.state is not ConfigEntryState.LOADED:
        return False
    connected: set[str] = set()
    for network in config_entry.runtime_data.account.networks:
        for client in network.clients:
            if client is not None and client.connected and client.id:
                connected.add(client.id)
    return can_remove_device(
        device_entry.model,
        device_entry.identifiers,
        DOMAIN,
        (MODEL_CLIENT_WIRED, MODEL_CLIENT_WIRELESS),
        connected,
    )


async def async_unload_entry(hass: HomeAssistant, config_entry: EeroConfigEntry) -> bool:
    """Unload a config entry.

    The aiohttp session is Home Assistant's shared one: it is not ours to close.
    """
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    if unload_ok:
        config_entry.runtime_data.clear_issues()
    return unload_ok


async def async_update_listener(hass: HomeAssistant, config_entry: EeroConfigEntry) -> None:
    """Reload when the options change, or when a new session arrives from a flow.

    Home Assistant fires update listeners on any change to the entry, data
    included, and a session token the integration persists itself is written
    back to the entry data. Rebuilding every entity in the house for that would
    reset the device trackers' consider_home clocks. The token this integration
    persisted itself is the one the running hub already holds, so it is the one
    change that needs no reload; a token that arrived from the reauth flow does
    not match, and does.
    """
    if config_entry.state is not ConfigEntryState.LOADED:
        return
    runtime: EeroRuntime = config_entry.runtime_data
    if (
        dict(config_entry.options) == runtime.options
        and config_entry.data.get(CONF_USER_TOKEN) == runtime.hub.user_token
    ):
        return
    await hass.config_entries.async_reload(config_entry.entry_id)
