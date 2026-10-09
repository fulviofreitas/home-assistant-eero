"""Property coverage for EeroNetwork: read-side getters the setter table doesn't exercise."""

from __future__ import annotations

import pytest

from helpers import FakeSDK, build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


def make_network(hub, **overrides):
    data = {"url": NETWORK_URL}
    data.update(overrides)
    return eero_api.network.EeroNetwork(hub, None, data)


FULL_DATA = {
    "activity": {
        "network": {
            "adblock_day": [{"insight_type": "adblock", "sum": 1}],
            "adblock_month": [{"insight_type": "adblock", "sum": 2}],
            "adblock_week": [{"insight_type": "adblock", "sum": 3}],
            "app_events": [{"id": "e1"}],
            "blocked_day": [
                {"insight_type": "blocked", "sum": 1},
                {"insight_type": "botnet", "sum": 2},
                {"insight_type": "unknown_type", "sum": 99},
            ],
            "blocked_month": [{"insight_type": "malware", "sum": 3}],
            "blocked_week": [{"insight_type": "parked", "sum": 4}],
            "data_usage_day": [
                {"type": "download", "sum": 100},
                {"type": "upload", "sum": 10},
            ],
            "data_usage_month": [
                {"type": "download", "sum": 200},
                {"type": "upload", "sum": 20},
            ],
            "data_usage_week": [
                {"type": "download", "sum": 300},
                {"type": "upload", "sum": 30},
            ],
            "eeros_data_usage_summary_day": [
                {"type": "download", "sum": 400},
                {"type": "upload", "sum": 40},
            ],
            "inspected_day": [{"insight_type": "inspected", "sum": 5}],
            "inspected_month": [{"insight_type": "inspected", "sum": 6}],
            "inspected_week": [{"insight_type": "inspected", "sum": 7}],
            "notifications_has_unread": {"has_unread": True},
            "unprofiled_data_usage_day": [
                {"type": "download", "sum": 500},
                {"type": "upload", "sum": 50},
            ],
        }
    },
    "backup_internet_enabled": True,
    "band_steering": True,
    "premium_dns": {
        "ad_block_settings": {"enabled": True, "profiles": []},
        "dns_policies": {"block_malware": True},
    },
    "geo_ip": {
        "city": "Chicago",
        "countryCode": "US",
        "countryName": "United States",
        "isp": "ExampleISP",
        "postalCode": "60601",
        "region": "IL",
        "regionName": "Illinois",
    },
    "clients": {"count": 2},
    "ddns": {"enabled": True, "subdomain": "home"},
    "dns": {"caching": True, "mode": "automatic"},
    "fast_transition_enabled": True,
    "gateway_ip": "192.168.4.1",
    "guest_network": {"enabled": True, "name": "Guest", "password": "pw"},
    "health": {
        "eero_network": {"status": "green"},
        "internet": {"isp_up": True, "status": "green"},
    },
    "ipv6_upstream": True,
    "capabilities": {"mlo_mode": {"capable": True}, "premium": {"capable": True}},
    "mlo_mode": "single",
    "name": "TestNetwork",
    "nickname_label": "Home",
    "password": "wifipw",
    "temporary_flags": {"hide_5g": {"value": True, "expires_on": "2030-01-01"}},
    "power_saving": True,
    "updates": {
        "preferred_update_hour": 0,
        "manifest_resource": "manifest",
        "release_notes": {"history": [{"os_version": "1.0.0"}], "target": {"os_version": "2.0.0"}},
    },
    "premium_status": "active",
    "entitlements": {"features": ["premium"]},
    "ip_settings": {"public_ip": "1.2.3.4"},
    "speed": {
        "date": "2024-01-01",
        "down": {"value": 100, "units": "Mbps"},
        "up": {"value": 10, "units": "Mbps"},
    },
    "sqm": True,
    "status": "connected",
    "thread": {
        "active_operational_dataset": "dataset",
        "channel": 15,
        "commissioning_credential": "cred",
        "enabled": True,
        "master_key": "key",
        "name": "thread-net",
        "pan_id": "pan1",
        "xpan_id": "xpan1",
    },
    "upnp": True,
    "resources": {
        "insights": f"{NETWORK_URL}/insights",
        "reboot": f"{NETWORK_URL}/reboot",
        "settings": f"{NETWORK_URL}/settings",
        "thread": f"{NETWORK_URL}/thread",
        "updates": f"{NETWORK_URL}/updates",
    },
    "lease": {"dhcp": {"router": "192.168.4.1", "mask": "255.255.255.0"}},
    "wpa3": True,
    "eeros": {
        "data": [
            {
                "url": "/2.2/eeros/e1",
                "model": "eero 6",
                "gateway": True,
                "mac_address": "aa:bb",
                "location": "Office",
            }
        ]
    },
    "devices": {
        "data": [
            {
                "url": f"{NETWORK_URL}/devices/a",
                "mac": "a",
                "connected": True,
                "is_guest": False,
                "device_type": "laptop_computer",
            },
            {
                "url": f"{NETWORK_URL}/devices/b",
                "mac": "b",
                "connected": True,
                "is_guest": True,
                "device_type": "laptop_computer",
            },
        ]
    },
}


def test_simple_getters_against_a_fully_populated_envelope() -> None:
    hub = build_hub()
    network = make_network(hub, **FULL_DATA)

    assert network.adblock_day == 1
    assert network.adblock_month == 2
    assert network.adblock_week == 3
    assert network.app_events == [{"id": "e1"}]
    assert network.backup_internet_enabled is True
    assert network.band_steering is True
    assert network.block_malware is True
    assert network.blocked_day["blocked"] == 1
    assert network.blocked_day["botnet"] == 2
    assert network.blocked_month["malware"] == 3
    assert network.blocked_week["parked"] == 4
    assert network.city == "Chicago"
    assert network.clients_count == 2
    assert network.country_code == "US"
    assert network.country_name == "United States"
    assert network.data_usage_day == (100, 10)
    assert network.data_usage_month == (200, 20)
    assert network.data_usage_week == (300, 30)
    assert network.ddns_enabled is True
    assert network.ddns_subdomain == "home"
    assert network.dns_caching is True
    assert network.eeros_data_usage_summary_day == (400, 40)
    assert network.fast_transition_enabled is True
    assert len(network.firmware_history) == 1
    assert network.gateway_ip == "192.168.4.1"
    assert network.gateway_mac_address == "aa:bb"
    assert network.gateway_name == "Office"
    assert network.guest_network_enabled is True
    assert network.guest_network_name == "Guest"
    assert network.guest_network_password == "pw"
    assert network.health_eero_network_status == "green"
    assert network.health_internet_isp_up is True
    assert network.health_internet_status == "green"
    assert network.inspected_day == 5
    assert network.inspected_month == 6
    assert network.inspected_week == 7
    assert network.ipv6_upstream is True
    assert network.isp == "ExampleISP"
    assert network.mlo_mode == "single"
    assert network.manifest_resource == "manifest"
    assert network.nickname == "Home"
    assert 'TestNetwork "Home" (Chicago, Illinois)' == network.name_unique
    assert network.notifications_has_unread is True
    assert network.password == "wifipw"
    assert network.pause_5g_enabled is True
    assert network.pause_5g_expiration == "2030-01-01"
    assert network.postal_code == "60601"
    assert network.power_saving_enabled is True
    assert network.preferred_update_hour == "12am_1am"
    assert network.premium_capable is True
    assert network.premium_status == "active"
    assert network.premium_enabled is True
    assert network.public_ip == "1.2.3.4"
    assert network.region == "IL"
    assert network.region_name == "Illinois"
    assert network.speed_date == "2024-01-01"
    assert network.speed_down == (100, "Mbps")
    assert network.speed_up == (10, "Mbps")
    assert network.sqm is True
    assert network.ssid == "TestNetwork"
    assert network.status == "connected"
    assert network.target_firmware.os_version == "2.0.0"
    assert network.thread_active_operational_dataset == "dataset"
    assert network.thread_channel == 15
    assert network.thread_commissioning_credential == "cred"
    assert network.thread_enabled is True
    assert network.thread_master_key == "key"
    assert network.thread_name == "thread-net"
    assert network.thread_pan_id == "pan1"
    assert network.thread_xpan_id == "xpan1"
    assert network.unprofiled_data_usage_day == (500, 50)
    assert network.upnp is True
    assert network.url_insights == f"{NETWORK_URL}/insights"
    assert network.url_reboot == f"{NETWORK_URL}/reboot"
    assert network.url_settings == f"{NETWORK_URL}/settings"
    assert network.url_thread == f"{NETWORK_URL}/thread"
    assert network.url_updates == f"{NETWORK_URL}/updates"
    assert network.wan_router_ip == "192.168.4.1"
    assert network.wan_subnet_mask == "255.255.255.0"
    assert network.wpa3 is True

    assert network.connected_clients_count == 2
    assert network.connected_clients_count_computers_personal == 2
    assert network.connected_clients_count_entertainment == 0
    assert network.connected_clients_count_home == 0
    assert network.connected_clients_count_other == 0
    assert network.connected_guest_clients_count == 1
    assert network.connected_guest_clients_count_computers_personal == 1
    assert network.connected_guest_clients_count_entertainment == 0
    assert network.connected_guest_clients_count_home == 0
    assert network.connected_guest_clients_count_other == 0


def test_reservation_and_forward_count_none_when_not_a_dict() -> None:
    hub = build_hub()
    network = make_network(hub)
    assert network.reservation_count is None
    assert network.forward_count is None

    with_data = make_network(
        hub, reservations={"count": 3}, forwards={"count": 1}
    )
    assert with_data.reservation_count == 3
    assert with_data.forward_count == 1


def test_mlo_mode_raises_when_not_capable() -> None:
    hub = build_hub()
    network = make_network(hub, capabilities={})
    with pytest.raises(AttributeError):
        _ = network.mlo_mode


def test_mlo_mode_raises_when_value_does_not_parse() -> None:
    hub = build_hub()
    network = make_network(
        hub, capabilities={"mlo_mode": {"capable": True}}, mlo_mode="garbage"
    )
    with pytest.raises(AttributeError):
        _ = network.mlo_mode


def test_mlo_mode_parses_a_dict_shape() -> None:
    hub = build_hub()
    network = make_network(
        hub,
        capabilities={"mlo_mode": {"capable": True}},
        mlo_mode={"mode": "multi"},
    )
    assert network.mlo_mode == "multi"


def test_mlo_mode_options() -> None:
    hub = build_hub()
    network = make_network(hub)
    assert network.mlo_mode_options == ["disabled", "single", "multi"]


def test_notifications_has_unread_none_when_not_fetched() -> None:
    hub = build_hub()
    network = make_network(hub)
    assert network.notifications_has_unread is None


def test_premium_enabled_falls_back_to_premium_ok_when_no_entitlements() -> None:
    hub = build_hub()
    network = make_network(
        hub, capabilities={"premium": {"capable": True}}, premium_status="active"
    )
    assert network.premium_enabled is True


def test_name_unique_without_nickname_or_location() -> None:
    hub = build_hub()
    network = make_network(hub, name="Plain")
    assert network.name_unique == "Plain"


async def test_async_set_preferred_update_hour_ignores_unknown_value() -> None:
    hub = build_hub()
    network = make_network(hub)
    await network.async_set_preferred_update_hour("not-a-real-hour")
    assert hub.sdk.calls == []


def test_normalize_dns_server_falls_back_to_raw_string_on_bad_ip() -> None:
    """_same_dns_servers tolerates a non-IP string instead of raising."""
    assert eero_api.network._same_dns_servers(["not-an-ip"], ["not-an-ip"])
    assert not eero_api.network._same_dns_servers(["not-an-ip"], ["other"])


def test_network_init_defaults_data_to_empty_dict_when_none() -> None:
    hub = build_hub()
    network = eero_api.network.EeroNetwork(hub, None, None)
    assert network.data == {}


def test_network_ad_block_true_only_when_enabled_network_wide() -> None:
    hub = build_hub()
    enabled = make_network(
        hub, premium_dns={"ad_block_settings": {"enabled": True, "profiles": []}}
    )
    assert enabled.ad_block is True
    assert enabled.ad_block_status == eero_api.const.STATE_NETWORK

    per_profile = make_network(
        hub, premium_dns={"ad_block_settings": {"enabled": True, "profiles": ["p1"]}}
    )
    assert per_profile.ad_block is False
    assert per_profile.ad_block_status == eero_api.const.STATE_PROFILE

    disabled = make_network(hub)
    assert disabled.ad_block is False
    assert disabled.ad_block_status == eero_api.const.STATE_DISABLED


def test_adblock_day_month_week_return_none_when_no_matching_entry() -> None:
    hub = build_hub()
    network = make_network(hub, activity={"network": {"adblock_day": []}})
    assert network.adblock_day is None
    assert network.adblock_month is None
    assert network.adblock_week is None


async def test_forward_create_skips_non_dict_entries_before_matching() -> None:
    """A non-dict forward entry is ignored, not treated as a match: the write still happens."""
    sdk = FakeSDK({"forwards.create_forward": {}})
    hub = build_hub(sdk=sdk)
    network = make_network(hub, forwards={"data": ["not-a-dict"]})

    await network.async_create_port_forward(
        {"ip": "1.2.3.4", "client_port": 1, "gateway_port": 1, "protocol": "tcp"}
    )

    assert any(m == "create_forward" for _d, m, _a, _kw in sdk.calls)


def test_gateway_mac_address_and_name_none_when_no_gateway() -> None:
    hub = build_hub()
    network = make_network(
        hub,
        eeros={"data": [{"url": "/2.2/eeros/e1", "model": "eero 6", "gateway": False}]},
    )
    assert network.gateway_mac_address is None
    assert network.gateway_name is None


def test_inspected_day_month_week_return_none_when_no_matching_entry() -> None:
    hub = build_hub()
    network = make_network(hub, activity={"network": {"inspected_day": []}})
    assert network.inspected_day is None
    assert network.inspected_month is None
    assert network.inspected_week is None


def test_eeros_includes_beacon_model() -> None:
    hub = build_hub()
    network = make_network(
        hub,
        eeros={
            "data": [{"url": "/2.2/eeros/b1", "model": eero_api.const.MODEL_BEACON}]
        },
    )
    eeros = network.eeros
    assert len(eeros) == 1
    assert isinstance(eeros[0], eero_api.eero.EeroDeviceBeacon)
