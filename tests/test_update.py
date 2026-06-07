"""Tests de la plateforme update (firmware BPC/AC1/LR-PR)."""

from __future__ import annotations

import dataclasses
from unittest.mock import AsyncMock

from custom_components.easycare_bywaterair.api.models import Module
from custom_components.easycare_bywaterair.const import (
    MODULE_TYPE_AC1,
    MODULE_TYPE_BPC,
    MODULE_TYPE_PRESSURE,
    MODULE_TYPE_WATBOX,
)

from tests.helpers import BPC_MODULE, WATBOX_MODULE, get_entity_id, setup_integration


def _bpc_with_version(version: str, firmware_available: dict | None = None) -> Module:
    return dataclasses.replace(
        BPC_MODULE,
        software_version=version,
        firmware_available=firmware_available or {},
    )


async def test_update_bpc_firmware_created(hass, mock_config_entry, mock_client):
    """L'entité firmware BPC est créée quand le BPC est présent."""
    mock_client.get_modules = AsyncMock(
        return_value=(
            dataclasses.replace(WATBOX_MODULE, software_version="1.0.0"),
            _bpc_with_version("1.2.3"),
        )
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "update", entry.entry_id, "bpc_firmware_update")
    assert entity_id is not None


async def test_update_bpc_no_update_available(hass, mock_config_entry, mock_client):
    """L'état est 'off' quand aucune mise à jour n'est disponible."""
    mock_client.get_firmware_update = AsyncMock(return_value={})
    mock_client.get_modules = AsyncMock(
        return_value=(
            WATBOX_MODULE,
            _bpc_with_version("1.2.3", firmware_available={}),
        )
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "update", entry.entry_id, "bpc_firmware_update")
    state = hass.states.get(entity_id)
    assert state is not None
    # Pas de mise à jour → état "off"
    assert state.state == "off"


async def test_update_bpc_update_available(hass, mock_config_entry, mock_client):
    """L'état est 'on' quand une mise à jour firmware est disponible."""
    # _parse_device_version attend un dict {major, minor, patch}, pas une string
    fw_data = {"availableUpdateVersion": {"major": 2, "minor": 0, "patch": 0}}
    mock_client.get_firmware_update = AsyncMock(return_value=fw_data)
    # Un seul BPC avec software_version — pas de doublon sinon get_bpc() prend le mauvais
    mock_client.get_modules = AsyncMock(
        return_value=(WATBOX_MODULE, _bpc_with_version("1.2.3", firmware_available=fw_data))
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "update", entry.entry_id, "bpc_firmware_update")
    state = hass.states.get(entity_id)
    assert state is not None
    # Mise à jour disponible : 2.0.0 != 1.2.3 → état "on"
    assert state.state == "on"


async def test_update_ac1_firmware_not_created_when_absent(hass, mock_config_entry, mock_client):
    """L'entité firmware AC1 n'est PAS créée si le module AC1 est absent."""
    # Surcharger get_modules pour exclure l'AC1 (présent par défaut dans le mock)
    from tests.helpers import LRPR_MODULE
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, BPC_MODULE, LRPR_MODULE))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "update", entry.entry_id, "ac1_firmware_update")
    assert entity_id is None


async def test_update_ac1_firmware_created_when_present(hass, mock_config_entry, mock_client):
    """L'entité firmware AC1 est créée si le module AC1 est présent."""
    ac1 = Module(
        type=MODULE_TYPE_AC1,
        name="AC1-XXYYZZ",
        id="ac1-id",
        serial_number="XXYYZZ",
        software_version="3.1.0",
    )
    mock_client.get_modules = AsyncMock(
        return_value=(WATBOX_MODULE, BPC_MODULE, ac1)
    )
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    entity_id = get_entity_id(hass, "update", entry.entry_id, "ac1_firmware_update")
    assert entity_id is not None
