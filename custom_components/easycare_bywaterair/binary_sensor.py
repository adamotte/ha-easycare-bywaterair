"""Plateforme binary_sensor pour Easy-care by Waterair.

Expose le statut de connexion à l'API Waterair :
  - "Connecté"     : le dernier refresh a réussi
  - "Déconnecté"   : le dernier refresh a échoué (réseau, serveur, etc.)

Reproduit le binary_sensor du plugin existant (parité fonctionnelle).
Rattaché à l'appareil WATBOX dans le Device Registry.
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

    On utilise le coordinator des modules comme baromètre — s'il arrive à
    rafraîchir la liste des modules, c'est qu'on est connecté. On pourrait
    aussi utiliser n'importe lequel des 3 coordinators, le plus rapide à
    se synchroniser est le bon choix.
    """

    _attr_translation_key = "connection"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: EasyCareModulesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise le binary_sensor de connexion."""
        super().__init__(coordinator, entry, unique_id_suffix="connection")

    @property
    def is_on(self) -> bool:
        """Vrai si le dernier refresh du coordinator a réussi.

        `last_update_success` est un attribut standard du DataUpdateCoordinator
        HA, mis à jour automatiquement après chaque tentative de refresh.
        """
        return self.coordinator.last_update_success
