"""Plateforme sensor pour Easy-care by Waterair.

Expose tous les capteurs en lecture seule, répartis sur 4 appareils :

  Appareil AC1 (Analyseur Connecté) — coordinator USER
  ├── sensor.easycare_bywaterair_ph
  ├── sensor.easycare_bywaterair_chlorine        (Redox/ORP, en mV)
  ├── sensor.easycare_bywaterair_temperature     (eau, en °C)
  ├── sensor.easycare_bywaterair_notification    (dernière alerte)
  ├── sensor.easycare_bywaterair_treatment       (traitement en cours)
  └── sensor.easycare_bywaterair_battery_ac1

  Appareil BPC — coordinator BPC
  ├── sensor.easycare_bywaterair_pump_state
  ├── sensor.easycare_bywaterair_filtration_mode
  ├── sensor.easycare_bywaterair_pump_total_runtime
  ├── sensor.easycare_bywaterair_pump_counter_date
  ├── sensor.easycare_bywaterair_pump_daily_runtime
  └── sensor.easycare_bywaterair_boost_remaining

  Appareil LR-PR (si présent) — coordinator USER
  └── sensor.easycare_bywaterair_pressure        (pression filtration)

  Appareil WATBOX — coordinator USER
  ├── sensor.easycare_bywaterair_owner           (propriétaire compte)
  └── sensor.easycare_bywaterair_detail          (modèle piscine)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfPressure,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    BPC_INDEX_PUMP,
    DOMAIN,
    MODULE_TYPE_AC1,
    MODULE_TYPE_PRESSURE,
)
from .coordinator import (
    EasyCareBPCCoordinator,
    EasyCareCoordinators,
    EasyCareModulesCoordinator,
    EasyCareUserCoordinator,
)
from .entity import (
    EasyCareAC1Entity,
    EasyCareBPCEntity,
    EasyCarePressureEntity,
    EasyCareWATBOXEntity,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configure tous les sensors depuis un ConfigEntry."""
    coords: EasyCareCoordinators = hass.data[DOMAIN][entry.entry_id]

    sensors: list[SensorEntity] = []

    has_ac1 = bool(coords.modules.get_modules_by_type(MODULE_TYPE_AC1))
    if has_ac1:
        sensors.extend([
            EasyCarePhSensor(coords.user, entry),
            EasyCareChlorineSensor(coords.user, entry),
            EasyCareTemperatureSensor(coords.user, entry),
            EasyCareNotificationSensor(coords.user, entry),
            EasyCareTreatmentSensor(coords.user, entry),
            EasyCareAC1BatterySensor(coords.modules, entry),
        ])

    if coords.modules.get_bpc() is not None:
        sensors.extend([
            EasyCarePumpStateSensor(coords.bpc, entry),
            EasyCareFiltrationModeSensor(coords.bpc, entry),
            EasyCarePumpTotalRuntimeSensor(coords.bpc, entry),
            EasyCarePumpCounterDateSensor(coords.bpc, entry),
            EasyCarePumpDailyRuntimeSensor(coords.bpc, entry),
            EasyCareBoostRemainingSensor(coords.bpc, entry),
        ])

    if coords.modules.get_modules_by_type(MODULE_TYPE_PRESSURE):
        sensors.append(EasyCarePressureSensor(coords.user, entry))

    sensors.extend([
        EasyCareOwnerSensor(coords.user, entry),
        EasyCareDetailSensor(coords.user, entry),
    ])

    _LOGGER.debug("Création de %d sensors", len(sensors))
    async_add_entities(sensors)


class EasyCarePhSensor(EasyCareAC1Entity[EasyCareUserCoordinator], SensorEntity):
    """Mesure du pH de l'eau."""

    _attr_translation_key = "ph"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2
    _attr_icon = "mdi:ph"

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="ph")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.metrics.ph_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.metrics.ph_date
        return {"last_measured": date_val.isoformat() if date_val else None}


class EasyCareChlorineSensor(EasyCareAC1Entity[EasyCareUserCoordinator], SensorEntity):
    """Mesure du chlore (Redox/ORP en mV).

    L'AC1 mesure le potentiel redox (ORP) et non une concentration directe
    de chlore. La valeur brute en mV est exposée telle quelle.
    """

    _attr_translation_key = "chlorine"
    _attr_native_unit_of_measurement = "mV"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:flask-outline"

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="chlorine")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.metrics.chlorine_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.metrics.chlorine_date
        return {"last_measured": date_val.isoformat() if date_val else None}


class EasyCareTemperatureSensor(EasyCareAC1Entity[EasyCareUserCoordinator], SensorEntity):
    """Température de l'eau de la piscine."""

    _attr_translation_key = "temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="temperature")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.metrics.temperature_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.metrics.temperature_date
        return {"last_measured": date_val.isoformat() if date_val else None}


class EasyCareNotificationSensor(EasyCareAC1Entity[EasyCareUserCoordinator], SensorEntity):
    """Dernière notification reçue (alerte chlore, pH, etc.)."""

    _attr_translation_key = "notification"
    _attr_icon = "mdi:bell-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="notification")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.alerts.latest_action

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        latest = self.coordinator.data.alerts.latest
        if latest is None:
            return {"count": 0}
        return {
            "count": len(self.coordinator.data.alerts.notifications),
            "last_date": latest.date.isoformat() if latest.date else None,
        }


class EasyCareTreatmentSensor(EasyCareAC1Entity[EasyCareUserCoordinator], SensorEntity):
    """Traitement de l'eau en cours."""

    _attr_translation_key = "treatment"
    _attr_icon = "mdi:beaker-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="treatment")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.treatment.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.treatment.date
        return {"date": date_val.isoformat() if date_val else None}


class EasyCareAC1BatterySensor(
    EasyCareAC1Entity[EasyCareModulesCoordinator], SensorEntity
):
    """Niveau de batterie de l'analyseur AC1.

    L'API retourne la valeur sur une échelle 0-5. Ajustez BATTERY_MAX si la
    valeur affichée ne correspond pas à la réalité.
    """

    BATTERY_MAX: float = 5.0

    _attr_translation_key = "battery_ac1"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareModulesCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="battery_ac1")

    def _get_ac1(self):
        """Récupère le module AC1 ou None."""
        modules = self.coordinator.get_modules_by_type(MODULE_TYPE_AC1)
        return modules[0] if modules else None

    @property
    def native_value(self) -> int | None:
        """Niveau batterie en pourcentage."""
        ac1 = self._get_ac1()
        if ac1 is None or ac1.battery_level is None:
            return None
        raw = float(ac1.battery_level)
        if raw <= self.BATTERY_MAX:
            return int(min(100, max(0, raw / self.BATTERY_MAX * 100)))
        return int(min(100, max(0, raw)))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        ac1 = self._get_ac1()
        if ac1 is None:
            return {}
        return {
            "raw_value": ac1.battery_level,
            "scale_max": self.BATTERY_MAX,
            "serial_number": ac1.serial_number,
        }


class EasyCarePumpStateSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """État textuel de la pompe (on/off) avec temps restant en attribut."""

    _attr_translation_key = "pump_state"
    _attr_icon = "mdi:pump"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_state")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is None:
            return None
        return "on" if pump.is_on else "off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is None:
            return {}
        return {"remaining_time": pump.remaining_time}


class EasyCareFiltrationModeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Mode de filtration actuel : AUTO / CONTINUOUS / MANUAL / PROG."""

    _attr_translation_key = "filtration_mode"
    _attr_icon = "mdi:water-sync"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="filtration_mode")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.filtration_mode


class EasyCarePumpTotalRuntimeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Durée totale de fonctionnement de la pompe (format HH:MM)."""

    _attr_translation_key = "pump_total_runtime"
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_total_runtime")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None or self.coordinator.data.pool_status is None:
            return None
        return self.coordinator.data.pool_status.total_activation_time


class EasyCarePumpCounterDateSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Date de référence du compteur de la pompe."""

    _attr_translation_key = "pump_counter_date"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_counter_date")

    @property
    def native_value(self) -> date | None:
        if self.coordinator.data is None or self.coordinator.data.pool_status is None:
            return None
        dt = self.coordinator.data.pool_status.total_activation_time_reset_date
        return dt.date() if dt else None


class EasyCarePumpDailyRuntimeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Durée de fonctionnement de la pompe aujourd'hui."""

    _attr_translation_key = "pump_daily_runtime"
    _attr_icon = "mdi:timer-sand"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_daily_runtime")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None or self.coordinator.data.pool_status is None:
            return None
        return self.coordinator.data.pool_status.total_operating_time_for_today


class EasyCareBoostRemainingSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Temps restant du boost en cours (00:00 si inactif)."""

    _attr_translation_key = "boost_remaining"
    _attr_icon = "mdi:timer-play"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="boost_remaining")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        if self.coordinator.data.pool_status is None:
            pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
            return pump.remaining_time if pump else None
        return self.coordinator.data.pool_status.boost_remaining_time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None or self.coordinator.data.pool_status is None:
            return {}
        return {"boost_active": self.coordinator.data.pool_status.is_boosting}


class EasyCarePressureSensor(EasyCarePressureEntity[EasyCareUserCoordinator], SensorEntity):
    """Pression de filtration mesurée par le LR-PR."""

    _attr_translation_key = "pressure"
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_native_unit_of_measurement = UnitOfPressure.BAR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pressure")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.metrics.pressure_value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.metrics.pressure_date
        return {"last_measured": date_val.isoformat() if date_val else None}


class EasyCareOwnerSensor(EasyCareWATBOXEntity[EasyCareUserCoordinator], SensorEntity):
    """Nom du propriétaire du compte Waterair."""

    _attr_translation_key = "owner"
    _attr_icon = "mdi:account"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="owner")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.client.full_name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        c = self.coordinator.data.client
        return {
            "email": c.email,
            "address": c.full_address,
        }


class EasyCareDetailSensor(EasyCareWATBOXEntity[EasyCareUserCoordinator], SensorEntity):
    """Modèle et caractéristiques de la piscine."""

    _attr_translation_key = "detail"
    _attr_icon = "mdi:pool"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareUserCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="detail")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.pool.model

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        p = self.coordinator.data.pool
        return {
            "volume_m3": p.volume,
            "address": p.address,
            "latitude": p.latitude,
            "longitude": p.longitude,
        }
