"""Tests du config flow EasyCare."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.easycare_bywaterair.api.exceptions import (
    EasyCareConnectionError,
    EasyCareError,
    EasyCareInvalidCredentialsError,
    EasyCareLoginError,
    EasyCareTimeoutError,
)
from custom_components.easycare_bywaterair.const import CONF_POOL_ID, DOMAIN

from tests.helpers import FAKE_BEARER, FAKE_NOW, FAKE_OAUTH_TOKENS

MODULE_AUTH = "custom_components.easycare_bywaterair.config_flow.EasyCareAuth"
MODULE_CLIENT = "custom_components.easycare_bywaterair.config_flow.EasyCareClient"


def _make_auth_mock(tokens=FAKE_OAUTH_TOKENS, bearer=FAKE_BEARER):
    auth = MagicMock()
    auth.login_with_credentials = AsyncMock(return_value=tokens)
    auth.bearer = bearer
    return auth


def _make_client_mock(pools=None):
    client = MagicMock()
    # "is None" évite que pools=[] soit remplacé par la valeur par défaut
    client.list_pools = AsyncMock(
        return_value=["Celebris 440 — pool-abc123"] if pools is None else pools
    )
    return client


async def _start_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )


class TestConfigFlowUser:
    async def test_form_shown_initially(self, hass):
        result = await _start_flow(hass)
        assert result["type"] == "form"
        assert result["step_id"] == "user"

    async def test_success_single_pool_creates_entry(self, hass):
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock()):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_POOL_ID] == 1

    async def test_success_multi_pool_goes_to_pool_step(self, hass):
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock(
                 pools=["Piscine A", "Piscine B"]
             )):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
        assert result["type"] == "form"
        assert result["step_id"] == "pool"

    async def test_pool_step_creates_entry_with_1based_id(self, hass):
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock(
                 pools=["Piscine A", "Piscine B"]
             )):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_POOL_ID: "Piscine B"},
            )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_POOL_ID] == 2

    async def test_invalid_credentials_error(self, hass):
        auth = MagicMock()
        auth.login_with_credentials = AsyncMock(
            side_effect=EasyCareInvalidCredentialsError("bad")
        )
        with patch(MODULE_AUTH, return_value=auth):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "wrong"},
            )
        assert result["type"] == "form"
        assert result["errors"]["base"] == "invalid_credentials"

    async def test_login_failed_error(self, hass):
        auth = MagicMock()
        auth.login_with_credentials = AsyncMock(side_effect=EasyCareLoginError("mfa"))
        with patch(MODULE_AUTH, return_value=auth):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
        assert result["errors"]["base"] == "login_failed"

    async def test_timeout_error(self, hass):
        auth = MagicMock()
        auth.login_with_credentials = AsyncMock(side_effect=EasyCareTimeoutError("timeout"))
        with patch(MODULE_AUTH, return_value=auth):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "u", CONF_PASSWORD: "p"},
            )
        assert result["errors"]["base"] == "timeout"

    async def test_cannot_connect_error(self, hass):
        auth = MagicMock()
        auth.login_with_credentials = AsyncMock(side_effect=EasyCareConnectionError("net"))
        with patch(MODULE_AUTH, return_value=auth):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "u", CONF_PASSWORD: "p"},
            )
        assert result["errors"]["base"] == "cannot_connect"

    async def test_unknown_error(self, hass):
        auth = MagicMock()
        auth.login_with_credentials = AsyncMock(side_effect=EasyCareError("unknown"))
        with patch(MODULE_AUTH, return_value=auth):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "u", CONF_PASSWORD: "p"},
            )
        assert result["errors"]["base"] == "unknown"

    async def test_no_pools_error(self, hass):
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock(pools=[])):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "u", CONF_PASSWORD: "p"},
            )
        assert result["type"] == "form"
        assert result.get("errors", {}).get("base") == "invalid_pool_id"

    async def test_unique_id_deduplication(self, hass):
        existing = MockConfigEntry(
            domain=DOMAIN,
            unique_id="easycare_pool_1",
        )
        existing.add_to_hass(hass)
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock()):
            result = await _start_flow(hass)
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
        assert result["type"] == "abort"
        assert result["reason"] == "already_configured"


class TestReauthFlow:
    async def test_reauth_shows_form(self, hass, mock_config_entry):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
            data=mock_config_entry.data,
        )
        assert result["type"] == "form"
        assert result["step_id"] == "reauth_confirm"

    async def test_reauth_success_aborts_with_reauth_successful(self, hass, mock_config_entry):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_REAUTH, "entry_id": mock_config_entry.entry_id},
            data=mock_config_entry.data,
        )
        with patch(MODULE_AUTH, return_value=_make_auth_mock()), \
             patch(MODULE_CLIENT, return_value=_make_client_mock()):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"],
                {CONF_USERNAME: "user@example.com", CONF_PASSWORD: "pass"},
            )
        assert result["type"] == "abort"
        assert result["reason"] == "reauth_successful"


class TestOptionsFlow:
    async def test_options_flow_shows_form(self, hass, mock_config_entry):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    async def test_options_flow_saves_pump_power(self, hass, mock_config_entry):
        mock_config_entry.add_to_hass(hass)
        result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                "pump_power_w": 1500,
                "pump_replacement": {
                    "pump_replacement_runtime_h": 0,
                    "pump_replacement_previous_power_w": 0,
                },
            },
        )
        assert result["type"] == "create_entry"
        assert result["data"]["pump_power_w"] == 1500
