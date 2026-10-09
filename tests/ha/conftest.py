"""Shared fixtures for the HA-dependent Eero tests (Python 3.14 only)."""

from __future__ import annotations

from pathlib import Path
import sys

import pytest

# pytest_homeassistant_custom_component registers itself via a pytest11
# entry point, so it does not need listing in pytest_plugins here (which
# pytest only allows in a top-level conftest anyway).

# tests/helpers.py (FakeSDK, FakeHTTPSession) lives one directory up; pytest
# only puts tests/ha on sys.path for modules under this directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from helpers import FakeSDK  # noqa: E402

from custom_components.eero.const import (  # noqa: E402
    CONF_ACTIVITY,
    CONF_BACKUP_NETWORKS,
    CONF_CONSIDER_HOME,
    CONF_EEROS,
    CONF_FILTER_INCLUDE,
    CONF_MISCELLANEOUS,
    CONF_NETWORKS,
    CONF_PREFIX_NETWORK_NAME,
    CONF_PROFILES,
    CONF_RESOURCES,
    CONF_SAVE_RESPONSES,
    CONF_SUFFIX_CONNECTION_TYPE,
    CONF_USER_TOKEN,
    CONF_WIRED_CLIENTS,
    CONF_WIRED_CLIENTS_FILTER,
    CONF_WIRELESS_CLIENTS,
    CONF_WIRELESS_CLIENTS_FILTER,
)

NETWORK_ID = "1234567"
NETWORK_URL = f"/2.2/networks/{NETWORK_ID}"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Every test in this directory needs custom_components loadable."""
    yield


def network_envelope(**overrides) -> dict:
    """A minimal, complete network envelope: eeros embedded, no Thread."""
    data = {
        "url": NETWORK_URL,
        "name": "TestNetwork",
        "band_steering": False,
        "eeros": {"count": 0, "data": []},
        "resources": {"settings": f"{NETWORK_URL}/settings"},
    }
    data.update(overrides)
    return data


def default_routes() -> dict:
    """SDK routes covering one full poll (fast + hourly + daily) with nothing configured."""
    return {
        "networks.get_network": network_envelope(),
        "eeros.get_eeros": [],
        "entitlements.get_features": {"features": []},
        "updates.get_updates": {},
        "reservations.get_reservations": [],
        "forwards.get_forwards": [],
        "security.get_fast_transition": {"fast_transition": False},
    }


def entry_data(**overrides) -> dict:
    """A VERSION 3 config entry data dict for one network, nothing configured."""
    resources = {
        NETWORK_ID: {
            CONF_BACKUP_NETWORKS: [],
            CONF_EEROS: [],
            CONF_PROFILES: [],
            CONF_WIRED_CLIENTS: [],
            CONF_WIRED_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
            CONF_WIRELESS_CLIENTS: [],
            CONF_WIRELESS_CLIENTS_FILTER: CONF_FILTER_INCLUDE,
        }
    }
    miscellaneous = {
        NETWORK_ID: {
            CONF_CONSIDER_HOME: 0,
            CONF_PREFIX_NETWORK_NAME: True,
            CONF_SUFFIX_CONNECTION_TYPE: True,
        }
    }
    data = {
        CONF_USER_TOKEN: "OLD-TOKEN",
        CONF_NETWORKS: [NETWORK_ID],
        CONF_RESOURCES: resources,
        CONF_ACTIVITY: {},
        CONF_MISCELLANEOUS: miscellaneous,
        CONF_SAVE_RESPONSES: False,
    }
    data.update(overrides)
    return data


@pytest.fixture
def sdk_factory(monkeypatch):
    """Patch EeroHub construction so it uses a FakeSDK instead of the real SDK.

    Returns a function that must be called with the routes for the test; it
    returns the FakeSDK so the test can inspect sdk.calls / mutate routes.
    """
    import custom_components.eero as eero_init
    from custom_components.eero.api import EeroHub as RealEeroHub

    created: list = []

    def make(routes: dict | None = None) -> FakeSDK:
        sdk = FakeSDK(routes if routes is not None else default_routes())
        created.append(sdk)

        def patched_hub(**kwargs):
            kwargs["sdk"] = sdk
            return RealEeroHub(**kwargs)

        monkeypatch.setattr(eero_init, "EeroHub", patched_hub)
        return sdk

    return make
