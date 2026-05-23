"""Plateforme light pour Easy-care by Waterair.

Expose les voies lumineuses du BPC :
  - light.easycare_bywaterair_spot      → projecteur principal (voie BPC index 1)
  - light.easycare_bywaterair_escalight → éclairage des marches (voie BPC index 2)

Les lumières ne supportent que ON/OFF. La durée par défaut est lue depuis
l'entité number associée (number.py).
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BPC_INDEX_ESCALIGHT,
    BPC_INDEX_SPOT,
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
    """Configure les lumières BPC depuis un ConfigEntry.

    Le spot est créé si le BPC a au moins 1 voie lumineuse (index 1).
    L'escalight est créé si le BPC a au moins 2 voies lumineuses (index 2).
    """
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    bpc = coordinators.modules.get_bpc()

    entities: list[LightEntity] = []

    if bpc is None:
        _LOGGER.debug("Pas de BPC détecté — aucune lumière créée")
        async_add_entities(entities)
        return

    n = bpc.number_of_inputs
    if n >= 1:
        entities.append(EasyCareSpotLight(coordinators.bpc, entry))
    if n >= 2:
        entities.append(EasyCareEscalightLight(coordinators.bpc, entry))

    if entities:
        _LOGGER.debug("Création de %d lumière(s) BPC (numberOfInputs=%d)", len(entities), n)

    async_add_entities(entities)


class EasyCareBPCLight(EasyCareBPCEntity[EasyCareBPCCoordinator], LightEntity):
    """Classe de base pour une lumière BPC.

    Les sous-classes doivent définir `_bpc_index` (voie 1 ou 2),
    `_attr_translation_key` et passer `unique_id_suffix` au constructeur.
    """

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    _bpc_index: int

    @property
    def is_on(self) -> bool | None:
        """Vrai si la voie BPC correspondante est active."""
        data = self.coordinator.data
        if data is None:
            return None
        bpc_input = data.get_input(self._bpc_index)
        if bpc_input is None:
            return None
        return bpc_input.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Temps restant de la voie en attribut."""
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
        """Allume la lumière via la commande BPC manual."""
        duration_hours = self._get_configured_duration_hours()
        duration_minutes = int(duration_hours * 60)

        _LOGGER.info("Allumage de la voie BPC %d pour %d minutes", self._bpc_index, duration_minutes)

        coordinators: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coordinators.modules.get_watbox()
        bpc = coordinators.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("WATBOX ou BPC introuvable")
            return

        client = coordinators.user._client  # noqa: SLF001
        await client.set_bpc_manual(
            watbox, bpc,
            index=self._bpc_index,
            action="on",
            duration_minutes=duration_minutes,
        )
        await self.coordinator.async_request_immediate_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Éteint la lumière via la commande BPC manual."""
        _LOGGER.info("Extinction de la voie BPC %d", self._bpc_index)

        coordinators: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coordinators.modules.get_watbox()
        bpc = coordinators.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("WATBOX ou BPC introuvable")
            return

        client = coordinators.user._client  # noqa: SLF001
        await client.set_bpc_manual(
            watbox, bpc,
            index=self._bpc_index,
            action="off",
        )
        await self.coordinator.async_request_immediate_refresh()

    def _get_configured_duration_hours(self) -> float:
        """Lit la durée configurée depuis l'entité number associée.

        Cherche dans les états HA l'entité number dont l'entity_id contient
        le suffixe (spot_duration ou escalight_duration). Retourne le défaut
        si l'entité est introuvable ou sa valeur invalide.
        """
        suffix = "spot_duration" if self._bpc_index == BPC_INDEX_SPOT else "escalight_duration"
        for state in self.hass.states.async_all("number"):
            if (
                state.entity_id.startswith("number.")
                and suffix in state.entity_id
                and DOMAIN in state.entity_id
            ):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return float(DEFAULT_DURATION_LIGHT_HOURS)


class EasyCareSpotLight(EasyCareBPCLight):
    """Projecteur principal de la piscine (voie BPC 1)."""

    _bpc_index = BPC_INDEX_SPOT
    _attr_translation_key = "spot"
    _attr_icon = "mdi:lightbulb"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="spot")


class EasyCareEscalightLight(EasyCareBPCLight):
    """Éclairage des marches de la piscine (voie BPC 2)."""

    _bpc_index = BPC_INDEX_ESCALIGHT
    _attr_translation_key = "escalight"
    _attr_icon = "mdi:stairs"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="escalight")
