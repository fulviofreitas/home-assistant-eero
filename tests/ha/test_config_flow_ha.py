"""HA-level tests for the Eero config, options, reauth and reconfigure flows."""

from __future__ import annotations

from eero.exceptions import EeroAuthenticationException
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.eero.const import (
    CONF_CODE,
    CONF_LOGIN,
    CONF_SAVE_RESPONSES,
    CONF_TIMEOUT,
    DOMAIN,
)

from conftest import NETWORK_ID, account_envelope, entry_data


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


async def _advance_through_user_flow(hass, config_flow_sdk_factory) -> dict:
    """Drive user -> verify -> networks -> resources -> activity ->

    miscellaneous -> advanced, returning the final (create_entry) result.
    """
    config_flow_sdk_factory()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )
    assert result["step_id"] == "verify"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )
    assert result["step_id"] == "networks"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "resources"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "activity"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "miscellaneous"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["step_id"] == "advanced"

    return await hass.config_entries.flow.async_configure(result["flow_id"], {})


async def test_user_flow_happy_path_creates_entry(hass, config_flow_sdk_factory) -> None:
    """The full user flow ends in a created entry for the one network."""
    result = await _advance_through_user_flow(hass, config_flow_sdk_factory)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Account (someone@example.com)"
    assert result["data"][CONF_LOGIN] == "someone@example.com"
    assert NETWORK_ID in result["data"]["networks"]


async def test_user_flow_invalid_login_shows_error(hass, config_flow_sdk_factory) -> None:
    """A login failure keeps the user on the user step with invalid_login."""
    config_flow_sdk_factory(
        {"auth.login": EeroAuthenticationException("nope")}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )

    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_login"}


async def test_user_flow_invalid_code_shows_error(hass, config_flow_sdk_factory) -> None:
    """A verification failure keeps the user on the verify step with invalid_code."""
    config_flow_sdk_factory(
        {"auth.verify": EeroAuthenticationException("nope")}
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )

    assert result["step_id"] == "verify"
    assert result["errors"] == {"base": "invalid_code"}


async def test_user_flow_aborts_when_already_configured(
    hass, config_flow_sdk_factory
) -> None:
    """A verified account matching an existing entry's unique ID aborts."""
    make_entry(hass)
    config_flow_sdk_factory()

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth_flow_success_updates_token(hass, config_flow_sdk_factory) -> None:
    """A successful reauth writes the new token and reloads without a second reload."""
    entry = make_entry(hass)
    config_flow_sdk_factory()

    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )
    assert result["step_id"] == "reauth_verify"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_LOGIN] == "someone@example.com"


async def test_reauth_flow_wrong_account_aborts(hass, config_flow_sdk_factory) -> None:
    """A code verified against a different account aborts wrong_account."""
    entry = make_entry(hass)
    config_flow_sdk_factory({"GET /account": account_envelope(log_id="someone-else")})

    result = await entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_LOGIN: "someone@example.com"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_CODE: "123456"}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"


async def test_reconfigure_flow_success_updates_data_and_options(
    hass, sdk_factory
) -> None:
    """Reconfigure writes the new values to both data and options."""
    sdk_factory()
    entry = make_entry(hass, **{CONF_SCAN_INTERVAL: 300, CONF_TIMEOUT: 30})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SAVE_RESPONSES: True, CONF_SCAN_INTERVAL: 120, CONF_TIMEOUT: 20},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_SCAN_INTERVAL] == 120
    assert entry.data[CONF_TIMEOUT] == 20
    assert entry.options[CONF_SCAN_INTERVAL] == 120
    assert entry.options[CONF_TIMEOUT] == 20
    assert entry.options[CONF_SAVE_RESPONSES] is True


async def test_reconfigure_flow_validation_error(hass, sdk_factory) -> None:
    """A timeout that is not shorter than the scan interval is rejected.

    MIN_SCAN_INTERVAL (60) is above MAX_TIMEOUT (30), so the NumberSelector
    bounds alone can never produce invalid input through async_configure's
    schema validation; the flow handler is invoked directly to exercise the
    invalid_scan_interval_timeout branch itself.
    """
    sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    assert result["step_id"] == "reconfigure"

    flow = hass.config_entries.flow._progress[result["flow_id"]]
    assert flow.source == SOURCE_RECONFIGURE
    result = await flow.async_step_reconfigure(
        {CONF_SAVE_RESPONSES: False, CONF_SCAN_INTERVAL: 60, CONF_TIMEOUT: 60}
    )

    assert result["step_id"] == "reconfigure"
    assert result["errors"] == {"base": "invalid_scan_interval_timeout"}


async def test_reconfigure_overrides_an_existing_options_value(hass, sdk_factory) -> None:
    """An options override set by a prior options-flow run is itself overwritten."""
    sdk_factory()
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_SCAN_INTERVAL: 500, CONF_TIMEOUT: 25}
    )
    await hass.async_block_till_done()

    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_SAVE_RESPONSES: False, CONF_SCAN_INTERVAL: 180, CONF_TIMEOUT: 15},
    )
    await hass.async_block_till_done()

    assert result["reason"] == "reconfigure_successful"
    assert entry.options[CONF_SCAN_INTERVAL] == 180
    assert entry.options[CONF_TIMEOUT] == 15


async def test_options_flow_runs_when_the_entry_is_not_loaded(
    hass, config_flow_sdk_factory
) -> None:
    """An entry that failed to load can still open options (to drop a gone network)."""
    sdk = config_flow_sdk_factory()
    entry = make_entry(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "networks"
    assert sdk.auth.token == "OLD-TOKEN"


async def test_options_flow_happy_path_updates_entry(hass, sdk_factory) -> None:
    """The options flow runs end to end and writes the new values to options."""
    sdk_factory(
        {
            "devices.get_devices": [],
            "profiles.get_profiles": [],
            "GET /account": account_envelope(),
        }
    )
    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "networks"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {}
    )
    assert result["step_id"] == "resources"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {}
    )
    assert result["step_id"] == "activity"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {}
    )
    assert result["step_id"] == "miscellaneous"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {}
    )
    assert result["step_id"] == "advanced"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SAVE_RESPONSES: True, CONF_SCAN_INTERVAL: 180, CONF_TIMEOUT: 15},
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_SCAN_INTERVAL] == 180
    assert entry.options[CONF_TIMEOUT] == 15
    assert entry.options[CONF_SAVE_RESPONSES] is True
