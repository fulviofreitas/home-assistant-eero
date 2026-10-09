"""One fully-featured network: every description must yield an entity, every writable one must reach the SDK."""

from __future__ import annotations

from datetime import time as _time

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero import binary_sensor, button, device_tracker, event
from custom_components.eero import light, number, select, sensor, switch, text
from custom_components.eero import time as eero_time
from custom_components.eero import update
from custom_components.eero.api.const import (
    MODEL_BEACON,
)
from custom_components.eero.const import (
    ACTIVITIES_PREMIUM,
    CONF_ACTIVITY,
    CONF_ACTIVITY_CLIENTS,
    CONF_ACTIVITY_EEROS,
    CONF_ACTIVITY_NETWORK,
    CONF_ACTIVITY_PROFILES,
    CONF_BACKUP_NETWORKS,
    CONF_EEROS,
    CONF_FILTER_EXCLUDE,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
)

from conftest import NETWORK_ID, NETWORK_URL, entry_data, network_envelope

#: platform -> description lists the platform builds entities from.
PLATFORM_DESCRIPTIONS = {
    "binary_sensor": binary_sensor.BINARY_SENSOR_DESCRIPTIONS,
    "button": button.BUTTON_DESCRIPTIONS,
    "device_tracker": device_tracker.DEVICE_TRACKER_DESCRIPTIONS,
    "event": event.EVENT_DESCRIPTIONS,
    "light": light.LIGHT_DESCRIPTIONS,
    "number": number.NUMBER_DESCRIPTIONS,
    "select": select.SELECT_DESCRIPTIONS,
    "sensor": [*sensor.SENSOR_DESCRIPTIONS, *sensor.PORT_SENSOR_DESCRIPTIONS],
    "switch": switch.SWITCH_DESCRIPTIONS,
    "text": text.TEXT_DESCRIPTIONS,
    "time": eero_time.TIME_DESCRIPTIONS,
    "update": update.UPDATE_DESCRIPTIONS,
}

#: (platform, key) pairs no single fixture can produce, with the reason.
ALLOWED_MISSING: dict[tuple[str, str], str] = {}

CLIENT_WIRED = f"{NETWORK_URL}/devices/aa"
CLIENT_WIRELESS = f"{NETWORK_URL}/devices/bb"
PROFILE_URL = f"{NETWORK_URL}/profiles/p1"
SCHEDULE_DAYS_WEEKDAY = ["monday", "tuesday", "wednesday", "thursday", "friday"]
SCHEDULE_DAYS_WEEKEND = ["saturday", "sunday"]


def full_network() -> dict:
    return network_envelope(
        name="TestNetwork",
        nickname_label="Home",
        band_steering=True,
        wpa3=True,
        upnp=True,
        sqm=True,
        ipv6_upstream=True,
        power_saving=True,
        mlo_mode="single",
        premium_status="active",
        backup_internet_enabled=True,
        ddns={"enabled": True, "subdomain": "home"},
        dns={"caching": True, "mode": "automatic"},
        gateway_ip="192.168.4.1",
        geo_ip={"city": "Chicago", "regionName": "Illinois", "isp": "ISP"},
        guest_network={"enabled": True, "name": "Guest", "password": "pw"},
        health={
            "eero_network": {"status": "green"},
            "internet": {"isp_up": True, "status": "green"},
        },
        ip_settings={"public_ip": "1.2.3.4"},
        lease={"dhcp": {"router": "192.168.4.1", "mask": "255.255.255.0"}},
        speed={
            "date": "2024-01-01",
            "down": {"value": 100, "units": "Mbps"},
            "up": {"value": 10, "units": "Mbps"},
        },
        status="connected",
        temporary_flags={"hide_5g": {"value": False}},
        capabilities={
            "premium": {"capable": True},
            "mlo_mode": {"capable": True},
            "backup_access_point": {"capable": True, "requirements": {}},
        },
        premium_dns={
            "ad_block_settings": {"enabled": True, "profiles": []},
            "dns_policies": {"block_malware": True},
        },
        updates={
            "preferred_update_hour": 3,
            "release_notes": {"history": [], "target": {"os_version": "9.9.9"}},
        },
        resources={
            "settings": f"{NETWORK_URL}/settings",
            "thread": f"{NETWORK_URL}/thread",
            "insights": f"{NETWORK_URL}/insights",
            "updates": f"{NETWORK_URL}/updates",
        },
        eeros={
            "count": 2,
            "data": [
                {
                    "url": "/2.2/eeros/e1",
                    "model": "eero 6",
                    "location": "Office",
                    "gateway": True,
                    "mac_address": "aa:bb",
                    "led_on": True,
                    "led_brightness": 50,
                    "os_version": "1.0.0",
                    "update_available": True,
                    "status": "green",
                    "connected_clients_count": 2,
                },
                {
                    "url": "/2.2/eeros/b1",
                    "model": MODEL_BEACON,
                    "location": "Hall",
                    "led_on": True,
                    "led_brightness": 50,
                    "os_version": "1.0.0",
                    "status": "green",
                    "nightlight": {
                        "enabled": True,
                        "brightness_percentage": 40,
                        "schedule": {"enabled": True, "on": "20:00", "off": "07:00"},
                    },
                },
            ],
        },
    )


def full_routes() -> dict:
    schedule = [
        {
            "name": "Bedtime",
            "days": SCHEDULE_DAYS_WEEKDAY,
            "start": "22:00",
            "end": "07:00",
            "enabled": True,
            "url": f"{PROFILE_URL}/schedules/1",
        },
        {
            "name": "Bedtime",
            "days": SCHEDULE_DAYS_WEEKEND,
            "start": "23:00",
            "end": "08:00",
            "enabled": True,
            "url": f"{PROFILE_URL}/schedules/2",
        },
    ]
    ports = {
        "ports": {
            "interfaces": [
                {
                    "interface_number": 1,
                    "connection_status": "CONNECTED",
                    "negotiated_speed": "P1000",
                    "actions": [{"position": 0, "type": "RESTART_POWER"}],
                }
            ]
        }
    }
    return {
        "networks.get_network": full_network(),
        "devices.get_devices": [
            {
                "url": CLIENT_WIRED,
                "mac": "aa",
                "wireless": False,
                "connected": True,
                "nickname": "Wired",
                "ip": "192.168.4.10",
                "device_type": "desktop_computer",
                "last_active": "2024-01-01T00:00:00+00:00",
                "usage": {"down_mbps": 1, "up_mbps": 2},
            },
            {
                "url": CLIENT_WIRELESS,
                "mac": "bb",
                "wireless": True,
                "connected": True,
                "nickname": "Wireless",
                "ip": "192.168.4.11",
                "is_guest": True,
                "connectivity": {"signal": "-50 dBm"},
                "last_active": "2024-01-01T00:00:00+00:00",
                "usage": {"down_mbps": 1, "up_mbps": 2},
            },
        ],
        "profiles.get_profiles": [
            {
                "url": PROFILE_URL,
                "name": "Kids",
                "paused": False,
                "devices": [{"url": CLIENT_WIRED, "mac": "aa", "connected": True}],
                "premium_dns": {"blocked_applications": ["netflix"]},
                "unified_content_filters": {"dns_policies": {"block_gaming_content": False}},
            }
        ],
        "blacklist.get_blacklist": [],
        "schedule.get_schedules": schedule,
        "reservations.get_reservations": [],
        "forwards.get_forwards": [],
        "security.get_fast_transition": {"fast_transition": True},
        "thread.get_thread": {"enabled": True, "name": "thread", "channel": 15},
        "entitlements.get_features": {"features": ["plus"]},
        "updates.get_updates": {},
        "backup_access_points.list": [
            {"uuid": "bn1", "ssid": "Backup", "password": "pw", "enabled": True}
        ],
        "backup.get_backup_internet": {"backup_internet_enabled": True},
        "eeros.get_connections": ports,
        # hourly activity reads: shape is irrelevant to entity creation
        "data_usage.get_data_usage": [],
        "data_usage.get_devices_usage": [],
        "data_usage.get_profile_usage": [],
        "data_usage.get_unprofiled_summary": [],
        "data_usage.get_eeros_summary": [],
        "GET /2.2/networks/1234567/data_usage/eeros": [],
        "insights.get_insights": [],
        "insights.get_devices_insights": [],
        "insights.get_profile_insights": [],
        "GET /2.2/networks/1234567/insights/eeros": [],
        "events.get_app_events": [],
        "notifications.has_unread": {"has_unread": True},
    }


def full_entry_data() -> dict:
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: ["bn1"],
            CONF_EEROS: ["e1", "b1"],
            CONF_PROFILES: ["p1"],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
        }
    }
    activities = list(ACTIVITIES_PREMIUM)
    activity = {
        NETWORK_ID: {
            CONF_ACTIVITY_NETWORK: activities,
            CONF_ACTIVITY_EEROS: activities,
            CONF_ACTIVITY_PROFILES: activities,
            CONF_ACTIVITY_CLIENTS: activities,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, CONF_ACTIVITY: activity})


async def setup_full(hass, sdk_factory):
    sdk = sdk_factory(full_routes())
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=full_entry_data(),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return sdk, entry


def registered(hass, entry):
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    return registry, er.async_entries_for_config_entry(registry, entry.entry_id)


async def test_every_description_key_produces_an_entity(hass, sdk_factory) -> None:
    """A missing (platform, key) is a description no entity is ever created from."""
    _sdk, entry = await setup_full(hass, sdk_factory)
    _registry, entities = registered(hass, entry)

    missing = []
    for platform, descriptions in PLATFORM_DESCRIPTIONS.items():
        unique_ids = [e.unique_id for e in entities if e.domain == platform]
        for description in descriptions:
            pair = (platform, description.key)
            if pair in ALLOWED_MISSING:
                continue
            if not any(uid.endswith((f"-{description.key}", f"_{description.key}")) for uid in unique_ids):
                missing.append(pair)
    assert not missing, f"descriptions that created no entity: {missing}"


WRITE_PLATFORMS = ("switch", "select", "number", "time", "text", "light", "button")


def is_write(call) -> bool:
    domain, method, _args, _kwargs = call
    if domain == "auth":
        return False
    return not method.startswith(("get", "list", "has_"))


async def test_every_writable_entity_reaches_the_sdk(hass, sdk_factory) -> None:
    sdk, entry = await setup_full(hass, sdk_factory)
    registry, entities = registered(hass, entry)

    # Any SDK write the fixture has no route for answers an empty body.
    original = sdk.resolve

    def permissive(key, args, kwargs):
        if key not in sdk._routes:
            sdk.set_route(key, {})
        return original(key, args, kwargs)

    sdk.resolve = permissive

    # Disabled-by-default entities (per-port buttons) need enabling first.
    disabled = [e for e in entities if e.disabled_by and e.domain in WRITE_PLATFORMS]
    for entity in disabled:
        registry.async_update_entity(entity.entity_id, disabled_by=None)
    if disabled:
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()
        _registry, entities = registered(hass, entry)
        sdk.resolve = permissive

    failures = []
    tried = 0
    for entity in sorted(entities, key=lambda e: e.entity_id):
        if entity.domain not in WRITE_PLATFORMS:
            continue
        state = hass.states.get(entity.entity_id)
        if state is None or state.state == "unavailable":
            failures.append((entity.entity_id, "no live state"))
            continue
        domain = entity.domain
        eid = entity.entity_id
        if domain == "switch" or domain == "light":
            service, data = ("turn_off" if state.state == "on" else "turn_on"), {}
        elif domain == "button":
            service, data = "press", {}
        elif domain == "select":
            options = [o for o in state.attributes["options"] if o != state.state]
            service, data = "select_option", {"option": options[0]}
        elif domain == "number":
            service, data = "set_value", {"value": 30 if state.state != "30.0" else 60}
        elif domain == "time":
            service, data = "set_value", {"time": _time(5, 7)}
        else:  # text
            service, data = "set_value", {"value": "new-value-123"}
        before = len(sdk.calls)
        tried += 1
        try:
            await hass.services.async_call(
                domain, service, {"entity_id": eid, **data}, blocking=True
            )
            await hass.async_block_till_done()
        except Exception as error:  # noqa: BLE001
            failures.append((eid, f"raised {error!r}"))
            continue
        if not any(is_write(call) for call in sdk.calls[before:]):
            failures.append((eid, "no SDK write recorded"))

    assert tried > 30
    assert not failures, failures
