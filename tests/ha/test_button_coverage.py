"""Coverage for EeroButtonEntity.async_press and the per-port action button."""

from __future__ import annotations

from custom_components.eero.const import (
    CONF_BACKUP_NETWORKS,
    CONF_EEROS,
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

from conftest import NETWORK_ID, entry_data, network_envelope


def eero_entry_data() -> dict:
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: ["e1"],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources})


def make_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=eero_entry_data(),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_network_reboot_button_press_calls_the_sdk(hass, sdk_factory) -> None:
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6"}
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "eeros.get_connections": {},
            "networks.reboot_network": {},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("button", DOMAIN, f"{NETWORK_ID}-reboot")
    assert entity_id is not None

    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )

    assert any(d == "networks" and m == "reboot_network" for d, m, _a, _kw in sdk.calls)


async def test_port_action_button_press_calls_port_action_and_refreshes(
    hass, sdk_factory
) -> None:
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6"}
    connections = {
        "ports": {
            "interfaces": [
                {
                    "interface_number": 1,
                    "connection_status": "CONNECTED",
                    "negotiated_speed": "P1000",
                    "actions": [{"position": 0, "type": "RESTART_POWER"}],
                }
            ]
        }
    }
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "eeros.get_connections": connections,
            "eeros.port_action": {},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{NETWORK_ID}-e1-port_1_action_restart_power"
    )
    assert button_id is not None
    # Disabled by default (disruptive, unconfirmed write): enable it, then
    # reload so the entity actually gets a state, before pressing it.
    registry.async_update_entity(button_id, disabled_by=None)
    await hass.async_block_till_done()
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "button", "press", {"entity_id": button_id}, blocking=True
    )

    assert ("eeros", "port_action", ("e1", "1", "RESTART_POWER"), {}) in sdk.calls
