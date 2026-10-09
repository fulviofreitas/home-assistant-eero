"""Coverage for custom_components/eero/__init__.py paths test_init_ha.py misses:
migration, the set_blocked_apps service, config-entry-device removal, the
device/entity cleanup loop, the consider_home warning, and a missing token.
"""

from __future__ import annotations

import logging

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero import async_migrate_entry, async_remove_config_entry_device
from custom_components.eero.const import (
    CONF_ACTIVITY,
    CONF_BACKUP_NETWORKS,
    CONF_CONSIDER_HOME,
    CONF_EEROS,
    CONF_FILTER_INCLUDE,
    CONF_MISCELLANEOUS,
    CONF_NETWORKS,
    CONF_PREFIX_NETWORK_NAME,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_SUFFIX_CONNECTION_TYPE,
    CONF_USER_TOKEN,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
    MODEL_CLIENT_WIRED,
    MODEL_NETWORK,
)

from conftest import NETWORK_ID, NETWORK_URL, entry_data, network_envelope


def make_entry(hass, **data_overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=entry_data(**data_overrides),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_migrate_entry_from_version_1_builds_resources_and_miscellaneous(
    hass,
) -> None:
    """A VERSION 1 entry gains CONF_RESOURCES and CONF_MISCELLANEOUS, bumped to VERSION 3."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=1,
        minor_version=0,
        data={CONF_USER_TOKEN: "OLD-TOKEN", CONF_NETWORKS: [NETWORK_ID]},
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 3
    assert NETWORK_ID in entry.data[CONF_RESOURCES]
    resources = entry.data[CONF_RESOURCES][NETWORK_ID]
    assert resources[CONF_BACKUP_NETWORKS] == []
    assert resources[CONF_EEROS] == []
    assert NETWORK_ID in entry.data[CONF_MISCELLANEOUS]
    miscellaneous = entry.data[CONF_MISCELLANEOUS][NETWORK_ID]
    assert CONF_CONSIDER_HOME in miscellaneous
    assert CONF_PREFIX_NETWORK_NAME in miscellaneous
    assert CONF_SUFFIX_CONNECTION_TYPE in miscellaneous


async def test_migrate_entry_from_version_2_only_adds_miscellaneous(hass) -> None:
    """A VERSION 2 entry (resources already migrated) only gains CONF_MISCELLANEOUS."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        minor_version=0,
        data={
            CONF_USER_TOKEN: "OLD-TOKEN",
            CONF_NETWORKS: [NETWORK_ID],
            CONF_RESOURCES: resources,
        },
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == 3
    assert NETWORK_ID in entry.data[CONF_MISCELLANEOUS]


async def test_migrate_entry_already_current_is_a_noop(hass) -> None:
    entry = make_entry(hass)
    assert await async_migrate_entry(hass, entry)
    assert entry.version == 3


async def test_migrate_entry_future_version_refuses(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=99,
        minor_version=0,
        data={CONF_USER_TOKEN: "OLD-TOKEN"},
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)

    assert not await async_migrate_entry(hass, entry)


def profile_entry_data(**overrides) -> dict:
    """Entry data with one configured profile."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: ["p1"],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, **overrides})


async def test_set_blocked_apps_service_calls_the_sdk_for_the_matching_profile(
    hass, sdk_factory
) -> None:
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(
                resources={
                    "settings": f"{NETWORK_URL}/settings",
                    "profiles": f"{NETWORK_URL}/profiles",
                },
            ),
            "profiles.get_profiles": [{"url": f"{NETWORK_URL}/profiles/p1", "name": "Kids"}],
            "dns_policies.set_profile_blocked_applications": {},
        }
    )
    entry = make_entry(hass, **profile_entry_data())

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "set_blocked_apps",
        {
            "blocked_apps": ["netflix"],
            "target_profile": ["Kids"],
            "target_network": [],
        },
        blocking=True,
    )

    assert any(
        d == "dns_policies" and m == "set_profile_blocked_applications"
        for d, m, _a, _kw in sdk.calls
    )


async def test_remove_config_entry_device_refuses_a_connected_client(hass, sdk_factory) -> None:
    from homeassistant.helpers import device_registry as dr

    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "devices.get_devices": [
                {
                    "url": f"{NETWORK_URL}/devices/aa",
                    "mac": "aa",
                    "connected": True,
                    "wireless": False,
                }
            ],
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass, **client_entry_data_with_device())

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    device_entry = registry.async_get_device_by_identifier((DOMAIN, "aa"), entry.entry_id)
    assert device_entry is not None

    allowed = await async_remove_config_entry_device(hass, entry, device_entry)
    assert allowed is False


def client_entry_data_with_device() -> dict:
    from custom_components.eero.const import CONF_FILTER_EXCLUDE

    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources})


async def test_setup_entry_raises_auth_failed_when_token_missing(hass, sdk_factory) -> None:
    from homeassistant.config_entries import ConfigEntryState

    sdk_factory()
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data={k: v for k, v in entry_data().items() if k != CONF_USER_TOKEN},
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR


async def test_consider_home_warning_logged_when_not_larger_than_scan_interval(
    hass, sdk_factory, caplog
) -> None:
    sdk_factory()
    entry = make_entry(hass)
    # consider_home (minutes) resolves to 1 minute = 60s, same as the
    # default scan interval -> triggers the "no functionality" warning.
    entry.data[CONF_MISCELLANEOUS][NETWORK_ID][CONF_CONSIDER_HOME] = 1

    with caplog.at_level(logging.INFO):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert "should be set larger than polling interval" in caplog.text


async def test_device_cleanup_removes_a_device_no_longer_configured(hass, sdk_factory) -> None:
    """A device entry for a backup network no longer in CONF_RESOURCES is removed."""
    from homeassistant.helpers import device_registry as dr

    sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = dr.async_get(hass)
    stray = registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "stray-backup-network")},
        manufacturer="eero",
        name="Stray",
        model="Backup Network",
    )
    assert registry.async_get(stray.id) is not None

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get(stray.id) is None
