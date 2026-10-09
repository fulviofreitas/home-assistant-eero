"""Eero API."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from .resource import EeroResource

if TYPE_CHECKING:
    from .network import EeroNetwork


class EeroBackupNetwork(EeroResource):
    """EeroBackupNetwork."""

    network: EeroNetwork

    @property
    def auto_join_enabled(self) -> bool | None:
        """Auto join enabled."""
        return self.data.get("enabled")

    async def async_set_auto_join_enabled(self, value: bool) -> None:
        """Set auto-join, re-sending SSID and password as the API expects."""
        await self.api.call(
            self.api.sdk.backup_access_points.update(
                self.network.known_id,
                cast("str", self.uuid),
                enabled=value,
                ssid=self.ssid,
                password=self.password,
            ),
            name=self.known_url,
        )

    @property
    def backup_access_point_id(self) -> str | None:
        """Backup access point."""
        return cast("str | None", self.data.get("connectivity", {}).get("backup_access_point_id"))

    @property
    def checked(self) -> str | None:
        """Checked."""
        return cast("str | None", self.data.get("connectivity", {}).get("checked"))

    @property
    def created(self) -> str | None:
        """Created."""
        return self.data.get("created")

    @property
    def failure_reason(self) -> str | None:
        """Failure reason."""
        return cast("str | None", self.data.get("connectivity", {}).get("failure_reason"))

    @property
    def id(self) -> str | None:
        """ID."""
        return self.uuid

    @property
    def last_updated_at(self) -> str | None:
        """Last updated at."""
        return self.data.get("last_updated_at")

    @property
    def name(self) -> str | None:
        """Name."""
        return self.ssid

    @property
    def password(self) -> str | None:
        """Password."""
        return self.data.get("password")

    @property
    def ssid(self) -> str | None:
        """SSID."""
        return self.data.get("ssid")

    @property
    def status(self) -> str | None:
        """Status."""
        return cast("str | None", self.data.get("connectivity", {}).get("status"))

    @property
    def uuid(self) -> str | None:
        """UUID."""
        return self.data.get("uuid")
