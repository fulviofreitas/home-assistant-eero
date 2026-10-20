"""Live WAN throughput sensors: burst, settle, read, sum; the rules of issue #9."""

from __future__ import annotations

from datetime import timedelta

from eero.exceptions import (
    EeroAccessDeniedException,
    EeroPremiumRequiredException,
    EeroRateLimitException,
    EeroTimeoutException,
)
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)
import pytest

from custom_components.eero import coordinator as coordinator_module
from custom_components.eero.const import DOMAIN

from conftest import NETWORK_ID, NETWORK_URL, entry_data, network_envelope

BURST = "burst_reporters.create_burst_reporter"
NEXT_BURST = "2026-10-20T00:01:00Z"
ISSUE_ID_SUFFIX = f"_{NETWORK_ID}_wan_throughput"


def devices(*entries: dict) -> list[dict]:
    """Two connected devices with live usage, plus whatever a test adds."""
    return [
        {
            "url": f"{NETWORK_URL}/devices/aa",
            "mac": "AA:BB:CC:DD:EE:01",
            "connected": True,
            "usage": {"down_mbps": 10.125, "up_mbps": 1.5},
        },
        {
            "url": f"{NETWORK_URL}/devices/bb",
            "mac": "aa:bb:cc:dd:ee:02",
            "connected": True,
            "usage": {"down_mbps": 2, "up_mbps": 0.25},
        },
        {
            "url": f"{NETWORK_URL}/devices/cc",
            "mac": "aa:bb:cc:dd:ee:03",
            "connected": False,
            "usage": {"down_mbps": 99, "up_mbps": 99},
        },
        *entries,
    ]


@pytest.fixture(autouse=True)
def no_settle(monkeypatch):
    """The 12 s between the POST and the device read is not worth waiting for here."""
    monkeypatch.setattr(coordinator_module, "BURST_SETTLE_SECONDS", 0)


def bursts(sdk) -> int:
    return sum(1 for domain, _method, _args, _kwargs in sdk.calls if domain == "burst_reporters")


def wan_entity_ids(hass, entry) -> tuple[str | None, str | None]:
    registry = er.async_get(hass)
    return (
        registry.async_get_entity_id("sensor", DOMAIN, f"{NETWORK_ID}-wan_download"),
        registry.async_get_entity_id("sensor", DOMAIN, f"{NETWORK_ID}-wan_upload"),
    )


async def tick(hass, freezer, seconds: float) -> None:
    """Move time on and fire whatever became due."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def setup_entry(
    hass, sdk_factory, freezer=None, routes: dict | None = None, *, enable: bool = True
):
    """Load one network; with enable, turn both WAN sensors on.

    Enabling an entity makes Home Assistant reload the entry 30 s later,
    which is when the sensors are added and the first burst goes out.
    """
    sdk = sdk_factory(
        {
            BURST: {"next_burst": NEXT_BURST},
            "devices.get_devices": devices(),
            **(routes or {}),
        }
    )
    entry = MockConfigEntry(
        domain=DOMAIN, version=3, minor_version=0, data=entry_data(), options={}
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    if enable:
        registry = er.async_get(hass)
        for entity_id in wan_entity_ids(hass, entry):
            assert entity_id is not None
            registry.async_update_entity(entity_id, disabled_by=None)
        await tick(hass, freezer, RELOAD_AFTER_UPDATE_DELAY + 1)
    return sdk, entry


async def test_disabled_by_default_and_then_no_requests(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, enable=False)
    registry = er.async_get(hass)

    download, upload = wan_entity_ids(hass, entry)
    for entity_id in (download, upload):
        assert entity_id is not None
        assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None

    await tick(hass, freezer, 10 * 60)
    assert bursts(sdk) == 0


async def test_enabled_sensors_burst_then_read_and_sum(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    download, upload = wan_entity_ids(hass, entry)

    assert bursts(sdk) == 1
    burst_index = next(i for i, call in enumerate(sdk.calls) if call[0] == "burst_reporters")
    assert sdk.calls[burst_index][2] == (NETWORK_ID,)
    assert sdk.calls[burst_index][3]["parent"]["url"] == NETWORK_URL
    # The device read that follows the burst is its own request, after the POST.
    assert ("devices", "get_devices", (NETWORK_ID,), {}) in sdk.calls[burst_index + 1 :]

    state = hass.states.get(download)
    assert state.state == "12.125"
    assert state.attributes["unit_of_measurement"] == "Mbit/s"
    assert state.attributes["device_class"] == "data_rate"
    assert state.attributes["state_class"] == "measurement"
    assert state.attributes["next_burst"] == NEXT_BURST
    assert state.attributes["devices"] == 2
    assert hass.states.get(upload).state == "1.75"

    registry = er.async_get(hass)
    for entity_id in (download, upload):
        options = registry.async_get(entity_id).options
        assert options["sensor"]["suggested_display_precision"] == 2


async def test_at_most_one_burst_per_minute(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    coordinator = entry.runtime_data.burst
    assert bursts(sdk) == 1

    # A refresh asked for within the minute (a second sensor being added, a
    # manual one) runs, but sends no burst.
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert bursts(sdk) == 1

    await tick(hass, freezer, 30)
    assert bursts(sdk) == 1
    await tick(hass, freezer, 31)
    assert bursts(sdk) == 2


async def test_transport_error_keeps_the_reading_until_it_expires(
    hass, sdk_factory, freezer
) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    download, _upload = wan_entity_ids(hass, entry)
    assert hass.states.get(download).state == "12.125"

    sdk.set_route(BURST, EeroTimeoutException("slow"))
    await tick(hass, freezer, 61)
    assert bursts(sdk) == 2
    assert hass.states.get(download).state == "12.125"

    # 91 s after the reading, the expiry timer retires it: unavailable, not 0.
    await tick(hass, freezer, 31)
    assert hass.states.get(download).state == "unavailable"

    sdk.set_route(BURST, {"next_burst": NEXT_BURST})
    await tick(hass, freezer, 30)
    assert hass.states.get(download).state == "12.125"


async def test_a_device_read_failure_also_keeps_the_reading(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    download, _upload = wan_entity_ids(hass, entry)

    sdk.set_route("devices.get_devices", EeroTimeoutException("slow"))
    await tick(hass, freezer, 61)

    assert bursts(sdk) == 2
    assert hass.states.get(download).state == "12.125"


async def test_a_rate_limit_waits_at_least_retry_after(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    download, _upload = wan_entity_ids(hass, entry)

    sdk.set_route(BURST, EeroRateLimitException("slow down", retry_after=150))
    await tick(hass, freezer, 61)
    assert bursts(sdk) == 2
    sdk.set_route(BURST, {"next_burst": NEXT_BURST})

    await tick(hass, freezer, 61)
    await tick(hass, freezer, 61)
    assert bursts(sdk) == 2
    assert hass.states.get(download).state == "unavailable"

    await tick(hass, freezer, 61)
    assert bursts(sdk) == 3
    assert hass.states.get(download).state == "12.125"


async def test_an_unusable_usage_pair_makes_the_total_unknown_not_zero(
    hass, sdk_factory, freezer
) -> None:
    broken = {"url": f"{NETWORK_URL}/devices/dd", "mac": "aa:bb:cc:dd:ee:04", "connected": True}
    _sdk, entry = await setup_entry(
        hass, sdk_factory, freezer, {"devices.get_devices": devices(broken)}
    )
    download, upload = wan_entity_ids(hass, entry)

    for entity_id in (download, upload):
        state = hass.states.get(entity_id)
        assert state.state == "unknown"
        assert state.attributes["devices"] == 3


@pytest.mark.parametrize(
    ("error", "translation_key"),
    [
        (EeroPremiumRequiredException("burst"), "premium_required"),
        (EeroAccessDeniedException(403, "denied"), "wan_throughput_unavailable"),
    ],
)
async def test_a_refusal_raises_an_issue_and_stops_asking(
    hass, sdk_factory, freezer, error, translation_key
) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer, {BURST: error})
    download, upload = wan_entity_ids(hass, entry)

    assert bursts(sdk) == 1
    for entity_id in (download, upload):
        assert hass.states.get(entity_id).state == "unavailable"
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}{ISSUE_ID_SUFFIX}")
    assert issue is not None
    assert issue.translation_key == translation_key
    assert issue.translation_placeholders["network"] == "TestNetwork"

    sdk.set_route(BURST, {"next_burst": NEXT_BURST})
    await tick(hass, freezer, 5 * 60)
    assert bursts(sdk) == 1
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}{ISSUE_ID_SUFFIX}")

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"{entry.entry_id}{ISSUE_ID_SUFFIX}") is None


async def test_a_bridged_network_gets_no_wan_sensors(hass, sdk_factory) -> None:
    _sdk, entry = await setup_entry(
        hass,
        sdk_factory,
        routes={"networks.get_network": network_envelope(connection={"mode": "BRIDGE"})},
        enable=False,
    )

    assert wan_entity_ids(hass, entry) == (None, None)


async def test_unload_stops_the_bursts(hass, sdk_factory, freezer) -> None:
    sdk, entry = await setup_entry(hass, sdk_factory, freezer)
    assert bursts(sdk) == 1

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    await tick(hass, freezer, 5 * 60)

    assert bursts(sdk) == 1


async def test_diagnostics_carry_the_burst_readings(hass, sdk_factory, freezer) -> None:
    from custom_components.eero.diagnostics import async_get_config_entry_diagnostics

    _sdk, entry = await setup_entry(hass, sdk_factory, freezer)

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)

    burst = diagnostics["tiers"]["burst"]
    assert burst["refused"] == []
    assert burst["readings"][NETWORK_ID]["down_mbps"] == 12.125
    assert burst["readings"][NETWORK_ID]["devices"] == 2
    assert burst["readings"][NETWORK_ID]["next_burst"] == NEXT_BURST
