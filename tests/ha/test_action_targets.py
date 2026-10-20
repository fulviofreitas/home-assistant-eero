"""Which networks (and profiles) an action writes to, by target_network and target_profile.

One entry, two networks, one configured profile on each. Every SDK write
takes the network's ID first, so the IDs the writes were made with are the
networks the action reached.
"""

from __future__ import annotations

import pytest
from homeassistant.config_entries import ConfigEntryState
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero.const import (
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
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
)

from conftest import NETWORK_ID, entry_data, network_envelope

SECOND_ID = "7654321"
NAMES = {NETWORK_ID: "TestNetwork", SECOND_ID: "Second"}
# Profile IDs are numeric too.
PROFILES = {NETWORK_ID: "111", SECOND_ID: "222"}

WRITES = {
    "set_blocked_apps": "dns_policies.set_profile_blocked_applications",
    "create_reservation": "reservations.create_reservation",
    "delete_reservation": "reservations.delete_reservation",
    "create_port_forward": "forwards.create_forward",
    "delete_port_forward": "forwards.delete_forward",
    "set_custom_dns": "dns.set_custom_dns",
}
FIELDS = {
    "set_blocked_apps": {"blocked_apps": ["netflix"]},
    "create_reservation": {"ip": "192.168.4.100", "mac": "aa:bb:cc:dd:ee:ff"},
    "delete_reservation": {"reservation": "r1"},
    "create_port_forward": {
        "ip": "192.168.4.100",
        "client_port": 8080,
        "gateway_port": 8080,
        "protocol": "tcp",
    },
    "delete_port_forward": {"forward": "f1"},
    "set_custom_dns": {"ipv4": ["1.1.1.1"]},
}
BOTH = {NETWORK_ID, SECOND_ID}
TARGETS = {
    "name": ("Second", {SECOND_ID}),
    "names": (["TestNetwork", "Second"], BOTH),
    "id-int": (int(NETWORK_ID), {NETWORK_ID}),
    "id-str": (NETWORK_ID, {NETWORK_ID}),
    "ids-int": ([int(NETWORK_ID), int(SECOND_ID)], BOTH),
    "id-int-and-name": ([int(SECOND_ID), "TestNetwork"], BOTH),
    "id-str-and-name": (["Second", NETWORK_ID], BOTH),
    "no-match": (["Elsewhere", 1], set()),
}


def resources(nid: str) -> dict:
    return {
        CONF_BACKUP_NETWORKS: [],
        CONF_EEROS: [],
        CONF_PROFILES: [PROFILES[nid]],
        CONF_WIRED_CLIENTS: [],
        CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        CONF_WIRELESS_CLIENTS: [],
        CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
    }


def network_route(names: dict[str, str]):
    def route(args, kwargs) -> dict:
        nid = args[0]
        url = f"/2.2/networks/{nid}"
        return network_envelope(
            url=url,
            name=names[nid],
            resources={"settings": f"{url}/settings", "profiles": f"{url}/profiles"},
        )

    return route


def profiles_route(args, kwargs) -> list:
    nid = args[0]
    return [{"url": f"/2.2/networks/{nid}/profiles/{PROFILES[nid]}", "name": "Kids"}]


@pytest.fixture
def names() -> dict[str, str]:
    return NAMES


@pytest.fixture
async def sdk(hass, sdk_factory, names):
    """One loaded entry with both networks; the writes are recorded, not answered."""
    sdk = sdk_factory(
        {
            "networks.get_network": network_route(names),
            "profiles.get_profiles": profiles_route,
            "schedule.get_schedules": [],
            "dns.get_dns_settings": {
                "dns": {"mode": "automatic"},
                "ipv6": {"name_servers": {"mode": "automatic"}},
            },
            **{write: {} for write in WRITES.values()},
        }
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=entry_data(
            **{
                CONF_NETWORKS: [NETWORK_ID, SECOND_ID],
                CONF_RESOURCES: {nid: resources(nid) for nid in NAMES},
                CONF_MISCELLANEOUS: {
                    nid: {
                        CONF_CONSIDER_HOME: 0,
                        CONF_PREFIX_NETWORK_NAME: True,
                        CONF_SUFFIX_CONNECTION_TYPE: True,
                    }
                    for nid in NAMES
                },
            }
        ),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    sdk.calls.clear()
    return sdk


def written(sdk, service: str) -> list[tuple]:
    """The arguments of every write the action made."""
    return [
        args
        for domain, method, args, _kwargs in sdk.calls
        if f"{domain}.{method}" == WRITES[service]
    ]


async def call(hass, service: str, **fields) -> None:
    await hass.services.async_call(
        DOMAIN, service, {**FIELDS[service], **fields}, blocking=True
    )
    await hass.async_block_till_done()


@pytest.mark.parametrize("service", sorted(WRITES))
@pytest.mark.parametrize("target", sorted(TARGETS))
async def test_target_network_by_name_or_id(hass, sdk, service, target) -> None:
    """A network ID matches whether it arrives as a number or a string.

    Regression: the schema turned every numeric value into an int, which
    never equals the network's string ID, so targeting by ID wrote nothing
    and raised nothing.
    """
    value, networks = TARGETS[target]

    await call(hass, service, target_network=value)

    assert sorted(args[0] for args in written(sdk, service)) == sorted(networks)


@pytest.mark.parametrize("names", [{NETWORK_ID: "TestNetwork", SECOND_ID: "007"}])
@pytest.mark.parametrize("service", sorted(WRITES))
async def test_a_network_named_like_a_number_is_targeted_by_name(
    hass, sdk, service
) -> None:
    """A name made of digits is compared as written, leading zeros and all."""
    await call(hass, service, target_network="007")

    assert [args[0] for args in written(sdk, service)] == [SECOND_ID]


async def test_set_blocked_apps_without_target_network_reaches_every_network(
    hass, sdk
) -> None:
    await call(hass, "set_blocked_apps")

    assert sorted(written(sdk, "set_blocked_apps")) == sorted(
        (nid, PROFILES[nid], ["netflix"]) for nid in NAMES
    )


@pytest.mark.parametrize(
    ("value", "profiles"),
    [
        ("Kids", set(PROFILES.values())),
        (111, {"111"}),
        ("222", {"222"}),
        ([111, "Kids"], set(PROFILES.values())),
        (["Adults", 333], set()),
    ],
    ids=["name", "id-int", "id-str", "id-and-name", "no-match"],
)
async def test_set_blocked_apps_target_profile_by_name_or_id(
    hass, sdk, value, profiles
) -> None:
    """Profile IDs are numeric too, and were dropped the same way."""
    await call(hass, "set_blocked_apps", target_profile=value)

    assert {args[1] for args in written(sdk, "set_blocked_apps")} == profiles
