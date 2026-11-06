"""Tests du setup d'intégration : device info (type matériel) + repair issue BPC (issue #10)."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

from homeassistant.helpers import device_registry as dr, issue_registry as ir

from custom_components.easycare_bywaterair.api.models import BPCInput, Module, ModuleOutput
from custom_components.easycare_bywaterair.const import (
    DEVICE_ID_BPC,
    DEVICE_ID_WATBOX,
    DOMAIN,
    SERVICE_PUMP_ON,
)

from tests.helpers import WATBOX_MODULE, setup_integration


def _bpc2(n_inputs: int = 3) -> Module:
    return Module(
        type="lr-ph", name="BPC2-D36C1B", id="bpc2", serial_number="D36C1B",
        number_of_inputs=n_inputs,
    )


# ---------------------------------------------------------------------------
# hw_version = type matériel dans le device registry
# ---------------------------------------------------------------------------

async def test_device_hw_version_is_module_type(hass, mock_config_entry, mock_client):
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    dev_reg = dr.async_get(hass)
    bpc = dev_reg.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}"), entry.entry_id)
    watbox = dev_reg.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"), entry.entry_id)
    assert bpc is not None and bpc.hw_version == "lr-pc"
    assert watbox is not None and watbox.hw_version == "lr-bst-compact"


async def test_device_hw_version_shows_bpc2_type(hass, mock_config_entry, mock_client):
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, _bpc2()))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    dev_reg = dr.async_get(hass)
    bpc = dev_reg.async_get_device_by_identifier((DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}"), entry.entry_id)
    assert bpc is not None and bpc.hw_version == "lr-ph"


# ---------------------------------------------------------------------------
# Repair issue selon l'état du BPC
# ---------------------------------------------------------------------------

async def test_no_repair_issue_for_standard_bpc(hass, mock_config_entry, mock_client):
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"bpc_variant_{entry.entry_id}")
    assert issue is None


async def test_repair_issue_variant_for_bpc2(hass, mock_config_entry, mock_client):
    # BPC2/lr-ph avec voie pompe présente → issue "variante" (commandes encore actives).
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, _bpc2()))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"bpc_variant_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "bpc_unsupported_variant"


async def test_repair_issue_commands_blocked_when_pump_missing(hass, mock_config_entry, mock_client):
    # BPC2/lr-ph SANS voie pompe (index 0) → issue "commandes désactivées".
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, _bpc2()))
    mock_client.get_bpc_status = AsyncMock(return_value=((BPCInput(index=1, value=0),), 27))
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"bpc_variant_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == "bpc_commands_blocked"


# ---------------------------------------------------------------------------
# Diagnostic des voies BPC (issue #11 — support BPC2)
# ---------------------------------------------------------------------------

async def test_bpc2_diagnostic_logged_at_info(hass, mock_config_entry, mock_client, caplog):
    # BPC2/lr-ph (non standard) → log INFO exposant les voies réelles ET les clés brutes
    # (révèle l'index du phOutput et les champs pH non parsés pour un utilisateur BPC2).
    bpc2 = Module(
        type="lr-ph", name="BPC2-D36C1B", id="bpc2", serial_number="D36C1B",
        number_of_inputs=3,
        outputs=(
            ModuleOutput(index=0, name="pompe", id="o0"),
            ModuleOutput(index=4, name="phPump", id="o4"),
        ),
        raw={"type": "lr-ph", "name": "BPC2-D36C1B", "outputs": [], "pHPumpFlow": 1.5},
    )
    mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, bpc2))
    with caplog.at_level(logging.INFO, logger="custom_components.easycare_bywaterair"):
        await setup_integration(hass, mock_config_entry, mock_client)
    assert "BPC diagnostic" in caplog.text
    assert "0:'pompe'" in caplog.text and "4:'phPump'" in caplog.text
    assert "pHPumpFlow" in caplog.text  # clé brute remontée → champ pH à parser plus tard


async def test_standard_bpc_diagnostic_not_at_info(hass, mock_config_entry, mock_client, caplog):
    # BPC standard → pas de log INFO "diagnostic" (réservé aux variantes non standard).
    with caplog.at_level(logging.INFO, logger="custom_components.easycare_bywaterair"):
        await setup_integration(hass, mock_config_entry, mock_client)
    assert "BPC diagnostic" not in caplog.text


# ---------------------------------------------------------------------------
# runtime_data & unload (ISSUE-00)
# ---------------------------------------------------------------------------

async def test_setup_entry_populates_runtime_data(hass, mock_config_entry, mock_client):
    """Vérifie que runtime_data est peuplé et que hass.data n'est pas utilisé pour stocker l'état."""
    from custom_components.easycare_bywaterair.coordinator import EasyCareCoordinators

    entry = await setup_integration(hass, mock_config_entry, mock_client)
    assert hasattr(entry, "runtime_data")
    assert isinstance(entry.runtime_data, EasyCareCoordinators)
    assert entry.runtime_data.user is not None
    assert entry.runtime_data.modules is not None
    assert entry.runtime_data.bpc is not None
    assert DOMAIN not in hass.data or entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_unload_entry(hass, mock_config_entry, mock_client):
    """Vérifie le déchargement propre de l'entrée et le nettoyage de runtime_data."""
    entry = await setup_integration(hass, mock_config_entry, mock_client)
    assert hass.services.has_service(DOMAIN, SERVICE_PUMP_ON)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    assert not hasattr(entry, "runtime_data")
    assert not hass.services.has_service(DOMAIN, SERVICE_PUMP_ON)


async def test_service_pump_on_uses_runtime_data(hass, mock_config_entry, mock_client):
    """Vérifie que l'appel d'un service utilise runtime_data sans passer par hass.data."""
    await setup_integration(hass, mock_config_entry, mock_client)
    await hass.services.async_call(
        DOMAIN,
        SERVICE_PUMP_ON,
        {"duration_minutes": 30},
        blocking=True,
    )
    mock_client.set_bpc_manual.assert_called_once()


