"""Setup's registry pruning: which registered devices and activity entities survive.

Setup drops the devices the entry no longer configures before the first poll.
The SDK here reports none of the configured eeros, profiles, backup networks
or clients, so no entity re-creates a device after pruning: what the registry
holds once setup is done is exactly what pruning kept.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.eero as eero_init
from custom_components.eero.const import (
    ACTIVITY_DATA_USAGE_DAY,
    ACTIVITY_DATA_USAGE_WEEK,
    CONF_ACTIVITY,
    CONF_ACTIVITY_NETWORK,
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
    CONF_SUFFIX_CONNECTION_TYPE,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
    MANUFACTURER,
    MODEL_BACKUP_NETWORK,
    MODEL_CLIENT_WIRED,
    MODEL_CLIENT_WIRELESS,
    MODEL_NETWORK,
    MODEL_PROFILE,
)

from conftest import NETWORK_ID, entry_data, network_envelope

SECOND_ID = "7654321"
GONE_ID = "9999999"
NAMES = {NETWORK_ID: "TestNetwork", SECOND_ID: "Second", GONE_ID: "Gone"}


def resources(nid: str, **overrides) -> dict:
    """Every kind of resource configured for a network, clients by include."""
    data = {
        CONF_BACKUP_NETWORKS: [f"b{nid}"],
        CONF_EEROS: [f"e{nid}"],
        CONF_PROFILES: [f"p{nid}"],
        CONF_WIRED_CLIENTS: [f"w{nid}"],
        CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        CONF_WIRELESS_CLIENTS: [f"l{nid}"],
        CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
    }
    data.update(overrides)
    return data


def miscellaneous() -> dict:
    return {
        CONF_CONSIDER_HOME: 0,
        CONF_PREFIX_NETWORK_NAME: True,
        CONF_SUFFIX_CONNECTION_TYPE: True,
    }


def make_entry(hass, conf_resources: dict, conf_activity: dict | None = None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=entry_data(
            **{
                CONF_NETWORKS: list(conf_resources),
                CONF_RESOURCES: conf_resources,
                CONF_ACTIVITY: conf_activity or {},
                CONF_MISCELLANEOUS: {nid: miscellaneous() for nid in conf_resources},
            }
        ),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    return entry


def network_route(args, kwargs) -> dict:
    """Each network as it was asked for, with no eeros embedded."""
    nid = args[0]
    url = f"/2.2/networks/{nid}"
    return network_envelope(
        url=url, name=NAMES[nid], resources={"settings": f"{url}/settings"}
    )


@pytest.fixture
def sdk(sdk_factory):
    """Every configured network exists; none of its resources are reported."""
    return sdk_factory(
        {
            "networks.get_network": network_route,
            "profiles.get_profiles": [],
            "schedule.get_schedules": [],
            "eeros.get_connections": {},
            "backup_access_points.list": [],
            "blacklist.get_blacklist": [],
        }
    )


class Seeded:
    """The devices registered to the entry before setup, by identifier."""

    def __init__(self, hass, entry) -> None:
        self.hass = hass
        self.entry = entry
        self.registry = dr.async_get(hass)
        self.network_devices: dict[str, dr.DeviceEntry] = {}

    def network(self, nid: str) -> None:
        self.network_devices[nid] = self.registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, nid)},
            manufacturer=MANUFACTURER,
            name=NAMES[nid],
            model=MODEL_NETWORK,
        )

    def child(self, nid: str, resource_id: str, model: str) -> None:
        self.registry.async_get_or_create(
            config_entry_id=self.entry.entry_id,
            identifiers={(DOMAIN, resource_id)},
            manufacturer=MANUFACTURER,
            name=f"{model} {resource_id}",
            model=model,
            via_device_id=self.network_devices[nid].id,
        )

    def every_kind(self, nid: str) -> None:
        """The network's device and one device of every kind under it."""
        self.network(nid)
        self.child(nid, f"e{nid}", "eero 6")
        self.child(nid, f"p{nid}", MODEL_PROFILE)
        self.child(nid, f"b{nid}", MODEL_BACKUP_NETWORK)
        self.child(nid, f"w{nid}", MODEL_CLIENT_WIRED)
        self.child(nid, f"l{nid}", MODEL_CLIENT_WIRELESS)

    def remaining(self) -> set[str]:
        return {
            resource_id
            for device in dr.async_entries_for_config_entry(
                self.registry, self.entry.entry_id
            )
            for _domain, resource_id in device.identifiers
        }


def kinds(nid: str) -> set[str]:
    return {nid, f"e{nid}", f"p{nid}", f"b{nid}", f"w{nid}", f"l{nid}"}


@pytest.fixture
def removals(monkeypatch) -> list[str]:
    """Every device removal setup asks the registry for, in order."""
    removed: list[str] = []
    real = dr.DeviceRegistry.async_remove_device

    def spy(self, device_id: str) -> None:
        removed.append(device_id)
        real(self, device_id)

    monkeypatch.setattr(dr.DeviceRegistry, "async_remove_device", spy)
    return removed


async def setup(hass, entry) -> None:
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED


async def test_two_networks_keep_every_device_either_network_configures(
    hass, sdk, removals
) -> None:
    """Network A's devices are not removed while network B is judged, nor the reverse.

    Regression: each device was judged against every configured network in
    turn and removed as soon as one of them did not configure it, so with two
    networks every eero, profile, backup network and client went.
    """
    entry = make_entry(
        hass, {nid: resources(nid) for nid in (NETWORK_ID, SECOND_ID)}
    )
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)
    seeded.every_kind(SECOND_ID)

    await setup(hass, entry)

    assert seeded.remaining() == kinds(NETWORK_ID) | kinds(SECOND_ID)
    assert removals == []


async def test_two_networks_remove_what_no_network_configures(
    hass, sdk, removals
) -> None:
    """A network no longer configured, and every device under it, is removed once."""
    entry = make_entry(
        hass, {nid: resources(nid) for nid in (NETWORK_ID, SECOND_ID)}
    )
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)
    seeded.every_kind(SECOND_ID)
    seeded.every_kind(GONE_ID)
    # Gone from a network that is still configured.
    seeded.child(NETWORK_ID, "e-unselected", "eero Pro 6E")
    seeded.child(SECOND_ID, "p-unselected", MODEL_PROFILE)

    await setup(hass, entry)

    assert seeded.remaining() == kinds(NETWORK_ID) | kinds(SECOND_ID)
    assert len(removals) == len(set(removals)) == len(kinds(GONE_ID)) + 2


async def test_two_networks_client_excluded_on_one_and_included_on_the_other(
    hass, sdk, removals
) -> None:
    """A client one network excludes stays while the other network still wants it.

    The same client (the same MAC) can join both networks, and is one device.
    """
    entry = make_entry(
        hass,
        {
            NETWORK_ID: resources(
                NETWORK_ID,
                **{
                    CONF_WIRELESS_CLIENTS: ["roamer", "dropped"],
                    CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
                    CONF_WIRED_CLIENTS: [],
                    CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
                },
            ),
            SECOND_ID: resources(
                SECOND_ID, **{CONF_WIRELESS_CLIENTS: [f"l{SECOND_ID}", "roamer"]}
            ),
        },
    )
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)
    seeded.every_kind(SECOND_ID)
    seeded.child(NETWORK_ID, "roamer", MODEL_CLIENT_WIRELESS)
    # Excluded on the first network, not included on the second.
    seeded.child(NETWORK_ID, "dropped", MODEL_CLIENT_WIRELESS)
    # Not included on the second network, but the first network's exclude
    # filter keeps every wired client it does not list, as a single
    # network's would: the registry cannot tell which network it is on.
    seeded.child(SECOND_ID, "unlisted", MODEL_CLIENT_WIRED)

    await setup(hass, entry)

    assert seeded.remaining() == (
        kinds(NETWORK_ID) | kinds(SECOND_ID) | {"roamer", "unlisted"}
    )
    assert len(removals) == 1


async def test_two_networks_prune_activity_entities_once_per_device(
    hass, sdk, monkeypatch
) -> None:
    """Unselected premium activity entities go, on both networks, each device visited once."""
    visited: list[str] = []
    real = eero_init._remove_unselected_activity_entities

    def spy(entity_registry, device_entry, conf_activity) -> None:
        visited.append(device_entry.id)
        real(entity_registry, device_entry, conf_activity)

    monkeypatch.setattr(eero_init, "_remove_unselected_activity_entities", spy)

    entry = make_entry(
        hass,
        {nid: resources(nid) for nid in (NETWORK_ID, SECOND_ID)},
        {
            NETWORK_ID: {CONF_ACTIVITY_NETWORK: [ACTIVITY_DATA_USAGE_DAY]},
            SECOND_ID: {CONF_ACTIVITY_NETWORK: [ACTIVITY_DATA_USAGE_WEEK]},
        },
    )
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)
    seeded.every_kind(SECOND_ID)
    entities = er.async_get(hass)
    for nid, device in seeded.network_devices.items():
        for key in (ACTIVITY_DATA_USAGE_DAY, ACTIVITY_DATA_USAGE_WEEK):
            entities.async_get_or_create(
                "sensor", DOMAIN, f"{nid}-{key}", config_entry=entry, device_id=device.id
            )

    await setup(hass, entry)

    def kept(unique_id: str) -> bool:
        return entities.async_get_entity_id("sensor", DOMAIN, unique_id) is not None

    assert kept(f"{NETWORK_ID}-{ACTIVITY_DATA_USAGE_DAY}")
    assert not kept(f"{NETWORK_ID}-{ACTIVITY_DATA_USAGE_WEEK}")
    assert not kept(f"{SECOND_ID}-{ACTIVITY_DATA_USAGE_DAY}")
    assert kept(f"{SECOND_ID}-{ACTIVITY_DATA_USAGE_WEEK}")
    assert len(visited) == len(set(visited)) == len(seeded.remaining())


async def test_no_network_configured_removes_nothing(hass, sdk, removals) -> None:
    """With no network to judge against, no device is stale."""
    entry = make_entry(hass, {})
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)

    await setup(hass, entry)

    assert seeded.remaining() == kinds(NETWORK_ID)
    assert removals == []


@pytest.mark.parametrize(
    ("overrides", "removed"),
    [
        ({}, {GONE_ID, "e-old", "p-old", "b-old", "w-old", "l-old"}),
        # Exclude: the listed clients go, every other client stays.
        (
            {
                CONF_WIRED_CLIENTS: ["w-old"],
                CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
                CONF_WIRELESS_CLIENTS: [f"l{NETWORK_ID}"],
                CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
            },
            {GONE_ID, "e-old", "p-old", "b-old", "w-old", f"l{NETWORK_ID}"},
        ),
        # Nothing selected: only the network device itself is wanted.
        (
            {
                CONF_BACKUP_NETWORKS: [],
                CONF_EEROS: [],
                CONF_PROFILES: [],
                CONF_WIRED_CLIENTS: [],
                CONF_WIRELESS_CLIENTS: [],
            },
            (kinds(NETWORK_ID) - {NETWORK_ID})
            | {GONE_ID, "e-old", "p-old", "b-old", "w-old", "l-old"},
        ),
    ],
    ids=["include", "exclude", "nothing-selected"],
)
async def test_one_network_prunes_what_it_no_longer_configures(
    hass, sdk, removals, overrides, removed
) -> None:
    """With one network, a device goes when that network does not configure it."""
    entry = make_entry(hass, {NETWORK_ID: resources(NETWORK_ID, **overrides)})
    seeded = Seeded(hass, entry)
    seeded.every_kind(NETWORK_ID)
    seeded.child(NETWORK_ID, "e-old", "eero 6")
    seeded.child(NETWORK_ID, "p-old", MODEL_PROFILE)
    seeded.child(NETWORK_ID, "b-old", MODEL_BACKUP_NETWORK)
    seeded.child(NETWORK_ID, "w-old", MODEL_CLIENT_WIRED)
    seeded.child(NETWORK_ID, "l-old", MODEL_CLIENT_WIRELESS)
    seeded.network(GONE_ID)
    before = seeded.remaining()

    await setup(hass, entry)

    assert seeded.remaining() == before - removed
    assert len(removals) == len(removed)
