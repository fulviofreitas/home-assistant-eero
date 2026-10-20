"""Adds config flow for Eero integration."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, Protocol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EeroAccount, EeroException, EeroHub
from .api.network import EeroNetwork
from .const import (
    CONF_ACTIVITY,
    CONF_CODE,
    CONF_LOGIN,
    CONF_MISCELLANEOUS,
    CONF_NETWORKS,
    CONF_RESOURCES,
    CONF_USER_TOKEN,
    DOMAIN,
    MAX_TIMEOUT,
)
from .schemas import (
    NO_DEFAULT,
    ActivityDefaults,
    MiscellaneousDefaults,
    PollingDefaults,
    activity_from_input,
    activity_schema,
    code_schema,
    labels,
    login_schema,
    miscellaneous_from_input,
    miscellaneous_schema,
    networks_schema,
    new_resource_defaults,
    polling_from_input,
    polling_invalid,
    polling_schema,
    resources_from_input,
    resources_schema,
    stored_activity_defaults,
    stored_miscellaneous_defaults,
    stored_polling_defaults,
    stored_resource_defaults,
)
from .util import stored_setting

_LOGGER = logging.getLogger(__name__)


class _PerNetworkFlow(Protocol):
    """What the per-network steps of the setup and the options flow read and write."""

    index: int
    user_input: dict[str, Any]
    response: EeroAccount


def _record(
    flow: _PerNetworkFlow,
    key: str,
    user_input: dict[str, Any],
    selection: Callable[[EeroNetwork, dict[str, Any]], dict[str, Any]],
) -> None:
    """Store what a submitted form selected for the network it was about."""
    target_network = flow.user_input[CONF_NETWORKS][flow.index]
    for network in flow.response.networks:
        if network.id == target_network:
            flow.user_input[key][network.id] = selection(network, user_input)
            flow.index += 1


def _advance(flow: _PerNetworkFlow, key: str) -> bool:
    """Return True once every network has had its form, else get the next one ready.

    The first network starts the step's storage off empty.
    """
    if flow.index == len(flow.user_input[CONF_NETWORKS]):
        flow.index = 0
        return True
    if flow.index == 0:
        flow.user_input[key] = {}
    return False


def _current_network(flow: _PerNetworkFlow) -> EeroNetwork | None:
    """Return the network the next form is about, or None if the account lost it."""
    target_network = flow.user_input[CONF_NETWORKS][flow.index]
    for network in flow.response.networks:
        if network.id == target_network:
            return network
    return None


class EeroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Eero integration."""

    VERSION = 3
    MINOR_VERSION = 0

    # Set by the user and reauth steps before any later step reads them.
    api: EeroHub
    response: EeroAccount

    def __init__(self) -> None:
        """Initialize."""
        self.index = 0
        self.user_input: dict[str, Any] = {}
        self.reauth_login: str | None = None

    @property
    def config_title(self) -> str:
        """Return the config title."""
        return f"{self.user_input[CONF_NAME]} ({self.user_input[CONF_LOGIN]})"

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step user."""
        errors: dict[str, str] = {}

        if user_input:
            self.api = EeroHub(session=async_get_clientsession(self.hass))
            try:
                await self.api.login(user_input[CONF_LOGIN])
            except (EeroException, TimeoutError) as exception:
                _LOGGER.error("Login failed: %s", type(exception).__name__)
                errors["base"] = "invalid_login"
            else:
                self.user_input[CONF_LOGIN] = user_input[CONF_LOGIN]
                return await self.async_step_verify()

        return self.async_show_form(
            step_id="user",
            data_schema=login_schema((user_input or {}).get(CONF_LOGIN, NO_DEFAULT)),
            errors=errors,
        )

    async def async_step_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step verify."""
        errors: dict[str, str] = {}

        if user_input:
            try:
                account = await self.api.login_verify(user_input[CONF_CODE])
            except (EeroException, TimeoutError) as exception:
                _LOGGER.error("Verification failed: %s", type(exception).__name__)
                errors["base"] = "invalid_code"
            else:
                await self.async_set_unique_id(account["log_id"].lower())
                self._abort_if_unique_id_configured()
                self.user_input[CONF_NAME] = account["name"]
                self.user_input[CONF_USER_TOKEN] = self.api.user_token
                try:
                    self.response = await self.api.snapshot(account)
                except (EeroException, TimeoutError) as exception:
                    _LOGGER.error(
                        "Could not read the account's networks: %s",
                        type(exception).__name__,
                    )
                    return self.async_abort(reason="cannot_connect")
                return await self.async_step_networks()

        return self.async_show_form(
            step_id="verify",
            data_schema=code_schema((user_input or {}).get(CONF_CODE, NO_DEFAULT)),
            description_placeholders={"login": self.user_input[CONF_LOGIN]},
            errors=errors,
        )

    async def async_step_networks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step networks."""
        if user_input is not None:
            self.user_input[CONF_NETWORKS] = [
                network.id
                for network in self.response.networks
                if network.name_unique in user_input[CONF_NETWORKS]
            ]
            return await self.async_step_resources()

        network_names = labels(network.name_unique for network in self.response.networks)

        return self.async_show_form(
            step_id="networks",
            data_schema=networks_schema(network_names, network_names),
        )

    async def async_step_resources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step resources."""
        if user_input is not None:
            _record(self, CONF_RESOURCES, user_input, resources_from_input)
        if _advance(self, CONF_RESOURCES):
            return await self.async_step_activity()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="resources",
            data_schema=resources_schema(network, new_resource_defaults(network)),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_activity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step activity."""
        if user_input is not None:
            _record(
                self,
                CONF_ACTIVITY,
                user_input,
                lambda _network, form: activity_from_input(form),
            )
        if _advance(self, CONF_ACTIVITY):
            return await self.async_step_miscellaneous()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="activity",
            data_schema=activity_schema(
                network, self.user_input[CONF_RESOURCES][network.id], ActivityDefaults()
            ),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_miscellaneous(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step miscellaneous."""
        if user_input is not None:
            _record(
                self,
                CONF_MISCELLANEOUS,
                user_input,
                lambda _network, form: miscellaneous_from_input(form),
            )
        if _advance(self, CONF_MISCELLANEOUS):
            # Always offered. The old gate on the user's HA "advanced mode" flag
            # "advanced mode" user toggle) is deprecated and removed in HA 2027.6; the
            # three fields have defaults, so the step costs a non-advanced user one click.
            return await self.async_step_advanced()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="miscellaneous",
            data_schema=miscellaneous_schema(MiscellaneousDefaults()),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input:
            if polling_invalid(user_input):
                errors["base"] = "invalid_scan_interval_timeout"
            else:
                self.user_input.update(polling_from_input(user_input))
                return self.async_create_entry(
                    title=self.config_title, data=self.user_input
                )

        return self.async_show_form(
            step_id="advanced",
            data_schema=polling_schema(PollingDefaults()),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user change polling interval, timeout and save-responses.

        These are the Advanced step's values. Options take precedence over
        data for them (see async_setup_entry), so a prior options flow run
        may already carry an override; writing options too (not just data)
        here ensures the new values actually take effect regardless of
        whether that override exists.
        """
        errors: dict[str, str] = {}
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input:
            if polling_invalid(user_input):
                errors["base"] = "invalid_scan_interval_timeout"
            else:
                updates = polling_from_input(user_input)
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates=updates,
                    options={**reconfigure_entry.options, **updates},
                )

        defaults = stored_polling_defaults(
            reconfigure_entry.options, reconfigure_entry.data
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=polling_schema(
                replace(defaults, timeout=min(MAX_TIMEOUT, defaults.timeout))
            ),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication when the Eero session can no longer be refreshed."""
        self.reauth_login = entry_data.get(CONF_LOGIN)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Request a new verification code for the configured account."""
        errors: dict[str, str] = {}

        if user_input:
            self.api = EeroHub(session=async_get_clientsession(self.hass))
            try:
                await self.api.login(user_input[CONF_LOGIN])
            except (EeroException, TimeoutError) as exception:
                _LOGGER.error("Login failed: %s", type(exception).__name__)
                errors["base"] = "invalid_login"
            else:
                self.reauth_login = user_input[CONF_LOGIN]
                return await self.async_step_reauth_verify()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=login_schema(self.reauth_login or NO_DEFAULT),
            errors=errors,
        )

    async def async_step_reauth_verify(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the code and write the new session token to the config entry."""
        errors: dict[str, str] = {}

        if user_input:
            try:
                response = await self.api.login_verify(user_input[CONF_CODE])
            except (EeroException, TimeoutError) as exception:
                _LOGGER.error("Verification failed: %s", type(exception).__name__)
                errors["base"] = "invalid_code"
            else:
                # The initial flow treats log_id as mandatory, so its absence
                # is a broken response, not a valid one. Fail closed rather
                # than write a token in without checking the account.
                if not (log_id := (response or {}).get("log_id")):
                    _LOGGER.error("Verification response carried no account ID")
                    errors["base"] = "invalid_code"
                else:
                    await self.async_set_unique_id(log_id.lower())
                    self._abort_if_unique_id_mismatch(reason="wrong_account")
                    return self.async_update_reload_and_abort(
                        self._get_reauth_entry(),
                        data_updates={
                            CONF_LOGIN: self.reauth_login,
                            CONF_USER_TOKEN: self.api.user_token,
                        },
                        # This entry has an update listener, which owns the
                        # reload. Asking for one here as well is deprecated and
                        # breaks in Home Assistant 2026.12.
                        reload_even_if_entry_is_unchanged=False,
                    )

        return self.async_show_form(
            step_id="reauth_verify",
            data_schema=code_schema(),
            description_placeholders={"login": str(self.reauth_login)},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> EeroOptionsFlowHandler:
        """Eero options callback."""
        return EeroOptionsFlowHandler()


class EeroOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options for Eero."""

    # Set by the init step before any later step reads them.
    api: EeroHub
    response: EeroAccount

    def __init__(self) -> None:
        """Initialize Eero options flow."""
        self.index = 0
        self.user_input: dict[str, Any] = {}

    @property
    def data(self) -> Mapping[str, Any]:
        """Return the data from a config entry."""
        return self.config_entry.data

    @property
    def options(self) -> Mapping[str, Any]:
        """Return the options from a config entry."""
        return self.config_entry.options

    def _stored(self, key: str) -> Any:
        """Return what the entry stores under key: its option, else its data, else {}."""
        return stored_setting(self.options, self.data, key, {})

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        try:
            if self.config_entry.state is config_entries.ConfigEntryState.LOADED:
                self.api = self.config_entry.runtime_data.hub
            else:
                # Not loaded, e.g. because a configured network is gone:
                # the options flow is how that network gets deselected, so
                # it must work without the running entry.
                self.api = EeroHub(session=async_get_clientsession(self.hass))
                await self.api.async_set_token(self.data[CONF_USER_TOKEN])
            self.response = await self.api.snapshot()
        except (EeroException, TimeoutError) as exception:
            _LOGGER.error(
                "Could not read the account's networks: %s", type(exception).__name__
            )
            return self.async_abort(reason="cannot_connect")
        return await self.async_step_networks()

    async def async_step_networks(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            self.user_input[CONF_NETWORKS] = [
                network.id
                for network in self.response.networks
                if network.name_unique in user_input[CONF_NETWORKS]
            ]
            return await self.async_step_resources()

        conf_networks = [
            network.name_unique
            for network in self.response.networks
            if network.id in self.options.get(CONF_NETWORKS, self.data[CONF_NETWORKS])
        ]
        network_names = labels(network.name_unique for network in self.response.networks)

        return self.async_show_form(
            step_id="networks",
            data_schema=networks_schema(network_names, conf_networks),
        )

    async def async_step_resources(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        if user_input is not None:
            _record(self, CONF_RESOURCES, user_input, resources_from_input)
        if _advance(self, CONF_RESOURCES):
            return await self.async_step_activity()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        stored = self._stored(CONF_RESOURCES).get(network.id, {})
        return self.async_show_form(
            step_id="resources",
            data_schema=resources_schema(
                network, stored_resource_defaults(network, stored)
            ),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_activity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step activity."""
        if user_input is not None:
            _record(
                self,
                CONF_ACTIVITY,
                user_input,
                lambda _network, form: activity_from_input(form),
            )
        if _advance(self, CONF_ACTIVITY):
            return await self.async_step_miscellaneous()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        stored = self._stored(CONF_ACTIVITY).get(network.id, {})
        return self.async_show_form(
            step_id="activity",
            data_schema=activity_schema(
                network,
                self.user_input[CONF_RESOURCES][network.id],
                stored_activity_defaults(stored),
            ),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_miscellaneous(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Async step miscellaneous."""
        if user_input is not None:
            _record(
                self,
                CONF_MISCELLANEOUS,
                user_input,
                lambda _network, form: miscellaneous_from_input(form),
            )
        if _advance(self, CONF_MISCELLANEOUS):
            # Always offered. The old gate on the user's HA "advanced mode" flag
            # "advanced mode" user toggle) is deprecated and removed in HA 2027.6; the
            # three fields have defaults, so the step costs a non-advanced user one click.
            return await self.async_step_advanced()
        if (network := _current_network(self)) is None:
            return self.async_abort(reason="cannot_connect")
        stored = self._stored(CONF_MISCELLANEOUS).get(network.id, {})
        return self.async_show_form(
            step_id="miscellaneous",
            data_schema=miscellaneous_schema(stored_miscellaneous_defaults(stored)),
            description_placeholders={"network": str(network.name_unique)},
        )

    async def async_step_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        if user_input:
            if polling_invalid(user_input):
                errors["base"] = "invalid_scan_interval_timeout"
            else:
                self.user_input.update(polling_from_input(user_input))
                return self.async_create_entry(title="", data=self.user_input)

        return self.async_show_form(
            step_id="advanced",
            data_schema=polling_schema(stored_polling_defaults(self.options, self.data)),
            errors=errors,
        )
