"""Plateforme number pour Easy-care by Waterair.

Expose les durées configurables des voies lumineuses BPC :
  - number.easycare_bywaterair_spot_duration       : durée du spot en heures
  - number.easycare_bywaterair_escalight_duration  : durée de l'escalight en heures

Ces valeurs sont purement locales (non envoyées au serveur) et lues par les
entités light lors du `light.turn_on`. La persistance entre redémarrages HA
est assurée par RestoreEntity. Plage : 1 à 24 heures, par pas de 0.5h.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DEFAULT_DURATION_LIGHT_HOURS, DOMAIN
from .coordinator import EasyCareCoordinators, EasyCareModulesCoordinator
from .entity import EasyCareBPCEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure les entités number depuis un ConfigEntry."""
    coordinators: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]
    bpc = coordinators.modules.get_bpc()

    entities: list[NumberEntity] = []
    if bpc is None:
        async_add_entities(entities)
        return

    n = bpc.number_of_inputs
    if n >= 1:
        entities.append(EasyCareSpotDurationNumber(coordinators.modules, entry))
    if n >= 2:
        entities.append(EasyCareEscalightDurationNumber(coordinators.modules, entry))

    async_add_entities(entities)


class EasyCareDurationNumberBase(
    EasyCareBPCEntity[EasyCareModulesCoordinator],
    NumberEntity,
    RestoreEntity,
):
    """Base pour une entité number mémorisant une durée locale.

    Hérite de RestoreEntity pour restaurer la valeur après redémarrage HA.
    """

    _attr_native_min_value = 1.0
    _attr_native_max_value = 24.0
    _attr_native_step = 0.5
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:timer-outline"

    def __init__(
        self,
        coordinator: EasyCareModulesCoordinator,
        entry: ConfigEntry,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_native_value = float(DEFAULT_DURATION_LIGHT_HOURS)

    async def async_added_to_hass(self) -> None:
        """Restaure la dernière valeur connue après un redémarrage HA."""
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (
            None, "", "unknown", "unavailable",
        ):
            try:
                self._attr_native_value = float(last_state.state)
                _LOGGER.debug("%s : durée restaurée à %.1fh", self.unique_id, self._attr_native_value)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Impossible de restaurer la durée %s (valeur=%r), utilisation du défaut",
                    self.unique_id, last_state.state,
                )

    async def async_set_native_value(self, value: float) -> None:
        """Sauvegarde la nouvelle valeur."""
        self._attr_native_value = float(value)
        self.async_write_ha_state()
        _LOGGER.debug("%s : nouvelle durée %.1fh", self.unique_id, value)


class EasyCareSpotDurationNumber(EasyCareDurationNumberBase):
    """Durée d'allumage par défaut du projecteur principal."""

    _attr_translation_key = "spot_duration"

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="spot_duration")


class EasyCareEscalightDurationNumber(EasyCareDurationNumberBase):
    """Durée d'allumage par défaut de l'éclairage des marches."""

    _attr_translation_key = "escalight_duration"

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="escalight_duration")
