"""Base entity for the Eero integration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
import logging
from typing import Any, cast

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import UNDEFINED
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import EeroAuthenticationException, EeroException
from .api.network import EeroNetwork
from .api.resource import EeroResource
from .const import (
    CONF_ACTIVITY_CLIENTS,
    CONF_ACTIVITY_EEROS,
    CONF_ACTIVITY_NETWORK,
    CONF_ACTIVITY_PROFILES,
    CONF_BACKUP_NETWORKS,
    CONF_EEROS,
    CONF_PREFIX_NETWORK_NAME,
    CONF_PROFILES,
    CONF_SUFFIX_CONNECTION_TYPE,
    DOMAIN,
    MANUFACTURER,
    MODEL_BACKUP_NETWORK,
    MODEL_CLIENT_WIRED,
    MODEL_CLIENT_WIRELESS,
    MODEL_NETWORK,
    MODEL_PROFILE,
    TIER_DAILY,
    TIER_FAST,
)
from .coordinator import EeroConfigEntry, EeroRuntime, EeroTierCoordinator
from .util import client_allowed, resource_supports

_LOGGER = logging.getLogger(__name__)

KIND_NETWORK = "network"
KIND_BACKUP_NETWORKS = "backup_networks"
KIND_EEROS = "eeros"
KIND_PROFILES = "profiles"
KIND_CLIENTS = "clients"

ACTIVITY_KEYS = {
    KIND_NETWORK: CONF_ACTIVITY_NETWORK,
    KIND_EEROS: CONF_ACTIVITY_EEROS,
    KIND_PROFILES: CONF_ACTIVITY_PROFILES,
    KIND_CLIENTS: CONF_ACTIVITY_CLIENTS,
}


@dataclass(frozen=True, kw_only=True)
class EeroEntityDescription(EntityDescription):
    """A class that describes Eero entities."""

    extra_attrs: dict[str, Callable] | None = None
    premium_type: bool = False
    request_refresh: bool = True
    translation_key: str | None = "all"
    # Which polling tier the entity's state comes from, any other tier whose
    # data it also shows, and whether the platform should check that the
    # resource has the attribute named by key before creating the entity.
    tier: str = TIER_FAST
    extra_tiers: tuple[str, ...] = ()
    refresh_tiers: tuple[str, ...] | None = None
    activity_type: bool = False
    wireless_only: bool = False
    check_support: bool = True
    # The attribute check_support looks for, when it is not the key itself:
    # an action entity (a button) checks for the method it calls.
    support_key: str | None = None
    # Don't create the entity while its value is None: an optional read that
    # failed or is not offered (a daily-tier 404, a blacklist not yet read).
    # A platform using async_setup_platform_entities picks it up later, on
    # the first fast poll after the value appears.
    requires_value: bool = False
    # True only for entities that read the fast tier's profiles payload
    # (e.g. a client's profile_assignment select): that payload is only
    # fetched for a network with at least one profile configured, so an
    # entity gated on this is skipped on a network with none, rather than
    # being created and reporting a false "unassigned" for every client.
    requires_profiles: bool = False


def iter_resources(
    runtime: EeroRuntime, network: EeroNetwork, kinds: tuple[str, ...]
) -> Iterator[tuple[str, EeroResource]]:
    """Yield (kind, resource) for every configured resource of the given kinds."""
    resources = runtime.resources[network.id]
    if KIND_NETWORK in kinds:
        yield KIND_NETWORK, network
    if KIND_BACKUP_NETWORKS in kinds:
        for backup_network in network.backup_networks:
            if backup_network.id in resources[CONF_BACKUP_NETWORKS]:
                yield KIND_BACKUP_NETWORKS, backup_network
    if KIND_EEROS in kinds:
        for eero in network.eeros:
            if eero.id in resources[CONF_EEROS]:
                yield KIND_EEROS, eero
    if KIND_PROFILES in kinds:
        for profile in network.profiles:
            if profile.id in resources[CONF_PROFILES]:
                yield KIND_PROFILES, profile
    if KIND_CLIENTS in kinds:
        for client in network.clients:
            if client_allowed(client, resources):
                yield KIND_CLIENTS, client


def build_entities[EntityT: "EeroEntity"](
    runtime: EeroRuntime,
    descriptions: list[Any],
    entity_class: type[EntityT],
    kinds: tuple[str, ...],
) -> list[EntityT]:
    """Create an entity for every description each configured resource supports."""
    entities: list[EntityT] = []
    for network in runtime.account.networks:
        if network.id not in runtime.networks:
            continue
        activity = runtime.activity.get(network.id, {})
        for kind, resource in iter_resources(runtime, network, kinds):
            for description in descriptions:
                if description.premium_type and not network.premium_enabled:
                    continue
                if description.activity_type and description.key not in activity.get(
                    ACTIVITY_KEYS.get(kind, ""), []
                ):
                    continue
                if description.wireless_only and not getattr(
                    resource, "wireless", False
                ):
                    continue
                if (
                    description.requires_profiles
                    and not runtime.update_config[network.id].get_profiles
                ):
                    continue
                if description.check_support and not resource_supports(
                    resource, description.support_key or description.key
                ):
                    continue
                if (
                    description.requires_value
                    and getattr(resource, description.key, None) is None
                ):
                    continue
                entities.append(
                    entity_class(
                        runtime,
                        network.id,
                        None if kind == KIND_NETWORK else resource.id,
                        description,
                        # Backup networks come from the daily tier, whatever
                        # tier the shared description names.
                        tier=TIER_DAILY if kind == KIND_BACKUP_NETWORKS else None,
                    )
                )
    return entities


def async_setup_platform_entities[EntityT: "EeroEntity"](
    config_entry: EeroConfigEntry,
    descriptions: list[Any],
    entity_class: type[EntityT],
    kinds: tuple[str, ...],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Build this platform's entities, and add new ones as they appear.

    Every platform that builds client entities calls this instead of
    build_entities()+async_add_entities() directly, so a client that joins
    the network after setup (or a profile added through the options flow
    without a reload) gets its entities without reloading the config entry.
    Respects the same include/exclude filter as initial setup, since it is
    build_entities() doing the filtering both times: an exclude filter means
    a new client is picked up automatically, an include filter means only
    already-listed clients ever get entities.

    Only wired to the fast tier, which is what reports clients (and
    profiles): a kind with nothing dynamic about it (the network itself, its
    eeros) simply never produces anything new, so the listener is a no-op
    for platforms that only build those.
    """
    runtime = config_entry.runtime_data
    added: set[str] = set()

    def _new_entities() -> list[EntityT]:
        entities = build_entities(runtime, descriptions, entity_class, kinds)
        fresh = [entity for entity in entities if entity.unique_id not in added]
        added.update(entity.unique_id for entity in fresh)
        return fresh

    async_add_entities(_new_entities())

    @callback
    def _check_for_new_entities() -> None:
        if fresh := _new_entities():
            async_add_entities(fresh)

    config_entry.async_on_unload(
        runtime.coordinator(TIER_FAST).async_add_listener(_check_for_new_entities)
    )


def resource_device_info(
    hass: HomeAssistant,
    runtime: EeroRuntime,
    network: EeroNetwork | None,
    resource: EeroResource,
) -> dr.DeviceInfo:
    """Return the full device info for a resource's device.

    Shared by every entity that sits on a resource's device, so whichever
    platform registers the device first registers it complete: a device
    first created from identifiers alone would have no name, and its
    entities' IDs no device prefix.
    """
    miscellaneous = runtime.miscellaneous.get(network.id if network else "", {})
    name = resource.name
    model = None
    if resource.is_network:
        model = MODEL_NETWORK
    elif resource.is_backup_network:
        model = MODEL_BACKUP_NETWORK
    elif resource.is_eero:
        model = resource.model
    elif resource.is_profile:
        model = MODEL_PROFILE
    elif resource.is_client:
        model = MODEL_CLIENT_WIRELESS if resource.wireless else MODEL_CLIENT_WIRED
        if miscellaneous.get(CONF_SUFFIX_CONNECTION_TYPE):
            name = resource.name_connection_type
    if miscellaneous.get(CONF_PREFIX_NETWORK_NAME) and not resource.is_network and network:
        name = f"{network.name} {name}"

    entry_type, suggested_area, sw_version, hw_version = None, None, None, None
    if resource.is_backup_network or resource.is_network or resource.is_profile:
        entry_type = dr.DeviceEntryType.SERVICE
    if resource.is_eero:
        suggested_area = resource.location
        sw_version = resource.os_version
        hw_version = resource.model_number
    device_info = dr.DeviceInfo(
        entry_type=entry_type,
        hw_version=hw_version,
        identifiers={(DOMAIN, resource.id)},
        manufacturer=MANUFACTURER,
        model=model,
        name=name,
        suggested_area=suggested_area,
        sw_version=sw_version,
    )
    if not resource.is_network and network is not None:
        # Linked by via_device_id, a device registry ID: the identifier
        # tuple via_device is removed in Home Assistant 2027.8. Left out
        # when the network device is not found, because Home Assistant
        # raises on an unknown via_device_id and drops the entity.
        network_device = dr.async_get(hass).async_get_device_by_identifier(
            (DOMAIN, network.id), runtime.entry.entry_id
        )
        if network_device is not None:
            device_info["via_device_id"] = network_device.id
    return device_info


class EeroEntity(CoordinatorEntity[EeroTierCoordinator]):
    """Representation of an Eero entity."""

    _attr_has_entity_name = True
    entity_description: EeroEntityDescription

    def __init__(
        self,
        runtime: EeroRuntime,
        network_id: str,
        resource_id: str | None,
        description: EeroEntityDescription,
        tier: str | None = None,
    ) -> None:
        """Initialize device."""
        self.tier = tier or description.tier
        super().__init__(runtime.coordinator(self.tier))
        self.runtime = runtime
        self.network_id = network_id
        self.resource_id = resource_id
        self.entity_description = description
        miscellaneous = runtime.miscellaneous[network_id]
        self.prefix_network_name = miscellaneous[CONF_PREFIX_NETWORK_NAME]
        self.suffix_connection_type = miscellaneous[CONF_SUFFIX_CONNECTION_TYPE]

    async def async_added_to_hass(self) -> None:
        """Also follow any other tier whose data this entity shows."""
        await super().async_added_to_hass()
        for tier in self.entity_description.extra_tiers:
            if tier != self.tier:
                self.async_on_remove(
                    self.runtime.coordinator(tier).async_add_listener(
                        self._handle_coordinator_update
                    )
                )

    @property
    def network(self) -> EeroNetwork | None:
        """Return the network for this entity, or None if it is no longer reported."""
        if self.coordinator.data is None:
            return None
        return self.runtime.account.network_by_id.get(self.network_id)

    @property
    def resource(self) -> EeroResource | None:
        """Return the resource for this entity, or None if it is no longer reported."""
        if (network := self.network) is None:
            return None
        if self.resource_id is None:
            return network
        return network.resource_by_id.get(self.resource_id)

    @property
    def available(self) -> bool:
        """Return True if the coordinator succeeded and this resource still exists."""
        return bool(
            self.coordinator.last_update_success
            and self.network is not None
            and self.resource is not None
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID.

        Built from the configured IDs rather than from live data, so a resource
        that is missing at registration time cannot inherit the network's ID.
        """
        if self.resource_id is None:
            return f"{self.network_id}-{self.entity_description.key}"
        return f"{self.network_id}-{self.resource_id}-{self.entity_description.key}"

    @property
    def network_device(self) -> dr.DeviceEntry | None:
        """Return the registry entry for this entity's network device."""
        registry = dr.async_get(self.hass if self.hass else self.coordinator.hass)
        return registry.async_get_device_by_identifier(
            (DOMAIN, self.network_id), self.runtime.entry.entry_id
        )

    @property
    def device_info(self) -> dr.DeviceInfo | None:
        """Return device specific attributes.

        None rather than the network's device: attaching to the wrong device
        is permanent, because Home Assistant reads this once at registration.
        Entities are only built from live resources, so this is unreachable in
        practice.
        """
        if (resource := self.resource) is None:
            return None
        return resource_device_info(
            self.hass or self.coordinator.hass, self.runtime, self.network, resource
        )

    # name is intentionally not overridden: has_entity_name is set, so Home
    # Assistant's own Entity.name resolves a translation_key against
    # strings.json/translations before falling back to entity_description.name
    # (and to the device name alone when neither is set, as for the device
    # tracker). Every other description sets its own translation_key.

    async def async_write(
        self,
        method: str,
        *args: Any,
        current: Any = UNDEFINED,
        target: Any = UNDEFINED,
        resource: EeroResource | None = None,
    ) -> None:
        """Call <resource>.<method>(*args), refresh the tier, map SDK errors.

        resource defaults to this entity's own resource.

        Read-compare-skip, as eero-api asks for every write: when the state
        already matches the target, nothing is sent. Some of these writes
        reboot every eero on the network; repeating one that changes nothing
        is never free.
        """
        if resource is None and (resource := self.resource) is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="resource_unavailable"
            )
        if target is not UNDEFINED and current == target:
            # The value is not logged: some targets are secrets.
            _LOGGER.debug("Skipping %s on %s: no change", method, self.entity_id)
            return
        await async_call_mapped(
            self.hass, self.runtime, getattr(resource, method)(*args)
        )
        if self.entity_description.request_refresh:
            await self.runtime.async_refresh_tiers(
                self.entity_description.refresh_tiers or (self.tier,)
            )


async def async_call_mapped(
    hass: HomeAssistant, runtime: EeroRuntime, request: Awaitable[Any]
) -> None:
    """Await an SDK write, turning its failures into readable action errors.

    An expired session also starts reauthentication.
    """
    try:
        await request
    except EeroAuthenticationException as error:
        runtime.entry.async_start_reauth(hass)
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="auth_failed"
        ) from error
    except (EeroException, TimeoutError) as error:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="api_error",
            translation_placeholders={"error": str(error)},
        ) from error


def async_setup_port_entities[EntityT: "EeroPortEntity"](
    config_entry: EeroConfigEntry,
    build: Callable[[EeroRuntime, str, str, dict], list[EntityT]],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Build per-port entities for every configured eero, and add new ports.

    build(runtime, network_id, eero_id, port) returns the entities for one
    port (e.g. one sensor per field, or one button per supported action);
    called for every port of every configured eero. Wired to the daily
    tier, which is what fetches ports (eeros.get_connections).
    """
    runtime = config_entry.runtime_data
    added: set[str] = set()

    def _new_entities() -> list[EntityT]:
        entities: list[EntityT] = []
        for network in runtime.account.networks:
            if network.id not in runtime.networks:
                continue
            for eero in network.eeros:
                if eero.id not in runtime.resources[network.id][CONF_EEROS]:
                    continue
                for port in eero.ports:
                    if port.get("interface_number") is None:
                        continue
                    for entity in build(runtime, network.id, eero.id, port):
                        if entity.unique_id not in added:
                            added.add(entity.unique_id)
                            entities.append(entity)
        return entities

    async_add_entities(_new_entities())

    @callback
    def _check_for_new_ports() -> None:
        if fresh := _new_entities():
            async_add_entities(fresh)

    config_entry.async_on_unload(
        runtime.coordinator(TIER_DAILY).async_add_listener(_check_for_new_ports)
    )


class EeroPortEntity(CoordinatorEntity[EeroTierCoordinator]):
    """Base for a port-level entity: one interface on one eero.

    Not an EeroEntity: a port is a sub-item of an eero's own data (keyed by
    interface_number), not one of the resource kinds build_entities
    iterates. Always reads the eero's current port list fresh rather than
    caching the port dict at construction time.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        runtime: EeroRuntime,
        network_id: str,
        eero_id: str,
        interface_number: int,
    ) -> None:
        """Initialize."""
        super().__init__(runtime.coordinator(TIER_DAILY))
        self.runtime = runtime
        self.network_id = network_id
        self.eero_id = eero_id
        self.interface_number = interface_number
        # Every port entity's translated name carries its port number, so the
        # same field on two ports of one eero gets distinct names.
        self._attr_translation_placeholders = {"port_number": str(interface_number)}

    @property
    def network(self) -> EeroNetwork | None:
        """Return the network for this entity, or None if it is no longer reported."""
        if self.coordinator.data is None:
            return None
        return self.runtime.account.network_by_id.get(self.network_id)

    @property
    def eero(self) -> EeroResource | None:
        """Return the eero for this entity, or None if it is no longer reported."""
        if (network := self.network) is None:
            return None
        for eero in network.eeros:
            if eero.id == self.eero_id:
                return eero
        return None

    @property
    def port(self) -> dict | None:
        """Return this entity's current port dict, or None if it no longer appears."""
        if (eero := self.eero) is None:
            return None
        for port in eero.ports:
            if port.get("interface_number") == self.interface_number:
                return cast("dict | None", port)
        return None

    @property
    def available(self) -> bool:
        """Return True if the coordinator succeeded and this port still exists."""
        return bool(self.coordinator.last_update_success and self.port is not None)

    @property
    def device_info(self) -> dr.DeviceInfo | None:
        """Return the eero's own device, complete.

        Complete rather than identifiers alone: if this platform happens to
        register the eero's device first, a bare device would have no name.
        """
        if (eero := self.eero) is None:
            return dr.DeviceInfo(identifiers={(DOMAIN, self.eero_id)})
        return resource_device_info(
            self.hass or self.coordinator.hass, self.runtime, self.network, eero
        )
