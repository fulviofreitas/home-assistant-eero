"""Coverage for EeroHub paths the other test modules don't exercise:
auth/session, account/network_ids, snapshot(), define_period(), and the
backup-access-point / updates-fallback branches of fetch_daily().
"""

from __future__ import annotations

import pytest

from eero.exceptions import EeroAuthenticationException
from helpers import FakeSDK, build_hub, eero_api, fixture

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


def test_api_url_passes_through_an_absolute_url_unchanged() -> None:
    absolute = "https://api-user.e2ro.com/2.2/networks/1/settings"
    assert eero_api.api_url(absolute) == absolute


async def test_async_set_token_stores_token_on_the_sdk_and_the_hub() -> None:
    sdk = FakeSDK({})
    hub = build_hub(sdk=sdk)

    await hub.async_set_token("NEW-TOKEN")

    assert sdk.auth.tokens_set == ["NEW-TOKEN"]
    assert hub.user_token == "NEW-TOKEN"


async def test_login_raises_when_the_sdk_returns_no_token() -> None:
    sdk = FakeSDK({"auth.login": False})
    hub = build_hub(sdk=sdk)

    with pytest.raises(EeroAuthenticationException):
        await hub.login("user@example.com")


async def test_login_verify_raises_when_the_code_is_rejected() -> None:
    sdk = FakeSDK({"auth.verify": False})
    hub = build_hub(sdk=sdk)

    with pytest.raises(EeroAuthenticationException):
        await hub.login_verify("000000")


async def test_login_verify_returns_the_account_on_success() -> None:
    sdk = FakeSDK(
        {
            "auth.verify": True,
            "GET /account": {"name": "Jane", "networks": {"data": []}},
        },
        token="SESSION-TOKEN",
    )
    hub = build_hub(sdk=sdk)

    account = await hub.login_verify("123456")

    assert account["name"] == "Jane"
    assert hub.user_token == "SESSION-TOKEN"


async def test_token_raises_when_the_sdk_has_none() -> None:
    sdk = FakeSDK({}, token=None)
    hub = build_hub(sdk=sdk)

    with pytest.raises(EeroAuthenticationException):
        await hub.get("/2.2/networks/1/settings")


async def test_get_account_raises_when_the_response_has_no_networks() -> None:
    sdk = FakeSDK({"GET /account": {"name": "Jane"}})
    hub = build_hub(sdk=sdk)

    with pytest.raises(eero_api.EeroException):
        await hub.get_account()


def test_network_ids_skips_an_entry_with_no_url() -> None:
    account = {
        "networks": {
            "data": [{"url": f"{NETWORK_URL}/"}, {"name": "no url"}]
        }
    }
    assert eero_api.EeroHub.network_ids(account) == [NETWORK_ID]


async def test_snapshot_fetches_fast_and_daily_tiers_for_every_network() -> None:
    sdk = FakeSDK(
        {
            "GET /account": {
                "name": "Jane",
                "networks": {"data": [{"url": NETWORK_URL}]},
            },
            "networks.get_network": fixture("network"),
            "eeros.get_eeros": [],
            "devices.get_devices": [],
            "profiles.get_profiles": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)

    account = await hub.snapshot()

    assert account.networks[0].id == NETWORK_ID
    # "*" is never resolved into a real schedules read.
    assert not any(m == "get_schedules" for _d, m, _a, _kw in sdk.calls)


@pytest.mark.parametrize("period", ["day", "week", "month", "unknown"])
def test_define_period_returns_a_window_for_every_known_period(period) -> None:
    hub = build_hub()

    start, end, cadence = hub.define_period(period=period, timezone="UTC")

    if period == "unknown":
        assert (start, end, cadence) == (None, None, None)
    else:
        assert start is not None
        assert end is not None
        assert cadence is not None


async def test_backup_access_points_and_internet_fetched_when_premium_and_capable() -> None:
    sdk = FakeSDK(
        {
            "entitlements.get_features": {"features": ["premium"]},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
            "backup_access_points.list": [{"uuid": "bn1"}],
            "backup.get_backup_internet": {"backup_internet_enabled": True},
        }
    )
    hub = build_hub(sdk=sdk)
    network = {
        "url": NETWORK_URL,
        "capabilities": {
            "backup_access_point": {"capable": True, "requirements": {"premium": True}},
            "premium": {"capable": True},
        },
        "premium_status": "active",
        "resources": {},
    }
    config = eero_api.EeroUpdateConfig(get_backup_access_points=True)

    daily = await hub.fetch_daily(NETWORK_ID, network, config)

    assert daily["backup_access_points"] == [{"uuid": "bn1"}]
    assert daily["backup_internet"]["backup_internet_enabled"] is True


async def test_backup_access_points_skipped_when_not_premium() -> None:
    sdk = FakeSDK(
        {
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    network = {
        "url": NETWORK_URL,
        "capabilities": {
            "backup_access_point": {"capable": True, "requirements": {}},
            "premium": {"capable": False},
        },
        "premium_status": "free",
        "resources": {},
    }
    config = eero_api.EeroUpdateConfig(get_backup_access_points=True)

    daily = await hub.fetch_daily(NETWORK_ID, network, config)

    assert "backup_access_points" not in daily


async def test_updates_falls_back_to_the_network_envelope_when_not_a_dict() -> None:
    sdk = FakeSDK(
        {
            "entitlements.get_features": {"features": []},
            "updates.get_updates": None,
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    network = {
        "url": NETWORK_URL,
        "resources": {},
        "updates": {"preferred_update_hour": 1},
    }
    config = eero_api.EeroUpdateConfig()

    daily = await hub.fetch_daily(NETWORK_ID, network, config)

    assert daily["updates"]["preferred_update_hour"] == 1


async def test_fetch_hourly_profiles_activity_is_keyed_per_profile_id() -> None:
    sdk = FakeSDK(
        {
            "insights.get_profile_insights": {"insights": [{"insight_type": "adblock", "sum": 1}]},
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(
        profiles=["p1", "p2"], activity={"profiles": ["adblock_day"]}
    )

    activity = await hub.fetch_hourly(NETWORK_ID, {}, config)

    assert set(activity["profiles"]["adblock_day"].keys()) == {"p1", "p2"}
    assert any(
        d == "insights" and m == "get_profile_insights" and a[1] == "p1"
        for d, m, a, _kw in sdk.calls
    )
    assert any(
        d == "insights" and m == "get_profile_insights" and a[1] == "p2"
        for d, m, a, _kw in sdk.calls
    )


async def test_fetch_hourly_non_profile_resource_calls_update_activity_once() -> None:
    sdk = FakeSDK({"insights.get_insights": {"insights": [{"insight_type": "adblock", "sum": 1}]}})
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(activity={"network": ["adblock_day"]})

    activity = await hub.fetch_hourly(NETWORK_ID, {}, config)

    assert activity["network"]["adblock_day"] == [{"insight_type": "adblock", "sum": 1}]


async def test_fetch_daily_never_resolves_the_snapshot_wildcard_profile() -> None:
    """profiles=["*"] (only ever set by snapshot()) is skipped, not read literally."""
    sdk = FakeSDK(
        {
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    hub = build_hub(sdk=sdk)
    network = {"url": NETWORK_URL, "resources": {}}
    config = eero_api.EeroUpdateConfig(profiles=["*"], get_schedules=True)

    daily = await hub.fetch_daily(NETWORK_ID, network, config)

    assert daily["schedules"] == {}
    assert not any(m == "get_schedules" for _d, m, _a, _kw in sdk.calls)


async def test_release_notes_rejects_non_json_object_body() -> None:
    from helpers import FakeHTTPSession

    url = "https://eeroassets.com/manifest-bad"
    session = FakeHTTPSession({url: (200, "[1, 2, 3]")})
    hub = build_hub(session=session)

    with pytest.raises(eero_api.EeroException):
        await hub.get_release_notes(url)


async def test_an_empty_list_activity_stays_a_list() -> None:
    """A series that is an empty list must not collapse into None.

    The properties iterate whatever update_activity returns, so None made
    every sensor reading that activity raise and be skipped.
    """
    sdk = FakeSDK({"data_usage.get_data_usage": []})
    hub = build_hub(sdk=sdk)

    series = await hub.update_activity("data_usage_day", NETWORK_ID, "network", "UTC")

    assert series == []


async def test_release_notes_rejects_invalid_json() -> None:
    from helpers import FakeHTTPSession

    url = "https://eeroassets.com/manifest-garbage"
    session = FakeHTTPSession({url: (200, "not json")})
    hub = build_hub(session=session)

    with pytest.raises(eero_api.EeroException):
        await hub.get_release_notes(url)


def test_assemble_adds_backup_access_points_and_backup_internet_from_the_daily_tier() -> (
    None
):
    hub = build_hub()
    fast = {NETWORK_ID: {"network": {"url": NETWORK_URL}}}
    daily = {
        NETWORK_ID: {
            "backup_access_points": [{"uuid": "bn1"}],
            "backup_internet": {"backup_internet_enabled": True},
        }
    }

    account = hub.assemble({"name": "Jane"}, fast, {}, daily)

    network = account.networks[0]
    assert network.backup_networks[0].uuid == "bn1"
    assert network.backup_internet_enabled is True


def test_assemble_ignores_backup_internet_without_the_enabled_key() -> None:
    hub = build_hub()
    fast = {NETWORK_ID: {"network": {"url": NETWORK_URL}}}
    daily = {NETWORK_ID: {"backup_internet": {"other_field": 1}}}

    account = hub.assemble({"name": "Jane"}, fast, {}, daily)

    assert "backup_internet_enabled" not in account.networks[0].data
