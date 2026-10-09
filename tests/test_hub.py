"""Unit tests for EeroHub: activity query shape, setter→SDK mapping, _optional,
premium_enabled, and the fast-tier request-count comparison against the old
requests-based client (b989da7, the commit immediately before this SDK port).
"""

from __future__ import annotations

from datetime import time as _time
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from eero.exceptions import (
    EeroAccessDeniedException,
    EeroFeatureUnavailableException,
    EeroNotFoundException,
    EeroPremiumRequiredException,
)
from helpers import FakeSDK, build_hub, eero_api

ROOT = Path(__file__).resolve().parents[1]

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"
NETWORK_RESOURCES = {
    "settings": f"{NETWORK_URL}/settings",
    "thread": f"{NETWORK_URL}/thread",
    "updates": f"{NETWORK_URL}/updates",
    "reboot": f"{NETWORK_URL}/reboot",
}


def make_network(hub, **overrides):
    """Return an EeroNetwork with the usual resource links."""
    data = {"url": NETWORK_URL, "name": "TestNetwork", "resources": dict(NETWORK_RESOURCES)}
    data.update(overrides)
    return eero_api.network.EeroNetwork(hub, None, data)


# -- activity: query params, never a JSON body -------------------------------


async def test_activity_uses_query_params_never_json_body() -> None:
    """Every activity read sends start/end/cadence as kwargs or params=, never json=."""
    sdk = FakeSDK(
        {
            "data_usage.get_data_usage": {},
            "data_usage.get_devices_usage": {},
            "data_usage.get_profile_usage": {},
            "GET /2.2/networks/1234567/data_usage/eeros": {},
            "insights.get_insights": {},
            "insights.get_devices_insights": {},
            "insights.get_profile_insights": {},
            "GET /2.2/networks/1234567/insights/eeros": {},
        }
    )
    hub = build_hub(sdk=sdk)

    for activity in ("data_usage_week", "inspected_week"):
        for resource in ("network", "devices", "eeros"):
            await hub.update_activity(activity, NETWORK_ID, resource, "UTC")
        await hub.update_activity(activity, NETWORK_ID, "profiles", "UTC", profile_id="p1")

    assert sdk.calls, "no requests were recorded"
    for domain, method, _args, kwargs in sdk.calls:
        if (domain, method) == ("auth", "get_auth_token"):
            continue  # the raw-verb helper fetching a token for the request, not the request
        assert "json" not in kwargs, f"{domain}.{method} sent a JSON body for an activity read"
        if method in ("get", "put", "post", "delete"):
            assert "params" in kwargs, f"{domain}.{method} (raw verb) carried no params="
            assert {"start", "end", "cadence"} <= kwargs["params"].keys()
        else:
            assert {"start", "end", "cadence"} <= kwargs.keys(), (
                f"{domain}.{method} did not pass start/end/cadence as kwargs"
            )


async def test_unprofiled_and_eeros_summary_route_to_their_sdk_methods() -> None:
    """The two new activity keys call get_unprofiled_summary/get_eeros_summary, not get_data_usage."""
    sdk = FakeSDK(
        {
            "data_usage.get_unprofiled_summary": [
                {"type": "download", "sum": 10},
                {"type": "upload", "sum": 2},
            ],
            "data_usage.get_eeros_summary": [
                {"type": "download", "sum": 30},
                {"type": "upload", "sum": 4},
            ],
        }
    )
    hub = build_hub(sdk=sdk)

    unprofiled = await hub.update_activity(
        "unprofiled_data_usage_day", NETWORK_ID, "network", "UTC"
    )
    eeros_summary = await hub.update_activity(
        "eeros_data_usage_summary_day", NETWORK_ID, "network", "UTC"
    )

    assert unprofiled == [{"type": "download", "sum": 10}, {"type": "upload", "sum": 2}]
    assert eeros_summary == [{"type": "download", "sum": 30}, {"type": "upload", "sum": 4}]
    assert not any(d == "data_usage" and m == "get_data_usage" for d, m, _a, _kw in sdk.calls)
    assert any(d == "data_usage" and m == "get_unprofiled_summary" for d, m, _a, _kw in sdk.calls)
    assert any(d == "data_usage" and m == "get_eeros_summary" for d, m, _a, _kw in sdk.calls)


async def test_app_events_and_has_unread_route_to_their_sdk_methods_and_shapes() -> None:
    """The two activities call events.get_app_events/notifications.has_unread.

    has_unread's {"has_unread": bool} dict is returned verbatim, never run
    through the insights/series/values extraction (which would discard it).
    """
    sdk = FakeSDK(
        {
            "events.get_app_events": {
                "events": [{"id": "1", "message": "device connected"}]
            },
            "notifications.has_unread": {"has_unread": True},
        }
    )
    hub = build_hub(sdk=sdk)

    events = await hub.update_activity("app_events", NETWORK_ID, "network", "UTC")
    unread = await hub.update_activity(
        "notifications_has_unread", NETWORK_ID, "network", "UTC"
    )

    assert events == [{"id": "1", "message": "device connected"}]
    assert unread == {"has_unread": True}
    assert any(
        d == "events" and m == "get_app_events" and kw.get("page_size") == 25
        for d, m, _a, kw in sdk.calls
    )
    assert ("notifications", "has_unread", (NETWORK_ID,), {}) in sdk.calls


# -- _optional -----------------------------------------------------------


@pytest.mark.parametrize(
    "exc,expected_premium",
    [
        (EeroPremiumRequiredException("nope"), True),
        (EeroFeatureUnavailableException("nope"), False),
    ],
)
async def test_optional_collects_unavailable_features(exc, expected_premium) -> None:
    """A premium/feature/not-found failure on a daily read yields None and is collected."""
    hub = build_hub()

    async def failing():
        raise exc

    with eero_api.collect_unavailable() as found:
        result = await hub._optional(failing(), "name", NETWORK_ID, "thread")

    assert result is None
    assert len(found) == 1
    assert found[0].network_id == NETWORK_ID
    assert found[0].feature == "thread"
    assert found[0].premium is expected_premium


@pytest.mark.parametrize(
    "exc",
    [
        EeroNotFoundException("thread", NETWORK_ID),
        EeroAccessDeniedException(403, "no access"),
    ],
)
async def test_optional_absorbs_not_found_and_access_denied_silently(exc) -> None:
    """Hardware without a feature (404) or an admin without access (403): None, no issue."""
    hub = build_hub()

    async def failing():
        raise exc

    with eero_api.collect_unavailable() as found:
        result = await hub._optional(failing(), "name", NETWORK_ID, "thread")

    assert result is None
    assert found == []


async def test_a_network_that_is_gone_is_skipped_with_an_issue() -> None:
    """A configured network answering 404 is skipped, not a failed poll (B2)."""
    hub = build_hub(
        routes={"networks.get_network": EeroNotFoundException("network", NETWORK_ID)}
    )

    with eero_api.collect_unavailable() as found:
        payload = await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())

    assert payload == {}
    assert [(item.network_id, item.feature) for item in found] == [(NETWORK_ID, "network")]
    assert hub.assemble(None, {NETWORK_ID: payload}, {}, {}).networks == []


async def test_optional_propagates_other_exceptions() -> None:
    """Any other exception is not swallowed."""
    hub = build_hub()

    async def failing():
        raise eero_api.EeroException("boom")

    with pytest.raises(eero_api.EeroException):
        await hub._optional(failing(), "name", NETWORK_ID, "thread")


# -- premium_enabled -------------------------------------------------------


def test_premium_enabled_from_entitlements_feature_list() -> None:
    """A non-empty entitlements feature list means premium is on."""
    assert eero_api.premium_enabled({}, {"features": ["foo"]}) is True


def test_premium_enabled_empty_feature_list_means_off() -> None:
    """An empty (but present) entitlements feature list means premium is off."""
    assert eero_api.premium_enabled({}, {"features": []}) is False


def test_premium_enabled_falls_back_to_premium_status() -> None:
    """When entitlements could not be read, fall back to premium_status."""
    active = {"capabilities": {"premium": {"capable": True}}, "premium_status": "active"}
    inactive = {"capabilities": {"premium": {"capable": True}}, "premium_status": "inactive"}

    assert eero_api.premium_enabled(active, None) is True
    assert eero_api.premium_enabled(inactive, None) is False


# -- setter -> SDK call mapping (mapping doc /tmp/eero-sdk-mapping.md §3) ----


def _case(case_id, routes, act, check):
    return pytest.param(routes, act, check, id=case_id)


SETTER_CASES = [
    _case(
        # Not sdk.sqm.set_sqm: that sends the value as a query param, a
        # request eero-api has not verified; this is a raw PUT to the
        # network's settings link with the JSON body 1.x always sent.
        "network.sqm",
        {"PUT /2.2/networks/1234567/settings": {}},
        lambda hub: make_network(hub).async_set_sqm(True),
        lambda sdk: any(
            d == "networks" and m == "put" and kw.get("json") == {"sqm": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.backup_internet_enabled",
        {"backup.set_backup_internet": {}},
        lambda hub: make_network(hub).async_set_backup_internet_enabled(True),
        lambda sdk: ("backup", "set_backup_internet", (NETWORK_ID, True), {}) in sdk.calls,
    ),
    _case(
        "network.band_steering",
        {"security.set_band_steering": {}},
        lambda hub: make_network(hub).async_set_band_steering(True),
        lambda sdk: any(
            d == "security" and m == "set_band_steering" and a[:2] == (NETWORK_ID, True)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.wpa3",
        {"security.set_wpa3": {}},
        lambda hub: make_network(hub).async_set_wpa3(True),
        lambda sdk: any(
            d == "security" and m == "set_wpa3" and a[:2] == (NETWORK_ID, True)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.upnp",
        {"security.set_upnp": {}},
        lambda hub: make_network(hub).async_set_upnp(True),
        lambda sdk: any(
            d == "security" and m == "set_upnp" and a[:2] == (NETWORK_ID, True)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.ddns_enabled.enable",
        {"ddns.enable": {}},
        lambda hub: make_network(hub).async_set_ddns_enabled(True),
        lambda sdk: any(
            d == "ddns" and m == "enable" and a == (NETWORK_ID,) and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.ddns_enabled.disable",
        {"ddns.disable": {}},
        lambda hub: make_network(hub).async_set_ddns_enabled(False),
        lambda sdk: any(
            d == "ddns" and m == "disable" and a == (NETWORK_ID,) and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.dns_caching",
        {"dns.set_dns_caching": {}},
        lambda hub: make_network(hub).async_set_dns_caching(True),
        lambda sdk: any(
            d == "dns" and m == "set_dns_caching" and a[:2] == (NETWORK_ID, True)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.guest_network_enabled",
        {"networks.set_guest_network": {}},
        lambda hub: make_network(hub).async_set_guest_network_enabled(True),
        lambda sdk: ("networks", "set_guest_network", (NETWORK_ID,), {"enabled": True})
        in sdk.calls,
    ),
    _case(
        "network.guest_network_name",
        {"networks.set_guest_network": {}},
        lambda hub: make_network(hub, guest_network={"enabled": True}).async_set_guest_network_name(
            "New Guest SSID"
        ),
        lambda sdk: (
            "networks",
            "set_guest_network",
            (NETWORK_ID,),
            {"enabled": True, "name": "New Guest SSID"},
        )
        in sdk.calls,
    ),
    _case(
        "network.guest_network_password",
        {"networks.set_guest_password": {}},
        lambda hub: make_network(hub).async_set_guest_network_password("supersecret1"),
        lambda sdk: (
            "networks",
            "set_guest_password",
            (NETWORK_ID, "supersecret1"),
            {},
        )
        in sdk.calls,
    ),
    _case(
        "network.create_reservation",
        {"reservations.create_reservation": {}},
        lambda hub: make_network(hub).async_create_reservation(
            {"ip": "192.168.4.100", "mac": "aa:bb:cc:dd:ee:ff"}
        ),
        lambda sdk: (
            "reservations",
            "create_reservation",
            (NETWORK_ID, {"ip": "192.168.4.100", "mac": "aa:bb:cc:dd:ee:ff"}),
            {},
        )
        in sdk.calls,
    ),
    _case(
        "network.delete_reservation",
        {"reservations.delete_reservation": {}},
        lambda hub: make_network(hub).async_delete_reservation("r1", True),
        lambda sdk: (
            "reservations",
            "delete_reservation",
            (NETWORK_ID, "r1"),
            {"delete_forwards": True},
        )
        in sdk.calls,
    ),
    _case(
        "network.create_port_forward",
        {"forwards.create_forward": {}},
        lambda hub: make_network(hub).async_create_port_forward(
            {"ip": "192.168.4.100", "client_port": 8080, "gateway_port": 8080}
        ),
        lambda sdk: (
            "forwards",
            "create_forward",
            (
                NETWORK_ID,
                {"ip": "192.168.4.100", "client_port": 8080, "gateway_port": 8080},
            ),
            {},
        )
        in sdk.calls,
    ),
    _case(
        "network.delete_port_forward",
        {"forwards.delete_forward": {}},
        lambda hub: make_network(hub).async_delete_port_forward("f1"),
        lambda sdk: ("forwards", "delete_forward", (NETWORK_ID, "f1"), {}) in sdk.calls,
    ),
    _case(
        "network.set_custom_dns.ipv4_and_ipv6",
        {"dns.set_custom_dns": {}},
        lambda hub: make_network(
            hub,
            dns={"mode": "custom", "custom": {"ips": ["9.9.9.9"]}},
            ipv6={"name_servers": {"mode": "automatic", "custom": []}},
        ).async_set_custom_dns(ipv4=["1.1.1.1"], ipv6=["2606:4700:4700::1111"]),
        # One write for both families: two would reboot the mesh twice.
        lambda sdk: [
            (m, a[1]) for d, m, a, _kw in sdk.calls if d == "dns"
        ]
        == [("set_custom_dns", ["1.1.1.1", "2606:4700:4700::1111"])],
    ),
    _case(
        "network.set_custom_dns.automatic",
        {"dns.set_dns_mode": {}},
        lambda hub: make_network(
            hub,
            dns={"mode": "custom"},
            ipv6={"name_servers": {"mode": "automatic"}},
        ).async_set_custom_dns(automatic=True),
        lambda sdk: any(
            d == "dns" and m == "set_dns_mode" and a[1] == "automatic"
            for d, m, a, _kw in sdk.calls
        ),
    ),
    _case(
        "network.mlo_mode",
        {"security.set_mlo_mode": {}},
        lambda hub: make_network(hub).async_set_mlo_mode("multi"),
        lambda sdk: any(
            d == "security" and m == "set_mlo_mode" and a[:2] == (NETWORK_ID, "multi")
            for d, m, a, _kw in sdk.calls
        ),
    ),
    _case(
        "network.fast_transition_enabled",
        {"security.set_fast_transition": {}},
        lambda hub: make_network(hub).async_set_fast_transition_enabled(True),
        lambda sdk: any(
            d == "security" and m == "set_fast_transition" and a[:2] == (NETWORK_ID, True)
            for d, m, a, _kw in sdk.calls
        ),
    ),
    _case(
        "network.power_saving_enabled",
        {"power_saving.set_power_saving": {}},
        lambda hub: make_network(hub).async_set_power_saving_enabled(True),
        lambda sdk: any(
            d == "power_saving"
            and m == "set_power_saving"
            and a[:1] == (NETWORK_ID,)
            and kw.get("enable") is True
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.thread_enabled",
        {"PUT /2.2/networks/1234567/thread/enable": {}},
        lambda hub: make_network(hub).async_set_thread_enabled(True),
        lambda sdk: any(
            d == "networks"
            and m == "put"
            and a[0] == "https://api-user.e2ro.com/2.2/networks/1234567/thread/enable"
            and kw.get("json") == {"enabled": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.ipv6_upstream",
        {"PUT /2.2/networks/1234567/settings": {}},
        lambda hub: make_network(hub).async_set_ipv6_upstream(True),
        lambda sdk: any(
            d == "networks" and m == "put" and kw.get("json") == {"ipv6_upstream": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.ad_block",
        {"POST /2.2/networks/1234567/dns_policies/adblock": {}},
        lambda hub: make_network(hub).async_set_ad_block(True),
        lambda sdk: any(
            d == "networks" and m == "post" and kw.get("json") == {"enable": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.block_malware",
        {"POST /2.2/networks/1234567/dns_policies/network": {}},
        lambda hub: make_network(hub).async_set_block_malware(True),
        lambda sdk: any(
            d == "networks" and m == "post" and kw.get("json") == {"block_malware": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.pause_5g_enabled.enable",
        {"PUT /2.2/networks/1234567/temporary_flags/hide_5g": {}},
        lambda hub: make_network(hub).async_set_pause_5g_enabled(True),
        lambda sdk: any(
            d == "networks" and m == "put" and kw.get("json") == {"value": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.pause_5g_enabled.disable",
        {"DELETE /2.2/networks/1234567/temporary_flags/hide_5g": {}},
        lambda hub: make_network(hub).async_set_pause_5g_enabled(False),
        lambda sdk: any(
            d == "networks" and m == "delete" and "json" not in kw
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.preferred_update_hour",
        {"POST /2.2/networks/1234567/updates/preferred_update_hour": {}},
        lambda hub: make_network(hub).async_set_preferred_update_hour("12am_1am"),
        lambda sdk: any(
            d == "networks"
            and m == "post"
            and kw.get("json") == {"preferred_update_hour": 0}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "network.reboot",
        {"networks.reboot_network": {}},
        lambda hub: make_network(hub).async_reboot(),
        lambda sdk: ("networks", "reboot_network", (NETWORK_ID,), {}) in sdk.calls,
    ),
    _case(
        "network.run_internet_backup_test",
        {"backup_access_points.connectivity_check": {}},
        lambda hub: make_network(hub).async_run_internet_backup_test(),
        lambda sdk: ("backup_access_points", "connectivity_check", (NETWORK_ID,), {})
        in sdk.calls,
    ),
    _case(
        "network.run_speed_test",
        {"networks.run_speed_test": {}},
        lambda hub: make_network(hub).async_run_speed_test(),
        lambda sdk: ("networks", "run_speed_test", (NETWORK_ID,), {}) in sdk.calls,
    ),
    _case(
        "network.install_firmware_update",
        {"updates.apply_update": {}},
        lambda hub: make_network(hub).async_install_firmware_update(),
        lambda sdk: ("updates", "apply_update", (NETWORK_ID,), {}) in sdk.calls,
    ),
    _case(
        "client.paused",
        {"devices.pause_device": {}},
        lambda hub: eero_api.client.EeroClient(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/devices/aa", "mac": "aa"}
        ).async_set_paused(True),
        lambda sdk: ("devices", "pause_device", (NETWORK_ID, "aa", True), {}) in sdk.calls,
    ),
    _case(
        "client.blocked.block",
        {"blacklist.add_to_blacklist": {}},
        lambda hub: eero_api.client.EeroClient(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/devices/aa", "mac": "aa"}
        ).async_set_blocked(True),
        lambda sdk: ("blacklist", "add_to_blacklist", (NETWORK_ID, "aa"), {}) in sdk.calls,
    ),
    _case(
        "client.blocked.unblock",
        {"blacklist.remove_from_blacklist": {}},
        lambda hub: eero_api.client.EeroClient(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/devices/aa", "mac": "aa"}
        ).async_set_blocked(False),
        lambda sdk: ("blacklist", "remove_from_blacklist", (NETWORK_ID, "aa"), {})
        in sdk.calls,
    ),
    _case(
        "profile.bedtime_enabled.create",
        {"schedule.set_weekday_bedtime": {}, "schedule.set_weekend_bedtime": {}},
        lambda hub: eero_api.profile.EeroProfile(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/profiles/p1"}
        ).async_set_bedtime_enabled(True),
        lambda sdk: (
            ("schedule", "set_weekday_bedtime", (NETWORK_ID, "p1", "22:00", "07:00"), {})
            in sdk.calls
            and (
                "schedule",
                "set_weekend_bedtime",
                (NETWORK_ID, "p1", "22:00", "07:00"),
                {},
            )
            in sdk.calls
        ),
    ),
    _case(
        "profile.bedtime_weekday_start.update_existing",
        {"schedule.update_schedule": {}},
        lambda hub: eero_api.profile.EeroProfile(
            hub,
            make_network(
                hub,
                schedules={
                    "p1": [
                        {
                            "name": "Bedtime",
                            "days": list(eero_api.profile.WEEKDAYS),
                            "start": "21:00",
                            "end": "06:00",
                            "enabled": True,
                            "url": f"{NETWORK_URL}/profiles/p1/schedules/1",
                        }
                    ]
                },
            ),
            {"url": f"{NETWORK_URL}/profiles/p1"},
        ).async_set_bedtime_weekday_start(_time(20, 30)),
        lambda sdk: any(
            d == "schedule" and m == "update_schedule" and kw.get("start") == "20:30"
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "client.secondary_wan_allow_access",
        {"PUT /2.3/networks/1234567/devices/aa": {}},
        lambda hub: eero_api.client.EeroClient(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/devices/aa", "mac": "aa"}
        ).async_set_secondary_wan_allow_access(False),
        lambda sdk: any(
            d == "networks"
            and m == "put"
            and a[0] == "https://api-user.e2ro.com/2.3/networks/1234567/devices/aa"
            and kw.get("json") == {"secondary_wan_deny_access": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "profile.paused",
        {"profiles.pause_profile": {}},
        lambda hub: eero_api.profile.EeroProfile(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/profiles/p1"}
        ).async_set_paused(True),
        lambda sdk: ("profiles", "pause_profile", (NETWORK_ID, "p1", True), {}) in sdk.calls,
    ),
    _case(
        "profile.blocked_applications",
        {"dns_policies.set_profile_blocked_applications": {}},
        lambda hub: eero_api.profile.EeroProfile(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/profiles/p1"}
        ).async_set_blocked_applications(["netflix"]),
        lambda sdk: (
            "dns_policies",
            "set_profile_blocked_applications",
            (NETWORK_ID, "p1", ["netflix"]),
            {},
        )
        in sdk.calls,
    ),
    _case(
        "profile.safe_search_enabled",
        {f"POST {NETWORK_URL}/dns_policies/profiles/p1": {}},
        lambda hub: eero_api.profile.EeroProfile(
            hub, make_network(hub), {"url": f"{NETWORK_URL}/profiles/p1"}
        ).async_set_safe_search_enabled(True),
        lambda sdk: any(
            d == "networks" and m == "post" and kw.get("json") == {"safe_search_enabled": True}
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "eero.reboot",
        {"eeros.reboot_eero": {}},
        lambda hub: eero_api.eero.EeroDevice(
            hub, make_network(hub), {"url": "/2.2/eeros/e1"}
        ).async_reboot(),
        lambda sdk: ("eeros", "reboot_eero", (NETWORK_ID, "e1"), {}) in sdk.calls,
    ),
    _case(
        "eero.status_light.on",
        {"eeros.set_led": {}},
        lambda hub: eero_api.eero.EeroDevice(
            hub, make_network(hub), {"url": "/2.2/eeros/e1"}
        ).async_set_status_light(True),
        lambda sdk: any(
            d == "eeros" and m == "set_led" and a == (NETWORK_ID, "e1", True)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "eero.status_light_brightness.zero_turns_off",
        {"eeros.set_led": {}},
        lambda hub: eero_api.eero.EeroDevice(
            hub, make_network(hub), {"url": "/2.2/eeros/e1"}
        ).async_set_status_light_brightness(0),
        lambda sdk: any(
            d == "eeros" and m == "set_led" and a == (NETWORK_ID, "e1", False)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "eero.status_light_brightness.nonzero",
        {"eeros.set_led_brightness": {}},
        lambda hub: eero_api.eero.EeroDevice(
            hub, make_network(hub), {"url": "/2.2/eeros/e1"}
        ).async_set_status_light_brightness(50),
        lambda sdk: any(
            d == "eeros" and m == "set_led_brightness" and a == (NETWORK_ID, "e1", 50)
            and kw.get("parent") is not None
            for d, m, a, kw in sdk.calls
        ),
    ),
    _case(
        "eero.port_action",
        {"eeros.port_action": {}},
        lambda hub: eero_api.eero.EeroDevice(
            hub, make_network(hub), {"url": "/2.2/eeros/e1"}
        ).async_port_action(1, "RESTART_POWER"),
        lambda sdk: ("eeros", "port_action", ("e1", "1", "RESTART_POWER"), {})
        in sdk.calls,
    ),
    _case(
        "backup_network.auto_join_enabled",
        {"backup_access_points.update": {}},
        lambda hub: eero_api.backup_network.EeroBackupNetwork(
            hub,
            make_network(hub),
            {"uuid": "bn1", "ssid": "Guest", "password": "pw"},
        ).async_set_auto_join_enabled(True),
        lambda sdk: (
            "backup_access_points",
            "update",
            (NETWORK_ID, "bn1"),
            {"enabled": True, "ssid": "Guest", "password": "pw"},
        )
        in sdk.calls,
    ),
]


@pytest.mark.parametrize("routes,act,check", SETTER_CASES)
async def test_setter_maps_to_expected_sdk_call(routes, act, check) -> None:
    """Every setter calls the SDK method (or raw verb+absolute URL) the mapping doc expects."""
    sdk = FakeSDK(routes)
    hub = build_hub(sdk=sdk)

    await act(hub)

    assert check(sdk), sdk.calls


# -- read-compare-skip: DNS, reservations, port forwards ---------------------


async def test_set_custom_dns_skips_a_write_that_already_matches() -> None:
    """DNS writes reboot the mesh: a family already at the target state is never written."""
    hub = build_hub(sdk=FakeSDK({}))
    network = make_network(
        hub,
        dns={"mode": "custom", "custom": {"ips": ["1.1.1.1", "1.0.0.1"]}},
        ipv6={
            "name_servers": {
                "mode": "custom",
                # Fully-expanded, as the API stores it; the caller supplies
                # the compressed form below.
                "custom": ["2606:4700:4700:0:0:0:0:1111"],
            }
        },
    )

    # Order-insensitive, and IPv6 compares through ipaddress, not by string.
    await network.async_set_custom_dns(
        ipv4=["1.0.0.1", "1.1.1.1"], ipv6=["2606:4700:4700::1111"]
    )

    assert hub.sdk.calls == []


async def test_set_custom_dns_automatic_skips_when_both_families_already_automatic() -> (
    None
):
    """automatic=True is a no-op once both families already report automatic."""
    hub = build_hub(sdk=FakeSDK({}))
    network = make_network(
        hub,
        dns={"mode": "automatic"},
        ipv6={"name_servers": {"mode": "automatic"}},
    )

    await network.async_set_custom_dns(automatic=True)

    assert hub.sdk.calls == []


async def test_set_custom_dns_reads_once_when_not_on_the_envelope() -> None:
    """Missing dns/ipv6 on the envelope triggers exactly one get_dns_settings read."""
    sdk = FakeSDK(
        {
            "dns.get_dns_settings": {
                "dns": {"mode": "automatic"},
                "ipv6": {"name_servers": {"mode": "automatic"}},
            }
        }
    )
    hub = build_hub(sdk=sdk)
    network = make_network(hub)

    await network.async_set_custom_dns(automatic=True)

    assert ("dns", "get_dns_settings", (NETWORK_ID,), {}) in sdk.calls
    assert not any(m == "set_dns_mode" for _d, m, _a, _kw in sdk.calls)


async def test_create_reservation_skips_an_identical_existing_entry() -> None:
    """A reservation with the same IP and MAC already on the daily-tier read is not recreated."""
    hub = build_hub(sdk=FakeSDK({}))
    network = make_network(
        hub,
        reservations={
            "data": [{"ip": "192.168.4.100", "mac": "aa:bb:cc:dd:ee:ff"}]
        },
    )

    await network.async_create_reservation(
        {"ip": "192.168.4.100", "mac": "aa:bb:cc:dd:ee:ff"}
    )

    assert hub.sdk.calls == []


async def test_create_port_forward_skips_an_identical_existing_entry() -> None:
    """A forward with the same ip/client_port/gateway_port/protocol is not recreated."""
    hub = build_hub(sdk=FakeSDK({}))
    network = make_network(
        hub,
        forwards={
            "data": [
                {
                    "ip": "192.168.4.100",
                    "client_port": 8080,
                    "gateway_port": 8080,
                    "protocol": "tcp",
                }
            ]
        },
    )

    await network.async_create_port_forward(
        {
            "ip": "192.168.4.100",
            "client_port": 8080,
            "gateway_port": 8080,
            "protocol": "tcp",
        }
    )

    assert hub.sdk.calls == []


async def test_raw_verb_writes_use_an_absolute_url_with_network_id() -> None:
    """Every no-SDK-method write targets an absolute https://api-user.e2ro.com/... URL.

    Using a relative path would make the SDK re-prefix /2.2 onto an
    already-absolute-looking path, corrupting the request.
    """
    sdk = FakeSDK({"POST /2.2/networks/1234567/dns_policies/adblock": {}})
    hub = build_hub(sdk=sdk)

    await make_network(hub).async_set_ad_block(True)

    (_domain, _method, args, _kwargs) = sdk.calls[-1]
    assert args[0].startswith("https://api-user.e2ro.com/")
    assert NETWORK_ID in args[0]


# -- request count: new fast tier vs the old monolithic update() -------------

NETWORK_IDS = ("1111111", "2222222", "3333333")
PROFILE_COUNTS = {"1111111": 4, "2222222": 3, "3333333": 3}


def _network_envelope(network_id: str) -> dict:
    return {
        "url": f"/2.2/networks/{network_id}",
        "name": f"Network {network_id}",
        "eeros": {
            "count": 1,
            "data": [{"url": f"/2.2/eeros/{network_id}-1", "model": "eero 6"}],
        },
        "resources": {
            "devices": f"/2.2/networks/{network_id}/devices",
            "profiles": f"/2.2/networks/{network_id}/profiles",
        },
    }


def _devices_for(network_id: str) -> list[dict]:
    return [
        {
            "url": f"/2.2/networks/{network_id}/devices/aa",
            "mac": "aa",
            "nickname": "Client",
        }
    ]


def _profiles_for(network_id: str) -> list[dict]:
    return [
        {"url": f"/2.2/networks/{network_id}/profiles/{i}", "name": f"Profile {i}"}
        for i in range(PROFILE_COUNTS[network_id])
    ]


async def test_new_fast_tier_makes_at_most_nine_requests_for_three_networks() -> None:
    """network + devices + profiles per network, eeros embedded: 3 x 3 = 9, never eeros.get_eeros."""

    def route_network(args, _kwargs):
        return _network_envelope(args[0])

    def route_devices(args, _kwargs):
        return _devices_for(args[0])

    def route_profiles(args, _kwargs):
        return _profiles_for(args[0])

    sdk = FakeSDK(
        {
            "networks.get_network": route_network,
            "devices.get_devices": route_devices,
            "profiles.get_profiles": route_profiles,
        }
    )
    hub = build_hub(sdk=sdk)
    config = eero_api.EeroUpdateConfig(get_devices=True, profiles=["0", "1", "2", "3"])

    for network_id in NETWORK_IDS:
        await hub.fetch_fast(network_id, config)

    assert ("eeros", "get_eeros") not in [(d, m) for d, m, _a, _kw in sdk.calls]
    assert len(sdk.calls) == 9
    assert len(sdk.calls) <= 9


# documented separately below (OLD_UPDATE_REQUEST_COUNT) and re-derived live
# by test_old_update_request_count_matches_the_documented_constant.
OLD_UPDATE_REQUEST_COUNT = 23
"""Requests the pre-SDK client (commit b989da7) made for one full update() over
the same 3-network/10-profile account, with devices + profiles fetched and a
single data_usage_week activity metric configured for both the network and
every profile, and no Thread resource / no backup-access-point capability (to
keep the comparison isolated to the fast-tier-equivalent work; the daily-tier
reads, which the new client only polls once a day, are intentionally excluded
from both sides).

1 account + 3 networks x (network + devices + profiles + 1 network-activity
request + N profile-activity requests) = 1 + (3 + 1 + 4) + (3 + 1 + 3) +
(3 + 1 + 3) = 1 + 8 + 7 + 7 = 23.

The new client's fast tier alone (test above) makes 9 requests for the same
account at the fast-tier cadence; its hourly tier (not exercised by that
test) would add the activity requests on its own, much slower cadence. The
old client made all 23 on every single poll, because it had no tiering.
"""


def _load_old_api(tmp_path):
    """Check out the api package as it was at b989da7 (pre-SDK) and load it standalone."""
    checkout = tmp_path / "old_api"
    checkout.mkdir()
    files = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "b989da7", "--", "custom_components/eero/api"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    for repo_path in files:
        content = subprocess.run(
            ["git", "show", f"b989da7:{repo_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        dest = checkout / Path(repo_path).name
        dest.write_text(content)
    spec = importlib.util.spec_from_file_location(
        "eero_api_old",
        checkout / "__init__.py",
        submodule_search_locations=[str(checkout)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["eero_api_old"] = module
    spec.loader.exec_module(module)
    return module


class _OldFakeResponse:
    def __init__(self, body) -> None:
        self.status_code = 200
        self.reason = "OK"
        self.url = "https://api-user.e2ro.com/"
        self.headers: dict[str, str] = {}
        self.text = json.dumps({"meta": {"code": 200}, "data": body})

    @property
    def ok(self) -> bool:
        return True


class _OldFakeSession:
    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str]] = []

    def _serve(self, method, url, **kwargs):
        path = url.replace("https://api-user.e2ro.com", "")
        self.calls.append((method, path))
        if path not in self.routes:
            raise AssertionError(f"old client: unexpected request {method} {path}")
        value = self.routes[path]
        return _OldFakeResponse(value(path) if callable(value) else value)

    def get(self, url, **kwargs):
        return self._serve("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._serve("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._serve("PUT", url, **kwargs)

    def delete(self, url, **kwargs):
        return self._serve("DELETE", url, **kwargs)

    def close(self) -> None:
        pass


def test_old_update_request_count_matches_the_documented_constant(tmp_path) -> None:
    """Run the pre-SDK client once over the same account and count its requests."""
    old_api = _load_old_api(tmp_path)

    account_body = {
        "name": "Test Account",
        "networks": {
            "data": [{"url": f"/2.2/networks/{network_id}"} for network_id in NETWORK_IDS]
        },
    }
    routes: dict = {"/2.2/account": account_body}
    config = {}
    for network_id in NETWORK_IDS:
        network_url = f"/2.2/networks/{network_id}"
        routes[network_url] = _network_envelope_for_old(network_id)
        routes[f"{network_url}/devices"] = _devices_for(network_id)
        routes[f"{network_url}/profiles"] = _profiles_for(network_id)
        profile_ids = list(range(PROFILE_COUNTS[network_id]))
        # update_activity() for resource="network" hits {network_url}/data_usage
        # unmodified; for resource="profiles" it appends /profiles/{profile_id}.
        routes[f"{network_url}/data_usage"] = []
        for profile_id in profile_ids:
            routes[f"{network_url}/data_usage/profiles/{profile_id}"] = []
        config[network_id] = old_api.EeroUpdateConfig(
            get_devices=True,
            profiles=profile_ids,
            activity={"network": ["data_usage_week"], "profiles": ["data_usage_week"]},
        )

    api = old_api.EeroAPI(user_token="OLD-TOKEN")
    api.session = _OldFakeSession(routes)

    api.update(config)

    assert len(api.session.calls) == OLD_UPDATE_REQUEST_COUNT


def _network_envelope_for_old(network_id: str) -> dict:
    """A network envelope with no Thread resource and no backup-access-point capability."""
    return {
        "url": f"/2.2/networks/{network_id}",
        "name": f"Network {network_id}",
        "resources": {
            "devices": f"/2.2/networks/{network_id}/devices",
            "profiles": f"/2.2/networks/{network_id}/profiles",
        },
    }
