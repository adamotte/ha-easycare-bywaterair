"""Plateforme light pour Easy-care by Waterair.

Expose les voies lumineuses du BPC :
  - light.easycare_bywaterair_spot      → projecteur principal (voie BPC index 1)
  - light.easycare_bywaterair_escalight → éclairage des marches (voie BPC index 2)

Les lumières ne supportent que ON/OFF (pas de variation, pas de couleur).
La durée par défaut est lue depuis l'entité `number.easycare_bywaterair_*_duration`
correspondante (entités créées par number.py).

L'état (ON/OFF + temps restant) est lu depuis le coordinator BPC :
  - bpc_inputs[1] pour le spot
  - bpc_inputs[2] pour l'escalight

Le temps restant est exposé comme attribut supplémentaire pour information.
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

    On crée le spot uniquement si le BPC a au moins 2 voies (input 0 = pompe, 1 = spot).
    On crée l'escalight uniquement si le BPC a au moins 3 voies (input 2 = escalight).
    """
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    bpc = coordinators.modules.get_bpc()

    entities: list[LightEntity] = []

    if bpc is None:
        _LOGGER.debug("Pas de BPC détecté — aucune lumière créée")
        async_add_entities(entities)
        return

    # number_of_inputs indique combien de voies physiques sont câblées.
    # Convention : index 0 = pompe (toujours présente), 1 = spot, 2 = escalight.
    # La pompe ne compte pas comme une lumière, donc :
    #   numberOfInputs >= 1 → spot disponible (la pompe + 1 lumière)
    #   numberOfInputs >= 2 → escalight disponible (pompe + 2 lumières)
    # En pratique on regarde le nombre d'inputs réels au-delà de la pompe.
    n = bpc.number_of_inputs

    if n >= 1:
        entities.append(EasyCareSpotLight(coordinators.bpc, entry))
    if n >= 2:
        entities.append(EasyCareEscalightLight(coordinators.bpc, entry))

    if entities:
        _LOGGER.debug(
            "Création de %d lumière(s) BPC (numberOfInputs=%d)",
            len(entities), n,
        )

    async_add_entities(entities)


# ─────────────────────────────────────────────────────────────────────────────
# Classe de base pour les lumières BPC
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareBPCLight(EasyCareBPCEntity[EasyCareBPCCoordinator], LightEntity):
    """Classe de base pour une lumière BPC.

    Les sous-classes (spot, escalight) doivent définir :
      - `_bpc_index` : la voie du BPC à piloter (1 ou 2)
      - `_attr_translation_key` : clé pour l'i18n du nom
      - `unique_id_suffix` : pour différencier les entités HA
    """

    # Les lumières BPC ne supportent que ON/OFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    # Sera défini dans les sous-classes
    _bpc_index: int

    @property
    def is_on(self) -> bool | None:
        """Vrai si la voie BPC correspondante est active.

        Returns None si on n'a pas encore de données (premier refresh en cours).
        """
        data = self.coordinator.data
        if data is None:
            return None
        bpc_input = data.get_input(self._bpc_index)
        if bpc_input is None:
            return None
        return bpc_input.is_on

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributs additionnels : temps restant de la voie."""
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
        """Allume la lumière via la commande BPC manual.

        Récupère la durée depuis l'entité number associée, ou utilise la
        valeur par défaut (DEFAULT_DURATION_LIGHT_HOURS).
        """
        duration_hours = self._get_configured_duration_hours()
        duration_minutes = int(duration_hours * 60)

        _LOGGER.info(
            "Allumage de la voie BPC %d pour %d minutes",
            self._bpc_index, duration_minutes,
        )

        # Récupération des composants nécessaires depuis hass.data
        coordinators: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coordinators.modules.get_watbox()
        bpc = coordinators.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("WATBOX ou BPC introuvable")
            return

        # Le client est partagé via le coordinator (architecture du __init__.py)
        client = coordinators.user._client  # noqa: SLF001 — accès interne légitime
        await client.set_bpc_manual(
            watbox, bpc,
            index=self._bpc_index,
            action="on",
            duration_minutes=duration_minutes,
        )

        # Force un refresh immédiat pour voir l'état réel
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

        Les entités number sont créées par number.py avec les unique_id :
          - {entry_id}_spot_duration
          - {entry_id}_escalight_duration

        Si l'entité n'existe pas ou n'a pas de valeur, on retourne le défaut.
        """
        suffix = "spot_duration" if self._bpc_index == BPC_INDEX_SPOT else "escalight_duration"
        entity_id_pattern = f"number.{DOMAIN}_{suffix}"

        # On parcourt les states HA pour trouver l'entité avec le bon unique_id
        # NB : entity_id réel peut différer si l'utilisateur l'a renommé,
        # donc on ne peut pas le hardcoder. On se fie au unique_id qui est stable.
        for state in self.hass.states.async_all("number"):
            if (
                state.entity_id.startswith(f"number.")
                and suffix in state.entity_id
                and DOMAIN in state.entity_id
            ):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass

        return float(DEFAULT_DURATION_LIGHT_HOURS)


# ─────────────────────────────────────────────────────────────────────────────
# Sous-classes — Spot et Escalight
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareSpotLight(EasyCareBPCLight):
    """Projecteur principal de la piscine (voie BPC 1)."""

    _bpc_index = BPC_INDEX_SPOT
    _attr_translation_key = "spot"
    _attr_icon = "mdi:lightbulb"

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="spot")


class EasyCareEscalightLight(EasyCareBPCLight):
    """Éclairage des marches de la piscine (voie BPC 2)."""

    _bpc_index = BPC_INDEX_ESCALIGHT
    _attr_translation_key = "escalight"
    _attr_icon = "mdi:stairs"

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="escalight")
