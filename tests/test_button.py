"""Tests de la plateforme button (refresh)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from tests.helpers import get_entity_id, setup_integration


async def test_button_refresh_created(hass, mock_config_entry, mock_client):
    """Le bouton refresh est toujours créé."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "button", entry.entry_id, "refresh")
    assert entity_id is not None


async def test_button_refresh_press_triggers_all_coordinators(hass, mock_config_entry, mock_client):
    """Appuyer sur refresh déclenche le rafraîchissement de tous les coordinators."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "button", entry.entry_id, "refresh")

    from custom_components.easycare_bywaterair.const import DOMAIN
    coords = hass.data[DOMAIN][entry.entry_id]

    with patch.object(coords.user, "async_request_refresh", new_callable=AsyncMock) as mock_user_refresh, \
         patch.object(coords.modules, "async_request_refresh", new_callable=AsyncMock) as mock_modules_refresh, \
         patch.object(coords.bpc, "async_request_immediate_refresh", new_callable=AsyncMock) as mock_bpc_refresh:

        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    mock_user_refresh.assert_called_once()
    mock_modules_refresh.assert_called_once()
    mock_bpc_refresh.assert_called_once()
