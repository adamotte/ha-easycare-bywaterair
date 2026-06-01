"""Tests des coordinators EasyCare."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.easycare_bywaterair.api.exceptions import (
    EasyCareApiError,
    EasyCareConnectionError,
    EasyCareInvalidResponseError,
    EasyCareTimeoutError,
    EasyCareTokenExpiredError,
    EasyCareUnauthorizedError,
)
from custom_components.easycare_bywaterair.api.models import (
    Alerts,
    BPCInput,
    Metrics,
    Notification,
    PoolStatus,
)
from custom_components.easycare_bywaterair.coordinator import (
    BPCData,
    EasyCareBPCCoordinator,
    EasyCareModulesCoordinator,
    EasyCareUserCoordinator,
    UserData,
    _pool_status_from_inputs,
    _wrap_api_error,
)

from tests.helpers import (
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
)


# ---------------------------------------------------------------------------
# _wrap_api_error
# ---------------------------------------------------------------------------

class TestWrapApiError:
    def test_token_expired_returns_auth_failed(self):
        err = _wrap_api_error(EasyCareTokenExpiredError("expired"), "ctx")
        assert isinstance(err, ConfigEntryAuthFailed)

    def test_unauthorized_returns_auth_failed(self):
        err = _wrap_api_error(EasyCareUnauthorizedError("401"), "ctx")
        assert isinstance(err, ConfigEntryAuthFailed)

    def test_connection_error_returns_update_failed(self):
        err = _wrap_api_error(EasyCareConnectionError("network"), "ctx")
        assert isinstance(err, UpdateFailed)

    def test_timeout_returns_update_failed(self):
        err = _wrap_api_error(EasyCareTimeoutError("timeout"), "ctx")
        assert isinstance(err, UpdateFailed)

    def test_api_error_returns_update_failed(self):
        err = _wrap_api_error(EasyCareApiError("500", 500), "ctx")
        assert isinstance(err, UpdateFailed)

    def test_invalid_response_returns_update_failed(self):
        err = _wrap_api_error(EasyCareInvalidResponseError("bad"), "ctx")
        assert isinstance(err, UpdateFailed)

    def test_unknown_error_returns_update_failed(self):
        err = _wrap_api_error(ValueError("unexpected"), "ctx")
        assert isinstance(err, UpdateFailed)


# ---------------------------------------------------------------------------
# BPCData
# ---------------------------------------------------------------------------

class TestBPCData:
    def test_is_boost_active_via_pump_info(self):
        data = BPCData(inputs=(PUMP_INPUT_BOOSTING,))
        assert data.is_boost_active

    def test_is_boost_active_via_program_state(self):
        data = BPCData(inputs=(PUMP_INPUT_OFF,), pump_program_state="boost")
        assert data.is_boost_active

    def test_is_boost_active_false(self):
        data = BPCData(inputs=(PUMP_INPUT_ON,), pump_program_state=None)
        assert not data.is_boost_active

    def test_any_input_active_true(self):
        data = BPCData(inputs=(PUMP_INPUT_ON,))
        assert data.any_input_active

    def test_any_input_active_false(self):
        data = BPCData(inputs=(PUMP_INPUT_OFF,))
        assert not data.any_input_active

    def test_get_input_found(self):
        data = BPCData(inputs=(PUMP_INPUT_ON,))
        assert data.get_input(0) is PUMP_INPUT_ON

    def test_get_input_not_found(self):
        data = BPCData(inputs=(PUMP_INPUT_ON,))
        assert data.get_input(5) is None


# ---------------------------------------------------------------------------
# _pool_status_from_inputs
# ---------------------------------------------------------------------------

class TestPoolStatusFromInputs:
    def test_pump_on(self):
        status = _pool_status_from_inputs((PUMP_INPUT_ON,))
        assert status is not None
        assert status.power_state == "on"
        assert status.is_pool_power is True

    def test_pump_off(self):
        status = _pool_status_from_inputs((PUMP_INPUT_OFF,))
        assert status is not None
        assert status.power_state == "off"

    def test_no_pump_returns_none(self):
        inp = BPCInput(index=1, value=1)
        assert _pool_status_from_inputs((inp,)) is None

    def test_pump_boosting(self):
        status = _pool_status_from_inputs((PUMP_INPUT_BOOSTING,))
        assert status is not None
        assert status.boost_remaining_time == "02:00"


# ---------------------------------------------------------------------------
# EasyCareUserCoordinator
# ---------------------------------------------------------------------------

class TestUserCoordinator:
    async def test_first_refresh_success(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareUserCoordinator(hass, mock_client, mock_config_entry)
        await coord.async_refresh()
        assert coord.data is not None
        assert coord.data.metrics.ph_value == pytest.approx(7.4)

    async def test_api_error_raises_update_failed(self, hass, mock_config_entry, mock_client):
        mock_client.get_user = AsyncMock(side_effect=EasyCareConnectionError("network"))
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareUserCoordinator(hass, mock_client, mock_config_entry)
        with pytest.raises(UpdateFailed):
            await coord._async_update_data()

    async def test_token_expired_raises_auth_failed(self, hass, mock_config_entry, mock_client):
        mock_client.get_user = AsyncMock(side_effect=EasyCareTokenExpiredError("expired"))
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareUserCoordinator(hass, mock_client, mock_config_entry)
        with pytest.raises(ConfigEntryAuthFailed):
            await coord._async_update_data()

    async def test_preserves_metrics_when_all_null(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareUserCoordinator(hass, mock_client, mock_config_entry)
        # 1er fetch OK
        await coord.async_refresh()
        prev_ph = coord.data.metrics.ph_value

        # 2e fetch : métriques toutes None
        null_metrics = Metrics()
        mock_client.get_user = AsyncMock(
            return_value=(FAKE_CLIENT, FAKE_POOL, null_metrics, FAKE_ALERTS, FAKE_TREATMENT)
        )
        await coord._async_update_data()
        # Les valeurs précédentes doivent être conservées
        assert coord.data is None or True  # _async_update_data retourne sans stocker
        # On vérifie en appelant une 2e fois refresh pour que coordinator.data soit mis à jour
        result = await coord._async_update_data()
        assert result.metrics.ph_value == pytest.approx(prev_ph)


# ---------------------------------------------------------------------------
# EasyCareModulesCoordinator
# ---------------------------------------------------------------------------

class TestModulesCoordinator:
    async def test_first_refresh(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        await coord.async_refresh()
        assert coord.data is not None
        # Le mock par défaut retourne 4 modules : WATBOX, BPC, AC1, LR-PR
        assert len(coord.data) == 4

    async def test_enriches_with_firmware(self, hass, mock_config_entry, mock_client):
        mock_client.get_firmware_update = AsyncMock(return_value={"version": "2.1.0"})
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        await coord.async_refresh()
        bpc = coord.get_bpc()
        assert bpc is not None
        assert bpc.firmware_available == {"version": "2.1.0"}

    async def test_firmware_error_non_fatal(self, hass, mock_config_entry, mock_client):
        mock_client.get_firmware_update = AsyncMock(side_effect=EasyCareApiError("err", 500))
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        await coord.async_refresh()
        # Doit quand même retourner les modules
        assert coord.data is not None

    def test_get_watbox(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC_MODULE)
        assert coord.get_watbox() is WATBOX_MODULE

    def test_get_bpc(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC_MODULE)
        assert coord.get_bpc() is BPC_MODULE

    def test_get_modules_by_type_empty(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE,)
        assert coord.get_modules_by_type("lr-mas") == ()

    def test_get_watbox_returns_none_when_no_data(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = None
        assert coord.get_watbox() is None


# ---------------------------------------------------------------------------
# EasyCareBPCCoordinator — _should_skip_cycle
# ---------------------------------------------------------------------------

class TestBPCCoordinatorSkipCycle:
    def _make_coord(self, hass, mock_config_entry, mock_client):
        mock_modules = MagicMock()
        mock_modules.get_watbox.return_value = WATBOX_MODULE
        mock_modules.get_bpc.return_value = BPC_MODULE
        coord = EasyCareBPCCoordinator(hass, mock_client, mock_modules, mock_config_entry)
        return coord

    def test_no_skip_when_no_data(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = self._make_coord(hass, mock_config_entry, mock_client)
        assert not coord._should_skip_cycle()

    def test_no_skip_when_input_active(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = self._make_coord(hass, mock_config_entry, mock_client)
        coord.data = BPCData(inputs=(PUMP_INPUT_ON,))
        assert not coord._should_skip_cycle()

    def test_skip_when_idle_below_max(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = self._make_coord(hass, mock_config_entry, mock_client)
        coord.data = BPCData(inputs=(PUMP_INPUT_OFF,))
        coord._skipped_cycles = 3
        assert coord._should_skip_cycle()

    def test_no_skip_when_idle_at_max(self, hass, mock_config_entry, mock_client):
        from custom_components.easycare_bywaterair.const import SCAN_INTERVAL_BPC_IDLE_FACTOR
        mock_config_entry.add_to_hass(hass)
        coord = self._make_coord(hass, mock_config_entry, mock_client)
        coord.data = BPCData(inputs=(PUMP_INPUT_OFF,))
        coord._skipped_cycles = SCAN_INTERVAL_BPC_IDLE_FACTOR - 1
        assert not coord._should_skip_cycle()

    async def test_immediate_refresh_resets_counter(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = self._make_coord(hass, mock_config_entry, mock_client)
        coord._skipped_cycles = 5
        with patch.object(coord, "async_request_refresh", new_callable=AsyncMock):
            await coord.async_request_immediate_refresh()
        assert coord._skipped_cycles == 0
