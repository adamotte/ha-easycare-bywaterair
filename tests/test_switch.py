"""Tests de la plateforme switch (électrolyseur, voie BPC index 2 — issue #13)."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.easycare_bywaterair.api.models import BPCInput
from custom_components.easycare_bywaterair.const import (
    AUXILIARY_ELECTROLYZER,
    AUXILIARY_ESCALIGHT,
    BPC_INDEX_ESCALIGHT,
    CONF_AUXILIARY_TYPE,
    DEFAULT_DURATION_LIGHT_HOURS,
)
from tests.helpers import (
    PUMP_INPUT_ON,
    WATBOX_MODULE,
    get_entity_id,
    setup_integration,
)


def _bpc_module_with_inputs(n_inputs: int):
    """Retourne un BPC module avec n_inputs voies configurées."""
    from custom_components.easycare_bywaterair.api.models import Module
    from custom_components.easycare_bywaterair.const import MODULE_TYPE_BPC
    return Module(
        type=MODULE_TYPE_BPC,
        name="BPC-DDEEFF",
        id="bpc-id-002",
        serial_number="DDEEFF",
        number_of_inputs=n_inputs,
    )


def _electrolyzer_options() -> dict:
    return {CONF_AUXILIARY_TYPE: AUXILIARY_ELECTROLYZER}


async def test_switch_not_created_by_default(hass, mock_config_entry, mock_client):
    """Aucun switch électrolyseur créé sans l'option (défaut = escalight)."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    assert get_entity_id(hass, "switch", entry.entry_id, "electrolyzer") is None


async def test_switch_not_created_when_escalight_option(hass, mock_config_entry, mock_client):
    """Aucun switch créé quand la voie 2 est déclarée « escalight »."""
    entry = await setup_integration(
        hass, mock_config_entry, mock_client,
        options={CONF_AUXILIARY_TYPE: AUXILIARY_ESCALIGHT},
    )
    assert get_entity_id(hass, "switch", entry.entry_id, "electrolyzer") is None


async def test_switch_created_when_electrolyzer_option(hass, mock_config_entry, mock_client):
    """Le switch électrolyseur est créé quand l'option vaut « electrolyzer »."""
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    assert get_entity_id(hass, "switch", entry.entry_id, "electrolyzer") is not None


async def test_switch_off_when_input_off(hass, mock_config_entry, mock_client):
    """Le switch est 'off' quand la voie BPC index 2 est inactive."""
    electrolyzer_off = BPCInput(index=BPC_INDEX_ESCALIGHT, value=0)
    mock_client.get_bpc_status = AsyncMock(
        return_value=((PUMP_INPUT_ON, electrolyzer_off), 27)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    entity_id = get_entity_id(hass, "switch", entry.entry_id, "electrolyzer")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_switch_on_when_input_on(hass, mock_config_entry, mock_client):
    """Le switch est 'on' quand la voie BPC index 2 est active."""
    electrolyzer_on = BPCInput(index=BPC_INDEX_ESCALIGHT, value=1, remaining_time="04:00")
    mock_client.get_bpc_status = AsyncMock(
        return_value=((PUMP_INPUT_ON, electrolyzer_on), 27)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    entity_id = get_entity_id(hass, "switch", entry.entry_id, "electrolyzer")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


async def test_switch_turn_on_calls_bpc_manual(hass, mock_config_entry, mock_client):
    """Turn on du switch appelle set_bpc_manual avec index=2, action='on' et la durée par défaut."""
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    entity_id = get_entity_id(hass, "switch", entry.entry_id, "electrolyzer")

    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )

    mock_client.set_bpc_manual.assert_called_once()
    call_kwargs = mock_client.set_bpc_manual.call_args
    assert call_kwargs.kwargs.get("index") == BPC_INDEX_ESCALIGHT
    assert call_kwargs.kwargs.get("action") == "on"
    # Durée par défaut (alignée sur les lumières) : 1 h.
    assert call_kwargs.kwargs.get("duration_minutes") == int(
        DEFAULT_DURATION_LIGHT_HOURS * 60
    )


async def test_switch_turn_on_uses_configured_duration(hass, mock_config_entry, mock_client):
    """Turn on du switch lit la durée depuis l'entité number electrolyzer_duration."""
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    number_entity_id = get_entity_id(hass, "number", entry.entry_id, "electrolyzer_duration")
    assert number_entity_id is not None

    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_entity_id, "value": 3.0},
        blocking=True,
    )
    assert float(hass.states.get(number_entity_id).state) == 3.0

    entity_id = get_entity_id(hass, "switch", entry.entry_id, "electrolyzer")
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": entity_id}, blocking=True
    )

    call_kwargs = mock_client.set_bpc_manual.call_args
    assert call_kwargs.kwargs.get("duration_minutes") == 180


async def test_switch_turn_off_calls_bpc_manual(hass, mock_config_entry, mock_client):
    """Turn off du switch appelle set_bpc_manual avec index=2 et action='off'."""
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    entity_id = get_entity_id(hass, "switch", entry.entry_id, "electrolyzer")

    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": entity_id}, blocking=True
    )

    mock_client.set_bpc_manual.assert_called_once()
    call_kwargs = mock_client.set_bpc_manual.call_args
    assert call_kwargs.kwargs.get("index") == BPC_INDEX_ESCALIGHT
    assert call_kwargs.kwargs.get("action") == "off"


async def test_switch_not_created_when_only_1_input(hass, mock_config_entry, mock_client):
    """Pas de switch si le BPC n'a qu'une seule voie."""
    mock_client.get_modules = AsyncMock(
        return_value=(WATBOX_MODULE, _bpc_module_with_inputs(1))
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    assert get_entity_id(hass, "switch", entry.entry_id, "electrolyzer") is None


async def test_switch_not_created_when_bpc_commands_blocked(hass, mock_config_entry, mock_client):
    """Pas de switch si l'agencement des voies est inconnu (voie pompe absente — issue #10)."""
    from custom_components.easycare_bywaterair.api.models import Module
    bpc2 = Module(
        type="lr-ph", name="BPC2-D36C1B", id="bpc2", serial_number="D36C1B",
        number_of_inputs=2,
    )
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, bpc2))
    mock_client.get_bpc_status = AsyncMock(
        return_value=((BPCInput(index=1, value=0),), 27)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client,
                                    options=_electrolyzer_options())
    assert get_entity_id(hass, "switch", entry.entry_id, "electrolyzer") is None
