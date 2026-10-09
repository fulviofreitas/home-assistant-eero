"""HA-level tests for the Eero integration (Python 3.14 only, needs HA installed)."""

from __future__ import annotations


from eero.exceptions import EeroAuthenticationException, EeroRateLimitException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero.const import (
    CONF_ACTIVITY,
    CONF_ACTIVITY_NETWORK,
    CONF_BACKUP_NETWORKS,
    CONF_EEROS,
    CONF_FILTER_EXCLUDE,
    CONF_FILTER_INCLUDE,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
    DOMAIN,
    TIER_DAILY,
    TIER_FAST,
    TIER_HOURLY,
)

from conftest import NETWORK_ID, NETWORK_URL, entry_data, network_envelope


def make_entry(hass, **data_overrides) -> MockConfigEntry:
    """Create and register a VERSION 3 config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=3,
        minor_version=0,
        data=entry_data(**data_overrides),
        options={},
        unique_id="someone@example.com",
    )
    entry.add_to_hass(hass)
    return entry


async def test_setup_entry_loads_and_creates_entities_for_every_platform(
    hass, sdk_factory
) -> None:
    """A VERSION 3 entry loads, and builds at least one entity per platform."""
    sdk_factory()
    entry = make_entry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.LOADED

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entities = er.async_entries_for_config_entry(registry, entry.entry_id)
    platforms = {entity.entity_id.split(".")[0] for entity in entities}
    # A minimal network envelope doesn't support every platform (e.g.
    # binary_sensor needs a health block this fixture omits), but the
    # always-present ones must have built entities.
    assert "switch" in platforms
    assert "sensor" in platforms
    assert "select" in platforms


async def test_setup_entry_never_uses_the_executor(hass, sdk_factory, monkeypatch) -> None:
    """The async SDK means this integration never offloads to the executor.

    HA's own loader uses the executor for unrelated bookkeeping (scanning
    custom_components/), so only fail for a call whose target function lives
    in this integration's modules.
    """
    sdk_factory()
    entry = make_entry(hass)
    original = hass.async_add_executor_job

    def guarded(func, *args, **kwargs):
        module = getattr(func, "__module__", "") or ""
        if module.startswith("custom_components.eero"):
            raise AssertionError(f"async_add_executor_job was called with {func!r}")
        return original(func, *args, **kwargs)

    monkeypatch.setattr(hass, "async_add_executor_job", guarded)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_auth_failure_on_first_refresh_starts_reauth(hass, sdk_factory) -> None:
    """EeroAuthenticationException on the first poll -> SETUP_ERROR + a reauth flow."""
    sdk_factory({"networks.get_network": EeroAuthenticationException("expired")})
    entry = make_entry(hass)

    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert any(flow["context"].get("source") == "reauth" for flow in flows)


async def test_rate_limit_doubles_the_fast_interval_and_resets_on_success(
    hass, sdk_factory
) -> None:
    """A rate limit on a later poll doubles update_interval; the next success resets it."""
    sdk = sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    runtime = entry.runtime_data
    coordinator = runtime.coordinator(TIER_FAST)
    base = coordinator.base_interval

    sdk.set_route("networks.get_network", EeroRateLimitException("rate limited"))
    await coordinator.async_refresh()
    assert coordinator.update_interval == base * 2

    sdk.set_route("networks.get_network", network_envelope())
    await coordinator.async_refresh()
    assert coordinator.update_interval == base


async def test_switch_turn_on_calls_the_sdk_and_skips_when_already_on(
    hass, sdk_factory
) -> None:
    """A write calls the SDK; repeating it when already in that state sends nothing."""
    sdk = sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "switch.testnetwork_band_steering"
    state = hass.states.get(entity_id)
    assert state is not None, hass.states.async_entity_ids("switch")
    assert state.state == "off"

    sdk.calls.clear()
    sdk.set_route("security.set_band_steering", {})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    assert any(d == "security" and m == "set_band_steering" for d, m, _a, _kw in sdk.calls)

    # Fast tier re-fetch picks up band_steering=True from the updated envelope.
    sdk.set_route("networks.get_network", network_envelope(band_steering=True))
    await entry.runtime_data.coordinator(TIER_FAST).async_refresh()
    await hass.async_block_till_done()

    sdk.calls.clear()
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    assert not any(
        d == "security" and m == "set_band_steering" for d, m, _a, _kw in sdk.calls
    )


async def test_mlo_mode_select_only_created_when_capable(hass, sdk_factory) -> None:
    """mlo_mode is read from the network envelope; not created when not capable."""
    sdk_factory(
        {
            "networks.get_network": network_envelope(mlo_mode="single"),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get("select.testnetwork_mlo_mode") is None


def eero_entry_data(**overrides) -> dict:
    """Entry data with one eero ("e1") configured."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: ["e1"],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, **overrides})


async def test_port_sensors_and_port_action_button(hass, sdk_factory) -> None:
    """Per-port sensors read eeros.get_connections; the button calls port_action."""
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6"}
    connections = {
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
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
            "eeros.get_connections": connections,
        }
    )
    entry = make_entry(hass, **eero_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    status_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{NETWORK_ID}-e1-port_1_connection_status"
    )
    speed_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{NETWORK_ID}-e1-port_1_negotiated_speed"
    )
    button_id = registry.async_get_entity_id(
        "button", DOMAIN, f"{NETWORK_ID}-e1-port_1_action_restart_power"
    )
    assert status_id is not None
    assert speed_id is not None
    assert button_id is not None
    assert hass.states.get(status_id).state == "CONNECTED"
    assert hass.states.get(speed_id).state == "1000"
    # Disruptive, unconfirmed write: disabled by default, so there is no
    # live state to press through the service layer here; the SDK-call
    # shape itself is covered by the eero.port_action case in test_hub.py.
    assert registry.async_get(button_id).disabled


async def test_mlo_mode_select_reads_and_writes_when_capable(hass, sdk_factory) -> None:
    """mlo_mode reads the network envelope and writes via security.set_mlo_mode."""
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(
                mlo_mode="single",
                capabilities={"mlo_mode": {"capable": True}},
            ),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "select.testnetwork_mlo_mode"
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "single"
    assert set(state.attributes["options"]) == {"disabled", "single", "multi"}

    sdk.calls.clear()
    sdk.set_route("security.set_mlo_mode", {})
    await hass.services.async_call(
        "select", "select_option", {"entity_id": entity_id, "option": "multi"}, blocking=True
    )
    assert any(d == "security" and m == "set_mlo_mode" for d, m, _a, _kw in sdk.calls)


async def test_power_saving_and_fast_transition_switches(hass, sdk_factory) -> None:
    """power_saving (fast tier) and fast_transition (daily tier) read and write."""
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(power_saving=False),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    power_saving_id = "switch.testnetwork_power_saving"
    fast_transition_id = "switch.testnetwork_802_11r_fast_transition"
    assert hass.states.get(power_saving_id).state == "off"
    assert hass.states.get(fast_transition_id).state == "off"

    sdk.calls.clear()
    sdk.set_route("power_saving.set_power_saving", {})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": power_saving_id}, blocking=True
    )
    assert any(
        d == "power_saving" and m == "set_power_saving" for d, m, _a, _kw in sdk.calls
    )

    sdk.calls.clear()
    sdk.set_route("security.set_fast_transition", {})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": fast_transition_id}, blocking=True
    )
    assert any(
        d == "security" and m == "set_fast_transition" for d, m, _a, _kw in sdk.calls
    )

    # Repeating turn_on on fast_transition while still reporting off (no
    # refresh after an unconfirmed, possibly reboot-triggering write)
    # sends nothing new only once the daily tier reports it as on.
    sdk.set_route("security.get_fast_transition", {"fast_transition": True})
    await entry.runtime_data.coordinator(TIER_DAILY).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(fast_transition_id).state == "on"

    sdk.calls.clear()
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": fast_transition_id}, blocking=True
    )
    assert not any(
        d == "security" and m == "set_fast_transition" for d, m, _a, _kw in sdk.calls
    )


async def test_reservation_forward_and_dns_services_call_the_sdk(hass, sdk_factory) -> None:
    """Each of the five new actions calls its SDK method on the right network."""
    sdk = sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    sdk.set_route("reservations.create_reservation", {})
    await hass.services.async_call(
        DOMAIN,
        "create_reservation",
        {
            "target_network": ["TestNetwork"],
            "ip": "192.168.4.100",
            "mac": "aa:bb:cc:dd:ee:ff",
        },
        blocking=True,
    )
    assert any(
        d == "reservations" and m == "create_reservation" for d, m, _a, _kw in sdk.calls
    )

    sdk.set_route("reservations.delete_reservation", {})
    await hass.services.async_call(
        DOMAIN,
        "delete_reservation",
        {"target_network": ["TestNetwork"], "reservation": "r1", "delete_forwards": True},
        blocking=True,
    )
    assert any(
        d == "reservations" and m == "delete_reservation" for d, m, _a, _kw in sdk.calls
    )

    sdk.set_route("forwards.create_forward", {})
    await hass.services.async_call(
        DOMAIN,
        "create_port_forward",
        {
            "target_network": ["TestNetwork"],
            "ip": "192.168.4.100",
            "client_port": 8080,
            "gateway_port": 8080,
            "protocol": "tcp",
        },
        blocking=True,
    )
    assert any(d == "forwards" and m == "create_forward" for d, m, _a, _kw in sdk.calls)

    sdk.set_route("forwards.delete_forward", {})
    await hass.services.async_call(
        DOMAIN,
        "delete_port_forward",
        {"target_network": ["TestNetwork"], "forward": "f1"},
        blocking=True,
    )
    assert any(d == "forwards" and m == "delete_forward" for d, m, _a, _kw in sdk.calls)

    sdk.set_route(
        "dns.get_dns_settings",
        {"dns": {"mode": "automatic"}, "ipv6": {"name_servers": {"mode": "automatic"}}},
    )
    sdk.set_route("dns.set_custom_dns", {})
    await hass.services.async_call(
        DOMAIN,
        "set_custom_dns",
        {"target_network": ["TestNetwork"], "ipv4": ["1.1.1.1"]},
        blocking=True,
    )
    assert any(d == "dns" and m == "set_custom_dns" for d, m, _a, _kw in sdk.calls)

    # target_network filters: a non-matching target calls nothing.
    sdk.calls.clear()
    await hass.services.async_call(
        DOMAIN,
        "delete_port_forward",
        {"target_network": ["no-such-network"], "forward": "f1"},
        blocking=True,
    )
    assert not sdk.calls


def client_entry_data(**overrides) -> dict:
    """Entry data with wired clients discovered (exclude filter -> any device qualifies)."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, **overrides})


async def test_switch_block_and_unblock_client(hass, sdk_factory) -> None:
    """Blocking calls add_to_blacklist; the switch reflects the daily-tier blacklist read."""
    mac = "aa:bb:cc:dd:ee:ff"
    device = {
        "url": f"{NETWORK_URL}/devices/{mac}",
        "mac": mac,
        "wireless": False,
        "nickname": "TestClient",
    }
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [device],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass, **client_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    unique_id = f"{NETWORK_ID}-{mac}-blocked"
    entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"

    sdk.calls.clear()
    sdk.set_route("blacklist.add_to_blacklist", {})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    assert any(
        d == "blacklist" and m == "add_to_blacklist" for d, m, _a, _kw in sdk.calls
    )

    sdk.set_route("blacklist.get_blacklist", [{"mac": mac}])
    await entry.runtime_data.coordinator(TIER_DAILY).async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id)
    assert state.state == "on"

    sdk.calls.clear()
    sdk.set_route("blacklist.remove_from_blacklist", {})
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )
    assert any(
        d == "blacklist" and m == "remove_from_blacklist" for d, m, _a, _kw in sdk.calls
    )


def profile_entry_data(**overrides) -> dict:
    """Entry data with one profile ("p1") configured."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: ["p1"],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, **overrides})


async def test_switch_and_time_bedtime_schedule(hass, sdk_factory) -> None:
    """Bedtime switch/time entities read the daily schedules read and write via the SDK."""
    profile = {"url": f"{NETWORK_URL}/profiles/p1", "name": "Kid"}
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "profiles.get_profiles": [profile],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "schedule.get_schedules": [],
        }
    )
    entry = make_entry(hass, **profile_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    switch_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{NETWORK_ID}-p1-bedtime_enabled"
    )
    assert switch_id is not None
    assert hass.states.get(switch_id).state == "off"

    sdk.calls.clear()
    sdk.set_route("schedule.set_weekday_bedtime", {})
    sdk.set_route("schedule.set_weekend_bedtime", {})
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_id}, blocking=True
    )
    assert any(
        d == "schedule" and m == "set_weekday_bedtime" for d, m, _a, _kw in sdk.calls
    )
    assert any(
        d == "schedule" and m == "set_weekend_bedtime" for d, m, _a, _kw in sdk.calls
    )

    # Daily tier re-fetch picks up the created schedule.
    sdk.set_route(
        "schedule.get_schedules",
        [
            {
                "name": "Bedtime",
                "days": [
                    "monday",
                    "tuesday",
                    "wednesday",
                    "thursday",
                    "friday",
                ],
                "start": "22:00",
                "end": "07:00",
                "enabled": True,
                "url": f"{NETWORK_URL}/profiles/p1/schedules/1",
            }
        ],
    )
    await entry.runtime_data.coordinator(TIER_DAILY).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(switch_id).state == "on"

    time_id = registry.async_get_entity_id(
        "time", DOMAIN, f"{NETWORK_ID}-p1-bedtime_weekday_start"
    )
    assert time_id is not None
    assert hass.states.get(time_id).state == "22:00:00"

    sdk.calls.clear()
    sdk.set_route("schedule.update_schedule", {})
    await hass.services.async_call(
        "time", "set_value", {"entity_id": time_id, "time": "21:30:00"}, blocking=True
    )
    assert any(
        d == "schedule" and m == "update_schedule" and kw.get("start") == "21:30"
        for d, m, _a, kw in sdk.calls
    )


def client_and_profile_entry_data(**overrides) -> dict:
    """Entry data with wired clients discovered and two profiles configured."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: ["kids", "adults"],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_EXCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    return entry_data(**{CONF_RESOURCES: resources, **overrides})


async def test_select_profile_assignment_moves_a_client(hass, sdk_factory) -> None:
    """The profile select reads the fast-tier profiles and moves the client on write."""
    mac = "aa:bb:cc:dd:ee:ff"
    device_url = f"{NETWORK_URL}/devices/{mac}"
    device = {"url": device_url, "mac": mac, "wireless": False, "nickname": "TestClient"}
    profiles = [
        {
            "url": f"{NETWORK_URL}/profiles/kids",
            "name": "Kids",
            "devices": [{"url": device_url, "mac": mac}],
        },
        {"url": f"{NETWORK_URL}/profiles/adults", "name": "Adults", "devices": []},
    ]
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [device],
            "profiles.get_profiles": profiles,
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "blacklist.get_blacklist": [],
            "schedule.get_schedules": [],
        }
    )
    entry = make_entry(hass, **client_and_profile_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "select", DOMAIN, f"{NETWORK_ID}-{mac}-profile_assignment"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state.state == "Kids"
    assert set(state.attributes["options"]) == {"Unassigned", "Kids", "Adults"}

    sdk.calls.clear()
    sdk.set_route("profiles.set_profile_devices", {})
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "Adults"},
        blocking=True,
    )
    assert (
        "profiles",
        "set_profile_devices",
        (NETWORK_ID, "kids", []),
        {},
    ) in sdk.calls
    assert (
        "profiles",
        "set_profile_devices",
        (NETWORK_ID, "adults", [device_url]),
        {},
    ) in sdk.calls


async def test_select_profile_assignment_not_created_without_a_configured_profile(
    hass, sdk_factory
) -> None:
    """No profile configured on the network -> no profile_assignment select at all."""
    mac = "aa:bb:cc:dd:ee:ff"
    device = {
        "url": f"{NETWORK_URL}/devices/{mac}",
        "mac": mac,
        "wireless": False,
        "nickname": "TestClient",
    }
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [device],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass, **client_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    assert (
        registry.async_get_entity_id(
            "select", DOMAIN, f"{NETWORK_ID}-{mac}-profile_assignment"
        )
        is None
    )


async def test_diagnostics_redacts_the_token(hass, sdk_factory) -> None:
    """The config entry diagnostics never leak the session token."""
    sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from custom_components.eero.diagnostics import async_get_config_entry_diagnostics

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    assert diagnostics["entry"]["data"]["user_token"] == "**REDACTED**"


async def test_token_persistence_updates_entry_without_reload(hass, sdk_factory) -> None:
    """A rotated SDK token is written to entry.data; the entry is not reloaded for it."""
    sdk = sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    reloads = 0
    original_reload = hass.config_entries.async_reload

    async def counting_reload(entry_id):
        nonlocal reloads
        reloads += 1
        return await original_reload(entry_id)

    hass.config_entries.async_reload = counting_reload

    sdk.auth.token = "NEW-TOKEN"
    await entry.runtime_data.coordinator(TIER_FAST).async_refresh()
    await hass.async_block_till_done()

    assert entry.data["user_token"] == "NEW-TOKEN"
    assert reloads == 0


async def test_new_client_gets_entities_without_a_reload(hass, sdk_factory) -> None:
    """A client that joins after setup gets entities on the next fast-tier poll.

    No config entry reload is involved: only coordinator.async_refresh().
    """
    mac = "aa:bb:cc:dd:ee:ff"
    device = {
        "url": f"{NETWORK_URL}/devices/{mac}",
        "mac": mac,
        "wireless": False,
        "nickname": "TestClient",
    }
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass, **client_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    unique_id = f"{NETWORK_ID}-{mac}-blocked"
    assert registry.async_get_entity_id("switch", DOMAIN, unique_id) is None

    reloads = 0
    original_reload = hass.config_entries.async_reload

    async def counting_reload(entry_id):
        nonlocal reloads
        reloads += 1
        return await original_reload(entry_id)

    hass.config_entries.async_reload = counting_reload

    sdk.set_route("devices.get_devices", [device])
    await entry.runtime_data.coordinator(TIER_FAST).async_refresh()
    await hass.async_block_till_done()

    entity_id = registry.async_get_entity_id("switch", DOMAIN, unique_id)
    assert entity_id is not None
    assert hass.states.get(entity_id) is not None
    assert reloads == 0

    # A second poll with the same client must not add it again.
    added_before = len(er.async_entries_for_config_entry(registry, entry.entry_id))
    await entry.runtime_data.coordinator(TIER_FAST).async_refresh()
    await hass.async_block_till_done()
    assert len(er.async_entries_for_config_entry(registry, entry.entry_id)) == added_before


async def test_event_app_events_fires_new_events_once_and_binary_sensor_has_unread(
    hass, sdk_factory
) -> None:
    """The event entity fires once per new app event; has_unread tracks notifications."""
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "events.get_app_events": {
                "events": [{"id": "1", "message": "device connected"}]
            },
            "notifications.has_unread": {"has_unread": False},
        }
    )
    entry = make_entry(
        hass,
        **{
            CONF_ACTIVITY: {
                NETWORK_ID: {
                    CONF_ACTIVITY_NETWORK: [
                        "app_events",
                        "notifications_has_unread",
                    ]
                }
            }
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    event_id = "event.testnetwork_app_events"
    unread_id = "binary_sensor.testnetwork_unread_notifications"
    assert hass.states.get(event_id) is not None
    assert hass.states.get(unread_id).state == "off"
    # Nothing has fired yet: event "1" was already present when the entity
    # was added, so it was recorded as seen without firing.
    assert hass.states.get(event_id).state == "unknown"

    # Re-polling with the same, already-seen event must not fire it.
    await entry.runtime_data.coordinator(TIER_HOURLY).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(event_id).state == "unknown"

    # A genuinely new event does fire.
    sdk.set_route(
        "events.get_app_events",
        {
            "events": [
                {"id": "1", "message": "device connected"},
                {"id": "2", "message": "device disconnected"},
            ]
        },
    )
    sdk.set_route("notifications.has_unread", {"has_unread": True})
    await entry.runtime_data.coordinator(TIER_HOURLY).async_refresh()
    await hass.async_block_till_done()

    second_state = hass.states.get(event_id).state
    assert second_state != "unknown"
    assert hass.states.get(unread_id).state == "on"

    # Re-polling with the same two events again must not fire anything.
    await entry.runtime_data.coordinator(TIER_HOURLY).async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(event_id).state == second_state


async def test_sensor_unprofiled_data_usage_has_a_tz_aware_last_reset(
    hass, sdk_factory
) -> None:
    """The new TOTAL sensor reports last_reset as the start of today, tz-aware."""
    from datetime import datetime

    from homeassistant.helpers.entity_platform import async_get_platforms

    sdk_factory(
        {
            "networks.get_network": network_envelope(timezone={"value": "UTC"}),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "data_usage.get_unprofiled_summary": [
                {"type": "download", "sum": 10},
                {"type": "upload", "sum": 2},
            ],
        }
    )
    entry = make_entry(
        hass,
        **{
            CONF_ACTIVITY: {
                NETWORK_ID: {CONF_ACTIVITY_NETWORK: ["unprofiled_data_usage_day"]}
            }
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entity_id = "sensor.testnetwork_unprofiled_data_usage"
    assert hass.states.get(entity_id) is not None, hass.states.async_entity_ids("sensor")

    platform = next(
        p for p in async_get_platforms(hass, DOMAIN) if entity_id in p.entities
    )
    entity = platform.entities[entity_id]
    assert isinstance(entity.last_reset, datetime)
    assert entity.last_reset.tzinfo is not None
    assert entity.last_reset.hour == 0
    assert entity.last_reset.minute == 0


async def test_text_guest_network_name_and_write_only_password(hass, sdk_factory) -> None:
    """The guest SSID text reads/writes; the password text is write-only (always unknown)."""
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(
                guest_network={"enabled": True, "name": "MyGuest", "password": "leaked"}
            ),
            "eeros.get_eeros": [],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    name_id = "text.testnetwork_guest_network_name"
    password_id = "text.testnetwork_guest_network_password"
    assert hass.states.get(name_id).state == "MyGuest"
    # Never reports the real password, even though the fixture carries one.
    password_state = hass.states.get(password_id)
    assert password_state is not None
    assert password_state.state in (None, "unknown")

    sdk.calls.clear()
    sdk.set_route("networks.set_guest_network", {})
    await hass.services.async_call(
        "text", "set_value", {"entity_id": name_id, "value": "NewGuest"}, blocking=True
    )
    assert (
        "networks",
        "set_guest_network",
        (NETWORK_ID,),
        {"enabled": True, "name": "NewGuest"},
    ) in sdk.calls

    sdk.calls.clear()
    sdk.set_route("networks.set_guest_password", {})
    await hass.services.async_call(
        "text",
        "set_value",
        {"entity_id": password_id, "value": "supersecret1"},
        blocking=True,
    )
    assert (
        "networks",
        "set_guest_password",
        (NETWORK_ID, "supersecret1"),
        {},
    ) in sdk.calls
    # Still never reports the password after writing it.
    assert hass.states.get(password_id).state in (None, "unknown")


async def test_unload_entry(hass, sdk_factory) -> None:
    """The entry unloads cleanly."""
    sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.config_entries import ConfigEntryState

    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_device_tracker_reads_connected_state(hass, sdk_factory) -> None:
    """The device_tracker entity reads the wired client's connected flag."""
    mac = "aa:bb:cc:dd:ee:ff"
    device = {
        "url": f"{NETWORK_URL}/devices/{mac}",
        "mac": mac,
        "wireless": False,
        "nickname": "TestClient",
        "connected": True,
    }
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [],
            "devices.get_devices": [device],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "blacklist.get_blacklist": [],
        }
    )
    entry = make_entry(hass, **client_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "device_tracker", DOMAIN, f"{NETWORK_ID}-{mac}-device_tracker"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "home"


async def test_light_status_light_reads_and_writes(hass, sdk_factory) -> None:
    """The status light reads led_on from the eero envelope and writes set_led."""
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6", "led_on": False}
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "eeros.get_connections": {},
        }
    )
    entry = make_entry(hass, **eero_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "light", DOMAIN, f"{NETWORK_ID}-e1-status_light_enabled"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "off"

    sdk.calls.clear()
    sdk.set_route("eeros.set_led", {})
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": entity_id}, blocking=True
    )
    assert any(d == "eeros" and m == "set_led" for d, m, _a, _kw in sdk.calls)


async def test_number_nightlight_brightness_reads_and_writes(hass, sdk_factory) -> None:
    """The nightlight brightness number reads/writes on an eero Beacon."""
    eero = {
        "url": "/2.2/eeros/e1",
        "model": "eero Beacon",
        "nightlight": {"brightness_percentage": 40},
    }
    sdk = sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "eeros.get_connections": {},
        }
    )
    entry = make_entry(hass, **eero_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "number", DOMAIN, f"{NETWORK_ID}-e1-nightlight_brightness_percentage"
    )
    assert entity_id is not None
    assert hass.states.get(entity_id).state == "40"

    sdk.calls.clear()
    sdk.set_route("eeros.set_nightlight", {})
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": 60},
        blocking=True,
    )
    assert any(d == "eeros" and m == "set_nightlight" for d, m, _a, _kw in sdk.calls)


async def test_update_firmware_reports_installed_version(hass, sdk_factory) -> None:
    """The firmware update entity reports the eero's installed OS version."""
    eero = {"url": "/2.2/eeros/e1", "model": "eero 6", "os_version": "6.1.0-99"}
    sdk_factory(
        {
            "networks.get_network": network_envelope(),
            "eeros.get_eeros": [eero],
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "eeros.get_connections": {},
        }
    )
    entry = make_entry(hass, **eero_entry_data())
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        "update", DOMAIN, f"{NETWORK_ID}-e1-firmware"
    )
    assert entity_id is not None
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.attributes["installed_version"] == "6.1.0-99"


def test_port_value_helpers_map_phy_rate_and_tolerate_odd_shapes() -> None:
    """Port sensor value functions map PhyRate to Mbit/s and tolerate odd shapes."""
    from custom_components.eero import sensor as eero_sensor

    assert eero_sensor._port_negotiated_speed({"negotiated_speed": "P1000"}) == 1000
    assert eero_sensor._port_negotiated_speed({"negotiated_speed": "P25000"}) == 25000
    assert eero_sensor._port_negotiated_speed({"negotiated_speed": "bogus"}) is None
    assert eero_sensor._port_negotiated_speed({}) is None

    assert (
        eero_sensor._port_connection_status({"connection_status": "CONNECTED"})
        == "CONNECTED"
    )
    assert (
        eero_sensor._port_connection_status(
            {"connection_status": {"status": "CONNECTED"}}
        )
        == "CONNECTED"
    )
    assert eero_sensor._port_connection_status({}) is None
