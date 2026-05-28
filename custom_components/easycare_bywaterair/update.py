"""Plateforme update pour Easy-care by Waterair.

Expose les entités de mise à jour logicielle pour les modules BPC et AC1.
L'installation depuis HA n'est pas supportée (mise à jour BLE uniquement via l'app mobile).
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.update import UpdateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MODULE_TYPE_AC1
from .coordinator import EasyCareCoordinators, EasyCareModulesCoordinator
from .entity import EasyCareAC1Entity, EasyCareBPCEntity


def _parse_device_version(data: dict[str, Any], key: str) -> str | None:
    """Parse un DeviceVersion {major, minor, patch} en string 'major.minor.patch'."""
    dv = data.get(key)
    if not isinstance(dv, dict):
        return None
    major = dv.get("major")
    minor = dv.get("minor")
    patch = dv.get("patch")
    if major is None and minor is None:
        return None
    parts = [str(major or 0), str(minor or 0)]
    if patch:
        parts.append(str(patch))
    return ".".join(parts)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les entités update depuis un ConfigEntry."""
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    entities: list[UpdateEntity] = []

    if coordinators.modules.get_bpc() is not None:
        entities.append(EasyCareBPCFirmwareUpdateEntity(coordinators.modules, entry))

    if coordinators.modules.get_modules_by_type(MODULE_TYPE_AC1):
        entities.append(EasyCareAC1FirmwareUpdateEntity(coordinators.modules, entry))

    async_add_entities(entities)


class EasyCareBPCFirmwareUpdateEntity(
    EasyCareBPCEntity[EasyCareModulesCoordinator],
    UpdateEntity,
):
    """Mise à jour logicielle du module BPC."""

    _attr_translation_key = "bpc_firmware"
    _attr_icon = "mdi:package-up"

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="bpc_firmware_update")

    @property
    def installed_version(self) -> str | None:
        """Version logicielle actuellement installée sur le BPC."""
        bpc = self.coordinator.get_bpc()
        return bpc.software_version if bpc else None

    @property
    def latest_version(self) -> str | None:
        """Dernière version disponible — égale à installed si à jour."""
        bpc = self.coordinator.get_bpc()
        if bpc is None or not bpc.firmware_available:
            return self.installed_version
        version = _parse_device_version(bpc.firmware_available, "availableUpdateVersion")
        return version if version else self.installed_version

    @property
    def title(self) -> str | None:
        """Nom du composant mis à jour."""
        return "BPC"


class EasyCareAC1FirmwareUpdateEntity(
    EasyCareAC1Entity[EasyCareModulesCoordinator],
    UpdateEntity,
):
    """Mise à jour logicielle du module AC1."""

    _attr_translation_key = "ac1_firmware"
    _attr_icon = "mdi:package-up"

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="ac1_firmware_update")

    @property
    def installed_version(self) -> str | None:
        """Version logicielle actuellement installée sur l'AC1."""
        modules = self.coordinator.get_modules_by_type(MODULE_TYPE_AC1)
        return modules[0].software_version if modules else None

    @property
    def latest_version(self) -> str | None:
        """Dernière version disponible — égale à installed si à jour."""
        modules = self.coordinator.get_modules_by_type(MODULE_TYPE_AC1)
        if not modules or not modules[0].firmware_available:
            return self.installed_version
        version = _parse_device_version(modules[0].firmware_available, "availableUpdateVersion")
        return version if version else self.installed_version

    @property
    def title(self) -> str | None:
        """Nom du composant mis à jour."""
        return "AC1"
