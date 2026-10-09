"""Entity names come from strings.json and match the names used before translations."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
from string import Formatter
from typing import Any

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.typing import UNDEFINED
from pytest_homeassistant_custom_component.common import MockConfigEntry
import pytest

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
from custom_components.eero.entity import EeroEntityDescription

from conftest import NETWORK_ID, entry_data, network_envelope

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / DOMAIN
PLATFORMS = (
    "binary_sensor",
    "button",
    "device_tracker",
    "event",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
    "text",
    "time",
    "update",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


STRINGS = _load(COMPONENT / "strings.json")


def _descriptions(platform: str) -> list[Any]:
    """Every entity description a platform module defines at module level."""
    module = importlib.import_module(f"custom_components.{DOMAIN}.{platform}")
    found = []
    for value in vars(module).values():
        if isinstance(value, (list, tuple)):
            found.extend(
                item
                for item in value
                if hasattr(item, "key") and hasattr(item, "translation_key")
            )
    return found


def _placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(text) if name}


def _structure(value: Any, path: str = "") -> dict[str, set[str]]:
    """Flatten a translation dict to {dotted key: placeholders in its string}."""
    if isinstance(value, dict):
        flat: dict[str, set[str]] = {}
        for key, item in value.items():
            flat.update(_structure(item, f"{path}.{key}" if path else key))
        return flat
    return {path: _placeholders(value)}


@pytest.mark.parametrize("platform", PLATFORMS)
def test_every_description_names_itself_through_strings_json(platform: str) -> None:
    """No literal names or icons; every translation_key exists in strings.json."""
    descriptions = _descriptions(platform)
    assert descriptions, platform
    translations = STRINGS["entity"].get(platform, {})
    for description in descriptions:
        assert description.name is UNDEFINED, (
            f"{platform}.{description.key} still sets a literal name"
        )
        assert description.icon is None, f"{platform}.{description.key} sets icon="
        if platform == "device_tracker":
            # Named after its device alone: "all" carries only attributes.
            assert description.translation_key == "all"
            assert "name" not in translations["all"]
            continue
        assert description.translation_key != "all", (platform, description.key)
        entry = translations.get(description.translation_key)
        assert entry is not None, f"{platform}.{description.translation_key}"
        assert entry.get("name"), f"{platform}.{description.translation_key}"


def test_no_description_sets_a_literal_name() -> None:
    """Checked at the source level too: an EntityDescription name= kwarg is gone."""
    for platform in PLATFORMS:
        source = (COMPONENT / f"{platform}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s+name=\"", source, re.MULTILINE), platform


def test_every_entity_translation_is_used() -> None:
    """strings.json has no entity names that no description or port entity uses."""
    used: dict[str, set[str]] = {}
    for platform in PLATFORMS:
        used[platform] = {d.translation_key for d in _descriptions(platform)}
    # Port action buttons build their key from the action at runtime.
    from custom_components.eero.api.const import PORT_ACTIONS

    used["button"] |= {f"port_action_{action.lower()}" for action in PORT_ACTIONS}
    for platform, keys in STRINGS["entity"].items():
        assert set(keys) == used[platform], platform


def test_en_matches_strings_and_pt_br_matches_its_structure() -> None:
    """en.json is strings.json; pt-BR has the same keys and the same placeholders."""
    assert _load(COMPONENT / "translations" / "en.json") == STRINGS
    expected = _structure(STRINGS)
    actual = _structure(_load(COMPONENT / "translations" / "pt-BR.json"))
    assert actual.keys() == expected.keys()
    for key, placeholders in expected.items():
        assert actual[key] == placeholders, key


def test_icons_json_only_names_translation_keys_in_strings_json() -> None:
    """Every entity icon is keyed by a translation_key strings.json defines."""
    icons = _load(COMPONENT / "icons.json")
    for platform, keys in icons["entity"].items():
        assert set(keys) <= set(STRINGS["entity"][platform]), platform


def test_port_entity_names_carry_the_port_number_placeholder() -> None:
    """Port names use {port_number}, which EeroPortEntity always supplies."""
    for platform in ("sensor", "button"):
        for key, entry in STRINGS["entity"][platform].items():
            if key.startswith("port_"):
                assert _placeholders(entry["name"]) == {"port_number"}, key


def test_eero_entity_description_default_is_the_shared_key() -> None:
    """The base default stays "all" (the device tracker relies on it)."""
    assert EeroEntityDescription(key="x").translation_key == "all"


def _make_entry(hass, **data_overrides) -> MockConfigEntry:
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


def _name(hass, platform: str, unique_id: str) -> tuple[str, str]:
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, unique_id)
    assert entity_id is not None, unique_id
    return entity_id, hass.states.get(entity_id).attributes["friendly_name"]


async def test_network_entity_names_are_unchanged(hass, sdk_factory) -> None:
    """Network entities are named "<network> <name>", entity_id from the English name."""
    sdk_factory()
    entry = _make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _name(hass, "switch", f"{NETWORK_ID}-band_steering") == (
        "switch.testnetwork_band_steering",
        "TestNetwork Band Steering",
    )
    assert _name(hass, "switch", f"{NETWORK_ID}-upnp") == (
        "switch.testnetwork_upnp",
        "TestNetwork UPnP",
    )
    assert _name(hass, "sensor", f"{NETWORK_ID}-public_ip") == (
        "sensor.testnetwork_public_ip",
        "TestNetwork Public IP",
    )


async def test_eero_and_port_entity_names(hass, sdk_factory) -> None:
    """Eero entities get the network prefix; port entities name their port."""
    eero = {
        "url": "/2.2/eeros/e1",
        "model": "eero 6",
        "location": "Office",
        "led_on": True,
        "led_brightness": 100,
    }
    port = {
        "interface_number": 2,
        "connection_status": "CONNECTED",
        "negotiated_speed": "P1000",
        "actions": [{"position": 0, "type": "RESTART_POWER"}],
    }
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "eeros.get_connections": {"ports": {"interfaces": [port]}},
        }
    )
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
    entry = _make_entry(hass, **{CONF_RESOURCES: resources})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _name(hass, "light", f"{NETWORK_ID}-e1-status_light_enabled") == (
        "light.testnetwork_office_status_light",
        "TestNetwork Office Status Light",
    )
    assert _name(hass, "update", f"{NETWORK_ID}-e1-firmware") == (
        "update.testnetwork_office_firmware",
        "TestNetwork Office Firmware",
    )
    assert _name(hass, "sensor", f"{NETWORK_ID}-e1-status") == (
        "sensor.testnetwork_office_status",
        "TestNetwork Office Status",
    )
    assert _name(hass, "sensor", f"{NETWORK_ID}-e1-port_2_connection_status") == (
        "sensor.testnetwork_office_port_2_connection_status",
        "TestNetwork Office Port 2 connection status",
    )
    registry = er.async_get(hass)
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{NETWORK_ID}-e1-port_2_action_restart_power"
    )
    # Disabled by default, so there is no state: check the registry. (Its
    # device may register before any named eero entity in this minimal
    # fixture, so only the entity's own part of the entity_id is checked.)
    assert button_id is not None
    assert button_id.endswith("_restart_port_2_power")
    assert registry.async_get(button_id).original_name == "Restart port 2 power"


async def test_pt_br_translates_names_and_keeps_registered_entity_ids(
    hass, sdk_factory
) -> None:
    """In pt-BR names are translated; a registered entity keeps its entity_id.

    pt-BR is one of Home Assistant's native entity ID languages, so an entity
    first registered on a pt-BR system gets a Portuguese object ID, while one
    already in the registry (an existing install) keeps the one it has.
    """
    hass.config.language = "pt-BR"
    sdk_factory()
    entry = _make_entry(hass)
    er.async_get(hass).async_get_or_create(
        "switch",
        DOMAIN,
        f"{NETWORK_ID}-band_steering",
        config_entry=entry,
        suggested_object_id="testnetwork_band_steering",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert _name(hass, "switch", f"{NETWORK_ID}-band_steering") == (
        "switch.testnetwork_band_steering",
        "TestNetwork Direcionamento de banda",
    )
    assert _name(hass, "switch", f"{NETWORK_ID}-guest_network_enabled") == (
        "switch.testnetwork_rede_de_convidados",
        "TestNetwork Rede de convidados",
    )
