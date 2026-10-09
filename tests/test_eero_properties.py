"""Property coverage for EeroDevice/EeroDeviceBeacon."""

from __future__ import annotations

from datetime import time as _time

from helpers import FakeSDK, build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"
EERO_URL = "/2.2/eeros/e1"


def make_network(hub, **overrides):
    data = {"url": NETWORK_URL}
    data.update(overrides)
    return eero_api.network.EeroNetwork(hub, None, data)


def make_eero(hub, network_overrides=None, **eero_overrides):
    network = make_network(hub, **(network_overrides or {}))
    data = {"url": EERO_URL}
    data.update(eero_overrides)
    return eero_api.eero.EeroDevice(hub, network, data)


def make_beacon(hub, network_overrides=None, **eero_overrides):
    network = make_network(hub, **(network_overrides or {}))
    data = {"url": EERO_URL}
    data.update(eero_overrides)
    return eero_api.eero.EeroDeviceBeacon(hub, network, data)


def test_connected_clients_count_and_names() -> None:
    hub = build_hub()
    eero = make_eero(
        hub,
        connected_clients_count=3,
        location="Office",
        network_overrides={
            "devices": {
                "data": [
                    {"url": f"{NETWORK_URL}/devices/a", "mac": "a", "source": {"location": "Office"}, "nickname": "A"},
                    {"url": f"{NETWORK_URL}/devices/b", "mac": "b", "source": {"location": "Other"}, "nickname": "B"},
                ]
            }
        },
    )
    assert eero.connected_clients_count == 3
    assert eero.connected_clients_names == ["A"]


def test_current_firmware_falls_back_to_empty_firmware_when_no_match() -> None:
    hub = build_hub()
    no_os_version = make_eero(hub)
    assert no_os_version.current_firmware.os_version is None

    no_history_match = make_eero(
        hub,
        os_version="9.9.9-xyz",
        network_overrides={"updates": {"release_notes": {"history": []}}},
    )
    assert no_history_match.current_firmware.os_version is None


def test_simple_getters() -> None:
    hub = build_hub()
    eero = make_eero(
        hub,
        mac_address="aa:bb",
        model="eero 6",
        model_number="A010001",
        serial="S123",
        status="green",
        led_brightness=50,
        led_on=True,
        update_available=True,
        resources={"led_action": f"{EERO_URL}/led", "reboot": f"{EERO_URL}/reboot"},
    )
    assert eero.mac_address == "aa:bb"
    assert eero.model == "eero 6"
    assert eero.model_number == "A010001"
    assert eero.serial == "S123"
    assert eero.status == "green"
    assert eero.status_light_brightness == 50
    assert eero.status_light_enabled is True
    assert eero.update_available is True
    assert eero.url_led == f"{EERO_URL}/led"
    assert eero.url_reboot == f"{EERO_URL}/reboot"


def test_target_firmware_uses_network_target_when_support_not_expired() -> None:
    hub = build_hub()
    eero = make_eero(
        hub,
        update_status={"support_expired": False},
        network_overrides={"updates": {"release_notes": {"target": {"os_version": "3.0.0"}}}},
    )
    assert eero.target_firmware.os_version == "3.0.0"


def test_ports_returns_empty_list_when_interfaces_missing_or_wrong_type() -> None:
    hub = build_hub()
    no_connections = make_eero(hub)
    assert no_connections.ports == []

    wrong_type = make_eero(
        hub,
        network_overrides={"connections": {"e1": {"ports": {"interfaces": "not-a-list"}}}},
    )
    assert wrong_type.ports == []

    with_ports = make_eero(
        hub,
        network_overrides={
            "connections": {
                "e1": {"ports": {"interfaces": [{"interface_number": 1}, "bad"]}}
            }
        },
    )
    assert with_ports.ports == [{"interface_number": 1}]


def test_nightlight_brightness_percentage_and_enabled() -> None:
    hub = build_hub()
    beacon = make_beacon(
        hub, nightlight={"brightness_percentage": 40, "enabled": True}
    )
    assert beacon.nightlight_brightness_percentage == 40
    assert beacon.nightlight_enabled is True


async def test_async_set_nightlight_brightness_percentage_rounds_to_int() -> None:
    sdk = FakeSDK({"eeros.set_nightlight": {}})
    hub = build_hub(sdk=sdk)
    beacon = make_beacon(hub, nightlight={"schedule": {"on": "20:00", "off": "07:00"}})

    await beacon.async_set_nightlight_brightness_percentage(42.9)

    calls = [kw for _d, m, _a, kw in sdk.calls if m == "set_nightlight"]
    assert calls[0]["brightness_percentage"] == 42


def test_nightlight_mode_options() -> None:
    hub = build_hub()
    beacon = make_beacon(hub)
    assert beacon.nightlight_mode_options == [
        eero_api.const.STATE_AMBIENT,
        eero_api.const.STATE_DISABLED,
        eero_api.const.STATE_SCHEDULE,
    ]


def test_data_usage_day_month_week_matched_by_url() -> None:
    hub = build_hub()
    entry = {"url": EERO_URL, "download": 10, "upload": 1}
    eero = make_eero(
        hub,
        network_overrides={
            "activity": {
                "eeros": {
                    "data_usage_day": [entry],
                    "data_usage_month": [entry],
                    "data_usage_week": [entry],
                }
            }
        },
    )
    assert eero.data_usage_day == (10, 1)
    assert eero.data_usage_month == (10, 1)
    assert eero.data_usage_week == (10, 1)


def test_data_usage_day_none_when_no_match() -> None:
    hub = build_hub()
    eero = make_eero(
        hub, network_overrides={"activity": {"eeros": {"data_usage_day": []}}}
    )
    assert eero.data_usage_day == (None, None)


def test_data_usage_month_week_none_when_no_match() -> None:
    hub = build_hub()
    eero = make_eero(
        hub,
        network_overrides={
            "activity": {"eeros": {"data_usage_month": [], "data_usage_week": []}}
        },
    )
    assert eero.data_usage_month == (None, None)
    assert eero.data_usage_week == (None, None)


def test_name_long() -> None:
    hub = build_hub()
    eero = make_eero(hub, location="Office")
    assert eero.name_long == "Office Eero"


def test_support_expiration_string_and_support_expired() -> None:
    hub = build_hub()
    eero = make_eero(
        hub,
        update_status={"support_expiration_string": "2030-01-01", "support_expired": True},
    )
    assert eero.support_expiration_string == "2030-01-01"
    assert eero.support_expired is True


def test_target_firmware_falls_back_to_current_when_support_expired() -> None:
    hub = build_hub()
    eero = make_eero(hub, update_status={"support_expired": True}, os_version="1.0.0-abc")
    assert eero.target_firmware.os_version == eero.current_firmware.os_version


def test_url_led_and_url_reboot() -> None:
    hub = build_hub()
    eero = make_eero(hub, resources={"led_action": f"{EERO_URL}/led", "reboot": f"{EERO_URL}/reboot"})
    assert eero.url_led == f"{EERO_URL}/led"
    assert eero.url_reboot == f"{EERO_URL}/reboot"


def test_format_time_returns_none_for_non_int() -> None:
    hub = build_hub()
    beacon = make_beacon(hub)
    assert beacon._format_time("not-an-int") is None
    assert beacon._format_time(5) == "05"
    assert beacon._format_time(15) == "15"


def test_nightlight_mode_disabled_ambient_and_schedule() -> None:
    hub = build_hub()
    disabled = make_beacon(hub, nightlight={"enabled": False})
    assert disabled.nightlight_mode == eero_api.const.STATE_DISABLED

    ambient = make_beacon(
        hub, nightlight={"enabled": True, "schedule": {"enabled": False}}
    )
    assert ambient.nightlight_mode == eero_api.const.STATE_AMBIENT

    scheduled = make_beacon(
        hub, nightlight={"enabled": True, "schedule": {"enabled": True}}
    )
    assert scheduled.nightlight_mode == eero_api.const.STATE_SCHEDULE


async def test_async_set_nightlight_mode_routes_to_each_branch() -> None:
    sdk = FakeSDK({"eeros.set_nightlight": {}})
    hub = build_hub(sdk=sdk)
    beacon = make_beacon(
        hub,
        nightlight={
            "enabled": True,
            "schedule": {"enabled": True, "on": "20:00", "off": "07:00"},
        },
    )

    await beacon.async_set_nightlight_mode(eero_api.const.STATE_DISABLED)
    await beacon.async_set_nightlight_mode(eero_api.const.STATE_AMBIENT)
    await beacon.async_set_nightlight_mode(eero_api.const.STATE_SCHEDULE)

    calls = [kw for _d, m, _a, kw in sdk.calls if m == "set_nightlight"]
    assert calls[0]["enabled"] is False
    assert calls[1]["enabled"] is True
    assert calls[1]["schedule"] == {"enabled": False}
    assert calls[2]["enabled"] is True
    assert calls[2]["schedule"] == {"enabled": True, "on": "20:00", "off": "07:00"}


def test_nightlight_schedule_hour_minute_parsing() -> None:
    hub = build_hub()
    beacon = make_beacon(
        hub, nightlight={"schedule": {"on": "20:15", "off": "07:05"}}
    )
    assert beacon.nightlight_schedule_on_hour == "20"
    assert beacon.nightlight_schedule_on_minute == "15"
    assert beacon.nightlight_schedule_off_hour == "07"
    assert beacon.nightlight_schedule_off_minute == "05"
    assert beacon.nightlight_schedule_on == _time(20, 15)
    assert beacon.nightlight_schedule_off == _time(7, 5)


async def test_async_set_nightlight_schedule_on_and_off_preserve_the_other_field() -> None:
    sdk = FakeSDK({"eeros.set_nightlight": {}})
    hub = build_hub(sdk=sdk)
    beacon = make_beacon(
        hub, nightlight={"schedule": {"on": "20:00", "off": "07:00"}}
    )

    await beacon.async_set_nightlight_schedule_on(_time(21, 30))
    await beacon.async_set_nightlight_schedule_off(_time(6, 45))

    calls = [kw for _d, m, _a, kw in sdk.calls if m == "set_nightlight"]
    assert calls[0]["schedule"] == {"enabled": True, "on": "21:30", "off": "07:00"}
    assert calls[1]["schedule"] == {"enabled": True, "on": "20:00", "off": "06:45"}


async def test_async_set_nightlight_schedule_noop_when_times_not_strings() -> None:
    sdk = FakeSDK({})
    hub = build_hub(sdk=sdk)
    beacon = make_beacon(hub)

    await beacon.async_set_nightlight_schedule(None, None)

    assert sdk.calls == []
