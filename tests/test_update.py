"""Tests for the update loop's tolerance of partial responses (audit H4, H3)."""

from __future__ import annotations

import pytest

from helpers import FakeSDK, build_hub, eero_api, fixture

NETWORK_ID = "1234567"


def full_sdk(network: dict | None = None, devices: list | None = None) -> FakeSDK:
    """Return a FakeSDK for a network that reports everything."""
    return FakeSDK(
        {
            "networks.get_network": network if network is not None else fixture("network"),
            "devices.get_devices": fixture("devices") if devices is None else devices,
            "profiles.get_profiles": [],
            "eeros.get_eeros": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )


async def test_update_reads_a_complete_network() -> None:
    """The happy path still assembles the account tree."""
    sdk = full_sdk()
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True)

    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})
    network = account.networks[0]

    assert network.id == NETWORK_ID
    assert network.name == "TestNetwork"
    assert network.thread_name == "eero-thread"
    assert sorted(client.name for client in network.clients) == [
        "Chloe iPad",
        "Office Printer",
    ]


async def test_eeros_fetched_only_when_the_network_envelope_lacks_them() -> None:
    """eeros.get_eeros is skipped once the network envelope embeds them."""
    network = dict(fixture("network"))
    network["eeros"] = {"count": 1, "data": [{"url": "/2.2/eeros/1", "model": "eero 6"}]}
    sdk = FakeSDK({"networks.get_network": network})
    hub = build_hub(sdk=sdk)

    payload = await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())

    assert "eeros" not in payload
    assert ("eeros", "get_eeros", (NETWORK_ID,), {}) not in sdk.calls

    account = hub.assemble(None, {NETWORK_ID: payload}, {}, {})
    assert [eero.id for eero in account.networks[0].eeros] == ["1"]


async def test_blacklist_fetched_only_when_configured_and_matched_by_mac() -> None:
    """The daily tier reads the blacklist only when configured; blocked() matches by MAC."""
    sdk = FakeSDK(
        {
            "networks.get_network": fixture("network"),
            "devices.get_devices": fixture("devices"),
            "eeros.get_eeros": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
            "blacklist.get_blacklist": [{"mac": "AA:BB:CC:DD:EE:FF"}],
        }
    )
    hub = build_hub(sdk=sdk)

    # Not configured: no request made, no blacklist in the payload.
    plain_config = eero_api.EeroUpdateConfig(get_devices=True)
    fast = await hub.fetch_fast(NETWORK_ID, plain_config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], plain_config)
    assert "blacklist" not in daily
    assert ("blacklist", "get_blacklist", (NETWORK_ID,), {}) not in sdk.calls

    # Configured: fetched once, and the matching client reports blocked=True.
    config = eero_api.EeroUpdateConfig(get_devices=True, get_blacklist=True)
    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    assert ("blacklist", "get_blacklist", (NETWORK_ID,), {}) in sdk.calls
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})
    network = account.networks[0]
    clients = {client.mac: client for client in network.clients}
    assert clients["aa:bb:cc:dd:ee:ff"].blocked is True
    assert clients["11:22:33:44:55:66"].blocked is False


async def test_schedules_fetched_only_when_profiles_configured_and_parsed_by_name_and_days() -> (
    None
):
    """The daily tier reads schedules per configured profile; bedtime is matched by name/days."""
    sdk = FakeSDK(
        {
            "networks.get_network": fixture("network"),
            "eeros.get_eeros": [],
            "profiles.get_profiles": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
            "schedule.get_schedules": [
                {
                    "name": "Bedtime",
                    "days": list(eero_api.profile.WEEKDAYS),
                    "start": "21:00",
                    "end": "06:30",
                    "enabled": True,
                    "url": "/2.2/networks/1234567/profiles/p1/schedules/1",
                },
                {
                    "name": "Homework",
                    "days": ["monday"],
                    "start": "15:00",
                    "end": "16:00",
                    "enabled": True,
                },
            ],
        }
    )
    hub = build_hub(sdk=sdk)

    # Not configured: no request made, no schedules in the payload.
    plain_config = eero_api.EeroUpdateConfig()
    fast = await hub.fetch_fast(NETWORK_ID, plain_config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], plain_config)
    assert "schedules" not in daily
    assert ("schedule", "get_schedules", (NETWORK_ID, "p1"), {}) not in sdk.calls

    # Configured: fetched once per configured profile.
    config = eero_api.EeroUpdateConfig(profiles=["p1"], get_schedules=True)
    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    assert ("schedule", "get_schedules", (NETWORK_ID, "p1"), {}) in sdk.calls
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})
    network = account.networks[0]
    profile = eero_api.profile.EeroProfile(
        hub, network, {"url": f"{network.url}/profiles/p1"}
    )
    assert profile.bedtime_enabled is True
    assert profile.bedtime_weekday_start.isoformat() == "21:00:00"
    assert profile.bedtime_weekday_end.isoformat() == "06:30:00"
    assert profile.bedtime_weekend_start is None


async def test_client_profile_assignment_reads_and_moves_between_profiles() -> None:
    """profile_assignment is read from the fast-tier profiles; moving rewrites both lists."""
    mac = "aa:bb:cc:dd:ee:ff"
    other_mac = "11:22:33:44:55:66"
    network = dict(fixture("network"))
    profiles = [
        {
            "url": f"/2.2/networks/{NETWORK_ID}/profiles/kids",
            "name": "Kids",
            "devices": [{"url": f"/2.2/networks/{NETWORK_ID}/devices/{mac}", "mac": mac}],
        },
        {
            "url": f"/2.2/networks/{NETWORK_ID}/profiles/adults",
            "name": "Adults",
            "devices": [],
        },
    ]
    sdk = FakeSDK(
        {
            "networks.get_network": network,
            "devices.get_devices": fixture("devices"),
            "eeros.get_eeros": [],
            "profiles.get_profiles": profiles,
            "profiles.set_profile_devices": {},
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True, profiles=["kids", "adults"])

    fast = await hub.fetch_fast(NETWORK_ID, config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {})
    net = account.networks[0]
    clients = {client.mac: client for client in net.clients}

    assert clients[mac].profile_assignment == "Kids"
    assert clients[other_mac].profile_assignment == "Unassigned"
    assert sorted(clients[mac].profile_assignment_options) == [
        "Adults",
        "Kids",
        "Unassigned",
    ]

    await clients[mac].async_set_profile_assignment("Adults")
    assert (
        "profiles",
        "set_profile_devices",
        (NETWORK_ID, "kids", []),
        {},
    ) in sdk.calls
    assert (
        "profiles",
        "set_profile_devices",
        (NETWORK_ID, "adults", [f"/2.2/networks/{NETWORK_ID}/devices/{mac}"]),
        {},
    ) in sdk.calls


async def test_client_profile_assignment_is_none_when_no_profiles_configured() -> None:
    """No profile configured on the network -> profiles never fetched -> None, not 'Unassigned'.

    The fast tier only fetches profiles when at least one is configured
    (EeroUpdateConfig.get_profiles); a client's profile_assignment must stay
    honest about that rather than reporting a false "unassigned" state.
    """
    sdk = FakeSDK(
        {
            "networks.get_network": fixture("network"),
            "devices.get_devices": fixture("devices"),
            "eeros.get_eeros": [],
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True)
    assert config.get_profiles is False

    fast = await hub.fetch_fast(NETWORK_ID, config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {})
    client = account.networks[0].clients[0]

    assert "profiles" not in account.networks[0].data
    assert client.profile_assignment is None
    assert client.profile_assignment_options == []


async def test_reservations_and_forwards_counted_in_the_daily_tier() -> None:
    """reservation_count/forward_count/dns_mode are always read in the daily tier."""
    network = dict(fixture("network"))
    network["dns"] = {"mode": "custom", "caching": True}
    sdk = FakeSDK(
        {
            "networks.get_network": network,
            "eeros.get_eeros": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [{"ip": "192.168.4.100"}],
            "forwards.get_forwards": [
                {"ip": "192.168.4.100", "client_port": 8080},
                {"ip": "192.168.4.101", "client_port": 9090},
            ],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig()

    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})
    net = account.networks[0]

    assert net.reservation_count == 1
    assert net.forward_count == 2
    assert net.dns_mode == "custom"


async def test_ports_fetched_only_when_eeros_configured_and_parsed_per_interface() -> (
    None
):
    """Connections (and so ports) are read per configured eero, only when configured."""
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6"}
    network = dict(fixture("network"))
    network["eeros"] = {"count": 1, "data": [eero]}
    connections = {
        "node_actions": [],
        "ports": {
            "interfaces": [
                {
                    "interface_number": 1,
                    "connection_status": "CONNECTED",
                    "negotiated_speed": "P1000",
                    "actions": [
                        {"position": 0, "type": "RESTART_POWER"},
                        {"position": 1, "type": "DISABLE_PORT"},
                    ],
                },
                {
                    "interface_number": 2,
                    "connection_status": "DISCONNECTED",
                    "negotiated_speed": None,
                    "actions": [],
                },
            ]
        },
        "wireless_devices": [],
    }
    sdk = FakeSDK(
        {
            "networks.get_network": network,
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
            "eeros.get_connections": connections,
        }
    )
    hub = build_hub(sdk=sdk)

    # Not configured: no request made, no connections in the payload.
    plain_config = eero_api.EeroUpdateConfig()
    fast = await hub.fetch_fast(NETWORK_ID, plain_config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], plain_config)
    assert "connections" not in daily
    assert ("eeros", "get_connections", (NETWORK_ID, "e1"), {}) not in sdk.calls

    # Configured: fetched once per configured eero.
    config = eero_api.EeroUpdateConfig(eeros=["e1"], get_connections=True)
    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    assert ("eeros", "get_connections", (NETWORK_ID, "e1"), {}) in sdk.calls
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})
    device = account.networks[0].eeros[0]
    ports = device.ports
    assert [port["interface_number"] for port in ports] == [1, 2]
    assert ports[0]["negotiated_speed"] == "P1000"


async def test_network_without_a_thread_resource() -> None:
    """A network with no Thread border router must not raise KeyError (H4)."""
    sdk = FakeSDK(
        {
            "networks.get_network": fixture("network_no_thread"),
            "devices.get_devices": fixture("devices"),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True)

    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})

    assert account.networks[0].name == "TestNetwork"
    assert account.networks[0].thread_enabled is None
    assert all(call[:2] != ("thread", "get_thread") for call in sdk.calls)


async def test_network_missing_capabilities_updates_and_timezone() -> None:
    """Absent capability, updates and timezone blocks are all optional (H4)."""
    network = {
        "url": f"/2.2/networks/{NETWORK_ID}",
        "name": "TestNetwork",
        "resources": {"devices": f"/2.2/networks/{NETWORK_ID}/devices"},
    }
    sdk = FakeSDK(
        {
            "networks.get_network": network,
            "devices.get_devices": [],
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True)

    fast = await hub.fetch_fast(NETWORK_ID, config)
    daily = await hub.fetch_daily(NETWORK_ID, fast["network"], config)
    account = hub.assemble(None, {NETWORK_ID: fast}, {}, {NETWORK_ID: daily})

    assert account.networks[0].target_firmware.os_version is None
    assert account.networks[0].firmware_history == []
    assert account.networks[0].preferred_update_hour is None


def test_network_entry_without_a_url_is_skipped() -> None:
    """A malformed networks entry is skipped, not fatal (H4)."""
    account = {"name": "Test Account", "networks": {"data": [{"name": "broken"}]}}

    assert eero_api.EeroHub.network_ids(account) == []


async def test_empty_account_response_raises() -> None:
    """A body with no networks member is a failed poll, not zero entities (N6)."""
    hub = build_hub(sdk=FakeSDK({"GET /account": {}}))

    with pytest.raises(eero_api.EeroException):
        await hub.get_account()


async def test_null_account_response_raises() -> None:
    """Same for a 200 carrying no data at all (N6)."""
    hub = build_hub(sdk=FakeSDK({"GET /account": None}))

    with pytest.raises(eero_api.EeroException):
        await hub.get_account()


async def test_empty_network_data_raises() -> None:
    """A network fetch that returns no data is a failed poll (N6)."""
    hub = build_hub(sdk=FakeSDK({"networks.get_network": None}))

    with pytest.raises(eero_api.EeroException):
        await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())


async def test_resource_that_disappears_between_polls() -> None:
    """A client removed from the Eero app is simply gone from resources (H3)."""
    client_id = "aa:bb:cc:dd:ee:ff"
    sdk = full_sdk()
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True)

    fast_before = await hub.fetch_fast(NETWORK_ID, config)
    before = hub.assemble(None, {NETWORK_ID: fast_before}, {}, {}).networks[0]
    assert client_id in [resource.id for resource in before.resources]

    remaining = [device for device in fixture("devices") if device["mac"] != client_id]
    sdk.set_route("devices.get_devices", remaining)

    fast_after = await hub.fetch_fast(NETWORK_ID, config)
    after = hub.assemble(None, {NETWORK_ID: fast_after}, {}, {}).networks[0]

    ids = [resource.id for resource in after.resources]
    assert client_id not in ids
    assert "11:22:33:44:55:66" in ids
