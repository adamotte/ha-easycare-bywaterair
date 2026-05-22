"""Plateforme button pour Easy-care by Waterair.

Expose 4 boutons d'action :
  - button.easycare_bywaterair_refresh        (sur l'appareil WATBOX)
  - button.easycare_bywaterair_boost_12h      (sur l'appareil BPC) NOUVEAU
  - button.easycare_bywaterair_boost_24h      (sur l'appareil BPC) NOUVEAU
  - button.easycare_bywaterair_cancel_boost   (sur l'appareil BPC) NOUVEAU

Les boutons boost permettent de lancer un boost de filtration prédéfini
(12h ou 24h) sans passer par les services HA — pratique pour un accès
rapide depuis l'UI Lovelace.
"""

from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BOOST_CANCEL,
    BOOST_MODE_4H,
    BOOST_MODE_12H,
    BOOST_MODE_24H,
    BOOST_MODE_36H,
    BOOST_MODE_48H,
    BOOST_MODE_72H,
    DOMAIN,
)
from .coordinator import (
    EasyCareBPCCoordinator,
    EasyCareCoordinators,
    EasyCareModulesCoordinator,
)
from .entity import EasyCareBPCEntity, EasyCareWATBOXEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les boutons depuis un ConfigEntry."""
    coords: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]

    buttons: list[ButtonEntity] = [
        EasyCareRefreshButton(coords.modules, entry),
    ]

    # Boutons boost uniquement si BPC présent
    if coords.modules.get_bpc() is not None:
        buttons.extend([
            EasyCareBoost4hButton(coords.bpc, entry),
            EasyCareBoost12hButton(coords.bpc, entry),
            EasyCareBoost24hButton(coords.bpc, entry),
            EasyCareBoost36hButton(coords.bpc, entry),
            EasyCareBoost48hButton(coords.bpc, entry),
            EasyCareBoost72hButton(coords.bpc, entry),
            EasyCareCancelBoostButton(coords.bpc, entry),
        ])

    async_add_entities(buttons)


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


# ─────────────────────────────────────────────────────────────────────────────
# Boutons boost — sur BPC
# ─────────────────────────────────────────────────────────────────────────────


class _BoostButtonBase(EasyCareBPCEntity[EasyCareBPCCoordinator], ButtonEntity):
    """Base pour les boutons de boost.

    Les sous-classes définissent le mode boost à envoyer
    (BOOST12H, BOOST24H, CANCELCURRENTBOOST).
    """

    _boost_mode: str  # à définir dans les sous-classes

    async def async_press(self) -> None:
        """Envoie la commande boost via le client API."""
        coords: EasyCareCoordinators = self.hass.data[DOMAIN][self._entry.entry_id]
        client = coords.user._client  # noqa: SLF001

        _LOGGER.info("Bouton boost pressé : %s", self._boost_mode)

        if self._boost_mode == BOOST_CANCEL:
            await client.cancel_boost()
        else:
            await client.start_boost(self._boost_mode)

        await self.coordinator.async_request_immediate_refresh()


class EasyCareBoost4hButton(_BoostButtonBase):
    _attr_translation_key = "boost_4h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_4H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_4h")


class EasyCareBoost12hButton(_BoostButtonBase):
    _attr_translation_key = "boost_12h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_12H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_12h")


class EasyCareBoost24hButton(_BoostButtonBase):
    _attr_translation_key = "boost_24h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_24H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_24h")


class EasyCareBoost36hButton(_BoostButtonBase):
    _attr_translation_key = "boost_36h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_36H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_36h")


class EasyCareBoost48hButton(_BoostButtonBase):
    _attr_translation_key = "boost_48h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_48H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_48h")


class EasyCareBoost72hButton(_BoostButtonBase):
    _attr_translation_key = "boost_72h"
    _attr_icon = "mdi:timer-outline"
    _boost_mode = BOOST_MODE_72H

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_72h")


class EasyCareCancelBoostButton(_BoostButtonBase):
    _attr_translation_key = "cancel_boost"
    _attr_icon = "mdi:timer-off"
    _boost_mode = BOOST_CANCEL

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="cancel_boost")
