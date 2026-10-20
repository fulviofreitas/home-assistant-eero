"""Contract tests: the integration's calls, through the real eero-api, on the wire.

Every other test fakes the SDK. These run the integration's setters and reads
through the installed eero-api with only the HTTP session stubbed, and pin the
exact method, path and body each one sends. An eero-api upgrade that changes a
request, or starts rejecting one (path confinement, version pins, setter
validation), fails here instead of on someone's network.
"""

from __future__ import annotations

from datetime import time as dtime
import json
from typing import Any

from eero import EeroAPI as EeroSDK
import pytest

from helpers import load_api

eero_api = load_api()

HOST = "https://api-user.e2ro.com"
NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"
MAC = "aa:bb:cc:dd:ee:ff"


class _Content:
    def __init__(self, body: bytes) -> None:
        self._body = body

    async def iter_chunked(self, size: int):
        yield self._body


class _Response:
    def __init__(self, body: Any) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self.content = _Content(json.dumps(body).encode())

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


class RecordingSession:
    """Stands in for aiohttp.ClientSession: records each request, answers 200."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, Any]]] = []
        self.data: Any = {}

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        assert url.startswith(HOST), url
        body = {k: kwargs[k] for k in ("json", "data", "params") if kwargs.get(k) is not None}
        self.requests.append((method, url[len(HOST) :], body))
        return _Response({"meta": {"code": 200}, "data": self.data})


@pytest.fixture
async def wire():
    """Return (session, hub, models) with a real SDK on a recording session."""
    session = RecordingSession()
    hub = eero_api.EeroHub(session=session, sdk=EeroSDK(session=session, use_keyring=False))
    await hub.async_set_token("TOKEN")
    network = eero_api.network.EeroNetwork(
        hub,
        None,
        {
            "url": NETWORK_URL,
            "name": "Home",
            # Only the links the integration itself reads; everything else
            # takes the SDK's own templates.
            "resources": {
                key: f"{NETWORK_URL}/{key}" for key in ("settings", "thread", "updates", "reboot")
            },
            "dns": {"mode": "automatic", "custom": {"ips": []}},
            "ipv6": {"name_servers": {"mode": "automatic", "custom": []}},
            "guest_network": {"enabled": True, "name": "Guests", "password": "old-password"},
            "premium_dns": {"ad_block_settings": {"enabled": False, "profiles": []}},
        },
    )
    models = {
        "network": network,
        "eero": eero_api.eero.EeroDeviceBeacon(
            hub,
            network,
            {
                "url": "/2.2/eeros/E1",
                "location": "Office",
                "model": "eero Beacon",
                "resources": {"led_action": "/2.2/eeros/E1/led", "reboot": "/2.2/eeros/E1/reboot"},
                "nightlight": {
                    "url": "/2.2/eeros/E1/nightlight/settings",
                    "enabled": True,
                    "schedule": {"enabled": True, "on": "20:00", "off": "06:00"},
                },
            },
        ),
        "profile": eero_api.profile.EeroProfile(
            hub, network, {"url": f"{NETWORK_URL}/profiles/P1", "name": "Kids", "devices": []}
        ),
        "client": eero_api.client.EeroClient(
            hub, network, {"url": f"{NETWORK_URL}/devices/aabbccddeeff", "mac": MAC}
        ),
        "backup": eero_api.backup_network.EeroBackupNetwork(
            hub, network, {"uuid": "U1", "ssid": "Backup", "password": "pw"}
        ),
    }
    return session, hub, models


EMPTY = '""'  # the SDK's two-byte empty JSON string body on bodyless POSTs

WRITES = [
    # (id, model, method name, args, expected (METHOD, path, body))
    ("network.ad_block", "network", "async_set_ad_block", (True,),
     ("POST", f"{NETWORK_URL}/dns_policies/adblock", {"json": {"enable": True}})),
    ("network.block_malware", "network", "async_set_block_malware", (True,),
     ("POST", f"{NETWORK_URL}/dns_policies/network", {"json": {"block_malware": True}})),
    ("network.backup_internet", "network", "async_set_backup_internet_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/backupinternet", {"json": {"backup_internet_enabled": True}})),
    ("network.band_steering", "network", "async_set_band_steering", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"band_steering": True}})),
    ("network.ddns_on", "network", "async_set_ddns_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/ddns/enable", {})),
    ("network.dns_caching", "network", "async_set_dns_caching", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"dns": {"caching": True}}})),
    ("network.guest_network", "network", "async_set_guest_network_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/guestnetwork", {"data": {"enabled": "true"}})),
    ("network.guest_name", "network", "async_set_guest_network_name", ("New guests",),
     ("PUT", f"{NETWORK_URL}/guestnetwork", {"data": {"enabled": "true", "name": "New guests"}})),
    ("network.guest_password", "network", "async_set_guest_network_password", ("new-password-1",),
     ("PUT", f"{NETWORK_URL}/guestnetwork/password", {"data": {"password": "new-password-1"}})),
    ("network.ipv6_upstream", "network", "async_set_ipv6_upstream", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"ipv6_upstream": True}})),
    ("network.hide_5g_on", "network", "async_set_pause_5g_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/temporary_flags/hide_5g", {"json": {"value": True}})),
    ("network.hide_5g_off", "network", "async_set_pause_5g_enabled", (False,),
     ("DELETE", f"{NETWORK_URL}/temporary_flags/hide_5g", {})),
    ("network.preferred_update_hour", "network", "async_set_preferred_update_hour", ("3am_4am",),
     ("POST", f"{NETWORK_URL}/updates/preferred_update_hour",
      {"json": {"preferred_update_hour": 3}})),
    ("network.reboot", "network", "async_reboot", (),
     ("POST", f"{NETWORK_URL}/reboot", {"data": EMPTY})),
    ("network.speed_test", "network", "async_run_speed_test", (),
     ("POST", f"{NETWORK_URL}/speedtest", {"data": EMPTY})),
    ("network.backup_test", "network", "async_run_internet_backup_test", (),
     ("POST", f"{NETWORK_URL}/backup_access_points/connectivity_check", {"data": EMPTY})),
    ("network.sqm", "network", "async_set_sqm", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"sqm": True}})),
    ("network.thread", "network", "async_set_thread_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/thread/enable", {"json": {"enabled": True}})),
    ("network.firmware", "network", "async_install_firmware_update", (),
     ("POST", f"{NETWORK_URL}/updates", {"data": EMPTY})),
    ("network.upnp", "network", "async_set_upnp", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"upnp": True}})),
    ("network.wpa3", "network", "async_set_wpa3", (True,),
     ("PUT", f"{NETWORK_URL}/settings", {"json": {"wpa3": True}})),
    ("network.power_saving", "network", "async_set_power_saving_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/power_saving", {"json": {"enable": True}})),
    ("network.fast_transition", "network", "async_set_fast_transition_enabled", (True,),
     ("PUT", f"{NETWORK_URL}/fast_transition", {"json": {"fast_transition": True}})),
    ("network.mlo_mode", "network", "async_set_mlo_mode", ("multi",),
     ("PUT", f"{NETWORK_URL}/mlo_mode", {"json": {"mlo_mode": "multi"}})),
    ("profile.ad_block_on", "profile", "async_set_ad_block", (True,),
     ("POST", f"{NETWORK_URL}/dns_policies/adblock",
      {"json": {"enable": True, "profiles": [f"{NETWORK_URL}/profiles/P1"]}})),
    ("profile.ad_block_off_last", "profile", "async_set_ad_block", (False,),
     ("POST", f"{NETWORK_URL}/dns_policies/adblock", {"json": {"enable": False, "profiles": []}})),
    # Still raw transport, by design (eero-api#174): pinned so an SDK change
    # that starts rejecting the path is caught.
    ("profile.content_filter", "profile", "async_set_block_gaming_content", (True,),
     ("POST", f"{NETWORK_URL}/dns_policies/profiles/P1", {"json": {"block_gaming_content": True}})),
    ("profile.paused", "profile", "async_set_paused", (True,),
     ("PUT", f"{NETWORK_URL}/profiles/P1", {"json": {"paused": True}})),
    ("profile.blocked_apps", "profile", "async_set_blocked_applications", (["netflix"],),
     ("PUT", f"{NETWORK_URL}/dns_policies/profiles/P1/applications/blocked",
      {"json": {"applications": ["netflix"]}})),
    # Device writes are pinned to API 2.3 (a 2.2 write is a silent no-op).
    ("client.paused", "client", "async_set_paused", (True,),
     ("PUT", f"/2.3/networks/{NETWORK_ID}/devices/{MAC}", {"json": {"paused": True}})),
    ("client.internet_backup", "client", "async_set_secondary_wan_allow_access", (False,),
     ("PUT", f"/2.3/networks/{NETWORK_ID}/devices/{MAC}",
      {"json": {"secondary_wan_deny_access": True}})),
    ("client.block", "client", "async_set_blocked", (True,),
     ("POST", f"{NETWORK_URL}/blacklist", {"data": {"mac": MAC}})),
    ("client.unblock", "client", "async_set_blocked", (False,),
     ("DELETE", f"{NETWORK_URL}/blacklist/{MAC}", {})),
    ("eero.reboot", "eero", "async_reboot", (),
     ("POST", "/2.2/eeros/E1/reboot", {"data": EMPTY})),
    ("eero.status_light", "eero", "async_set_status_light", (False,),
     ("PUT", "/2.2/eeros/E1/led", {"data": {"led_on": "false"}})),
    ("eero.status_light_brightness", "eero", "async_set_status_light_brightness", (40,),
     ("PUT", "/2.2/eeros/E1/led", {"data": {"led_brightness": "40"}})),
    ("eero.nightlight_off", "eero", "async_set_nightlight_disabled", (),
     ("PUT", "/2.2/eeros/E1/nightlight/settings", {"json": {"enabled": False}})),
    ("eero.nightlight_on_time", "eero", "async_set_nightlight_schedule_on", (dtime(21, 30),),
     ("PUT", "/2.2/eeros/E1/nightlight/settings",
      {"json": {"enabled": True, "schedule": {"enabled": True, "on": "21:30", "off": "06:00"}}})),
    ("backup.auto_join", "backup", "async_set_auto_join_enabled", (False,),
     ("PUT", f"{NETWORK_URL}/backup_access_points/U1",
      {"json": {"ssid": "Backup", "password": "pw", "enabled": False}})),
]


@pytest.mark.parametrize(
    ("model", "method", "args", "expected"),
    [pytest.param(m, n, a, e, id=i) for i, m, n, a, e in WRITES],
)
async def test_write_sends_exactly_this_request(wire, model, method, args, expected) -> None:
    """Each setter sends one request, with this method, path and body."""
    session, _hub, models = wire

    await getattr(models[model], method)(*args)

    assert session.requests == [expected]


async def test_custom_dns_sends_both_families_in_one_write(wire) -> None:
    """Two families changing is one settings write: one mesh reboot, not two."""
    session, _hub, models = wire

    await models["network"].async_set_custom_dns(
        ipv4=["1.1.1.1"], ipv6=["2606:4700:4700::1111"]
    )

    assert session.requests == [
        (
            "PUT",
            f"{NETWORK_URL}/settings",
            {
                "json": {
                    "dns": {"mode": "custom", "custom": {"ips": ["1.1.1.1"]}},
                    "ipv6": {
                        "name_servers": {"mode": "custom", "custom": ["2606:4700:4700::1111"]}
                    },
                }
            },
        )
    ]


async def test_custom_dns_already_automatic_sends_nothing(wire) -> None:
    """Read-compare-skip reaches the wire: no request when nothing changes."""
    session, _hub, models = wire

    await models["network"].async_set_custom_dns(automatic=True)

    assert session.requests == []


async def test_account_read(wire) -> None:
    """The account comes from eero-api's AccountAPI.get_account."""
    session, hub, _models = wire
    session.data = {"name": "Owner", "networks": {"count": 0, "data": []}}

    account = await hub.get_account()

    assert session.requests == [("GET", "/2.2/account", {})]
    assert account["name"] == "Owner"


async def test_fast_tier_reads(wire) -> None:
    """A fast poll reads the network, its clients and profiles (and eeros if not embedded)."""
    session, hub, _models = wire

    await hub.fetch_fast(
        NETWORK_ID, eero_api.EeroUpdateConfig(get_devices=True, profiles=["P1"])
    )

    assert [(method, path) for method, path, _body in session.requests] == [
        ("GET", NETWORK_URL),
        ("GET", f"{NETWORK_URL}/devices"),
        ("GET", f"{NETWORK_URL}/profiles"),
        ("GET", f"{NETWORK_URL}/eeros"),
    ]


@pytest.mark.parametrize(
    ("activity", "resource", "profile_id", "path", "param_keys"),
    [
        ("data_usage_week", "network", None, f"{NETWORK_URL}/data_usage",
         {"start", "end", "cadence", "timezone"}),
        ("adblock_day", "profiles", "P1", f"{NETWORK_URL}/insights/profiles/P1",
         {"start", "end", "cadence", "insight_type"}),
        ("data_usage_week", "eeros", None, f"{NETWORK_URL}/data_usage/eeros",
         {"start", "end", "cadence", "timezone"}),
    ],
)
async def test_activity_reads_use_query_parameters(
    wire, activity, resource, profile_id, path, param_keys
) -> None:
    """Activity windows travel as query parameters; a GET never carries a body."""
    session, hub, _models = wire

    await hub.update_activity(activity, NETWORK_ID, resource, "UTC", profile_id)

    [(method, sent_path, body)] = session.requests
    assert (method, sent_path) == ("GET", path)
    assert set(body) == {"params"}
    assert set(body["params"]) == param_keys


async def test_burst_then_device_read(wire) -> None:
    """The live-usage burst is a bodyless POST to burst_reporters, then a plain device GET."""
    session, hub, _models = wire
    session.data = {"next_burst": "2026-10-20T00:01:00Z"}

    next_burst = await hub.request_burst(NETWORK_ID, {"url": NETWORK_URL})
    session.data = []
    devices = await hub.get_devices(NETWORK_ID)

    assert session.requests == [
        ("POST", f"{NETWORK_URL}/burst_reporters", {"data": EMPTY}),
        ("GET", f"{NETWORK_URL}/devices", {}),
    ]
    assert next_burst == "2026-10-20T00:01:00Z"
    assert devices == []


async def test_burst_follows_the_network_envelope_link(wire) -> None:
    """With a published burst_reporters link, the SDK posts there, not to the template."""
    session, hub, _models = wire
    link = f"/2.3/networks/{NETWORK_ID}/burst_reporters"

    await hub.request_burst(NETWORK_ID, {"url": NETWORK_URL, "resources": {"burst_reporters": link}})

    assert [(method, path) for method, path, _body in session.requests] == [("POST", link)]
