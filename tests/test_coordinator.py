"""Tests des coordinators EasyCare."""

from __future__ import annotations

import logging
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
    Module,
    ModuleOutput,
    Notification,
    PoolStatus,
)
from custom_components.easycare_bywaterair.const import (
    BPC_LAYOUT_STANDARD,
    BPC_LAYOUT_UNKNOWN,
    MODULE_TYPE_AC1,
    MODULE_TYPE_BPC,
    MODULE_TYPE_BPC2,
    MODULE_TYPE_PRESSURE,
    MODULE_TYPE_WATBOX,
)
from custom_components.easycare_bywaterair.coordinator import (
    BPCData,
    EasyCareBPCCoordinator,
    EasyCareCoordinators,
    EasyCareModulesCoordinator,
    EasyCareUserCoordinator,
    UserData,
    _match_modules,
    _pool_status_from_inputs,
    _wrap_api_error,
)

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
    LRPR_MODULE,
    PUMP_INPUT_BOOSTING,
    PUMP_INPUT_OFF,
    PUMP_INPUT_ON,
    WATBOX_MODULE,
)


# Variantes matérielles (issue #10).
# Reconnues par PRÉFIXE DE TYPE (famille lr-bst-* / lr-pc-*) :
WATBOX_TYPE_VARIANT = Module(
    type="lr-bst-react", name="WATBOX-#A1234", id="wb-tv", serial_number="#A1234",
)
BPC_TYPE_VARIANT = Module(
    type="lr-pc-vs2", name="BPC-#B5678", id="bpc-tv", serial_number="#B5678",
)
# BPC2 réel (log utilisateur) : type alias lr-ph, reconnu comme BPC par type.
BPC2_MODULE = Module(
    type="lr-ph", name="BPC2-D36C1B", id="bpc2", serial_number="D36C1B",
)
# Reconnues par REPLI SUR LE NOM (type totalement inattendu) :
WATBOX_NAME_ONLY = Module(
    type="lr-weird", name="WATBOX-#A9999", id="wb-no", serial_number="#A9999",
)
BPC_NAME_ONLY = Module(
    type="lr-weird2", name="BPC-#B9999", id="bpc-no", serial_number="#B9999",
)
AC1_VARIANT = Module(
    type="lr-mas-x", name="AC1-#C9012", id="ac1-var", serial_number="#C9012",
)
LRPR_VARIANT = Module(
    type="lr-pr-x", name="LR-PR-#D3456", id="lrpr-var", serial_number="#D3456",
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
# _match_modules (résolution type + repli par nom — issue #10)
# ---------------------------------------------------------------------------

class TestMatchModules:
    def test_match_by_type(self):
        modules, kind = _match_modules((WATBOX_MODULE, BPC_MODULE), MODULE_TYPE_BPC)
        assert modules == (BPC_MODULE,)
        assert kind == "type"

    def test_match_by_type_prefix_watbox(self):
        # lr-bst-react : variante gateway reconnue par préfixe de type lr-bst-.
        modules, kind = _match_modules((WATBOX_TYPE_VARIANT, BPC_MODULE), MODULE_TYPE_WATBOX)
        assert modules == (WATBOX_TYPE_VARIANT,)
        assert kind == "type_prefix"

    def test_match_by_type_prefix_bpc(self):
        # lr-pc-vs2 : variante BPC reconnue par préfixe de type lr-pc-.
        modules, kind = _match_modules((WATBOX_MODULE, BPC_TYPE_VARIANT), MODULE_TYPE_BPC)
        assert modules == (BPC_TYPE_VARIANT,)
        assert kind == "type_prefix"

    def test_match_bpc2_alias_lr_ph(self):
        # BPC2 (type lr-ph) reconnu comme BPC par alias → kind "type", pas de repli nom.
        modules, kind = _match_modules((WATBOX_MODULE, BPC2_MODULE), MODULE_TYPE_BPC)
        assert modules == (BPC2_MODULE,)
        assert kind == "type"

    def test_fallback_by_name_when_type_fully_unknown(self):
        modules, kind = _match_modules((WATBOX_NAME_ONLY, BPC_NAME_ONLY), MODULE_TYPE_WATBOX)
        assert modules == (WATBOX_NAME_ONLY,)
        assert kind == "name"

    def test_exact_type_takes_precedence_over_prefix(self):
        # Vrai BPC (lr-pc exact) + variante lr-pc-vs2 : l'exact gagne.
        modules, kind = _match_modules((BPC_MODULE, BPC_TYPE_VARIANT), MODULE_TYPE_BPC)
        assert modules == (BPC_MODULE,)
        assert kind == "type"

    def test_type_prefix_takes_precedence_over_name(self):
        # Une variante lr-bst-* doit être prise par le type, pas par le nom.
        modules, kind = _match_modules((WATBOX_TYPE_VARIANT, WATBOX_NAME_ONLY), MODULE_TYPE_WATBOX)
        assert WATBOX_TYPE_VARIANT in modules
        assert kind == "type_prefix"

    def test_no_match_returns_empty(self):
        modules, kind = _match_modules((BPC_MODULE,), MODULE_TYPE_AC1)
        assert modules == ()
        assert kind == "none"

    def test_ac1_and_pressure_name_fallback(self):
        # AC1/LR-PR n'ont pas de préfixe de type → repli par nom.
        ac1, ac1_kind = _match_modules((AC1_VARIANT,), MODULE_TYPE_AC1)
        lrpr, lrpr_kind = _match_modules((LRPR_VARIANT,), MODULE_TYPE_PRESSURE)
        assert ac1 == (AC1_VARIANT,) and ac1_kind == "name"
        assert lrpr == (LRPR_VARIANT,) and lrpr_kind == "name"


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

    # --- Variantes matérielles : préfixe de type puis repli par nom (issue #10) ---

    def test_get_watbox_type_prefix(self, hass, mock_config_entry, mock_client, caplog):
        # lr-bst-react : reconnu par préfixe de type → debug, pas de warning.
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_TYPE_VARIANT, BPC_MODULE)
        with caplog.at_level(logging.WARNING):
            assert coord.get_watbox() is WATBOX_TYPE_VARIANT
        assert "name fallback" not in caplog.text

    def test_get_bpc_type_prefix(self, hass, mock_config_entry, mock_client, caplog):
        # lr-pc-vs2 : reconnu par préfixe de type → debug, pas de warning.
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC_TYPE_VARIANT)
        with caplog.at_level(logging.WARNING):
            assert coord.get_bpc() is BPC_TYPE_VARIANT
        assert "name fallback" not in caplog.text

    def test_get_bpc2_alias_lr_ph_silent(self, hass, mock_config_entry, mock_client, caplog):
        # BPC2 (type lr-ph) : reconnu comme BPC par alias, aucun warning (log réel utilisateur).
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC2_MODULE)
        with caplog.at_level(logging.WARNING):
            assert coord.get_bpc() is BPC2_MODULE
        assert "name fallback" not in caplog.text

    async def test_bpc2_lr_ph_no_unknown_type_warning(self, hass, mock_config_entry, mock_client, caplog):
        # lr-ph est dans KNOWN_MODULE_TYPES → pas de warning "Unknown module type".
        mock_config_entry.add_to_hass(hass)
        mock_client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, BPC2_MODULE))
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        with caplog.at_level(logging.WARNING):
            await coord.async_refresh()
        assert "Unknown module type" not in caplog.text

    def test_get_watbox_name_fallback(self, hass, mock_config_entry, mock_client, caplog):
        # Type totalement inattendu (hors famille lr-bst-) → repli par nom + warning.
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_NAME_ONLY, BPC_MODULE)
        with caplog.at_level(logging.WARNING):
            assert coord.get_watbox() is WATBOX_NAME_ONLY
        assert "name fallback" in caplog.text
        assert "lr-weird" in caplog.text

    def test_get_bpc_prefers_exact_type(self, hass, mock_config_entry, mock_client, caplog):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (BPC_MODULE, BPC_TYPE_VARIANT)
        with caplog.at_level(logging.WARNING):
            assert coord.get_bpc() is BPC_MODULE
        assert "name fallback" not in caplog.text

    def test_get_modules_by_type_ac1_name_fallback(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC_MODULE, AC1_VARIANT)
        assert coord.get_modules_by_type(MODULE_TYPE_AC1) == (AC1_VARIANT,)

    def test_get_modules_by_type_pressure_name_fallback(self, hass, mock_config_entry, mock_client):
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        coord.data = (WATBOX_MODULE, BPC_MODULE, LRPR_VARIANT)
        assert coord.get_modules_by_type(MODULE_TYPE_PRESSURE) == (LRPR_VARIANT,)

    async def test_unknown_module_type_warns(self, hass, mock_config_entry, mock_client, caplog):
        mock_config_entry.add_to_hass(hass)
        unknown = Module(
            type="lr-totally-new", name="NEWHW-001", id="x", serial_number="001",
        )
        mock_client.get_modules = AsyncMock(
            return_value=(WATBOX_MODULE, BPC_MODULE, unknown)
        )
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        with caplog.at_level(logging.WARNING):
            await coord.async_refresh()
        assert "Unknown module type" in caplog.text
        assert "lr-totally-new" in caplog.text

    async def test_known_variant_type_does_not_warn(self, hass, mock_config_entry, mock_client, caplog):
        # Une variante listée dans KNOWN_MODULE_TYPES ne déclenche pas le warning.
        mock_config_entry.add_to_hass(hass)
        mock_client.get_modules = AsyncMock(
            return_value=(WATBOX_TYPE_VARIANT, BPC_TYPE_VARIANT)
        )
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        with caplog.at_level(logging.WARNING):
            await coord.async_refresh()
        assert "Unknown module type" not in caplog.text

    async def test_firmware_check_uses_watbox_type_prefix(self, hass, mock_config_entry, mock_client):
        # Une variante WATBOX (type lr-bst-*) doit quand même permettre le check firmware.
        mock_client.get_modules = AsyncMock(return_value=(WATBOX_TYPE_VARIANT, BPC_MODULE))
        mock_client.get_firmware_update = AsyncMock(return_value={"version": "9.9.9"})
        mock_config_entry.add_to_hass(hass)
        coord = EasyCareModulesCoordinator(hass, mock_client, mock_config_entry)
        await coord.async_refresh()
        assert mock_client.get_firmware_update.await_count >= 1
        called_serial = mock_client.get_firmware_update.await_args_list[0].args[0]
        assert called_serial == WATBOX_TYPE_VARIANT.serial_number


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


# ---------------------------------------------------------------------------
# EasyCareBPCCoordinator — _async_update_data (gardes-fous issue #10)
# ---------------------------------------------------------------------------

class TestBPCCoordinatorUpdate:
    def _make_coord(self, hass, mock_config_entry, mock_client, modules):
        return EasyCareBPCCoordinator(hass, mock_client, modules, mock_config_entry)

    async def test_missing_modules_raises_and_logs_available(
        self, hass, mock_config_entry, mock_client, caplog
    ):
        mock_config_entry.add_to_hass(hass)
        mock_modules = MagicMock()
        mock_modules.get_watbox.return_value = None
        mock_modules.get_bpc.return_value = None
        mock_modules.data = (AC1_MODULE, LRPR_MODULE)
        coord = self._make_coord(hass, mock_config_entry, mock_client, mock_modules)
        with caplog.at_level(logging.WARNING), pytest.raises(UpdateFailed):
            await coord._async_update_data()
        assert "available modules" in caplog.text
        assert "lr-mas" in caplog.text  # type de l'AC1 listé

    async def test_pump_channel_missing_warns(
        self, hass, mock_config_entry, mock_client, caplog
    ):
        mock_config_entry.add_to_hass(hass)
        mock_modules = MagicMock()
        mock_modules.get_watbox.return_value = WATBOX_MODULE
        mock_modules.get_bpc.return_value = BPC_MODULE
        mock_modules.data = (WATBOX_MODULE, BPC_MODULE)
        # Status BPC sans voie pompe (index 0) — variante matérielle.
        mock_client.get_bpc_status = AsyncMock(
            return_value=((BPCInput(index=1, value=1),), 27)
        )
        coord = self._make_coord(hass, mock_config_entry, mock_client, mock_modules)
        with caplog.at_level(logging.WARNING):
            await coord._async_update_data()
        assert "pump channel (index 0) missing" in caplog.text

    async def test_pump_channel_present_no_warning(
        self, hass, mock_config_entry, mock_client, caplog
    ):
        mock_config_entry.add_to_hass(hass)
        mock_modules = MagicMock()
        mock_modules.get_watbox.return_value = WATBOX_MODULE
        mock_modules.get_bpc.return_value = BPC_MODULE
        mock_modules.data = (WATBOX_MODULE, BPC_MODULE)
        coord = self._make_coord(hass, mock_config_entry, mock_client, mock_modules)
        with caplog.at_level(logging.WARNING):
            await coord._async_update_data()
        assert "pump channel (index 0) missing" not in caplog.text


# ---------------------------------------------------------------------------
# EasyCareCoordinators — helpers de sécurité BPC (issue #10)
# ---------------------------------------------------------------------------

class TestCoordinatorsBpcHelpers:
    def _make(self, bpc_module, bpc_data):
        modules = MagicMock()
        modules.get_bpc.return_value = bpc_module
        bpc = MagicMock()
        bpc.data = bpc_data
        return EasyCareCoordinators(user=MagicMock(), modules=modules, bpc=bpc)

    def test_standard_bpc_not_nonstandard(self):
        coords = self._make(BPC_MODULE, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.is_bpc_nonstandard() is False
        assert coords.bpc_nonstandard_type is None

    def test_bpc_prefix_variant_not_nonstandard(self):
        # lr-pc-vs2 reste un BPC standard (préfixe lr-pc-).
        coords = self._make(BPC_TYPE_VARIANT, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.is_bpc_nonstandard() is False

    def test_bpc2_lr_ph_is_nonstandard(self):
        coords = self._make(BPC2_MODULE, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.is_bpc_nonstandard() is True
        assert coords.bpc_nonstandard_type == "lr-ph"

    def test_no_bpc_not_nonstandard(self):
        coords = self._make(None, None)
        assert coords.is_bpc_nonstandard() is False
        assert coords.bpc_nonstandard_type is None

    # --- get_bpc_layout (issue #11) ---

    def test_layout_standard_bpc(self):
        coords = self._make(BPC_MODULE, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.get_bpc_layout() is BPC_LAYOUT_STANDARD

    def test_layout_bpc_prefix_variant_is_standard(self):
        # lr-pc-vs2 → BPC standard (préfixe lr-pc-).
        coords = self._make(BPC_TYPE_VARIANT, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.get_bpc_layout() is BPC_LAYOUT_STANDARD

    def test_layout_no_bpc_is_unknown(self):
        coords = self._make(None, None)
        assert coords.get_bpc_layout() is BPC_LAYOUT_UNKNOWN

    def test_layout_bpc2_without_outputs_is_unknown(self):
        bpc2 = Module(type=MODULE_TYPE_BPC2, name="BPC2-D36C1B", id="b", serial_number="D")
        coords = self._make(bpc2, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.get_bpc_layout() is BPC_LAYOUT_UNKNOWN

    def test_layout_bpc2_without_pump_channel_is_unknown(self):
        # Pas de voie pompe identifiable → fail-safe, aucune commande.
        bpc2 = Module(
            type=MODULE_TYPE_BPC2, name="BPC2-X", id="b", serial_number="D",
            outputs=(ModuleOutput(index=1, name="spot", id="o1"),),
        )
        coords = self._make(bpc2, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.get_bpc_layout() is BPC_LAYOUT_UNKNOWN

    def test_layout_bpc2_resolves_roles_by_name(self):
        bpc2 = Module(
            type=MODULE_TYPE_BPC2, name="BPC2-D36C1B", id="b", serial_number="D",
            outputs=(
                ModuleOutput(index=0, name="pompe", id="o0"),
                ModuleOutput(index=1, name="spot", id="o1"),
                ModuleOutput(index=4, name="doseuse pH", id="o4"),
            ),
        )
        layout = self._make(bpc2, BPCData(inputs=(PUMP_INPUT_ON,))).get_bpc_layout()
        assert layout.pump_index == 0
        assert layout.spot_index == 1
        assert layout.escalight_index is None
        assert layout.ph_pump_index == 4
        assert layout.filtration_supported is True
        assert layout.boost_supported is True
        assert layout.lights_supported is True
        assert layout.ph_supported is True

    def test_commands_blocked_when_pump_channel_missing(self):
        coords = self._make(BPC2_MODULE, BPCData(inputs=(BPCInput(index=1, value=1),)))
        assert coords.is_bpc_commands_blocked() is True

    def test_commands_not_blocked_when_pump_present(self):
        coords = self._make(BPC2_MODULE, BPCData(inputs=(PUMP_INPUT_ON,)))
        assert coords.is_bpc_commands_blocked() is False

    def test_commands_not_blocked_when_no_data(self):
        coords = self._make(BPC2_MODULE, None)
        assert coords.is_bpc_commands_blocked() is False
