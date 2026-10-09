"""Diagnostics support for the Eero integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from .api.const import REDACT_KEYS
from .const import CONF_LOGIN
from .coordinator import EeroConfigEntry

# The secrets the saved-responses option already strips, plus the account
# holder's contact details: a diagnostics file is made to be attached to a
# public issue.
TO_REDACT = REDACT_KEYS | {CONF_LOGIN, "email", "phone"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: EeroConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    payload: dict[str, Any] | None = None
    tiers: dict[str, Any] = {}
    if config_entry.state is ConfigEntryState.LOADED:
        runtime = config_entry.runtime_data
        payload = runtime.account.data
        for tier, coordinator in runtime.coordinators.items():
            tiers[tier] = {
                "last_update_success": coordinator.last_update_success,
                "update_interval": coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None,
            }
    return {
        "entry": {
            "data": async_redact_data(dict(config_entry.data), TO_REDACT),
            "options": async_redact_data(dict(config_entry.options), TO_REDACT),
            "version": config_entry.version,
            "minor_version": config_entry.minor_version,
        },
        "tiers": tiers,
        "payload": async_redact_data(payload, TO_REDACT) if payload else None,
    }
