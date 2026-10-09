"""Eero API."""

from __future__ import annotations

from functools import cached_property

from .network import EeroNetwork
from .resource import EeroResource


class EeroAccount(EeroResource):
    """EeroAccount."""

    def __init__(self, api, data) -> None:
        """Initialize."""
        super().__init__(api=api, network=None, data=data)

    @property
    def email(self) -> str | None:
        """Email."""
        return self.data.get("email", {}).get("value")

    @property
    def log_id(self) -> str | None:
        """Log ID."""
        return self.data.get("log_id")

    @property
    def name(self) -> str | None:
        """Name."""
        return self.data.get("name")

    @property
    def phone(self) -> str | None:
        """Phone."""
        return self.data.get("phone", {}).get("value")

    @property
    def premium_status(self) -> str | None:
        """Premium status."""
        return self.data.get("premium_status")

    @cached_property
    def networks(self) -> list[EeroNetwork | None]:
        """Networks."""
        return [
            EeroNetwork(self.api, self, network)
            for network in self.data.get("networks", {}).get("data", [])
        ]

    @cached_property
    def network_by_id(self) -> dict[str, EeroNetwork]:
        """Networks by ID.

        This tree is rebuilt whenever a tier has new data and never changes
        after, so it is safe to build each list and index once per tree.
        """
        index: dict[str, EeroNetwork] = {}
        for network in self.networks:
            if network is not None and network.id is not None:
                index.setdefault(network.id, network)
        return index
