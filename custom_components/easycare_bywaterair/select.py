"""Plateforme select pour Easy-care by Waterair.

Expose le sélecteur du mode de filtration :
  - select.easycare_bywaterair_filtration_mode

Options disponibles (confirmées dans l'APK) :
  - AUTO       : durée automatique selon la température de l'eau
  - CONTINUOUS : marche forcée (équivalent du 'ON' dans l'app mobile)
  - MANUAL     : arrêt forcé (équivalent du 'OFF' dans l'app mobile)
  - PROG       : programmation horaire utilisateur

L'état courant est lu depuis le coordinator BPC → pool_status.mode.
Le changement de mode appelle set_filtration_mode() sur le host Solem.
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import BOOST_CANCEL, BOOST_MODES, DOMAIN, FILTRATION_MODES
from .coordinator import EasyCareBPCCoordinator, EasyCareCoordinators
from .entity import EasyCareBPCEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les selects si un BPC est présent."""
    coords: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    if coords.modules.get_bpc() is None:
        return
    async_add_entities([
        EasyCareFiltrationModeSelect(coords.bpc, entry),
        EasyCareBoostSelect(coords.bpc, entry),
    ])


class EasyCareFiltrationModeSelect(
    EasyCareBPCEntity[EasyCareBPCCoordinator],
    SelectEntity,
):
    """Sélecteur du mode de filtration.

    Les valeurs exposées sont les modes API bruts (AUTO, CONTINUOUS, MANUAL, PROG).
    Les labels lisibles sont gérés par les fichiers de traduction
    (`translations/fr.json` et `en.json`).
    """

    _attr_translation_key = "filtration_mode"
    _attr_icon = "mdi:water-sync"
    _attr_options = list(FILTRATION_MODES)

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="filtration_mode_select")

    @property
    def current_option(self) -> str | None:
        """Mode courant lu depuis pool_status.

        Si on est dans un mode boost (BOOST12H, BOOST24H), on ne peut pas le
        mapper à un mode "principal" — on retourne None pour ne pas afficher
        une option fausse.
        """
        if self.coordinator.data is None or self.coordinator.data.pool_status is None:
            return None
        mode = self.coordinator.data.pool_status.mode
        if mode in FILTRATION_MODES:
            return mode
        return None  # mode boost ou inconnu → pas de sélection affichée

    async def async_select_option(self, option: str) -> None:
        """Change le mode de filtration."""
        if option not in FILTRATION_MODES:
            _LOGGER.error("Mode invalide demandé : %s", option)
            return

        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        client = coords.user._client  # noqa: SLF001

        _LOGGER.info("Changement mode filtration → %s", option)
        await client.set_filtration_mode(option)

        # Refresh immédiat pour voir la prise en compte
        await self.coordinator.async_request_immediate_refresh()


# ─────────────────────────────────────────────────────────────────────────────
# Select boost — démarre / annule / montre le boost en cours
# ─────────────────────────────────────────────────────────────────────────────

_BOOST_OFF = "off"
_BOOST_ACTIVE = "active"   # état lecture seule : boost en cours, durée indéterminée
_BOOST_OPTIONS = [_BOOST_OFF, _BOOST_ACTIVE] + list(BOOST_MODES)


class EasyCareBoostSelect(EasyCareBPCEntity[EasyCareBPCCoordinator], SelectEntity):
    """Sélecteur de boost de filtration.

    - Sélectionner une durée démarre le boost correspondant.
    - Sélectionner « off » annule le boost en cours.
    - Quand un boost tourne, l'état affiche « active » avec le temps restant
      en attribut. L'API ne retourne pas la durée initiale du boost, seulement
      le temps restant — on ne peut donc pas retrouver le mode d'origine.
    """

    _attr_translation_key = "boost"
    _attr_icon = "mdi:timer-play"
    _attr_options = _BOOST_OPTIONS

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_select")

    @property
    def current_option(self) -> str | None:
        """'active' si boost en cours, 'off' sinon."""
        if self.coordinator.data is None:
            return _BOOST_OFF
        pump = self.coordinator.data.get_input(0)
        if pump is not None and pump.is_boosting:
            return _BOOST_ACTIVE
        return _BOOST_OFF

    @property
    def extra_state_attributes(self) -> dict:
        """Temps boost restant en attribut."""
        if self.coordinator.data is None:
            return {"remaining": "00:00"}
        pump = self.coordinator.data.get_input(0)
        if pump is not None and pump.is_boosting:
            return {"remaining": pump.remaining_time}
        return {"remaining": "00:00"}

    async def async_select_option(self, option: str) -> None:
        """Démarre un boost ou l'annule."""
        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        client = coords.user._client  # noqa: SLF001

        if option in (_BOOST_OFF, _BOOST_ACTIVE):
            # 'off' annule le boost ; 'active' est un état lecture seule → cancel aussi
            _LOGGER.info("Annulation boost")
            await client.cancel_boost()
        else:
            _LOGGER.info("Démarrage boost %s", option)
            await client.start_boost(option)

        await self.coordinator.async_request_immediate_refresh()
