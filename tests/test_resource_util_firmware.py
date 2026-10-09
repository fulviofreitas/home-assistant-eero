"""Property coverage for EeroResource, firmware, and api/util helpers."""

from __future__ import annotations

from helpers import build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


def test_resource_id_is_none_for_account_and_backup_network() -> None:
    hub = build_hub()
    account = eero_api.account.EeroAccount(hub, {})
    assert account.id is None

    network = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL})
    backup = eero_api.backup_network.EeroBackupNetwork(hub, network, {"uuid": "bn1"})
    # id is overridden on EeroBackupNetwork itself (returns uuid); use the base
    # EeroResource.id behaviour directly to exercise the "no match" branch.
    assert eero_api.resource.EeroResource.id.fget(backup) is None


def test_is_eero_beacon_true_for_beacon_instances() -> None:
    hub = build_hub()
    network = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL})
    beacon = eero_api.eero.EeroDeviceBeacon(hub, network, {"url": "/2.2/eeros/b1"})
    device = eero_api.eero.EeroDevice(hub, network, {"url": "/2.2/eeros/d1"})
    assert beacon.is_eero_beacon is True
    assert device.is_eero_beacon is False


def test_url_for_account_uses_the_fixed_account_url() -> None:
    hub = build_hub()
    account = eero_api.account.EeroAccount(hub, {})
    assert account.url == eero_api.const.URL_ACCOUNT


def test_firmware_properties_default_to_none_when_no_data() -> None:
    firmware = eero_api.firmware.EeroFirmware()
    assert firmware.features is None
    assert firmware.os_version is None
    assert firmware.release_date is None
    assert firmware.title is None


def test_firmware_properties_read_from_data() -> None:
    firmware = eero_api.firmware.EeroFirmware(
        {
            "features": ["a", "b"],
            "os_version": "1.0.0",
            "release_date": "2024-01-01",
            "title": "Release",
        }
    )
    assert firmware.features == ["a", "b"]
    assert firmware.os_version == "1.0.0"
    assert firmware.release_date == "2024-01-01"
    assert firmware.title == "Release"


def test_backup_access_point_ok_requires_capable_and_all_requirements_true() -> None:
    assert eero_api.util.backup_access_point_ok(True, {"a": True, "b": True}) is True
    assert eero_api.util.backup_access_point_ok(True, {"a": True, "b": False}) is False
    assert eero_api.util.backup_access_point_ok(False, {"a": True}) is False
    assert eero_api.util.backup_access_point_ok(True, None) is True
