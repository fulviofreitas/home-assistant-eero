"""Support for Eero update entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.update import (
    UpdateDeviceClass,
    UpdateEntity,
    UpdateEntityDescription,
    UpdateEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import RELEASE_URL, TIER_DAILY
from .coordinator import EeroConfigEntry
from .entity import KIND_EEROS, EeroEntity, EeroEntityDescription, build_entities


@dataclass(frozen=True, kw_only=True)
class EeroUpdateEntityDescription(EeroEntityDescription, UpdateEntityDescription):
    """Class to describe an Eero update entity."""

    entity_category: EntityCategory | None = EntityCategory.CONFIG
    check_support: bool = False
    # Firmware versions come with the eero (fast tier); the target version
    # and release notes come with the network's updates (daily tier).
    extra_tiers: tuple[str, ...] = (TIER_DAILY,)


UPDATE_DESCRIPTIONS: list[EeroUpdateEntityDescription] = [
    EeroUpdateEntityDescription(
        key="firmware",
        name="Firmware",
        device_class=UpdateDeviceClass.FIRMWARE,
        request_refresh=False,
    ),
]


PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: EeroConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up an Eero update entity based on a config entry."""
    async_add_entities(
        build_entities(
            config_entry.runtime_data,
            UPDATE_DESCRIPTIONS,
            EeroUpdateEntity,
            (KIND_EEROS,),
        )
    )


class EeroUpdateEntity(EeroEntity, UpdateEntity):
    """Representation of an Eero update entity."""

    @property
    def auto_update(self) -> bool:
        """Indicate if the device or service has auto update enabled."""
        return True

    @property
    def installed_version(self) -> str | None:
        """Version installed and in use."""
        if os_version := self.resource.current_firmware.os_version:
            return os_version
        return self.resource.os_version

    @property
    def latest_version(self) -> str | None:
        """Latest version available for install."""
        return self.resource.target_firmware.os_version

    @property
    def release_summary(self) -> str | None:
        """Summary of the release notes or changelog.

        This is not suitable for long changelogs, but merely suitable
        for a short excerpt update description of max 255 characters.
        """
        features = self.resource.target_firmware.features
        if features:
            return str("- " + "\n- ".join(features))
        return None

    def release_notes(self) -> str | None:
        """Return full release notes.

        This is suitable for a long changelog that does not fit in the release_summary property.
        The returned string can contain markdown.
        """
        return self.release_summary

    @property
    def release_url(self) -> str | None:
        """URL to the full release notes of the latest version available."""
        return RELEASE_URL

    @property
    def supported_features(self) -> int:
        """Flag supported features.

        Read even while unavailable, so it has to cope with a resource that is
        no longer reported.
        """
        if self.resource is not None and self.resource.target_firmware.features:
            return UpdateEntityFeature.INSTALL | UpdateEntityFeature.RELEASE_NOTES
        return UpdateEntityFeature.INSTALL

    @property
    def title(self) -> str | None:
        """Title of the software.

        This helps to differentiate between the device or entity name
        versus the title of the software installed.
        """
        return self.resource.target_firmware.title

    async def async_install(
        self, version: str | None, backup: bool, **kwargs: Any
    ) -> None:
        """Install the pending firmware.

        Eero updates every eero on the network at once, so version and backup
        are ignored; supported_features never offers SPECIFIC_VERSION or
        BACKUP. Sent to the network, not to this eero.
        """
        await self.async_write(
            "async_install_firmware_update", resource=self.network
        )
