"""Tests for saved responses and the release-notes fetch (audit C1, M2, M5)."""

from __future__ import annotations

import json

from helpers import FakeHTTPSession, FakeSDK, build_hub, eero_api, fixture

NETWORK_ID = "1234567"
MANIFEST = "https://api-user.e2ro.com/2.2/updates/manifest-7.1.0"


def network_sdk() -> FakeSDK:
    """Return a FakeSDK serving a complete network with no eeros embedded."""
    return FakeSDK(
        {
            "networks.get_network": fixture("network"),
            "eeros.get_eeros": [],
            "thread.get_thread": fixture("thread"),
            "entitlements.get_features": {"features": []},
            "updates.get_updates": {},
            "reservations.get_reservations": [],
            "forwards.get_forwards": [],
            "security.get_fast_transition": {"fast_transition": False},
        }
    )


async def test_saved_responses_are_redacted(tmp_path) -> None:
    """Secrets never reach the saved file (C1)."""
    hub = build_hub(sdk=network_sdk(), save_location=str(tmp_path))

    await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())
    await hub.call(
        hub.sdk.thread.get_thread(NETWORK_ID),
        name=f"/2.2/networks/{NETWORK_ID}/thread",
    )

    saved = json.loads((tmp_path / f"_2_2_networks_{NETWORK_ID}.json").read_text())
    assert saved["password"] == "**REDACTED**"
    assert saved["name"] == "TestNetwork"

    thread = json.loads((tmp_path / f"_2_2_networks_{NETWORK_ID}_thread.json").read_text())
    assert thread["master_key"] == "**REDACTED**"
    assert thread["active_operational_dataset"] == "**REDACTED**"
    assert thread["channel"] == 15


async def test_nested_and_listed_secrets_are_redacted(tmp_path) -> None:
    """Redaction walks lists and nested dicts (C1)."""
    hub = build_hub(save_location=str(tmp_path))

    await hub.save_response(
        response={
            "devices": [{"nickname": "iPad", "psk": "hunter2"}],
            "guest_network": {"password": "guest-pass"},
        },
        name="update_data",
    )

    saved = json.loads((tmp_path / "update_data.json").read_text())
    assert saved["devices"][0]["psk"] == "**REDACTED**"
    assert saved["devices"][0]["nickname"] == "iPad"
    assert saved["guest_network"]["password"] == "**REDACTED**"


async def test_auth_responses_are_never_written(tmp_path) -> None:
    """The login/refresh exchange carries the session token, never saved (C1).

    The SDK now owns the refresh handshake internally (never surfaced to this
    package), so this only tests save_response's own guard against any name
    containing "/login".
    """
    hub = build_hub(save_location=str(tmp_path))

    await hub.save_response({"user_token": "NEW-TOKEN"}, name="/2.2/login/refresh")

    assert list(tmp_path.iterdir()) == []


async def test_nothing_is_written_without_a_save_location(tmp_path) -> None:
    """Saving is off by default."""
    hub = build_hub(sdk=network_sdk())

    await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())

    assert list(tmp_path.iterdir()) == []


async def test_release_notes_rejects_an_unexpected_host() -> None:
    """A manifest URL pointing off eero's domains is not fetched (M5)."""
    hub = build_hub()

    assert await hub.get_release_notes("https://evil.example.com/manifest") is None
    assert await hub.get_release_notes("http://api-user.e2ro.com/manifest") is None
    assert await hub.get_release_notes("https://eeroassets.com.evil.example/x") is None
    assert await hub.get_release_notes("http://eeroassets.com/manifest") is None
    assert await hub.get_release_notes(None) is None


async def test_release_notes_allows_the_eero_asset_host() -> None:
    """eeroassets.com is where the real manifest URL points, so it is fetched."""
    body = json.dumps({"target": {"os_version": "7.6.1"}})
    bare = "https://eeroassets.com/manifests/manifest-7.6.1"
    subdomain = "https://d1n7v1ld1cnhbi.cloudfront.eeroassets.com/manifest-7.6.1"
    session = FakeHTTPSession({bare: (200, body), subdomain: (200, body)})
    hub = build_hub(session=session)

    assert await hub.get_release_notes(bare) == {"target": {"os_version": "7.6.1"}}
    assert await hub.get_release_notes(subdomain) == {"target": {"os_version": "7.6.1"}}
    assert session.calls == [bare, subdomain]


async def test_release_notes_are_fetched_once_per_url() -> None:
    """The manifest is cached rather than refetched every poll (M2)."""
    body = json.dumps({"target": {"os_version": "7.1.0"}})
    session = FakeHTTPSession({MANIFEST: (200, body)})
    hub = build_hub(session=session)

    first = await hub.get_release_notes(MANIFEST)
    second = await hub.get_release_notes(MANIFEST)

    assert first == second == {"target": {"os_version": "7.1.0"}}
    assert session.calls == [MANIFEST]


async def test_a_failed_release_notes_fetch_does_not_fail_the_poll(caplog) -> None:
    """A 404 on the firmware manifest is a warning, not a dead network (N2)."""
    session = FakeHTTPSession({})  # every URL 404s
    sdk = network_sdk()
    sdk.set_route("updates.get_updates", fixture("network")["updates"])
    hub = build_hub(sdk=sdk, session=session)

    fast = await hub.fetch_fast(NETWORK_ID, eero_api.EeroUpdateConfig())
    daily = await hub.fetch_daily(
        NETWORK_ID, fast["network"], eero_api.EeroUpdateConfig(get_release_notes=True)
    )

    assert daily["updates"]["manifest_resource"] == fixture("network")["updates"][
        "manifest_resource"
    ]
    assert "release_notes" not in daily["updates"]
    assert "Could not fetch release notes" in caplog.text


async def test_a_rejected_host_warns_once(caplog) -> None:
    """The refusal is cached, so it does not warn on every poll (N3)."""
    hub = build_hub()

    assert await hub.get_release_notes("https://evil.example.com/manifest") is None
    assert await hub.get_release_notes("https://evil.example.com/manifest") is None

    assert caplog.text.count("Refusing to fetch release notes") == 1
