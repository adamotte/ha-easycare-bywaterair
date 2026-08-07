"""Plateforme number pour Easy-care by Waterair.

Expose les durées configurables des voies BPC :
  - number.easycare_bywaterair_spot_duration       : durée du spot en heures
  - number.easycare_bywaterair_escalight_duration  : durée de l'escalight en heures
  - number.easycare_bywaterair_electrolyzer_duration : durée de l'électrolyseur en heures

Le comportement de ces entités est identique (plage 1–6 h, slider, persistance
via RestoreEntity) — seuls le libellé et l'entity_id diffèrent. Une seule classe
générique `EasyCareDurationNumber` est donc instanciée par voie.

Création conditionnelle (issue #13) : spot_duration existe dès que le BPC a au
moins 1 voie ; escalight_duration est créée si l'option `auxiliary_type` vaut
« escalight » (défaut) ; electrolyzer_duration si elle vaut « electrolyzer »,
et est lue par le switch électrolyseur.

Ces valeurs sont purement locales (non envoyées au serveur) et lues par les
entités light/switch lors du ON. La persistance entre redémarrages HA est
assurée par RestoreEntity.
"""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    AUXILIARY_DEFAULT,
    AUXILIARY_ELECTROLYZER,
    AUXILIARY_ESCALIGHT,
    CONF_AUXILIARY_TYPE,
    DEFAULT_DURATION_LIGHT_HOURS,
    DOMAIN,
)
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
        entities.append(EasyCareDurationNumber(
            coordinators.modules, entry,
            translation_key="spot_duration",
            unique_id_suffix="spot_duration",
        ))
    auxiliary_type = entry.options.get(CONF_AUXILIARY_TYPE, AUXILIARY_DEFAULT)
    if n >= 2 and auxiliary_type == AUXILIARY_ESCALIGHT:
        entities.append(EasyCareDurationNumber(
            coordinators.modules, entry,
            translation_key="escalight_duration",
            unique_id_suffix="escalight_duration",
        ))
    if n >= 2 and auxiliary_type == AUXILIARY_ELECTROLYZER:
        entities.append(EasyCareDurationNumber(
            coordinators.modules, entry,
            translation_key="electrolyzer_duration",
            unique_id_suffix="electrolyzer_duration",
        ))

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
    _attr_native_max_value = 6.0
    _attr_native_step = 1.0
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_mode = NumberMode.SLIDER
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
                _LOGGER.debug("%s: duration restored to %.1fh", self.unique_id, self._attr_native_value)
            except (ValueError, TypeError):
                _LOGGER.warning(
                    "Could not restore duration %s (value=%r), using default",
                    self.unique_id, last_state.state,
                )

    async def async_set_native_value(self, value: float) -> None:
        """Sauvegarde la nouvelle valeur."""
        self._attr_native_value = float(value)
        self.async_write_ha_state()
        _LOGGER.debug("%s: new duration %.1fh", self.unique_id, value)


class EasyCareDurationNumber(EasyCareDurationNumberBase):
    """Durée configurable d'une voie BPC.

    Classe générique : le comportement est identique quelle que soit la voie
    (plage 1–6 h, persistance RestoreEntity) — seuls le libellé (translation_key)
    et l'entity_id (unique_id_suffix) varient selon la voie : spot, escalight
    ou électrolyseur (issue #13).
    """

    def __init__(
        self,
        coordinator: EasyCareModulesCoordinator,
        entry: ConfigEntry,
        translation_key: str,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix)
        self._attr_translation_key = translation_key
