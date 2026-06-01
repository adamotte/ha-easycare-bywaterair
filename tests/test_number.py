"""Tests de la plateforme number (durée lumières)."""

from __future__ import annotations

from tests.helpers import get_entity_id, setup_integration


async def test_number_spot_duration_default_value(hass, mock_config_entry, mock_client):
    """La durée spot a une valeur par défaut valide (1–6h)."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "number", entry.entry_id, "spot_duration")
    state = hass.states.get(entity_id)
    assert state is not None
    value = float(state.state)
    assert 1.0 <= value <= 6.0


async def test_number_spot_duration_set_value(hass, mock_config_entry, mock_client):
    """Modifier la durée spot met à jour l'état local (pas d'appel API)."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "number", entry.entry_id, "spot_duration")

    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": entity_id, "value": 3.0},
        blocking=True,
    )

    state = hass.states.get(entity_id)
    assert float(state.state) == 3.0
    # Aucun appel API — stockage local uniquement
    mock_client.set_bpc_manual.assert_not_called()


async def test_number_escalight_duration_created(hass, mock_config_entry, mock_client):
    """La durée escalight est créée si le BPC a ≥ 2 voies."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "number", entry.entry_id, "escalight_duration")
    assert entity_id is not None


async def test_number_escalight_duration_range(hass, mock_config_entry, mock_client):
    """La plage escalight est bien 1–6h avec pas de 1."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "number", entry.entry_id, "escalight_duration")
    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.attributes["min"]) == 1.0
    assert float(state.attributes["max"]) == 6.0
    assert float(state.attributes["step"]) == 1.0
