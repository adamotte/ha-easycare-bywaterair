"""Tests de la plateforme sensor."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.easycare_bywaterair.api.models import (
    Alerts,
    BPCInput,
    Metrics,
    Notification,
    PoolStatus,
)
from custom_components.easycare_bywaterair.coordinator import BPCData, UserData

from tests.helpers import (
    AC1_MODULE,
    BPC_MODULE,
    FAKE_ALERTS,
    FAKE_CLIENT,
    FAKE_METRICS,
    FAKE_POOL,
    FAKE_POOL_STATUS,
    FAKE_TREATMENT,
    FILTER_SCHEDULE_AUTO,
    PUMP_INPUT_BOOSTING,
    PUMP_INPUT_OFF,
    PUMP_INPUT_ON,
    WATBOX_MODULE,
    get_entity_id,
    setup_integration,
)


# ---------------------------------------------------------------------------
# Capteurs USER coordinator (AC1 / WATBOX)
# ---------------------------------------------------------------------------

async def test_sensor_ph_nominal(hass, mock_config_entry, mock_client):
    """pH retourne la valeur correcte depuis les métriques."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "ph")
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(7.4)


async def test_sensor_ph_unavailable_when_none(hass, mock_config_entry, mock_client):
    """pH est unknown/unavailable si ph_value est None."""
    null_metrics = Metrics()
    mock_client.get_user = AsyncMock(
        return_value=(FAKE_CLIENT, FAKE_POOL, null_metrics, FAKE_ALERTS, FAKE_TREATMENT)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "ph")
    state = hass.states.get(entity_id)
    assert state is not None
    # HA retourne "unknown" (pas "unavailable") quand native_value is None sur un SensorEntity
    assert state.state in ("unknown", "unavailable")


async def test_sensor_chlorine_nominal(hass, mock_config_entry, mock_client):
    """Chlore retourne la valeur correcte."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "chlorine")
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(650.0)


async def test_sensor_temperature_nominal(hass, mock_config_entry, mock_client):
    """Température retourne la valeur correcte."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "temperature")
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(25.0)


async def test_sensor_notification_maps_action(hass, mock_config_entry, mock_client):
    """Notification retourne la clé snake_case correspondant à l'action."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "notification")
    state = hass.states.get(entity_id)
    assert state is not None
    # batteryLow → "battery_low" (via _NOTIFICATION_ACTION_TO_KEY)
    assert state.state == "battery_low"


async def test_sensor_notification_none_when_no_alerts(hass, mock_config_entry, mock_client):
    """Notification est None si aucune alerte."""
    mock_client.get_user = AsyncMock(
        return_value=(FAKE_CLIENT, FAKE_POOL, FAKE_METRICS, Alerts(), FAKE_TREATMENT)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "notification")
    state = hass.states.get(entity_id)
    assert state is not None
    # Aucune alerte → latest_action = "None" → mappé sur la clé "none" via _NOTIFICATION_ACTION_TO_KEY
    assert state.state == "none"


async def test_sensor_treatment_value(hass, mock_config_entry, mock_client):
    """Treatment retourne la valeur du protocole."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "treatment")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "None"


async def test_sensor_owner_full_name(hass, mock_config_entry, mock_client):
    """Owner retourne le nom complet du propriétaire."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "owner")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Jean Testeur"


async def test_sensor_pool_detail_model(hass, mock_config_entry, mock_client):
    """Detail retourne le modèle de la piscine."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "detail")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "Waterair Celebris 440"


# ---------------------------------------------------------------------------
# Capteurs BPC coordinator
# ---------------------------------------------------------------------------

async def test_sensor_pump_state_on(hass, mock_config_entry, mock_client):
    """Pump state est 'on' quand la pompe est active."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "pump_state")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


async def test_sensor_pump_state_off(hass, mock_config_entry, mock_client):
    """Pump state est 'off' quand la pompe est inactive."""
    mock_client.get_bpc_status = AsyncMock(return_value=((PUMP_INPUT_OFF,), 27))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "pump_state")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_sensor_filtration_mode_auto(hass, mock_config_entry, mock_client):
    """Filtration mode en AUTO sans offset → 'auto'."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "filtration_mode")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "auto"


async def test_sensor_boost_remaining_inactive(hass, mock_config_entry, mock_client):
    """Boost remaining affiche '00:00' quand pas de boost."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "boost_remaining")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "00:00"


async def test_sensor_boost_remaining_active(hass, mock_config_entry, mock_client):
    """Boost remaining affiche le temps restant quand boost actif."""
    mock_client.get_bpc_status = AsyncMock(return_value=((PUMP_INPUT_BOOSTING,), 27))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "boost_remaining")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "02:00"


async def test_sensor_filtration_daily_duration(hass, mock_config_entry, mock_client):
    """Filtration daily duration retourne une valeur calculée depuis le schedule."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "filtration_daily_duration")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state not in ("unavailable", "unknown")
    assert float(state.state) > 0


# ---------------------------------------------------------------------------
# Capteurs MODULES coordinator (optionnels)
# ---------------------------------------------------------------------------

async def test_sensor_ac1_battery_created_when_module_present(hass, mock_config_entry, mock_client):
    """Battery AC1 est créée quand le module AC1 est présent (inclus dans le mock par défaut)."""
    # AC1_MODULE est inclus par défaut dans make_mock_client(), battery_level=3
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    # unique_id_suffix correct : "battery_ac1" (pas "ac1_battery")
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "battery_ac1")
    state = hass.states.get(entity_id)
    assert state is not None
    # 3 / 5.0 * 100 = 60 %
    assert int(state.state) == 60


async def test_sensor_ac1_battery_not_created_when_absent(hass, mock_config_entry, mock_client):
    """Battery AC1 n'est PAS créée si le module AC1 est absent."""
    from tests.helpers import LRPR_MODULE
    # On surcharge get_modules pour retirer l'AC1 (LR-PR reste présent)
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, BPC_MODULE, LRPR_MODULE))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "sensor", entry.entry_id, "battery_ac1")
    assert entity_id is None
