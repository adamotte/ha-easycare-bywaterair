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
  ├── sensor.easycare_bywaterair_boost_remaining
  ├── sensor.easycare_bywaterair_spot_mode       (si voie 1 présente)
  └── sensor.easycare_bywaterair_escalight_mode  (si voie 2 présente)

  Appareil LR-PR (si présent) — coordinator USER
  └── sensor.easycare_bywaterair_pressure        (pression filtration)

  Appareil WATBOX — coordinator USER
  ├── sensor.easycare_bywaterair_owner           (propriétaire compte)
  └── sensor.easycare_bywaterair_detail          (modèle piscine)
"""

from __future__ import annotations

import logging
import math
from datetime import date, datetime
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
    UnitOfEnergy,
    UnitOfPower,
    UnitOfPressure,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    ADAPT_OFFSET_MINUS,
    ADAPT_OFFSET_PLUS,
    BPC_INDEX_PUMP,
    CONF_PUMP_POWER_W,
    DOMAIN,
    HA_MODE_AUTO,
    HA_MODE_AUTO_MINUS,
    HA_MODE_AUTO_PLUS,
    HA_MODE_OFF,
    HA_MODE_ON,
    HA_MODE_PROG,
    MODE_AUTO,
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

# Mapping valeurs brutes API → clés de traduction HA (snake_case, [a-z0-9_]+)
_NOTIFICATION_ACTION_TO_KEY: dict[str, str] = {
    "None": "none",
    "shouldBeCalibrated": "should_be_calibrated",
    "shouldBeWintered": "should_be_wintered",
    "shouldBePutBackIntoOperation": "should_be_put_back_into_operation",
    "shouldDoChlorineTreatment": "should_do_chlorine_treatment",
    "pHCanShouldBeReplaced": "ph_can_should_be_replaced",
    "pHCalibrationNecessary": "ph_calibration_necessary",
    "severalInsufficientFillings": "several_insufficient_fillings",
}


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

    bpc = coords.modules.get_bpc()
    if bpc is not None:
        sensors.extend([
            EasyCarePumpStateSensor(coords.bpc, entry),
            EasyCareFiltrationModeSensor(coords.bpc, entry),
            EasyCarePumpTotalRuntimeSensor(coords.bpc, entry),
            EasyCarePumpCounterDateSensor(coords.bpc, entry),
            EasyCareBoostRemainingSensor(coords.bpc, entry),
            EasyCareFiltrationDurationSensor(coords.bpc, coords.user, entry),
            EasyCareFiltrationNextStartSensor(coords.bpc, coords.user, entry),
            EasyCareFiltrationNextEndSensor(coords.bpc, coords.user, entry),
        ])
        pump_power_w: int = entry.options.get(CONF_PUMP_POWER_W, 0)
        if pump_power_w > 0:
            sensors.extend([
                EasyCarePumpPowerSensor(coords.bpc, entry, pump_power_w),
                EasyCarePumpEnergySensor(coords.bpc, entry, pump_power_w),
            ])
        n = bpc.number_of_inputs
        if n >= 1:
            sensors.append(EasyCareSpotModeSensor(coords.bpc, entry))
        if n >= 2:
            sensors.append(EasyCareEscalightModeSensor(coords.bpc, entry))

    pressure_modules = coords.modules.get_modules_by_type(MODULE_TYPE_PRESSURE)
    if pressure_modules:
        sensors.append(EasyCarePressureSensor(coords.user, entry, pressure_modules[0].static_pressure))

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
        raw = self.coordinator.data.alerts.latest_action
        return _NOTIFICATION_ACTION_TO_KEY.get(raw, raw)

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
    """Mode de filtration actuel — labels identiques à l'app mobile Waterair.

    AUTO-2H / AUTO / AUTO+2H / ON (marche forcée) / OFF (arrêt) / PROG
    """

    _attr_translation_key = "filtration_mode"
    _attr_icon = "mdi:water-sync"

    # Mapping API → clé HA valide
    _MODE_LABELS: dict[str, str] = {
        "CONTINUOUS": HA_MODE_ON,
        "MANUAL": HA_MODE_OFF,
        "PROG": HA_MODE_PROG,
    }

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="filtration_mode")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        mode = self.coordinator.data.filtration_mode
        if mode is None:
            return None
        if mode == MODE_AUTO:
            offset = self.coordinator.data.adapt_offset
            if offset == ADAPT_OFFSET_MINUS:
                return HA_MODE_AUTO_MINUS
            if offset == ADAPT_OFFSET_PLUS:
                return HA_MODE_AUTO_PLUS
            return HA_MODE_AUTO
        return self._MODE_LABELS.get(mode, mode.lower())


class EasyCarePumpTotalRuntimeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Durée totale de fonctionnement de la pompe depuis la date de remise à zéro.

    Source : getUserWithHisModules → BPC outputs[0].totalActivationTime (en minutes).
    Exprimée en heures dans HA.
    """

    _attr_translation_key = "pump_total_runtime"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0
    _attr_icon = "mdi:timer-outline"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_total_runtime")

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        minutes = self.coordinator.data.pump_total_activation_minutes
        if minutes is None:
            return None
        return round(minutes / 60, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        reset = self.coordinator.data.pump_activation_reset_date
        return {"counter_reset_date": reset.date().isoformat() if reset else None}


class EasyCarePumpPowerSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Puissance instantanée de la pompe (W nominaux configurés, 0 si arrêtée)."""

    _attr_translation_key = "pump_power"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry, power_w: int) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_power")
        self._power_w = power_w

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is None:
            return None
        return self._power_w if pump.is_on else 0


class EasyCarePumpEnergySensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Énergie cumulée de la pompe depuis la date de remise à zéro du compteur.

    Calculée à partir du temps total d'activation (minutes) et de la puissance
    nominale configurée. Compatible avec le dashboard énergie de HA.
    """

    _attr_translation_key = "pump_energy"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_suggested_display_precision = 3

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry, power_w: int) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_energy")
        self._power_w = power_w

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        minutes = self.coordinator.data.pump_total_activation_minutes
        if minutes is None:
            return None
        return round(minutes / 60 * self._power_w / 1000, 3)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        reset = self.coordinator.data.pump_activation_reset_date
        return {"counter_reset_date": reset.date().isoformat() if reset else None}


class EasyCarePumpCounterDateSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Date de remise à zéro du compteur de la pompe."""

    _attr_translation_key = "pump_counter_date"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pump_counter_date")

    @property
    def native_value(self) -> date | None:
        if self.coordinator.data is None:
            return None
        dt = self.coordinator.data.pump_activation_reset_date
        return dt.date() if dt else None



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
        # Source primaire : BPCInput (endpoint status BPC), seul à jour pour le boost programme
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is not None and pump.is_boosting:
            return pump.remaining_time
        # Repli : pool_status (ne reflète pas les boosts programme, mais vaut mieux que rien)
        if self.coordinator.data.pool_status is not None:
            return self.coordinator.data.pool_status.boost_remaining_time
        return "00:00"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {"boost_active": False}
        pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
        if pump is not None:
            return {"boost_active": pump.is_boosting}
        if self.coordinator.data.pool_status is not None:
            return {"boost_active": self.coordinator.data.pool_status.is_boosting}
        return {"boost_active": False}


class EasyCarePressureSensor(EasyCarePressureEntity[EasyCareUserCoordinator], SensorEntity):
    """Pression de filtration mesurée par le LR-PR.

    La valeur affichée est la différence entre la mesure brute et la pression
    statique de référence (étalonnage du capteur), arrondie au centième supérieur.
    """

    _attr_translation_key = "pressure"
    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_native_unit_of_measurement = UnitOfPressure.BAR
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 2

    def __init__(
        self,
        coordinator: EasyCareUserCoordinator,
        entry: ConfigEntry,
        static_pressure: float = 0.0,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="pressure")
        self._static_pressure = static_pressure

    @property
    def native_value(self) -> float | None:
        """Pression relative = |mesure - référence étalonnage|, arrondie au centième."""
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.metrics.pressure_value
        if raw is None:
            return None
        diff = abs(raw - self._static_pressure)
        if diff < 0.01:
            return 0.0
        return math.ceil(diff / 0.01) * 0.01

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        date_val = self.coordinator.data.metrics.pressure_date
        return {
            "last_measured": date_val.isoformat() if date_val else None,
            "static_pressure": self._static_pressure,
        }


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
        last_fetched = self.coordinator.last_fetched_at
        return {
            "volume_m3": p.volume,
            "address": p.address,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "custom_photo": p.custom_photo or None,
            "last_update": last_fetched.isoformat() if last_fetched else None,
        }


class EasyCareFiltrationDurationSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Durée de filtration journalière depuis les masques horaires BPC (sched).

    Calcul par popcount du masque 24 bits actif pour le seuil sélectionné par le BPC.
    Source primaire : BPCInput.temp_ref (index committé par le BPC au démarrage du
    cycle matinal, stable toute la journée).
    Fallback sur la température courante AC1 si temp_ref absent.
    Retourne None (unavailable) si aucune source de seuil n'est disponible.
    """

    _attr_translation_key = "filtration_daily_duration"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 1
    _attr_icon = "mdi:timer-sand"

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        user_coordinator: EasyCareUserCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="filtration_daily_duration")
        self._user_coordinator = user_coordinator

    def _get_threshold_idx_or_temp(self) -> tuple[int | None, float | None]:
        """Retourne (threshold_idx, ref_temp) pour les lookups de planning.

        Source primaire : BPCInput.temp_ref — index commité par le BPC au démarrage
        du cycle journalier (ex. 6 → 27°C → 9h–19h). Stable toute la journée.
        Fallback       : température courante de l'eau depuis l'AC1.

        L'un au moins est non-None si des données sont disponibles.
        """
        if self.coordinator.data is not None:
            pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
            if pump is not None and pump.temp_ref is not None:
                return pump.temp_ref, None
        # Fallback température (water temp AC1)
        if self._user_coordinator.data is not None:
            t = self._user_coordinator.data.metrics.temperature_value
            if t is not None:
                return None, t
        return None, None

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        schedule = self.coordinator.data.filter_schedule
        if schedule is None:
            return None
        threshold_idx, ref_temp = self._get_threshold_idx_or_temp()
        if threshold_idx is None and ref_temp is None:
            return None
        temp = ref_temp if ref_temp is not None else 0.0
        # Source primaire : masque sched (popcount) — précis à l'heure près
        hours = schedule.daily_hours_from_sched(temp, threshold_idx=threshold_idx)
        if hours is not None:
            return hours
        # Fallback : ratio dur/per depuis les règles cyclic
        rule = schedule.active_rule_for_temp(temp, threshold_idx=threshold_idx)
        return rule.daily_hours if rule is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        schedule = self.coordinator.data.filter_schedule
        if schedule is None:
            return {}
        threshold_idx, ref_temp = self._get_threshold_idx_or_temp()
        current_temp = (
            self._user_coordinator.data.metrics.temperature_value
            if self._user_coordinator.data is not None
            else None
        )

        attrs: dict[str, Any] = {
            "thresholds_c": list(schedule.thresholds),
            "bpc_temp_ref_idx": threshold_idx,
            "current_water_temp_c": current_temp,
        }

        # Résolution du seuil actif
        effective_idx = threshold_idx
        if effective_idx is None and ref_temp is not None:
            effective_idx = schedule.active_threshold_index_for_temp(ref_temp)
        attrs["active_threshold_temp_c"] = (
            schedule.thresholds[effective_idx]
            if effective_idx is not None and effective_idx < len(schedule.thresholds)
            else None
        )

        temp = ref_temp if ref_temp is not None else 0.0
        if threshold_idx is not None or ref_temp is not None:
            windows = schedule.filter_windows_from_sched(temp, threshold_idx=threshold_idx)
            if windows is not None:
                attrs["filter_windows"] = [
                    {"start_h": s, "end_h": e} for s, e in windows
                ]

        return attrs


class _FiltrationScheduleSensorBase(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Classe de base pour les sensors de planning de filtration.

    Partage la logique d'accès au FilterSchedule et au seuil BPC de référence.
    """

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        user_coordinator: EasyCareUserCoordinator,
        entry: ConfigEntry,
        *,
        unique_id_suffix: str,
    ) -> None:
        super().__init__(coordinator, entry, unique_id_suffix=unique_id_suffix)
        self._user_coordinator = user_coordinator

    def _get_threshold_idx_or_temp(self) -> tuple[int | None, float | None]:
        """Retourne (threshold_idx, ref_temp) pour les lookups de planning.

        Source primaire : BPCInput.temp_ref — index commité par le BPC au démarrage
        du cycle journalier (ex. 6 → 27°C → 9h–19h). Stable toute la journée.
        Fallback       : température courante de l'eau depuis l'AC1.

        L'un au moins est non-None si des données sont disponibles.
        """
        if self.coordinator.data is not None:
            pump = self.coordinator.data.get_input(BPC_INDEX_PUMP)
            if pump is not None and pump.temp_ref is not None:
                return pump.temp_ref, None
        # Fallback température (water temp AC1)
        if self._user_coordinator.data is not None:
            t = self._user_coordinator.data.metrics.temperature_value
            if t is not None:
                return None, t
        return None, None


class EasyCareFiltrationNextStartSensor(_FiltrationScheduleSensorBase):
    """Prochain démarrage programmé de la filtration.

    Si la pompe est actuellement en filtration, indique le démarrage de la
    prochaine plage (après la plage courante).
    Si la pompe n'est pas en filtration, indique le démarrage de la prochaine plage.
    """

    _attr_translation_key = "filtration_next_start"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-play-outline"

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        user_coordinator: EasyCareUserCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            coordinator, user_coordinator, entry,
            unique_id_suffix="filtration_next_start",
        )

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator.data is None:
            return None
        schedule = self.coordinator.data.filter_schedule
        if schedule is None:
            return None
        threshold_idx, ref_temp = self._get_threshold_idx_or_temp()
        if threshold_idx is None and ref_temp is None:
            return None
        temp = ref_temp if ref_temp is not None else 0.0
        next_start, _ = schedule.next_filtration_events(temp, dt_util.now(), threshold_idx=threshold_idx)
        return next_start


class EasyCareFiltrationNextEndSensor(_FiltrationScheduleSensorBase):
    """Prochain arrêt programmé de la filtration.

    Si la pompe est actuellement en filtration, indique la fin de la plage courante.
    Sinon, indique la fin de la prochaine plage programmée.
    """

    _attr_translation_key = "filtration_next_end"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:timer-stop-outline"

    def __init__(
        self,
        coordinator: EasyCareBPCCoordinator,
        user_coordinator: EasyCareUserCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            coordinator, user_coordinator, entry,
            unique_id_suffix="filtration_next_end",
        )

    @property
    def native_value(self) -> datetime | None:
        if self.coordinator.data is None:
            return None
        schedule = self.coordinator.data.filter_schedule
        if schedule is None:
            return None
        threshold_idx, ref_temp = self._get_threshold_idx_or_temp()
        if threshold_idx is None and ref_temp is None:
            return None
        temp = ref_temp if ref_temp is not None else 0.0
        _, next_end = schedule.next_filtration_events(temp, dt_util.now(), threshold_idx=threshold_idx)
        return next_end


def _derive_light_mode(program: dict | None) -> str | None:
    """Dérive le mode textuel d'une lumière depuis son programCharacteristics brut.

    Mapping défensif — les noms de champs sont supposés d'après le SDK Solem
    et seront ajustés si l'API retourne des noms différents.

    Returns:
        "AUTO", "MANUEL", "ETEINT", "PAUSE", ou None si program est None.
    """
    if program is None:
        return None
    pause = int(program.get("pauseDuration", 0) or 0)
    if pause > 0:
        return "PAUSE"
    mode = int(program.get("mode", -1) or -1)
    if mode == 2:
        return "AUTO"
    if mode == 1:
        return "MANUEL"
    if mode == 0:
        return "ETEINT"
    return None


def _light_mode_attributes(program: dict | None) -> dict[str, Any]:
    """Construit les attributs extra d'un capteur mode lumière."""
    if program is None:
        return {}
    pause = int(program.get("pauseDuration", 0) or 0)
    if pause > 0:
        return {"pause_days": pause}
    mode = int(program.get("mode", -1) or -1)
    if mode == 2:
        return {
            "slots": program.get("slots") or [],
            "pause_days": 0,
        }
    if mode in (0, 1):
        manual_secs = int(program.get("manualDuration", 0) or 0)
        return {"manual_duration_hours": round(manual_secs / 3600, 2)}
    return {}


class EasyCareSpotModeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Mode configuré du projecteur principal (AUTO / MANUEL / ETEINT / PAUSE)."""

    _attr_translation_key = "spot_mode"
    _attr_icon = "mdi:spotlight"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="spot_mode")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return _derive_light_mode(self.coordinator.data.spot_program)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return _light_mode_attributes(self.coordinator.data.spot_program)


class EasyCareEscalightModeSensor(EasyCareBPCEntity[EasyCareBPCCoordinator], SensorEntity):
    """Mode configuré de l'éclairage des marches (AUTO / MANUEL / ETEINT / PAUSE)."""

    _attr_translation_key = "escalight_mode"
    _attr_icon = "mdi:stairs"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: EasyCareBPCCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, unique_id_suffix="escalight_mode")

    @property
    def native_value(self) -> str | None:
        if self.coordinator.data is None:
            return None
        return _derive_light_mode(self.coordinator.data.escalight_program)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        if self.coordinator.data is None:
            return {}
        return _light_mode_attributes(self.coordinator.data.escalight_program)
