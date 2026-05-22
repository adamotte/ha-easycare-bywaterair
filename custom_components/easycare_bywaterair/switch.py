"""Plateforme switch pour Easy-care by Waterair.

Expose le switch de la pompe de filtration :
  - switch.easycare_bywaterair_pump

Permet le contrôle ON/OFF immédiat de la pompe via l'API BPC manual,
comme le bouton 'ON'/'OFF' dans l'app Waterair.

L'état est lu depuis le coordinator BPC :
  - bpc_inputs[0] = voie pompe
  - is_on = (remaining_time != "00:00")

Pour des modes plus avancés (AUTO, PROG), utilisez select.easycare_bywaterair_filtration_mode.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BPC_INDEX_PUMP,
    DEFAULT_DURATION_PUMP_HOURS,
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
    """Configure le switch pompe si un BPC est présent."""
    coords: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    if coords.modules.get_bpc() is None:
        _LOGGER.debug("Pas de BPC — switch pompe non créé")
        return
    async_add_entities([EasyCarePumpSwitch(coords.bpc, entry)])


class EasyCarePumpSwitch(
    EasyCareBPCEntity[EasyCareBPCCoordinator],
    SwitchEntity,
):
    """Switch de la pompe de filtration."""

    _attr_translation_key = "pump"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump")

    @property
    def is_on(self) -> bool | None:
        """Vrai si la pompe est active (temps restant > 00:00)."""
        if self.coordinator.data is None:
            return None
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        return pump.is_on if pump else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributs : temps restant + mode filtration courant."""
        attrs: dict[str, Any] = {}
        if self.coordinator.data is None:
            return attrs
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is not None:
            attrs["remaining_time"] = pump.remaining_time
        if self.coordinator.data.pool_status is not None:
            attrs["mode"] = self.coordinator.data.pool_status.mode
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Démarre la pompe pour la durée par défaut."""
        await self._send_command("on", duration_minutes=DEFAULT_DURATION_PUMP_HOURS * 60)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Arrête la pompe immédiatement."""
        await self._send_command("off")

    async def _send_command(self, action: str, duration_minutes: int = 60) -> None:
        """Envoie la commande BPC manual et force un refresh."""
        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        watbox = coords.modules.get_watbox()
        bpc = coords.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("Pompe : WATBOX ou BPC introuvable")
            return

        client = coords.user._client  # noqa: SLF001 — accès interne légitime
        _LOGGER.info("Pompe : commande %s (durée=%dm)", action.upper(), duration_minutes)

        await client.set_bpc_manual(
            watbox, bpc,
            index=BPC_INDEX_PUMP,
            action=action,
            duration_minutes=duration_minutes,
        )
        await self.coordinator.async_request_immediate_refresh()
