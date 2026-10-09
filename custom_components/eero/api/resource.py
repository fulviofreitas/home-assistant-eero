"""Eero API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from .const import URL_ACCOUNT

if TYPE_CHECKING:
    from . import EeroHub
    from .network import EeroNetwork


class EeroResource:
    """EeroResource."""

    def __init__(
        self, api: EeroHub, network: EeroNetwork | None, data: dict[str, Any]
    ) -> None:
        """Initialize."""
        self.api = api
        self.network = network
        self.data = data

    @property
    def id(self) -> str | None:
        """ID."""
        url = self.url
        if url is None:
            return None
        if self.is_network:
            return url.replace("/2.2/networks/", "")
        if self.is_eero:
            return url.replace("/2.2/eeros/", "")
        if self.is_profile and self.network is not None:
            return url.replace(f"{self.network.url}/profiles/", "")
        if self.is_client and self.network is not None:
            return url.replace(f"{self.network.url}/devices/", "")
        return None

    @property
    def sdk_id(self) -> str:
        """ID for SDK and URL building.

        Typing only: every resource fetched from the API carries a URL, so the
        ID is set; a missing one is passed through unchanged, as before.
        """
        return cast("str", self.id)

    @property
    def sdk_url(self) -> str:
        """URL for SDK and call naming; same contract as ``sdk_id``."""
        return cast("str", self.url)

    @property
    def is_account(self) -> bool:
        """Is account."""
        return bool(self.__class__.__name__ == "EeroAccount")

    @property
    def is_backup_network(self) -> bool:
        """Is backup network."""
        return bool(self.__class__.__name__ == "EeroBackupNetwork")

    @property
    def is_client(self) -> bool:
        """Is client."""
        return bool(self.__class__.__name__ == "EeroClient")

    @property
    def is_eero(self) -> bool:
        """Is Eero."""
        return bool(self.__class__.__name__ in ["EeroDevice", "EeroDeviceBeacon"])

    @property
    def is_eero_beacon(self) -> bool:
        """Is Eero beacon."""
        return bool(self.__class__.__name__ == "EeroDeviceBeacon")

    @property
    def is_network(self) -> bool:
        """Is network."""
        return bool(self.__class__.__name__ == "EeroNetwork")

    @property
    def is_profile(self) -> bool:
        """Is profile."""
        return bool(self.__class__.__name__ == "EeroProfile")

    @property
    def url(self) -> str | None:
        """URL."""
        if self.is_account:
            return URL_ACCOUNT
        if self.is_backup_network:
            uuid = self.data.get("uuid")
            if self.network is None:
                return None
            return f"{self.network.url}/backup_access_points/{uuid}"
        return cast("str | None", self.data.get("url"))
