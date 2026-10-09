"""Property coverage for EeroClient: activity/insight getters and other reads."""

from __future__ import annotations

import pytest

from eero.exceptions import EeroException
from helpers import FakeSDK, build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"
CLIENT_URL = f"{NETWORK_URL}/devices/aa"


def make_network(hub, **overrides):
    data = {"url": NETWORK_URL, "resources": {"insights": f"{NETWORK_URL}/insights"}}
    data.update(overrides)
    return eero_api.network.EeroNetwork(hub, None, data)


def make_client(hub, network_overrides=None, **client_overrides):
    network = make_network(hub, **(network_overrides or {}))
    data = {"url": CLIENT_URL, "mac": "aa"}
    data.update(client_overrides)
    return eero_api.client.EeroClient(hub, network, data)


def test_adblock_day_month_week_matched_by_insights_url() -> None:
    hub = build_hub()
    client = make_client(hub)
    insights_url = client.url_insights
    network_overrides = {
        "activity": {
            "devices": {
                "adblock_day": [{"insights_url": insights_url, "sum": 1}],
                "adblock_month": [{"insights_url": insights_url, "sum": 2}],
                "adblock_week": [{"insights_url": insights_url, "sum": 3}],
            }
        }
    }
    client = make_client(hub, network_overrides=network_overrides)
    assert client.adblock_day == 1
    assert client.adblock_month == 2
    assert client.adblock_week == 3


def test_adblock_day_none_when_no_match() -> None:
    hub = build_hub()
    client = make_client(
        hub, network_overrides={"activity": {"devices": {"adblock_day": []}}}
    )
    assert client.adblock_day is None
    assert client.adblock_month is None
    assert client.adblock_week is None


def test_blocked_day_month_week_matched_by_insights_url() -> None:
    hub = build_hub()
    client = make_client(hub)
    insights_url = client.url_insights
    network_overrides = {
        "activity": {
            "devices": {
                "blocked_day": [{"insights_url": insights_url, "sum": 10}],
                "blocked_month": [{"insights_url": insights_url, "sum": 20}],
                "blocked_week": [{"insights_url": insights_url, "sum": 30}],
            }
        }
    }
    client = make_client(hub, network_overrides=network_overrides)
    assert client.blocked_day == 10
    assert client.blocked_month == 20
    assert client.blocked_week == 30


def test_blocked_property_matched_by_mac_case_and_separator_insensitive() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        mac="AA:BB:CC",
        network_overrides={"blacklist": {"data": [{"mac": "aabbcc"}]}},
    )
    assert client.blocked is True

    not_blocked = make_client(
        hub,
        mac="AA:BB:CC",
        network_overrides={"blacklist": {"data": [{"device_id": "zzzzzz"}]}},
    )
    assert not_blocked.blocked is False


def test_blocked_property_none_when_blacklist_not_fetched() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.blocked is None


def test_channel_width_rx_and_tx() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        connectivity={
            "rx_rate_info": {"channel_width": "40MHz"},
            "tx_rate_info": {"channel_width": "80MHz"},
        },
    )
    assert client.channel_width_rx == "40MHz"
    assert client.channel_width_tx == "80MHz"


def test_connection_type() -> None:
    hub = build_hub()
    client = make_client(hub, connection_type="wireless")
    assert client.connection_type == "wireless"


def test_data_usage_day_month_week_matched_by_url() -> None:
    hub = build_hub()
    client = make_client(hub)
    entry = {"url": CLIENT_URL, "download": 100, "upload": 50}
    network_overrides = {
        "activity": {
            "devices": {
                "data_usage_day": [entry],
                "data_usage_month": [entry],
                "data_usage_week": [entry],
            }
        }
    }
    client = make_client(hub, network_overrides=network_overrides)
    assert client.data_usage_day == (100, 50)
    assert client.data_usage_month == (100, 50)
    assert client.data_usage_week == (100, 50)


def test_data_usage_day_none_when_no_match() -> None:
    hub = build_hub()
    client = make_client(
        hub, network_overrides={"activity": {"devices": {"data_usage_day": []}}}
    )
    assert client.data_usage_day == (None, None)


def test_inspected_day_month_week_matched_by_insights_url() -> None:
    hub = build_hub()
    client = make_client(hub)
    insights_url = client.url_insights
    network_overrides = {
        "activity": {
            "devices": {
                "inspected_day": [{"insights_url": insights_url, "sum": 7}],
                "inspected_month": [{"insights_url": insights_url, "sum": 8}],
                "inspected_week": [{"insights_url": insights_url, "sum": 9}],
            }
        }
    }
    client = make_client(hub, network_overrides=network_overrides)
    assert client.inspected_day == 7
    assert client.inspected_month == 8
    assert client.inspected_week == 9


def test_interface_frequency() -> None:
    hub = build_hub()
    client = make_client(hub, interface={"frequency": 5, "frequency_unit": "GHz"})
    assert client.interface_frequency == (5, "GHz")


def test_is_guest_and_is_private() -> None:
    hub = build_hub()
    client = make_client(hub, is_guest=True, is_private=False)
    assert client.is_guest is True
    assert client.is_private is False


def test_last_active_parses_iso_timestamp_and_none_when_missing() -> None:
    hub = build_hub()
    client = make_client(hub, last_active="2024-03-01T12:00:00+00:00")
    assert client.last_active is not None
    assert client.last_active.month == 3

    none_client = make_client(hub)
    assert none_client.last_active is None


def test_name_connection_type_known_and_unknown() -> None:
    hub = build_hub()
    known = make_client(hub, nickname="Phone", connection_type="wireless")
    assert known.name_connection_type == "Phone (Wireless)"

    unknown = make_client(hub, nickname="Phone")
    assert unknown.name_connection_type == "Phone (Unknown)"


def test_name_mac() -> None:
    hub = build_hub()
    client = make_client(hub, nickname="Phone")
    assert client.name_mac == "Phone (aa)"


def test_profile_assignment_options_includes_unassigned_sentinel() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        network_overrides={
            "profiles": {
                "data": [
                    {"url": f"{NETWORK_URL}/profiles/p1", "name": "Kids"},
                    {"url": f"{NETWORK_URL}/profiles/p2", "name": "Adults"},
                ]
            }
        },
    )
    assert client.profile_assignment_options == [
        eero_api.client.UNASSIGNED_PROFILE,
        "Kids",
        "Adults",
    ]


def test_profile_assignment_options_empty_when_profiles_not_fetched() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.profile_assignment_options == []


def test_secondary_wan_allow_access_defaults_true_when_unset() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.secondary_wan_allow_access is True

    denied = make_client(hub, secondary_wan_deny_access=True)
    assert denied.secondary_wan_allow_access is False


def test_source_location() -> None:
    hub = build_hub()
    client = make_client(hub, source={"location": "wifi"})
    assert client.source_location == "wifi"


def test_url_insights() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.url_insights == f"{NETWORK_URL}/insights/devices/aa"


def test_blocked_day_month_week_none_when_no_match() -> None:
    hub = build_hub()
    client = make_client(
        hub, network_overrides={"activity": {"devices": {"blocked_day": []}}}
    )
    assert client.blocked_day is None
    assert client.blocked_month is None
    assert client.blocked_week is None


def test_channel_and_hostname_and_manufacturer() -> None:
    hub = build_hub()
    client = make_client(hub, channel=36, hostname="my-host", manufacturer="Acme")
    assert client.channel == 36
    assert client.hostname == "my-host"
    assert client.manufacturer == "Acme"


def test_name_falls_back_to_hostname_then_mac() -> None:
    hub = build_hub()
    with_hostname = make_client(hub, hostname="my-host")
    assert with_hostname.name == "my-host"

    mac_only = make_client(hub)
    assert mac_only.name == "aa"


def test_data_usage_month_week_none_when_no_match() -> None:
    hub = build_hub()
    client = make_client(
        hub, network_overrides={"activity": {"devices": {"data_usage_month": []}}}
    )
    assert client.data_usage_month == (None, None)
    assert client.data_usage_week == (None, None)


def test_inspected_day_month_week_none_when_no_match() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        network_overrides={
            "activity": {
                "devices": {"inspected_day": [], "inspected_month": [], "inspected_week": []}
            }
        },
    )
    assert client.inspected_day is None
    assert client.inspected_month is None
    assert client.inspected_week is None


def test_wireless_getter() -> None:
    hub = build_hub()
    wired = make_client(hub, wireless=False)
    wireless = make_client(hub, wireless=True)
    assert wired.wireless is False
    assert wireless.wireless is True


def test_ip_is_guest_is_private() -> None:
    hub = build_hub()
    client = make_client(hub, ip="192.168.4.5", is_guest=True, is_private=False)
    assert client.ip == "192.168.4.5"
    assert client.is_guest is True
    assert client.is_private is False


def test_paused_getter() -> None:
    hub = build_hub()
    client = make_client(hub, paused=True)
    assert client.paused is True


def test_profile_assignment_none_when_profiles_never_fetched() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.profile_assignment is None


def test_profile_assignment_unassigned_when_not_in_any_profile() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        network_overrides={
            "profiles": {"data": [{"url": f"{NETWORK_URL}/profiles/p1", "name": "Kids"}]}
        },
    )
    assert client.profile_assignment == eero_api.client.UNASSIGNED_PROFILE


def test_profile_assignment_resolves_assigned_profile_name() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        network_overrides={
            "profiles": {
                "data": [
                    {
                        "url": f"{NETWORK_URL}/profiles/p1",
                        "name": "Kids",
                        "devices": [{"url": CLIENT_URL, "mac": "aa"}],
                    }
                ]
            }
        },
    )
    assert client.profile_assignment == "Kids"


async def test_async_set_profile_assignment_raises_when_current_list_unknown() -> None:
    hub = build_hub()
    client = make_client(
        hub,
        network_overrides={
            "profiles": {
                "data": [
                    {
                        "url": f"{NETWORK_URL}/profiles/p1",
                        "name": "Kids",
                        # no "devices" key: current list is unknown.
                    }
                ]
            }
        },
    )
    with pytest.raises(EeroException):
        await client.async_set_profile_assignment("Kids")


async def test_async_set_paused_calls_pause_device() -> None:
    sdk = FakeSDK({"devices.pause_device": {}})
    hub = build_hub(sdk=sdk)
    client = make_client(hub)

    await client.async_set_paused(True)

    assert ("devices", "pause_device", (NETWORK_ID, "aa", True), {}) in sdk.calls


def test_usage_down_and_up_default_to_zero() -> None:
    hub = build_hub()
    client = make_client(hub)
    assert client.usage_down == 0
    assert client.usage_up == 0

    with_usage = make_client(hub, usage={"down_mbps": 12.5, "up_mbps": 3.5})
    assert with_usage.usage_down == 12.5
    assert with_usage.usage_up == 3.5
