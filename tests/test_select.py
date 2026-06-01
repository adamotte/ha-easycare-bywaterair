"""Tests de la plateforme select (mode filtration + boost)."""

from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from tests.helpers import get_entity_id, setup_integration


async def test_select_filtration_mode_current_option_auto(hass, mock_config_entry, mock_client):
    """current_option est 'auto' quand le mode BPC est AUTO sans offset."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "filtration_mode_select")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "auto"


async def test_select_filtration_mode_options_present(hass, mock_config_entry, mock_client):
    """Toutes les options de filtration sont disponibles."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "filtration_mode_select")
    state = hass.states.get(entity_id)
    assert state is not None
    options = state.attributes.get("options", [])
    assert "auto" in options
    assert "auto_minus_2h" in options
    assert "auto_plus_2h" in options
    assert "continuous" in options
    assert "manual" in options


async def test_select_filtration_mode_calls_client(hass, mock_config_entry, mock_client):
    """Sélectionner 'continuous' appelle set_filtration_mode_with_offset."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "filtration_mode_select")

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "continuous"},
        blocking=True,
    )

    mock_client.set_filtration_mode_with_offset.assert_called_once_with("CONTINUOUS")


async def test_select_boost_current_option_off(hass, mock_config_entry, mock_client):
    """Boost est 'off' quand pas de boost actif."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "boost_select")
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == "off"


async def test_select_boost_start_calls_client(hass, mock_config_entry, mock_client):
    """Sélectionner 'boost_4h' appelle start_boost avec BOOST4H."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "boost_select")

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "boost_4h"},
        blocking=True,
    )

    mock_client.start_boost.assert_called_once_with("BOOST4H")


async def test_select_boost_cancel_calls_client(hass, mock_config_entry, mock_client):
    """Sélectionner 'off' appelle cancel_boost."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "select", entry.entry_id, "boost_select")

    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": "off"},
        blocking=True,
    )

    mock_client.cancel_boost.assert_called_once()
