"""Classe de base pour toutes les entités Easy-care by Waterair.

Cette classe encapsule :
  - Le pattern CoordinatorEntity (HA standard)
  - Les helpers de DeviceInfo (WATBOX, BPC, AC1, LR-PR)
  - L'attribut `unique_id` standardisé pour éviter les conflits

Toutes les entités du plugin doivent hériter de :
  - `EasyCareBPCEntity`     pour les entités du BPC (pompe, lumières, etc.)
  - `EasyCareAC1Entity`     pour les entités de l'analyseur AC1
  - `EasyCareWATBOXEntity`  pour les entités globales (connexion, refresh)
  - `EasyCarePressureEntity` pour les entités du capteur de pression LR-PR

Ces sous-classes injectent automatiquement le bon `DeviceInfo`, ce qui
garantit que chaque entité apparaît rattachée à son appareil physique dans
le Device Registry HA, conformément aux bonnes pratiques.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    DEVICE_ID_AC1,
    DEVICE_ID_BPC,
    DEVICE_ID_PRESSURE,
    DEVICE_ID_WATBOX,
    DOMAIN,
    MANUFACTURER,
)

# Type générique pour le coordinator — permet à l'entité d'avoir un type
# précis pour `self.coordinator.data` selon le coordinator utilisé.
_CoordinatorT = TypeVar("_CoordinatorT", bound=DataUpdateCoordinator)


class EasyCareEntity(CoordinatorEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Classe de base pour toutes les entités Easy-care.

    Ne pas instancier directement — utiliser une des sous-classes (WATBOX,
    BPC, AC1, LR-PR) qui injectent le bon DeviceInfo.

    Attributs auto-générés :
      - `_attr_has_entity_name = True` → HA construit le nom complet à partir
        de `name` + nom de l'appareil (ex: "BPC-06DFC6 Pompe de filtration")
      - `_attr_unique_id` → préfixé par entry_id pour éviter les conflits
        en cas de plusieurs comptes Waterair
    """

    _attr_has_entity_name = True
    """Indique à HA d'utiliser le nom de l'appareil comme préfixe.

    Voir : https://developers.home-assistant.io/docs/core/entity#has_entity_name
    """

    def __init__(
        self,
        coordinator: _CoordinatorT,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        """Initialise l'entité.

        Args:
            coordinator      : le DataUpdateCoordinator que l'entité écoute.
            entry            : ConfigEntry pour préfixer le unique_id.
            unique_id_suffix : identifiant unique pour cette entité dans
                l'intégration (ex: "pump", "spot", "battery_ac1").
        """
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{unique_id_suffix}"


# ─────────────────────────────────────────────────────────────────────────────
# Sous-classes spécialisées par appareil — injectent le DeviceInfo correct
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareWATBOXEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil WATBOX (passerelle).

    Utilisée pour les entités globales : statut de connexion,
    bouton de rafraîchissement, etc.
    """

    def __init__(
        self,
        coordinator: _CoordinatorT,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}")},
            manufacturer=MANUFACTURER,
            model="WATBOX",
        )


class EasyCareBPCEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil BPC (Boîtier Piscine Connecté).

    Utilisée pour : pompe, spot, escalight, mode filtration, boost, compteurs.
    """

    def __init__(
        self,
        coordinator: _CoordinatorT,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}")},
            manufacturer=MANUFACTURER,
            model="BPC (Boîtier Piscine Connecté)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )


class EasyCareAC1Entity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil AC1 (Analyseur Connecté).

    Utilisée pour : température, pH, chlore, batterie, alertes.
    Les mesures viennent du coordinator User (pas du BPC) car l'AC1
    transmet ses données via getUser.
    """

    def __init__(
        self,
        coordinator: _CoordinatorT,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_AC1}")},
            manufacturer=MANUFACTURER,
            model="AC1 (Analyseur Connecté)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )


class EasyCarePressureEntity(EasyCareEntity[_CoordinatorT], Generic[_CoordinatorT]):
    """Entité rattachée à l'appareil LR-PR (capteur de pression).

    Optionnel — n'est créé que si un module lr-pr est présent.
    """

    def __init__(
        self,
        coordinator: _CoordinatorT,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_PRESSURE}")},
            manufacturer=MANUFACTURER,
            model="LR-PR (Capteur Pression)",
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )
