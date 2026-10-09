"""Eero API."""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Any, cast

from .const import (
    STATE_AMBIENT,
    STATE_DISABLED,
    STATE_SCHEDULE,
)
from .firmware import EeroFirmware
from .resource import EeroResource

if TYPE_CHECKING:
    from .network import EeroNetwork


class EeroDevice(EeroResource):
    """EeroDevice."""

    network: EeroNetwork

    @property
    def connected_clients_count(self) -> int | None:
        """Connected clients counts."""
        return self.data.get("connected_clients_count")

    @property
    def connected_clients_names(self) -> list[str]:
        """Connected clients names."""
        return cast(
            "list[str]",
            [
                client.name
                for client in self.network.clients
                if client.source_location == self.name
            ],
        )

    @property
    def current_firmware(self) -> EeroFirmware:
        """Current firmware."""
        if not (os_version := self.os_version):
            return EeroFirmware()
        history = {
            firmware.os_version: firmware for firmware in self.network.firmware_history
        }
        return history.get(os_version.split("-")[0], EeroFirmware())

    @property
    def data_usage_day(self) -> tuple[int | None, int | None]:
        """Data usage day."""
        for eero in (
            self.network.data.get("activity", {})
            .get("eeros", {})
            .get("data_usage_day", [])
        ):
            if eero["url"] == self.url:
                return (eero["download"], eero["upload"])
        return (None, None)

    @property
    def data_usage_month(self) -> tuple[int | None, int | None]:
        """Data usage month."""
        for eero in (
            self.network.data.get("activity", {})
            .get("eeros", {})
            .get("data_usage_month", [])
        ):
            if eero["url"] == self.url:
                return (eero["download"], eero["upload"])
        return (None, None)

    @property
    def data_usage_week(self) -> tuple[int | None, int | None]:
        """Data usage week."""
        for eero in (
            self.network.data.get("activity", {})
            .get("eeros", {})
            .get("data_usage_week", [])
        ):
            if eero["url"] == self.url:
                return (eero["download"], eero["upload"])
        return (None, None)

    @property
    def is_gateway(self) -> bool | None:
        """Is gateway."""
        return self.data.get("gateway")

    @property
    def location(self) -> str | None:
        """Location."""
        return self.data.get("location")

    @property
    def mac_address(self) -> str | None:
        """MAC address."""
        return self.data.get("mac_address")

    @property
    def model(self) -> str | None:
        """Model."""
        return self.data.get("model")

    @property
    def model_number(self) -> str | None:
        """Model number."""
        return self.data.get("model_number")

    @property
    def name(self) -> str | None:
        """Name."""
        return self.location

    @property
    def name_long(self) -> str:
        """Name long."""
        return f"{self.name} Eero"

    @property
    def os_version(self) -> str | None:
        """OS version."""
        return self.data.get("os_version")

    async def async_reboot(self) -> None:
        """Reboot this eero."""
        await self.api.call(
            self.api.sdk.eeros.reboot_eero(self.network.known_id, self.known_id),
            name=f"{self.url}/reboot",
        )

    @property
    def serial(self) -> str | None:
        """Serial."""
        return self.data.get("serial")

    async def async_set_status_light(self, value: bool) -> None:
        """Turn the status light on or off."""
        await self.api.call(
            self.api.sdk.eeros.set_led(
                self.network.known_id, self.known_id, value, parent=self.data
            ),
            name=f"{self.url}/led",
        )

    async def async_set_status_light_brightness(self, value: int) -> None:
        """Set status light brightness; 0 turns it off."""
        if not value:
            await self.async_set_status_light(False)
            return
        await self.api.call(
            self.api.sdk.eeros.set_led_brightness(
                self.network.known_id, self.known_id, int(value), parent=self.data
            ),
            name=f"{self.url}/led",
        )

    @property
    def status(self) -> str | None:
        """Status."""
        return self.data.get("status")

    @property
    def status_light_brightness(self) -> int | None:
        """Status light brightness."""
        return self.data.get("led_brightness")

    @property
    def status_light_enabled(self) -> bool | None:
        """Status light enabled."""
        return self.data.get("led_on")

    @property
    def support_expiration_string(self) -> str | None:
        """Support expiration string."""
        return cast("str | None", self.data.get("update_status", {}).get("support_expiration_string"))

    @property
    def support_expired(self) -> bool | None:
        """Support expired."""
        return cast("bool | None", self.data.get("update_status", {}).get("support_expired"))

    @property
    def target_firmware(self) -> EeroFirmware:
        """Target firmware."""
        if self.support_expired:
            return self.current_firmware
        return self.network.target_firmware

    @property
    def update_available(self) -> bool | None:
        """Update available."""
        return self.data.get("update_available")

    @property
    def url_led(self) -> str | None:
        """URL led."""
        return cast("str | None", self.data.get("resources", {}).get("led_action"))

    @property
    def url_reboot(self) -> str | None:
        """URL reboot."""
        return cast("str | None", self.data.get("resources", {}).get("reboot"))

    @property
    def ports(self) -> list[dict[str, Any]]:
        """This eero's port interfaces, from the daily-tier connections read.

        eeros.get_connections has no dedicated "list ports" reader in the
        SDK -- this is the only eeros.py read that happens to carry a
        "ports" block alongside the client-connection data it is actually
        for. Shape (``ports.interfaces[]``, each with ``interface_number``,
        ``connection_status``, ``negotiated_speed``, ``actions``, ...)
        comes from the eero app's own observed API schema, not from
        eero-api, which does not document or verify this shape at all.
        """
        connections = self.network.data.get("connections") or {}
        ports = (connections.get(self.id) or {}).get("ports") or {}
        interfaces = ports.get("interfaces")
        if not isinstance(interfaces, list):
            return []
        return [interface for interface in interfaces if isinstance(interface, dict)]

    async def async_port_action(self, interface_number: int, action: str) -> None:
        """Perform a port-level action (e.g. RESTART_POWER, DISABLE_PORT).

        Unconfirmed write; several of the declared actions are inherently
        disruptive to whatever is connected to that port.
        """
        await self.api.call(
            self.api.sdk.eeros.port_action(self.known_id, str(interface_number), action),
            name=f"{self.url}/ports/{interface_number}/action",
        )


class EeroDeviceBeacon(EeroDevice):
    """EeroDeviceBeacon."""

    def _format_time(self, value: int) -> str | None:
        if not isinstance(value, int):
            return None
        if value < 10:
            return f"0{value}"
        return str(value)

    @property
    def nightlight_brightness_percentage(self) -> int | None:
        """Nightlight brightness percentage."""
        return cast("int | None", self.data.get("nightlight", {}).get("brightness_percentage"))

    async def async_set_nightlight_brightness_percentage(self, value: float) -> None:
        """Set nightlight brightness."""
        await self.async_set_nightlight_brightness(int(value))

    @property
    def nightlight_enabled(self) -> bool | None:
        """Nightlight enabled."""
        return cast("bool | None", self.data.get("nightlight", {}).get("enabled"))

    @property
    def nightlight_mode(self) -> str:
        """Nightlight mode."""
        if not self.nightlight_enabled:
            return STATE_DISABLED
        if not self.nightlight_schedule_enabled:
            return STATE_AMBIENT
        return STATE_SCHEDULE

    async def async_set_nightlight_mode(self, value: str) -> None:
        """Set nightlight mode."""
        if value == STATE_DISABLED:
            await self.async_set_nightlight_disabled()
        elif value == STATE_AMBIENT:
            await self.async_set_nightlight_ambient()
        elif value == STATE_SCHEDULE:
            await self.async_set_nightlight_schedule(*self.nightlight_schedule)

    @property
    def nightlight_mode_options(self) -> list[str]:
        """Nightlight mode options."""
        return [STATE_AMBIENT, STATE_DISABLED, STATE_SCHEDULE]

    @property
    def nightlight_schedule(self) -> tuple[str | None, str | None]:
        """Nightlight schedule."""
        return (
            self.data.get("nightlight", {}).get("schedule", {}).get("on"),
            self.data.get("nightlight", {}).get("schedule", {}).get("off"),
        )

    @property
    def nightlight_schedule_enabled(self) -> bool | None:
        """Nightlight schedule enabled."""
        return cast("bool | None", self.data.get("nightlight", {}).get("schedule", {}).get("enabled"))

    @property
    def nightlight_schedule_off(self) -> time:
        """Nightlight schedule off."""
        return time(
            hour=int(self.nightlight_schedule_off_hour),
            minute=int(self.nightlight_schedule_off_minute),
        )

    async def async_set_nightlight_schedule_off(self, value: time) -> None:
        """Set the nightlight off time."""
        await self.async_set_nightlight_schedule(
            time_on=self.nightlight_schedule[0],
            time_off=f"{self._format_time(value.hour)}:{self._format_time(value.minute)}",
        )

    @property
    def nightlight_schedule_off_hour(self) -> str:
        """Nightlight schedule off hour."""
        return cast("str", self.nightlight_schedule[1]).split(":")[0]

    @property
    def nightlight_schedule_off_minute(self) -> str:
        """Nightlight schedule off minute."""
        return cast("str", self.nightlight_schedule[1]).split(":")[1]

    @property
    def nightlight_schedule_on(self) -> time:
        """Nightlight schedule on."""
        return time(
            hour=int(self.nightlight_schedule_on_hour),
            minute=int(self.nightlight_schedule_on_minute),
        )

    async def async_set_nightlight_schedule_on(self, value: time) -> None:
        """Set the nightlight on time."""
        await self.async_set_nightlight_schedule(
            time_on=f"{self._format_time(value.hour)}:{self._format_time(value.minute)}",
            time_off=self.nightlight_schedule[1],
        )

    @property
    def nightlight_schedule_on_hour(self) -> str:
        """Nightlight schedule on hour."""
        return cast("str", self.nightlight_schedule[0]).split(":")[0]

    @property
    def nightlight_schedule_on_minute(self) -> str:
        """Nightlight schedule on minute."""
        return cast("str", self.nightlight_schedule[0]).split(":")[1]

    async def _set_nightlight(self, **settings: Any) -> None:
        await self.api.call(
            self.api.sdk.eeros.set_nightlight(
                self.network.known_id, self.known_id, parent=self.data, **settings
            ),
            name=f"{self.url}/nightlight",
        )

    async def async_set_nightlight_ambient(self) -> None:
        """Set nightlight ambient."""
        await self._set_nightlight(enabled=True, schedule={"enabled": False})

    async def async_set_nightlight_brightness(self, value: int) -> None:
        """Set nightlight brightness."""
        await self._set_nightlight(
            enabled=True,
            brightness_percentage=value,
            schedule={
                "enabled": True,
                "on": self.nightlight_schedule[0],
                "off": self.nightlight_schedule[1],
            },
        )

    async def async_set_nightlight_disabled(self) -> None:
        """Set nightlight disabled."""
        await self._set_nightlight(enabled=False)

    async def async_set_nightlight_schedule(
        self, time_on: str | None, time_off: str | None
    ) -> None:
        """Set nightlight schedule."""
        if not isinstance(time_on, str) or not isinstance(time_off, str):
            return
        await self._set_nightlight(
            enabled=True, schedule={"enabled": True, "on": time_on, "off": time_off}
        )
