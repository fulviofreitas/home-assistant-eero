"""Property coverage for EeroAccount and EeroBackupNetwork."""

from __future__ import annotations

from helpers import build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


def test_account_properties() -> None:
    hub = build_hub()
    account = eero_api.account.EeroAccount(
        hub,
        {
            "email": {"value": "user@example.com"},
            "log_id": "log-1",
            "name": "Jane",
            "phone": {"value": "+15555550123"},
            "premium_status": "active",
            "networks": {"data": [{"url": NETWORK_URL, "name": "Home"}]},
        },
    )
    assert account.email == "user@example.com"
    assert account.log_id == "log-1"
    assert account.name == "Jane"
    assert account.phone == "+15555550123"
    assert account.premium_status == "active"
    networks = account.networks
    assert len(networks) == 1
    assert networks[0].name == "Home"


def test_account_properties_default_to_none_when_missing() -> None:
    hub = build_hub()
    account = eero_api.account.EeroAccount(hub, {})
    assert account.email is None
    assert account.phone is None
    assert account.networks == []


def test_backup_network_properties() -> None:
    hub = build_hub()
    network = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL})
    backup = eero_api.backup_network.EeroBackupNetwork(
        hub,
        network,
        {
            "uuid": "bn1",
            "ssid": "Guest",
            "password": "secret",
            "created": "2024-01-01",
            "last_updated_at": "2024-02-01",
            "connectivity": {
                "backup_access_point_id": "bap1",
                "checked": "2024-02-02",
                "failure_reason": None,
                "status": "connected",
            },
            "enabled": True,
        },
    )
    assert backup.auto_join_enabled is True
    assert backup.backup_access_point_id == "bap1"
    assert backup.checked == "2024-02-02"
    assert backup.created == "2024-01-01"
    assert backup.failure_reason is None
    assert backup.id == "bn1"
    assert backup.last_updated_at == "2024-02-01"
    assert backup.name == "Guest"
    assert backup.password == "secret"
    assert backup.ssid == "Guest"
    assert backup.status == "connected"
    assert backup.uuid == "bn1"


def test_backup_network_properties_default_to_none() -> None:
    hub = build_hub()
    network = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL})
    backup = eero_api.backup_network.EeroBackupNetwork(hub, network, {})
    assert backup.auto_join_enabled is None
    assert backup.backup_access_point_id is None
    assert backup.checked is None
    assert backup.created is None
    assert backup.failure_reason is None
    assert backup.id is None
    assert backup.last_updated_at is None
    assert backup.name is None
    assert backup.password is None
    assert backup.ssid is None
    assert backup.status is None
    assert backup.uuid is None
