"""Tests de la plateforme binary_sensor."""

from __future__ import annotations

from tests.helpers import get_entity_id, setup_integration


async def test_binary_sensor_connection_on(hass, mock_config_entry, mock_client):
    """Connection est 'on' quand le dernier refresh modules a réussi."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "binary_sensor", entry.entry_id, "connection")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "on"


async def test_binary_sensor_connection_created(hass, mock_config_entry, mock_client):
    """L'entité connection est toujours créée (non optionnelle)."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "binary_sensor", entry.entry_id, "connection")
    assert entity_id is not None
