"""Coverage for EeroBinarySensorEntity's extra_state_attributes branches."""

from __future__ import annotations

from custom_components.eero.const import (
    CONF_BACKUP_NETWORKS,
    CONF_EEROS,
    CONF_FILTER_EXCLUDE,
    CONF_FILTER_INCLUDE,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
)
from pytest_homeassistant_custom_component.common import MockConfigEntry

from conftest import NETWORK_ID, NETWORK_URL, entry_data, network_envelope


def wireless_client_entry_data() -> dict:
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources})


def make_entry(hass, **data_overrides) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=data_overrides or wireless_client_entry_data(),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_connected_binary_sensor_reports_wireless_only_attrs(hass, sdk_factory) -> None:
    mac = "aa:bb:cc:dd:ee:ff"
    device = {
        "url": f"{NETWORK_URL}/devices/{mac}",
        "mac": mac,
        "wireless": True,
        "nickname": "TestClient",
        "connected": True,
        "channel": 36,
        "connectivity": {
            "rx_rate_info": {"channel_width": "40MHz"},
            "tx_rate_info": {"channel_width": "80MHz"},
        },
        "interface": {"frequency": 5, "frequency_unit": "GHz"},
    }
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [device],
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{NETWORK_ID}-{mac}-connected"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "on"
    assert state.attributes["bandwidth_receive"] == "40MHz"
    assert state.attributes["bandwidth_transmit"] == "80MHz"
    assert state.attributes["channel"] == 36
    assert state.attributes["operating_band"] == "5 GHz"
