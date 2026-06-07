"""Tests de la plateforme light (spot + escalight)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.easycare_bywaterair.api.models import BPCInput
from custom_components.easycare_bywaterair.const import BPC_INDEX_ESCALIGHT, BPC_INDEX_SPOT

from tests.helpers import (
    BPC_MODULE,
    PUMP_INPUT_OFF,
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


async def test_light_spot_is_off_when_input_off(hass, mock_config_entry, mock_client):
    """Spot est 'off' quand la voie BPC index 1 est inactive."""
    spot_off = BPCInput(index=BPC_INDEX_SPOT, value=0)
    mock_client.get_bpc_status = AsyncMock(
        return_value=((PUMP_INPUT_ON, spot_off), 27)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "spot")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_light_spot_is_on_when_input_on(hass, mock_config_entry, mock_client):
    """Spot est 'on' quand la voie BPC index 1 est active."""
    spot_on = BPCInput(index=BPC_INDEX_SPOT, value=1, remaining_time="01:00")
    mock_client.get_bpc_status = AsyncMock(
        return_value=((PUMP_INPUT_ON, spot_on), 27)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "spot")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


async def test_light_spot_turn_on_calls_bpc_manual(hass, mock_config_entry, mock_client):
    """Turn on du spot appelle set_bpc_manual avec index=1 et action='on'."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "spot")

    await hass.services.async_call(
        "light", "turn_on", {"entity_id": entity_id}, blocking=True
    )

    mock_client.set_bpc_manual.assert_called_once()
    call_kwargs = mock_client.set_bpc_manual.call_args
    assert call_kwargs.kwargs.get("index") == BPC_INDEX_SPOT
    assert call_kwargs.kwargs.get("action") == "on"


async def test_light_spot_turn_off_calls_bpc_manual(hass, mock_config_entry, mock_client):
    """Turn off du spot appelle set_bpc_manual avec index=1 et action='off'."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "spot")

    await hass.services.async_call(
        "light", "turn_off", {"entity_id": entity_id}, blocking=True
    )

    mock_client.set_bpc_manual.assert_called_once()
    call_kwargs = mock_client.set_bpc_manual.call_args
    assert call_kwargs.kwargs.get("index") == BPC_INDEX_SPOT
    assert call_kwargs.kwargs.get("action") == "off"


async def test_light_escalight_not_created_when_only_1_input(hass, mock_config_entry, mock_client):
    """Escalight n'est PAS créé si le BPC n'a qu'une seule voie (spot seulement)."""
    mock_client.get_modules = AsyncMock(
        return_value=(WATBOX_MODULE, _bpc_module_with_inputs(1))
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "escalight")
    assert entity_id is None


async def test_light_escalight_created_when_2_inputs(hass, mock_config_entry, mock_client):
    """Escalight est créé si le BPC a 2 voies ou plus."""
    mock_client.get_modules = AsyncMock(
        return_value=(WATBOX_MODULE, _bpc_module_with_inputs(2))
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "light", entry.entry_id, "escalight")
    assert entity_id is not None
