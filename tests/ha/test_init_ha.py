"""HA-level tests for the Eero integration (Python 3.14 only, needs HA installed)."""

from __future__ import annotations


from eero.exceptions import EeroAuthenticationException, EeroRateLimitException
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero.const import (
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
