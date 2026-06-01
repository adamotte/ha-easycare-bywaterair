"""Fixtures pytest partagées pour l'intégration EasyCare by Waterair."""

from __future__ import annotations

import asyncio
import sys

import pytest

from custom_components.easycare_bywaterair.api.auth import EasyCareAuth
from custom_components.easycare_bywaterair.coordinator import BPCData, UserData

# Toutes les constantes et helpers vivent dans helpers.py (importable normalement).
from tests.helpers import (
    AC1_MODULE,
    BPC_MODULE,
    LRPR_MODULE,
    FAKE_ALERTS,
    FAKE_BEARER,
    FAKE_CLIENT,
    FAKE_METRICS,
    FAKE_NOW,
    FAKE_OAUTH_TOKENS,
    FAKE_POOL,
    FAKE_POOL_STATUS,
    FAKE_TREATMENT,
    FILTER_SCHEDULE_AUTO,
    PUMP_INPUT_BOOSTING,
    PUMP_INPUT_OFF,
    PUMP_INPUT_ON,
    WATBOX_MODULE,
    make_mock_client,
    make_mock_config_entry,
)
from tests.helpers import get_entity_id, setup_integration  # noqa: F401  (re-export)


def pytest_configure(config):
    """Sur Windows, forcer SelectorEventLoop avant le plugin HA."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def event_loop_policy():
    """Sur Windows, forcer SelectorEventLoop — requis par HA et aiohttp."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Rend les custom integrations disponibles dans HA pour tous les tests.

    Sans cette fixture, HA ne sait pas où trouver custom_components/ et
    config_entries.async_setup() échoue silencieusement (UnknownHandler).
    """


@pytest.fixture
def mock_config_entry():
    return make_mock_config_entry()


@pytest.fixture
def mock_client():
    return make_mock_client()


@pytest.fixture
def mock_auth():
    from unittest.mock import AsyncMock, MagicMock
    auth = MagicMock(spec=EasyCareAuth)
    auth.login_with_credentials = AsyncMock(return_value=FAKE_OAUTH_TOKENS)
    auth.bearer = FAKE_BEARER
    auth.get_valid_bearer = AsyncMock(return_value=FAKE_BEARER.bearer)
    return auth


@pytest.fixture
def mock_user_data() -> UserData:
    return UserData(
        client=FAKE_CLIENT,
        pool=FAKE_POOL,
        metrics=FAKE_METRICS,
        alerts=FAKE_ALERTS,
        treatment=FAKE_TREATMENT,
    )


@pytest.fixture
def mock_bpc_data() -> BPCData:
    return BPCData(
        inputs=(PUMP_INPUT_ON,),
        pool_status=FAKE_POOL_STATUS,
        filtration_mode="AUTO",
        adapt_offset=0,
        filter_schedule=FILTER_SCHEDULE_AUTO,
        bpc_temp_reference=27,
    )
