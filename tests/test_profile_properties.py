"""Property coverage for EeroProfile: read-side behaviour the setter table doesn't exercise."""

from __future__ import annotations

from datetime import time as _time

from helpers import FakeSDK, build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"
PROFILE_URL = f"{NETWORK_URL}/profiles/p1"


def make_network(hub, **overrides):
    data = {"url": NETWORK_URL, "name": "TestNetwork"}
    data.update(overrides)
    return eero_api.network.EeroNetwork(hub, None, data)


def make_profile(hub, network_overrides=None, **profile_overrides):
    network = make_network(hub, **(network_overrides or {}))
    data = {"url": PROFILE_URL}
    data.update(profile_overrides)
    return eero_api.profile.EeroProfile(hub, network, data)


def test_ad_block_true_only_when_enabled_and_profile_listed() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "premium_dns": {
                "ad_block_settings": {"enabled": True, "profiles": [PROFILE_URL]}
            }
        },
    )
    assert profile.ad_block is True


def test_ad_block_false_when_profile_not_listed_or_disabled() -> None:
    hub = build_hub()
    # Disabled entirely.
    disabled = make_profile(
        hub,
        network_overrides={
            "premium_dns": {"ad_block_settings": {"enabled": False, "profiles": [PROFILE_URL]}}
        },
    )
    assert disabled.ad_block is False
    # Enabled, but this profile is not in the list.
    not_listed = make_profile(
        hub,
        network_overrides={
            "premium_dns": {"ad_block_settings": {"enabled": True, "profiles": []}}
        },
    )
    assert not_listed.ad_block is False


async def test_async_set_ad_block_adds_profile_to_existing_list() -> None:
    sdk = FakeSDK({f"POST {NETWORK_URL}/dns_policies/adblock": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "premium_dns": {"ad_block_settings": {"enabled": True, "profiles": ["other"]}}
        },
    )

    await profile.async_set_ad_block(True)

    _domain, _method, _args, kwargs = sdk.calls[-1]
    assert kwargs["json"] == {"enable": True, "profiles": ["other", PROFILE_URL]}


async def test_async_set_ad_block_removes_profile_from_list() -> None:
    sdk = FakeSDK({f"POST {NETWORK_URL}/dns_policies/adblock": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "premium_dns": {
                "ad_block_settings": {"enabled": True, "profiles": [PROFILE_URL, "other"]}
            }
        },
    )

    await profile.async_set_ad_block(False)

    _domain, _method, _args, kwargs = sdk.calls[-1]
    assert kwargs["json"] == {"enable": True, "profiles": ["other"]}


async def test_async_set_ad_block_disable_clears_enable_flag_when_list_empties() -> None:
    sdk = FakeSDK({f"POST {NETWORK_URL}/dns_policies/adblock": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "premium_dns": {"ad_block_settings": {"enabled": True, "profiles": [PROFILE_URL]}}
        },
    )

    await profile.async_set_ad_block(False)

    _domain, _method, _args, kwargs = sdk.calls[-1]
    assert kwargs["json"] == {"enable": False, "profiles": []}


def test_adblock_day_month_week_sum_from_insights() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "activity": {
                "profiles": {
                    "adblock_day": {"p1": [{"insight_type": "adblock", "sum": 5}]},
                    "adblock_month": {"p1": [{"insight_type": "adblock", "sum": 50}]},
                    "adblock_week": {"p1": [{"insight_type": "adblock", "sum": 15}]},
                }
            }
        },
    )
    assert profile.adblock_day == 5
    assert profile.adblock_month == 50
    assert profile.adblock_week == 15


def test_insight_sum_returns_none_when_series_not_a_dict_or_entry_missing() -> None:
    hub = build_hub()
    not_a_dict = make_profile(
        hub, network_overrides={"activity": {"profiles": {"adblock_day": []}}}
    )
    assert not_a_dict.adblock_day is None

    no_matching_type = make_profile(
        hub,
        network_overrides={
            "activity": {
                "profiles": {"adblock_day": {"p1": [{"insight_type": "other", "sum": 1}]}}
            }
        },
    )
    assert no_matching_type.adblock_day is None

    missing_profile_id = make_profile(
        hub, network_overrides={"activity": {"profiles": {"adblock_day": {}}}}
    )
    assert missing_profile_id.adblock_day is None


def test_bedtime_entries_ignored_when_schedules_missing_or_not_dict() -> None:
    hub = build_hub()
    profile = make_profile(hub)
    assert profile.bedtime_enabled is None
    assert profile.bedtime_weekday_start is None

    not_dict = make_profile(hub, network_overrides={"schedules": []})
    assert not_dict.bedtime_enabled is None


def test_bedtime_entries_skips_non_bedtime_and_non_dict_entries() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    "not-a-dict",
                    {"name": "Something Else", "days": list(eero_api.profile.WEEKDAYS)},
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": True,
                        "start": "21:00",
                        "end": "06:00",
                    },
                    {
                        "name": "bedtime",
                        "days": list(eero_api.profile.WEEKEND),
                        "enabled": False,
                        "start": "23:00",
                        "end": "08:00",
                    },
                ]
            }
        },
    )
    assert profile.bedtime_enabled is True
    assert profile.bedtime_weekday_start == _time(21, 0)
    assert profile.bedtime_weekday_end == _time(6, 0)
    assert profile.bedtime_weekend_start == _time(23, 0)
    assert profile.bedtime_weekend_end == _time(8, 0)


def test_bedtime_enabled_false_when_both_entries_disabled() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": False,
                    }
                ]
            }
        },
    )
    assert profile.bedtime_enabled is False


def test_parse_hhmm_returns_none_for_malformed_value() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": True,
                        "start": "not-a-time",
                    }
                ]
            }
        },
    )
    assert profile.bedtime_weekday_start is None


async def test_async_set_bedtime_enabled_skips_already_enabled_entries() -> None:
    """No SDK call at all when both weekday and weekend are already enabled."""
    sdk = FakeSDK({})
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": True,
                    },
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKEND),
                        "enabled": True,
                    },
                ]
            }
        },
    )

    await profile.async_set_bedtime_enabled(True)

    assert sdk.calls == []


async def test_async_set_bedtime_enabled_disables_existing_entries() -> None:
    sdk = FakeSDK({"schedule.update_schedule": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": True,
                    },
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKEND),
                        "enabled": True,
                    },
                ]
            }
        },
    )

    await profile.async_set_bedtime_enabled(False)

    disabled_calls = [kw for d, m, a, kw in sdk.calls if m == "update_schedule"]
    assert len(disabled_calls) == 2
    assert all(kw.get("enabled") is False for kw in disabled_calls)


async def test_async_set_bedtime_enabled_reenables_an_existing_disabled_entry() -> None:
    sdk = FakeSDK(
        {"schedule.update_schedule": {}, "schedule.set_weekend_bedtime": {}}
    )
    hub = build_hub(sdk=sdk)
    profile = make_profile(
        hub,
        network_overrides={
            "schedules": {
                "p1": [
                    {
                        "name": "Bedtime",
                        "days": list(eero_api.profile.WEEKDAYS),
                        "enabled": False,
                    }
                ]
            }
        },
    )

    await profile.async_set_bedtime_enabled(True)

    assert any(
        kw.get("enabled") is True
        for _d, m, _a, kw in sdk.calls
        if m == "update_schedule"
    )


async def test_async_set_bedtime_weekday_end_and_weekend_start_delegate() -> None:
    sdk = FakeSDK({"schedule.set_weekday_bedtime": {}, "schedule.set_weekend_bedtime": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(hub)

    await profile.async_set_bedtime_weekday_end(_time(7, 15))
    await profile.async_set_bedtime_weekend_start(_time(22, 45))

    assert any(
        d == "schedule" and m == "set_weekday_bedtime" and a[3] == "07:15"
        for d, m, a, _kw in sdk.calls
    )
    assert any(
        d == "schedule" and m == "set_weekend_bedtime" and a[2] == "22:45"
        for d, m, a, _kw in sdk.calls
    )


async def test_async_set_bedtime_time_uses_default_for_the_other_field_when_creating() -> None:
    sdk = FakeSDK({"schedule.set_weekend_bedtime": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(hub)

    await profile.async_set_bedtime_weekend_end(_time(8, 30))

    call = next(
        (a, kw) for d, m, a, kw in sdk.calls if d == "schedule" and m == "set_weekend_bedtime"
    )
    args, _kwargs = call
    assert args == (NETWORK_ID, "p1", eero_api.profile._DEFAULT_BEDTIME_START, "08:30")


def test_block_properties_read_unified_content_filters() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        unified_content_filters={
            "dns_policies": {
                "block_gaming_content": True,
                "block_illegal_content": True,
                "block_messaging_content": False,
                "block_pornographic_content": True,
                "block_shopping_content": False,
                "block_social_content": True,
                "block_streaming_content": False,
                "block_violent_content": True,
                "safe_search_enabled": True,
                "youtube_restricted": False,
            }
        },
    )
    assert profile.block_gaming_content is True
    assert profile.block_illegal_content is True
    assert profile.block_messaging_content is False
    assert profile.block_pornographic_content is True
    assert profile.block_shopping_content is False
    assert profile.block_social_content is True
    assert profile.block_streaming_content is False
    assert profile.block_violent_content is True
    assert profile.safe_search_enabled is True
    assert profile.youtube_restricted is False


def test_block_properties_missing_filters_are_none() -> None:
    hub = build_hub()
    profile = make_profile(hub)
    assert profile.block_gaming_content is None
    assert profile.block_illegal_content is None
    assert profile.block_messaging_content is None
    assert profile.block_pornographic_content is None
    assert profile.block_shopping_content is None
    assert profile.block_social_content is None
    assert profile.block_streaming_content is None
    assert profile.block_violent_content is None
    assert profile.safe_search_enabled is None
    assert profile.youtube_restricted is None


async def test_block_setters_post_expected_json() -> None:
    url = f"{NETWORK_URL}/dns_policies/profiles/p1"
    sdk = FakeSDK({f"POST {url}": {}})
    hub = build_hub(sdk=sdk)
    profile = make_profile(hub)

    await profile.async_set_block_gaming_content(True)
    await profile.async_set_block_illegal_content(True)
    await profile.async_set_block_messaging_content(True)
    await profile.async_set_block_pornographic_content(True)
    await profile.async_set_block_shopping_content(True)
    await profile.async_set_block_social_content(True)
    await profile.async_set_block_streaming_content(True)
    await profile.async_set_block_violent_content(True)
    await profile.async_set_safe_search_enabled(True)
    await profile.async_set_youtube_restricted(True)

    bodies = [kw.get("json") for _d, _m, _a, kw in sdk.calls]
    assert {"block_gaming_content": True} in bodies
    assert {"block_illegal_content": True} in bodies
    assert {"block_messaging_content": True} in bodies
    assert {"block_pornographic_content": True} in bodies
    assert {"block_shopping_content": True} in bodies
    assert {"block_social_content": True} in bodies
    assert {"block_streaming_content": True} in bodies
    assert {"block_violent_content": True} in bodies
    assert {"safe_search_enabled": True} in bodies
    assert {"youtube_restricted": True} in bodies


def test_blocked_applications_count_and_block_apps_enabled() -> None:
    hub = build_hub()
    empty = make_profile(hub)
    assert empty.blocked_applications == []
    assert empty.blocked_applications_count == 0
    assert empty.block_apps_enabled is False

    with_apps = make_profile(hub, premium_dns={"blocked_applications": ["netflix", "hulu"]})
    assert with_apps.blocked_applications == ["netflix", "hulu"]
    assert with_apps.blocked_applications_count == 2
    assert with_apps.block_apps_enabled is True


def test_blocked_day_month_week() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "activity": {
                "profiles": {
                    "blocked_day": {"p1": [{"insight_type": "blocked", "sum": 1}]},
                    "blocked_month": {"p1": [{"insight_type": "blocked", "sum": 2}]},
                    "blocked_week": {"p1": [{"insight_type": "blocked", "sum": 3}]},
                }
            }
        },
    )
    assert profile.blocked_day == 1
    assert profile.blocked_month == 2
    assert profile.blocked_week == 3


def test_connected_and_connected_clients() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        devices=[
            {"url": f"{NETWORK_URL}/devices/a", "mac": "a", "connected": True, "nickname": "A"},
            {"url": f"{NETWORK_URL}/devices/b", "mac": "b", "connected": False, "nickname": "B"},
        ],
    )
    assert profile.connected is True
    assert profile.connected_clients_count == 1
    assert profile.connected_clients_names == ["A"]

    empty = make_profile(hub)
    assert empty.connected is False
    assert empty.connected_clients_count == 0


def test_data_usage_day_month_week() -> None:
    hub = build_hub()
    series = [{"type": "download", "sum": 100}, {"type": "upload", "sum": 20}]
    profile = make_profile(
        hub,
        network_overrides={
            "activity": {
                "profiles": {
                    "data_usage_day": {"p1": series},
                    "data_usage_month": {"p1": series},
                    "data_usage_week": {"p1": series},
                }
            }
        },
    )
    assert profile.data_usage_day == (100, 20)
    assert profile.data_usage_month == (100, 20)
    assert profile.data_usage_week == (100, 20)

    empty = make_profile(hub)
    assert empty.data_usage_day == (None, None)


def test_inspected_day_month_week() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        network_overrides={
            "activity": {
                "profiles": {
                    "inspected_day": {"p1": [{"insight_type": "inspected", "sum": 7}]},
                    "inspected_month": {"p1": [{"insight_type": "inspected", "sum": 8}]},
                    "inspected_week": {"p1": [{"insight_type": "inspected", "sum": 9}]},
                }
            }
        },
    )
    assert profile.inspected_day == 7
    assert profile.inspected_month == 8
    assert profile.inspected_week == 9


def test_last_active_is_max_of_clients_and_none_when_no_clients() -> None:
    hub = build_hub()
    profile = make_profile(
        hub,
        devices=[
            {
                "url": f"{NETWORK_URL}/devices/a",
                "mac": "a",
                "last_active": "2024-01-01T00:00:00+00:00",
            },
            {
                "url": f"{NETWORK_URL}/devices/b",
                "mac": "b",
                "last_active": "2024-06-01T00:00:00+00:00",
            },
        ],
    )
    assert profile.last_active is not None
    assert profile.last_active.month == 6

    empty = make_profile(hub)
    assert empty.last_active is None


def test_name_name_long_and_paused() -> None:
    hub = build_hub()
    profile = make_profile(hub, name="Kids", paused=True)
    assert profile.name == "Kids"
    assert profile.name_long == "Kids Profile"
    assert profile.paused is True


def test_url_dns_policies_and_url_insights() -> None:
    hub = build_hub()
    profile = make_profile(
        hub, network_overrides={"resources": {"insights": f"{NETWORK_URL}/insights"}}
    )
    assert profile.url_dns_policies == f"{NETWORK_URL}/dns_policies/profiles/p1"
    assert profile.url_insights == f"{NETWORK_URL}/insights/profiles/p1"
