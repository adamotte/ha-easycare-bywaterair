"""Plateforme button pour Easy-care by Waterair.

Expose un seul bouton :
  - button.easycare_bywaterair_refresh  (sur l'appareil WATBOX)

Le contrôle du boost est géré par select.easycare_bywaterair_boost.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import EasyCareCoordinators, EasyCareModulesCoordinator
from .entity import EasyCareWATBOXEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les boutons depuis un ConfigEntry."""
    coords: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([EasyCareRefreshButton(coords.modules, entry)])


# ─────────────────────────────────────────────────────────────────────────────
# Bouton refresh — sur WATBOX
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareRefreshButton(
    EasyCareWATBOXEntity[EasyCareModulesCoordinator],
    ButtonEntity,
):
    """Force un rafraîchissement immédiat de toutes les données."""

    _attr_translation_key = "refresh"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="refresh")

    async def async_press(self) -> None:
        """Refresh des 3 coordinators en parallèle."""
        import asyncio

        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        _LOGGER.info("Refresh manuel déclenché par l'utilisateur")
        await asyncio.gather(
            coords.user.async_request_refresh(),
            coords.modules.async_request_refresh(),
            coords.bpc.async_request_immediate_refresh(),
        )



