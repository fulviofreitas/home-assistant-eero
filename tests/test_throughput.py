"""Live WAN throughput: the sum over a device list, and the hub's burst request.

Standalone (no Home Assistant): the pure wan_total() rules from issue #9,
and the two hub reads the burst coordinator makes, through a FakeSDK.
"""

from __future__ import annotations

import math
from typing import Any

from eero.exceptions import EeroAccessDeniedException
import pytest

from helpers import FakeSDK, build_hub, eero_api

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


def device(
    mac: str | None = "aa:bb:cc:dd:ee:01",
    *,
    connected: Any = True,
    down: Any = 1.5,
    up: Any = 0.5,
    url: str | None = None,
    usage: Any = ...,
) -> dict[str, Any]:
    """Return one device-list entry; usage=None drops the usage block."""
    data: dict[str, Any] = {"connected": connected}
    if mac is not None:
        data["mac"] = mac
    if url is not None:
        data["url"] = url
    if usage is ...:
        data["usage"] = {"down_mbps": down, "up_mbps": up}
    elif usage is not None:
        data["usage"] = usage
    return data


def test_sums_connected_devices_only() -> None:
    total = eero_api.wan_total(
        [
            device("aa", down=10, up=1),
            device("bb", down=2.25, up=0.75),
            device("cc", connected=False, down=100, up=100),
        ]
    )
    assert total == eero_api.WanTotal(12.25, 1.75, 2)


@pytest.mark.parametrize("connected", ["true", 1, None, "connected"])
def test_connected_must_be_exactly_true(connected: Any) -> None:
    assert eero_api.wan_total([device("aa", connected=connected)]) == eero_api.WanTotal(
        0.0, 0.0, 0
    )


def test_dedupes_by_lower_cased_mac_first_occurrence_wins() -> None:
    total = eero_api.wan_total(
        [device("AA:BB:CC:DD:EE:01", down=3, up=1), device("aa:bb:cc:dd:ee:01", down=9, up=9)]
    )
    assert total == eero_api.WanTotal(3.0, 1.0, 1)


def test_falls_back_to_url_without_a_mac_and_skips_entries_with_neither() -> None:
    total = eero_api.wan_total(
        [
            device(None, url=f"{NETWORK_URL}/devices/x", down=1, up=1),
            device(None, url=f"{NETWORK_URL}/devices/x", down=5, up=5),
            device("", url=f"{NETWORK_URL}/devices/y", down=2, up=2),
            device(None, down=100, up=100),
        ]
    )
    assert total == eero_api.WanTotal(3.0, 3.0, 2)


def test_non_dict_entries_are_ignored() -> None:
    assert eero_api.wan_total([None, "device", 3, device("aa", down=1, up=2)]) == (
        eero_api.WanTotal(1.0, 2.0, 1)
    )


def test_no_connected_devices_is_a_real_zero() -> None:
    assert eero_api.wan_total([]) == eero_api.WanTotal(0.0, 0.0, 0)


@pytest.mark.parametrize(
    "usage",
    [
        None,
        "usage",
        {},
        {"down_mbps": 1},
        {"down_mbps": 1, "up_mbps": math.nan},
        {"down_mbps": math.inf, "up_mbps": 1},
        {"down_mbps": -0.1, "up_mbps": 1},
        {"down_mbps": True, "up_mbps": 1},
        {"down_mbps": "3.2", "up_mbps": 1},
        {"down_mbps": 1, "up_mbps": None},
    ],
)
def test_one_unusable_pair_makes_the_whole_total_unknown(usage: Any) -> None:
    total = eero_api.wan_total([device("aa", down=4, up=2), device("bb", usage=usage)])
    assert total == eero_api.WanTotal(None, None, 2)


def test_a_disconnected_device_with_bad_usage_does_not_matter() -> None:
    total = eero_api.wan_total(
        [device("aa", down=4, up=2), device("bb", connected=False, usage={"down_mbps": "x"})]
    )
    assert total == eero_api.WanTotal(4.0, 2.0, 1)


def test_zero_rates_are_valid_values() -> None:
    assert eero_api.wan_total([device("aa", down=0, up=0)]) == eero_api.WanTotal(0.0, 0.0, 1)


async def test_request_burst_returns_next_burst_and_passes_the_network_envelope() -> None:
    sdk = FakeSDK({"burst_reporters.create_burst_reporter": {"next_burst": "2026-10-20T00:01:00Z"}})
    hub = build_hub(sdk=sdk)
    network = {"url": NETWORK_URL, "resources": {}}

    assert await hub.request_burst(NETWORK_ID, network) == "2026-10-20T00:01:00Z"

    assert sdk.calls[-1] == (
        "burst_reporters",
        "create_burst_reporter",
        (NETWORK_ID,),
        {"parent": network},
    )


@pytest.mark.parametrize("body", [{}, {"next_burst": None}, None, []])
async def test_request_burst_without_next_burst_returns_none(body: Any) -> None:
    hub = build_hub(routes={"burst_reporters.create_burst_reporter": body})

    assert await hub.request_burst(NETWORK_ID) is None


async def test_request_burst_refusals_propagate_unchanged() -> None:
    hub = build_hub(
        routes={"burst_reporters.create_burst_reporter": EeroAccessDeniedException(403, "no")}
    )

    with pytest.raises(EeroAccessDeniedException):
        await hub.request_burst(NETWORK_ID)


async def test_get_devices_reads_the_device_list_and_never_returns_none() -> None:
    sdk = FakeSDK({"devices.get_devices": (None, [device("aa")])})
    hub = build_hub(sdk=sdk)

    assert await hub.get_devices(NETWORK_ID) == []
    assert await hub.get_devices(NETWORK_ID) == [device("aa")]
    assert sdk.calls == [("devices", "get_devices", (NETWORK_ID,), {})] * 2


def test_network_connection_mode_and_bridge_detection() -> None:
    hub = build_hub()
    routed = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL, "connection": {"mode": "NAT"}})
    bridged = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL, "connection": {"mode": "bridge"}})
    unknown = eero_api.network.EeroNetwork(hub, None, {"url": NETWORK_URL, "connection": "odd"})

    assert (routed.connection_mode, routed.wan_throughput_supported) == ("NAT", True)
    assert (bridged.connection_mode, bridged.wan_throughput_supported) == ("bridge", False)
    assert (unknown.connection_mode, unknown.wan_throughput_supported) == (None, True)
