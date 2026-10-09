"""Test helpers: load the api package and fake the eero-api SDK.

The api package is loaded under its own name because its real parent,
custom_components.eero, imports homeassistant, and these tests run without
Home Assistant installed. It now imports ``eero`` (the SDK) and ``aiohttp``,
both installed in the standalone (3.13) and HA (3.14) test venvs.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "custom_components" / "eero" / "api"
FIXTURE_DIR = Path(__file__).parent / "fixtures"

_VERBS = {"get": "GET", "put": "PUT", "post": "POST", "delete": "DELETE"}


def load_api():
    """Load custom_components/eero/api as a standalone package."""
    if (module := sys.modules.get("eero_api")) is not None:
        return module
    spec = importlib.util.spec_from_file_location(
        "eero_api",
        API_DIR / "__init__.py",
        submodule_search_locations=[str(API_DIR)],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["eero_api"] = module
    spec.loader.exec_module(module)
    return module


def __getattr__(name: str) -> Any:
    """Load eero_api lazily on first access (PEP 562).

    `from helpers import eero_api` used to run load_api() eagerly at import
    time, which is early enough (during tests/ha/conftest.py's own import,
    before coverage starts tracing) that pytest-cov would never see the
    module's code execute: every line it runs afterwards still gets
    attributed to the same already-compiled code objects, but the HA
    (tests/ha) suite never names eero_api directly (it goes through
    custom_components.eero.api, loaded under its real name at test time),
    so deferring this load until something actually asks for it keeps that
    file out of this module's import-time side effects entirely.
    """
    if name == "eero_api":
        return load_api()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def fixture(name: str) -> Any:
    """Return a recorded response body."""
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())


class FakeDomain:
    """Stand-in for one SDK domain object (sdk.networks, sdk.devices, ...).

    Any attribute access returns an awaitable-returning callable that records
    the call on the owning FakeSDK and resolves it against routes. The four
    HTTP-verb names (get/put/post/delete) -- used by the integration for
    endpoints the SDK has no dedicated method for -- are routed by the
    request's URL path rather than by method name, since every domain
    inherits the same verbs from the SDK's BaseAPI.
    """

    def __init__(self, sdk: FakeSDK, name: str) -> None:
        """Initialize."""
        self._sdk = sdk
        self._name = name

    def __getattr__(self, method: str) -> Any:
        async def call(*args: Any, **kwargs: Any) -> Any:
            self._sdk.calls.append((self._name, method, args, kwargs))
            if method in _VERBS and args and isinstance(args[0], str):
                raw = args[0]
                path = urlparse(raw).path if raw.startswith("http") else raw
                key = f"{_VERBS[method]} {path}"
            else:
                key = f"{self._name}.{method}"
            return self._sdk.resolve(key, args, kwargs)

        return call


class FakeAuth(FakeDomain):
    """Stand-in for sdk.auth: token get/set are plain values, not envelopes."""

    def __init__(self, sdk: FakeSDK, token: str | None) -> None:
        """Initialize."""
        super().__init__(sdk, "auth")
        self.token = token
        self.tokens_set: list[str] = []

    async def get_auth_token(self) -> str | None:
        """Return the current token."""
        self._sdk.calls.append(("auth", "get_auth_token", (), {}))
        return self.token

    async def set_session_token(self, token: str) -> None:
        """Record and store a new token."""
        self._sdk.calls.append(("auth", "set_session_token", (token,), {}))
        self.tokens_set.append(token)
        self.token = token


class FakeSDK:
    """Stand-in for eero.EeroAPI.

    routes maps "<domain>.<method>" (for dedicated SDK methods) or
    "<VERB> <path>" (for the generic get/put/post/delete fallbacks) to a
    response body, a callable(args, kwargs) -> body, or an Exception
    instance to raise. Every resolved body is wrapped in a
    {"meta": {"code": 200}, "data": body} envelope, matching what the real
    SDK returns.

    A route value is served once and then repeats forever, *unless* it is a
    tuple, in which case each element is served in order and the last one
    repeats once exhausted -- a tuple rather than a list, because API data
    is itself very often a bare list (device/profile/eero collections), and
    that must not be mistaken for a sequence of responses. Use set_route()
    to change a route after construction (e.g. mid-test, to simulate a
    resource appearing or disappearing between polls).
    """

    def __init__(self, routes: dict[str, Any], token: str | None = "OLD-TOKEN") -> None:
        """Initialize."""
        self._routes = {
            key: (value if isinstance(value, tuple) else (value,))
            for key, value in routes.items()
        }
        self._cursor: dict[str, int] = dict.fromkeys(self._routes, 0)
        self.calls: list[tuple[str, str, tuple, dict]] = []
        self.auth = FakeAuth(self, token)

    def __getattr__(self, name: str) -> FakeDomain:
        return FakeDomain(self, name)

    def resolve(self, key: str, args: tuple, kwargs: dict) -> dict[str, Any]:
        """Resolve one recorded call against the configured routes."""
        if key not in self._routes:
            raise AssertionError(f"unexpected SDK call: {key}")
        sequence = self._routes[key]
        index = self._cursor[key]
        item = sequence[index] if index < len(sequence) else sequence[-1]
        if index < len(sequence) - 1:
            self._cursor[key] += 1
        if isinstance(item, Exception):
            raise item
        data = item(args, kwargs) if callable(item) else item
        return {"meta": {"code": 200}, "data": data}

    def set_route(self, key: str, value: Any) -> None:
        """Replace a route after construction and reset its sequence cursor."""
        self._routes[key] = value if isinstance(value, tuple) else (value,)
        self._cursor[key] = 0


class _FakeHTTPResponse:
    """Stand-in for aiohttp.ClientResponse."""

    def __init__(self, status: int, body: str) -> None:
        """Initialize."""
        self.status = status
        self._body = body

    async def text(self) -> str:
        """Return the response body."""
        return self._body


class _FakeHTTPContext:
    """Stand-in for the async context manager aiohttp.ClientSession.get returns."""

    def __init__(self, response: _FakeHTTPResponse | None, error: Exception | None) -> None:
        """Initialize."""
        self._response = response
        self._error = error

    async def __aenter__(self) -> _FakeHTTPResponse:
        """Enter."""
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response

    async def __aexit__(self, *exc_info: Any) -> bool:
        """Exit."""
        return False


class FakeHTTPSession:
    """Stand-in for aiohttp.ClientSession, used only for the release-notes GET.

    routes maps an exact URL to (status, text), or to an Exception to raise
    on entering the context manager. A URL with no configured route 404s.
    """

    def __init__(self, routes: dict[str, Any] | None = None) -> None:
        """Initialize."""
        self.routes = routes or {}
        self.calls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeHTTPContext:
        """GET, returning an async context manager like aiohttp does."""
        self.calls.append(url)
        item = self.routes.get(url, (404, ""))
        if isinstance(item, Exception):
            return _FakeHTTPContext(None, item)
        status, text = item
        return _FakeHTTPContext(_FakeHTTPResponse(status, text), None)


def build_hub(
    sdk: FakeSDK | None = None,
    session: FakeHTTPSession | None = None,
    routes: dict[str, Any] | None = None,
    user_token: str = "OLD-TOKEN",
    **kwargs: Any,
) -> Any:
    """Return an EeroHub wired to a FakeSDK and a FakeHTTPSession."""
    return load_api().EeroHub(
        session=session if session is not None else FakeHTTPSession(),
        sdk=sdk if sdk is not None else FakeSDK(routes or {}),
        user_token=user_token,
        **kwargs,
    )
