"""Plateforme binary_sensor pour Easy-care by Waterair.

Expose le statut de connexion à l'API Waterair :
  - binary_sensor.easycare_bywaterair_connection (sur l'appareil WATBOX)
"""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EasyCareCoordinators, EasyCareModulesCoordinator
from .entity import EasyCareWATBOXEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les binary_sensors depuis un ConfigEntry."""
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        EasyCareConnectionBinarySensor(coordinators.modules, entry),
    ])


class EasyCareConnectionBinarySensor(
    EasyCareWATBOXEntity[EasyCareModulesCoordinator],
    BinarySensorEntity,
):
    """Statut de connexion à l'API Waterair.

    Utilise le coordinator des modules comme indicateur : si le dernier
    refresh a réussi, la connexion est active.
    """

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="connection")

    @property
    def is_on(self) -> bool:
        """Vrai si le dernier refresh du coordinator a réussi."""
        return self.coordinator.last_update_success
