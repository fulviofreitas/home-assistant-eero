"""The Eero integration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import CONF_SCAN_INTERVAL, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    config_validation as cv,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import EeroException, EeroHub, EeroUpdateConfig
from .config_flow import EeroConfigFlow
from .const import (
    ACTIVITIES_PREMIUM,
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
)
from .coordinator import EeroConfigEntry, EeroRuntime
from .device_removal import can_remove_device
from .entity import EeroEntity, EeroEntityDescription
from .services import async_setup_services
from .util import stored_setting

__all__ = ["EeroEntity", "EeroEntityDescription"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.DEVICE_TRACKER,
    Platform.EVENT,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TEXT,
    Platform.TIME,
    Platform.UPDATE,
]

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the integration's actions once, for every entry."""
    async_setup_services(hass)
    return True


def _default_network_resources() -> dict[str, Any]:
    """Return the resources a network has selected before anything is chosen."""
    return {
        CONF_BACKUP_NETWORKS: [],
        CONF_EEROS: [],
        CONF_PROFILES: [],
        CONF_WIRED_CLIENTS: [],
        CONF_WIRED_CLIENTS_FILTER: DEFAULT_WIRED_CLIENTS_FILTER,
        CONF_WIRELESS_CLIENTS: [],
        CONF_WIRELESS_CLIENTS_FILTER: DEFAULT_WIRELESS_CLIENTS_FILTER,
    }


def _was_selected(
    options: dict[str, Any],
    data: dict[str, Any],
    network_id: str,
    conf: str,
    resource_id: str,
) -> bool:
    """Return True if a version 1 entry's settings list the resource as selected."""
    return any(
        [
            resource_id in options.get(conf, data.get(conf, [])),
            resource_id
            in data.get(CONF_RESOURCES, {}).get(network_id, {}).get(conf, []),
            resource_id
            in options.get(CONF_RESOURCES, {}).get(network_id, {}).get(conf, []),
        ]
    )


def _migrate_resources(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    data: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Rebuild the per-network resource selection of a version 1 entry.

    Version 1 kept the selection in flat lists; the devices the entry
    registered, linked to their network's device, say what was selected.
    """
    resources: dict[str, dict[str, Any]] = {}
    for network_id in options.get(CONF_NETWORKS, data.get(CONF_NETWORKS, [])):
        _LOGGER.info("Migrating resources for network: %s", network_id)
        resources[network_id] = _default_network_resources()

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
                # A parent that is gone is skipped; this used to raise.
                if (
                    network_device := device_registry.async_get(network_device_id)
                ) is None:
                    continue
                network_id = list(network_device.identifiers)[0][1]
                network_name = network_device.name
                resource_id = list(device_entry.identifiers)[0][1]
                if _was_selected(options, data, network_id, conf, resource_id):
                    _LOGGER.info(
                        "Migrating resource: %s in network: %s\n- Name: %s\n- Type: %s\n- Network: %s",
                        resource_id,
                        network_id,
                        device_entry.name,
                        device_entry.model,
                        network_name,
                    )
                    resources[network_id][conf].append(resource_id)
    return resources


def _migrate_miscellaneous(
    data: dict[str, Any], options: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """Build the per-network miscellaneous settings from the version 2 flat ones."""
    miscellaneous = {}
    for network_id in options.get(CONF_NETWORKS, data.get(CONF_NETWORKS, [])):
        _LOGGER.info("Migrating miscellaneous options for network: %s", network_id)
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
                data.get(CONF_SUFFIX_CONNECTION_TYPE, DEFAULT_SUFFIX_CONNECTION_TYPE),
            ),
        }
    return miscellaneous


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
            resources = _migrate_resources(hass, config_entry, data, options)
            data[CONF_RESOURCES] = resources
            options[CONF_RESOURCES] = resources

        if config_entry.version <= 2:
            miscellaneous = _migrate_miscellaneous(data, options)
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
    conf_resources: dict[str, Any], conf_activity: dict[str, Any]
) -> dict[str, EeroUpdateConfig]:
    """Work out what each configured network needs fetched."""
    conf_update = {}
    for network_id, resources in conf_resources.items():
        has_clients = any(
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
            eeros=resources[CONF_EEROS],
            get_backup_access_points=bool(resources[CONF_BACKUP_NETWORKS]),
            # Always read: the network's connected/guest client counts and
            # the eeros' client names are computed from this list, and those
            # entities exist whether or not any client entity is configured.
            get_devices=True,
            get_release_notes=bool(resources[CONF_EEROS]),
            # The block switch's state has nothing else to read: gated on
            # client entities being configured, so networks with none never
            # pay for this daily-tier request.
            get_blacklist=has_clients,
            # Bedtime schedules: one read per configured profile.
            get_schedules=bool(resources[CONF_PROFILES]),
            # Per-port sensors/buttons: one connections read per configured
            # eero.
            get_connections=bool(resources[CONF_EEROS]),
        )
    return conf_update


def _option(config_entry: ConfigEntry, key: str, default: Any) -> Any:
    """Return a setting of the entry: its option, else its data, else the default."""
    return stored_setting(config_entry.options, config_entry.data, key, default)


def _scan_interval(config_entry: ConfigEntry) -> Any:
    """Return the polling interval in seconds, never below the floor.

    Clamped: an entry stored before the floor was raised would otherwise
    poll faster than the integration now allows, and would fail validation
    the moment the advanced options form was submitted.
    """
    return max(
        MIN_SCAN_INTERVAL,
        _option(config_entry, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
    )


def _request_timeout(config_entry: ConfigEntry) -> Any:
    """Return the request timeout in seconds, never above the SDK's cap.

    Clamped: eero-api gives every request ClientTimeout(total=30), so a
    longer timeout stored by 1.x could never take effect.
    """
    return min(MAX_TIMEOUT, _option(config_entry, CONF_TIMEOUT, DEFAULT_TIMEOUT))


def _is_stale_client(
    device_entry: dr.DeviceEntry,
    model: str,
    configured: list[tuple[str, str]],
    clients_filter: str,
) -> bool:
    """Return True if a client device of this model is no longer wanted.

    An exclude filter lists the clients to drop, an include filter the ones
    to keep.
    """
    if device_entry.model != model:
        return False
    listed = all(identifier in configured for identifier in device_entry.identifiers)
    unlisted = all(
        identifier not in configured for identifier in device_entry.identifiers
    )
    return (listed and clients_filter == CONF_FILTER_EXCLUDE) or (
        unlisted and clients_filter == CONF_FILTER_INCLUDE
    )


def _is_stale_device(
    device_entry: dr.DeviceEntry, network_id: str, resources: dict[str, Any]
) -> bool:
    """Return True if a registered device is no longer wanted for the network."""
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
        (DOMAIN, resource_id) for resource_id in resources[CONF_WIRELESS_CLIENTS]
    ]
    return any(
        [
            all(
                [
                    device_entry.model not in [MODEL_CLIENT_WIRED, MODEL_CLIENT_WIRELESS],
                    all(
                        bool(identifier not in conf_identifiers)
                        for identifier in device_entry.identifiers
                    ),
                ]
            ),
            _is_stale_client(
                device_entry,
                MODEL_CLIENT_WIRED,
                conf_wired_client_identifiers,
                resources[CONF_WIRED_CLIENTS_FILTER],
            ),
            _is_stale_client(
                device_entry,
                MODEL_CLIENT_WIRELESS,
                conf_wireless_client_identifiers,
                resources[CONF_WIRELESS_CLIENTS_FILTER],
            ),
        ]
    )


def _remove_device(
    device_registry: dr.DeviceRegistry, device_entry: dr.DeviceEntry
) -> None:
    """Remove a device the entry no longer configures."""
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
        _LOGGER.debug("Device entry %s was already removed", device_entry.id)


def _remove_unselected_activity_entities(
    entity_registry: er.EntityRegistry,
    device_entry: dr.DeviceEntry,
    conf_activity: dict[str, Any],
) -> None:
    """Remove the device's premium activity entities that are no longer selected."""
    for entity_entry in er.async_entries_for_device(entity_registry, device_entry.id):
        unique_id = entity_entry.unique_id.split("-")
        activity = conf_activity.get(unique_id[0], {})
        if all(
            [
                unique_id[-1] in ACTIVITIES_PREMIUM,
                any(
                    [
                        device_entry.model == MODEL_NETWORK
                        and unique_id[-1] not in activity.get(CONF_ACTIVITY_NETWORK, []),
                        MANUFACTURER in (device_entry.model or "")
                        and unique_id[-1] not in activity.get(CONF_ACTIVITY_EEROS, []),
                        device_entry.model == MODEL_PROFILE
                        and unique_id[-1]
                        not in activity.get(CONF_ACTIVITY_PROFILES, []),
                        device_entry.model in [MODEL_CLIENT_WIRED, MODEL_CLIENT_WIRELESS]
                        and unique_id[-1] not in activity.get(CONF_ACTIVITY_CLIENTS, []),
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


def _prune_registries(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    conf_resources: dict[str, Any],
    conf_activity: dict[str, Any],
) -> None:
    """Drop the devices and the activity entities the entry no longer configures."""
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
            if _is_stale_device(device_entry, network_id, resources):
                _remove_device(device_registry, device_entry)
            else:
                _remove_unselected_activity_entities(
                    entity_registry, device_entry, conf_activity
                )


def _warn_consider_home(
    runtime: EeroRuntime, conf_miscellaneous: dict[str, Any], conf_scan_interval: Any
) -> None:
    """Warn about a consider-home interval that polling would make meaningless."""
    for network in runtime.account.networks:
        if conf_miscellaneous_network := conf_miscellaneous.get(network.known_id):
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


def _register_network_devices(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    runtime: EeroRuntime,
    conf_networks: list[str],
) -> None:
    """Register the device of every configured network."""
    device_registry = dr.async_get(hass)
    for network in runtime.account.networks:
        if network.id in conf_networks:
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, network.known_id)},
                manufacturer=MANUFACTURER,
                name=network.name,
                model=MODEL_NETWORK,
            )


async def async_setup_entry(hass: HomeAssistant, config_entry: EeroConfigEntry) -> bool:
    """Set up a config entry."""
    conf_networks = _option(config_entry, CONF_NETWORKS, [])
    conf_resources = _option(config_entry, CONF_RESOURCES, {})
    conf_activity = _option(config_entry, CONF_ACTIVITY, {})
    conf_miscellaneous = _option(config_entry, CONF_MISCELLANEOUS, {})
    conf_save_responses = _option(
        config_entry, CONF_SAVE_RESPONSES, DEFAULT_SAVE_RESPONSES
    )
    conf_scan_interval = _scan_interval(config_entry)
    conf_timeout = _request_timeout(config_entry)

    _prune_registries(hass, config_entry, conf_resources, conf_activity)

    hub = EeroHub(
        session=async_get_clientsession(hass),
        save_location=hass.config.path(".storage", DEFAULT_SAVE_DIRECTORY)
        if conf_save_responses
        else None,
        request_timeout=conf_timeout,
    )
    try:
        await hub.async_set_token(config_entry.data[CONF_USER_TOKEN])
    except (KeyError, EeroException) as error:
        # No token stored, or one the SDK rejects as a header value.
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from error

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
    _warn_consider_home(runtime, conf_miscellaneous, conf_scan_interval)

    config_entry.runtime_data = runtime
    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))
    _register_network_devices(hass, config_entry, runtime, conf_networks)

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
