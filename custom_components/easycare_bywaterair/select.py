"""Plateforme select pour Easy-care by Waterair.

Expose les sélecteurs du mode de filtration et du boost de filtration.
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ADAPT_OFFSET_MINUS,
    ADAPT_OFFSET_PLUS,
    DOMAIN,
    HA_BOOST_ACTIVE,
    HA_BOOST_OFF,
    HA_BOOST_OPTIONS,
    HA_FILTRATION_MODES,
    HA_MODE_AUTO,
    HA_MODE_AUTO_MINUS,
    HA_MODE_AUTO_PLUS,
    HA_MODE_CONTINUOUS,
    HA_MODE_MANUAL,
    HA_TO_API_BOOST,
    HA_TO_API_FILTRATION_MODE,
    MODE_AUTO,
    MODE_PROG,
)
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

    Options disponibles :
      - AUTO-2H    : mode AUTO avec offset -2h (adaptOffset = -60 min)
      - AUTO       : mode AUTO standard (adaptOffset = 0)
      - AUTO+2H    : mode AUTO avec offset +2h (adaptOffset = +60 min)
      - CONTINUOUS : marche forcée
      - MANUAL     : arrêt forcé

    Le mode PROG est détecté en lecture (capteur filtration_mode) mais n'est
    pas proposé en écriture — le sélecteur affiche alors aucune option active.
    Les labels lisibles sont gérés par les fichiers de traduction.

    État optimiste : après une sélection, l'option choisie est conservée
    localement jusqu'à ce que le coordinateur confirme le nouveau mode.
    Évite le rebond visuel identique au problème des lumières BPC.
    """

    _attr_translation_key = "filtration_mode"
    _attr_icon = "mdi:water-sync"
    _attr_options = list(HA_FILTRATION_MODES)

    _optimistic_option: str | None = None

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="filtration_mode_select")

    def _handle_coordinator_update(self) -> None:
        """Efface l'état optimiste dès que le coordinateur confirme l'option attendue."""
        if self._optimistic_option is not None:
            confirmed = self._current_option_from_data()
            if confirmed == self._optimistic_option:
                _LOGGER.debug(
                    "Mode filtration : option optimiste '%s' confirmée par le coordinateur",
                    self._optimistic_option,
                )
                self._optimistic_option = None
        super()._handle_coordinator_update()

    @property
    def current_option(self) -> str | None:
        """Mode courant — optimiste si une commande est en attente de confirmation."""
        if self._optimistic_option is not None:
            return self._optimistic_option
        return self._current_option_from_data()

    def _current_option_from_data(self) -> str | None:
        """Dérive l'option courante depuis les données du coordinateur."""
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.filtration_mode
        if mode is None:
            return None
        if mode == MODE_PROG:
            return None
        if mode == MODE_AUTO:
            offset = self.coordinator.data.adapt_offset
            if offset == ADAPT_OFFSET_MINUS:
                return HA_MODE_AUTO_MINUS
            if offset == ADAPT_OFFSET_PLUS:
                return HA_MODE_AUTO_PLUS
            return HA_MODE_AUTO
        if mode == "CONTINUOUS":
            return HA_MODE_CONTINUOUS
        if mode == "MANUAL":
            return HA_MODE_MANUAL
        return None

    async def async_select_option(self, option: str) -> None:
        """Change le mode de filtration."""
        api_option = HA_TO_API_FILTRATION_MODE.get(option)
        if api_option is None:
            _LOGGER.error("Mode invalide demandé : %s", option)
            return

        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        client = coords.user._client  # noqa: SLF001

        _LOGGER.info("Changement mode filtration → %s (%s)", option, api_option)
        await client.set_filtration_mode_with_offset(api_option)
        # Mise à jour optimiste immédiate — pas de refresh immédiat,
        # le poll naturel (1 min en mode actif) confirmera le nouveau mode.
        self._optimistic_option = option
        self.async_write_ha_state()




class EasyCareBoostSelect(EasyCareBPCEntity[EasyCareBPCCoordinator], SelectEntity):
    """Sélecteur de boost de filtration.

    - Sélectionner une durée démarre le boost correspondant.
    - Sélectionner « off » annule le boost en cours.
    - Quand un boost tourne, l'état affiche « active » avec le temps restant en attribut.

    État optimiste : après une commande, l'option attendue est conservée
    localement jusqu'à confirmation par le coordinateur.
    """

    _attr_translation_key = "boost"
    _attr_icon = "mdi:timer-play"
    _attr_options = list(HA_BOOST_OPTIONS)

    _optimistic_option: str | None = None

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_select")

    def _handle_coordinator_update(self) -> None:
        """Efface l'état optimiste dès que le coordinateur confirme l'option attendue."""
        if self._optimistic_option is not None:
            confirmed = self._current_option_from_data()
            if confirmed == self._optimistic_option:
                _LOGGER.debug(
                    "Boost : option optimiste '%s' confirmée par le coordinateur",
                    self._optimistic_option,
                )
                self._optimistic_option = None
        super()._handle_coordinator_update()

    @property
    def current_option(self) -> str | None:
        """'active' si boost en cours, 'off' sinon — optimiste si commande en attente."""
        if self._optimistic_option is not None:
            return self._optimistic_option
        return self._current_option_from_data()

    def _current_option_from_data(self) -> str:
        """Dérive l'option courante depuis les données du coordinateur.

        Un boost est actif s'il est signalé soit par la voie pompe (tag 'boost'),
        soit par l'état racine du programme pompe (state == 'boost', cas d'un
        boost déclenché depuis l'app mobile).
        """
        if self.coordinator.data is None:
            return HA_BOOST_OFF
        if self.coordinator.data.is_boost_active:
            return HA_BOOST_ACTIVE
        return HA_BOOST_OFF

    @property
    def extra_state_attributes(self) -> dict:
        """Temps boost restant en attribut."""
        data = self.coordinator.data
        if data is None or not data.is_boost_active:
            return {"remaining": "00:00"}
        pump = data.get_input(0)
        if pump is not None and pump.remaining_time not in (None, "", "00:00"):
            return {"remaining": pump.remaining_time}
        if data.pump_program_remaining_minutes:
            mins = data.pump_program_remaining_minutes
            return {"remaining": f"{mins // 60:02d}:{mins % 60:02d}"}
        return {"remaining": "00:00"}

    async def async_select_option(self, option: str) -> None:
        """Démarre un boost ou l'annule."""
        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        client = coords.user._client  # noqa: SLF001

        if option in (HA_BOOST_OFF, HA_BOOST_ACTIVE):
            _LOGGER.info("Annulation boost")
            await client.cancel_boost()
            self._optimistic_option = HA_BOOST_OFF
        else:
            api_boost = HA_TO_API_BOOST.get(option)
            if api_boost is None:
                _LOGGER.error("Mode boost invalide : %s", option)
                return
            _LOGGER.info("Démarrage boost %s (%s)", option, api_boost)
            await client.start_boost(api_boost)
            self._optimistic_option = HA_BOOST_ACTIVE
        # Pas de refresh immédiat — poll naturel (1 min) confirmera l'état.
        self.async_write_ha_state()
