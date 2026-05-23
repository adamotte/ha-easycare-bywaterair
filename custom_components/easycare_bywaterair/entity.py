"""Classe de base pour toutes les entités Easy-care by Waterair."""

from __future__ import annotations

from typing import Generic, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DEVICE_ID_AC1, DEVICE_ID_BPC, DEVICE_ID_PRESSURE, DEVICE_ID_WATBOX, DOMAIN, MANUFACTURER

_CoordinatorT = TypeVar("_CoordinatorT", bound=DataUpdateCoordinator)


class EasyCareEntity(CoordinatorEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Classe de base pour toutes les entités Easy-care."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: _CoordinatorT, entry: ConfigEntry, unique_id_suffix: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"


class EasyCareWATBOXEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil WATBOX (passerelle)."""

    def __init__(self, coordinator: _CoordinatorT, entry: ConfigEntry, unique_id_suffix: str) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}")},
            manufacturer=MANUFACTURER, model="WATBOX",
        )


class EasyCareBPCEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil BPC (Boîtier Piscine Connecté)."""

    def __init__(self, coordinator: _CoordinatorT, entry: ConfigEntry, unique_id_suffix: str) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}")},
            manufacturer=MANUFACTURER, model="BPC (Boîtier Piscine Connecté)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )


class EasyCareAC1Entity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil AC1 (Analyseur Connecté)."""

    def __init__(self, coordinator: _CoordinatorT, entry: ConfigEntry, unique_id_suffix: str) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_AC1}")},
            manufacturer=MANUFACTURER, model="AC1 (Analyseur Connecté)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )


class EasyCarePressureEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil LR-PR (capteur de pression)."""

    def __init__(self, coordinator: _CoordinatorT, entry: ConfigEntry, unique_id_suffix: str) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_PRESSURE}")},
            manufacturer=MANUFACTURER, model="LR-PR (Capteur Pression)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )
