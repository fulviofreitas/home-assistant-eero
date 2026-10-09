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


async def test_network_without_a_thread_resource() -> None:
    """A network with no Thread border router must not raise KeyError (H4)."""
    sdk = FakeSDK(
        {
            "networks.get_network": fixture("network_no_thread"),
            "devices.get_devices": fixture("devices"),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
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
