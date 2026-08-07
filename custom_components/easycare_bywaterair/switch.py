"""Plateforme switch pour Easy-care by Waterair.

Expose la voie auxiliaire 2 du BPC comme un interrupteur « électrolyseur »
lorsque l'option `auxiliary_type` est réglée sur `electrolyzer` (issue #13) :
  - switch.easycare_bywaterair_electrolyzer → électrolyseur (voie BPC index 2)

Le type de la voie est déclaré par l'utilisateur dans les options de
l'intégration : l'API ne permet pas de déduire de façon fiable ce que la voie
auxiliaire représente physiquement (projecteur, traitement, robot, PAC…).

Par défaut, la production de chlore est pilotée automatiquement par le BPC
(ON/OFF selon le taux de chlore mesuré par l'AC1, bornier AUX). L'interrupteur
est un override manuel : `on` démarre une marche forcée datée dont la durée est
lue depuis l'entité number `electrolyzer_duration` (même mécanisme que les
lumières). L'API ne supportant pas de mode permanent, la session s'arrête à
l'expiration ou sur OFF. De plus, un canal « traitement » est dépendant de la
filtration : il reste inhibé tant que la filtration est coupée.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    AUXILIARY_DEFAULT,
    AUXILIARY_ELECTROLYZER,
    BPC_INDEX_ESCALIGHT,
    CONF_AUXILIARY_TYPE,
    DEFAULT_DURATION_LIGHT_HOURS,
    DOMAIN,
)
from .coordinator import EasyCareBPCCoordinator, EasyCareCoordinators
from .entity import EasyCareBPCEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les switchs BPC depuis un ConfigEntry.

    L'électrolyseur est créé si le BPC a au moins 2 voies (index 2) et que
    l'utilisateur a déclaré le type de la voie comme « electrolyzer ».
    """
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    bpc = coordinators.modules.get_bpc()

    entities: list[SwitchEntity] = []

    if bpc is None:
        _LOGGER.debug("No BPC detected — no switches created")
        async_add_entities(entities)
        return

    # Garde-fou variantes matérielles (issue #10) : même logique que light.py.
    if coordinators.is_bpc_commands_blocked():
        _LOGGER.warning(
            "BPC switch commands disabled: pump channel (index 0) missing — "
            "unverified channel layout (non-standard BPC variant). Read-only sensors remain."
        )
        async_add_entities(entities)
        return

    auxiliary_type = entry.options.get(CONF_AUXILIARY_TYPE, AUXILIARY_DEFAULT)
    if auxiliary_type == AUXILIARY_ELECTROLYZER and bpc.number_of_inputs >= 2:
        entities.append(EasyCareElectrolyzerSwitch(coordinators.bpc, entry))

    if entities:
        _LOGGER.debug(
            "Creating %d BPC switch(es) (numberOfInputs=%d, auxiliary_type=%s)",
            len(entities), bpc.number_of_inputs, auxiliary_type,
        )

    async_add_entities(entities)


class EasyCareElectrolyzerSwitch(EasyCareBPCEntity[EasyCareBPCCoordinator], SwitchEntity):
    """Électrolyseur sur la voie auxiliaire 2 du BPC (index 2).

    État optimiste : après une commande on/off, l'état est écrit immédiatement
    dans l'UI sans attendre le prochain poll (même approche que light.py).
    """

    _bpc_index = BPC_INDEX_ESCALIGHT
    _attr_translation_key = "electrolyzer"
    _attr_icon = "mdi:pool"

    _optimistic_is_on: bool | None = None

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="electrolyzer")

    @property
    def is_on(self) -> bool | None:
        """État de la voie BPC — optimiste si une commande est en attente de confirmation."""
        if self._optimistic_is_on is not None:
            return self._optimistic_is_on
        data = self.coordinator.data
        if data is None:
            return None
        bpc_input = data.get_input(self._bpc_index)
        if bpc_input is None:
            return None
        return bpc_input.is_on

    def _handle_coordinator_update(self) -> None:
        """Efface l'état optimiste dès que le coordinateur confirme la valeur attendue."""
        if self._optimistic_is_on is not None:
            data = self.coordinator.data
            if data is not None:
                bpc_input = data.get_input(self._bpc_index)
                if bpc_input is not None and bpc_input.is_on == self._optimistic_is_on:
                    _LOGGER.debug(
                        "BPC channel %d: optimistic state '%s' confirmed by coordinator",
                        self._bpc_index, self._optimistic_is_on,
                    )
                    self._optimistic_is_on = None
        super()._handle_coordinator_update()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Informations sur la voie BPC en attribut."""
        data = self.coordinator.data
        if data is None:
            return {}
        bpc_input = data.get_input(self._bpc_index)
        if bpc_input is None:
            return {}
        return {
            "remaining_time": bpc_input.remaining_time,
            "bpc_index": self._bpc_index,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Allume l'électrolyseur via la commande BPC manual (session datée)."""
        duration_hours = self._get_configured_duration_hours()
        duration_minutes = int(duration_hours * 60)
        _LOGGER.info(
            "Turning on BPC channel %d (electrolyzer) for %d minutes",
            self._bpc_index, duration_minutes,
        )

        coordinators: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coordinators.modules.get_watbox()
        bpc = coordinators.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("WATBOX or BPC not found")
            return

        client = coordinators.user._client
        await client.set_bpc_manual(
            watbox, bpc,
            index=self._bpc_index,
            action="on",
            duration_minutes=duration_minutes,
        )
        # Mise à jour optimiste immédiate : l'UI bascule à On sans attendre le poll.
        self._optimistic_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Éteint l'électrolyseur via la commande BPC manual."""
        _LOGGER.info("Turning off BPC channel %d (electrolyzer)", self._bpc_index)

        coordinators: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coordinators.modules.get_watbox()
        bpc = coordinators.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("WATBOX or BPC not found")
            return

        client = coordinators.user._client
        await client.set_bpc_manual(
            watbox, bpc,
            index=self._bpc_index,
            action="off",
        )
        # Mise à jour optimiste immédiate : l'UI bascule à Off.
        self._optimistic_is_on = False
        self.async_write_ha_state()

    def _get_configured_duration_hours(self) -> float:
        """Lit la durée configurée depuis l'entité number associée.

        Cherche dans les états HA l'entité number dont l'entity_id contient
        le suffixe `electrolyzer_duration` (les entity_ids ne portent pas le
        domaine de l'intégration, on ne peut donc pas filtrer dessus).
        Retourne le défaut si l'entité est introuvable ou sa valeur invalide.
        """
        suffix = "electrolyzer_duration"
        for state in self.hass.states.async_all("number"):
            if state.entity_id.startswith("number.") and suffix in state.entity_id:
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return float(DEFAULT_DURATION_LIGHT_HOURS)
