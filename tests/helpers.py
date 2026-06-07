"""Constantes et helpers partagés entre les tests.

Ce module (importable normalement) centralise les données de test réutilisables.
conftest.py importe depuis ici ; les fichiers de test aussi.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from custom_components.easycare_bywaterair.api.auth import EasyCareAuth
from custom_components.easycare_bywaterair.api.client import EasyCareClient
from custom_components.easycare_bywaterair.api.models import (
    Alerts,
    BPCInput,
    BearerToken,
    Client,
    FilterSchedule,
    Metrics,
    Module,
    ModuleOutput,
    Notification,
    OAuthTokens,
    Pool,
    PoolStatus,
    Treatment,
)
from custom_components.easycare_bywaterair.const import (
    CONF_BEARER,
    CONF_BEARER_EXPIRES_AT,
    CONF_ID_TOKEN,
    CONF_ID_TOKEN_EXPIRES_AT,
    CONF_POOL_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
    MODULE_TYPE_AC1,
    MODULE_TYPE_BPC,
    MODULE_TYPE_PRESSURE,
    MODULE_TYPE_WATBOX,
)
from custom_components.easycare_bywaterair.coordinator import BPCData, UserData

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Timestamp fixe : 2023-11-15 00:00:00 UTC
FAKE_NOW = 1_700_006_400.0


def load_fixture(filename: str) -> dict:
    return json.loads((FIXTURES_DIR / filename).read_text())


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

FAKE_OAUTH_TOKENS = OAuthTokens(
    access_token="fake-access-token",
    id_token="fake-id-token",
    refresh_token="fake-refresh-token",
    expires_at=FAKE_NOW + 3600,
)

FAKE_BEARER = BearerToken(
    bearer="fake-bearer-token",
    expires_at=FAKE_NOW + 86400,
)

# ---------------------------------------------------------------------------
# Modules
# ---------------------------------------------------------------------------

WATBOX_MODULE = Module(
    type=MODULE_TYPE_WATBOX,
    name="WATBOX-AABBCC",
    id="watbox-id-001",
    serial_number="AABBCC",
    software_version="1.2.3",
    hardware_version="2.0",
)

BPC_MODULE = Module(
    type=MODULE_TYPE_BPC,
    name="BPC-DDEEFF",
    id="bpc-id-002",
    serial_number="DDEEFF",
    number_of_inputs=3,
    outputs=(
        ModuleOutput(
            index=0,
            name="pompe",
            id="out-pump-0",
            total_activation_time=1200,
        ),
        ModuleOutput(
            index=1,
            name="spot",
            id="out-spot-1",
            total_activation_time=300,
        ),
    ),
)

# Module AC1 présent par défaut — requis pour les sensors pH, chlore, temp, notification
AC1_MODULE = Module(
    type=MODULE_TYPE_AC1,
    name="AC1-XXYYZZ",
    id="ac1-id-003",
    serial_number="XXYYZZ",
    battery_level=3,
)

# Module LR-PR présent par défaut — requis pour les sensors pression et battery_lrpr
LRPR_MODULE = Module(
    type=MODULE_TYPE_PRESSURE,
    name="LR-PR-GGHHII",
    id="lrpr-id-004",
    serial_number="GGHHII",
    battery_level=4,
    static_pressure=1.0,
)

# ---------------------------------------------------------------------------
# BPCInput
# ---------------------------------------------------------------------------

PUMP_INPUT_ON = BPCInput(index=0, value=1, remaining_time="01:30", origin=0, info=(), temp_ref=6)
PUMP_INPUT_OFF = BPCInput(index=0, value=0, remaining_time="00:00", origin=0, info=())
PUMP_INPUT_BOOSTING = BPCInput(index=0, value=1, remaining_time="02:00", origin=3, info=("boost",), temp_ref=6)

# ---------------------------------------------------------------------------
# FilterSchedule minimal
# ---------------------------------------------------------------------------

FILTER_SCHEDULE_AUTO = FilterSchedule(
    thresholds=(10, 12, 14, 16, 20, 24, 27, 28, 29, 30, 31, 127),
    sched=(
        (32, 32, 3072, 7168, 61440, 261120, 523264, 1046528, 2093056, 4186112, 4186112, 0),
    ) * 7,
)

# ---------------------------------------------------------------------------
# Objets de domaine
# ---------------------------------------------------------------------------

FAKE_CLIENT = Client(
    first_name="Jean",
    last_name="Testeur",
    email="jean.testeur@example.com",
)

FAKE_POOL = Pool(
    model="Waterair Celebris 440",
    id="pool-abc123",
    volume=44.0,
)

FAKE_METRICS = Metrics(
    ph_value=7.4,
    chlorine_value=650.0,
    temperature_value=25.0,
    pressure_value=1.2,
)

FAKE_ALERTS = Alerts(
    notifications=(
        Notification(action="batteryLow", date=None),
    )
)

FAKE_TREATMENT = Treatment(value="None")

FAKE_POOL_STATUS = PoolStatus(
    mode="auto",
    power_state="on",
    boost_remaining_time="00:00",
    is_pool_power=True,
)

# ---------------------------------------------------------------------------
# Helpers d'intégration HA
# ---------------------------------------------------------------------------

MODULE_INIT = "custom_components.easycare_bywaterair"


def make_mock_client() -> MagicMock:
    """Crée un EasyCareClient mocké avec des valeurs par défaut cohérentes."""
    client = MagicMock(spec=EasyCareClient)
    client.get_user = AsyncMock(
        return_value=(FAKE_CLIENT, FAKE_POOL, FAKE_METRICS, FAKE_ALERTS, FAKE_TREATMENT)
    )
    # AC1 + LR-PR inclus par défaut : les sensors associés ne sont créés que si ces modules existent
    client.get_modules = AsyncMock(return_value=(WATBOX_MODULE, BPC_MODULE, AC1_MODULE, LRPR_MODULE))
    client.get_bpc_status = AsyncMock(return_value=((PUMP_INPUT_ON,), 27))
    client.get_pool_status = AsyncMock(return_value=FAKE_POOL_STATUS)
    client.get_bpc_programs_data = AsyncMock(
        return_value=("AUTO", 0, None, None, FILTER_SCHEDULE_AUTO, None, None, None)
    )
    client.get_firmware_update = AsyncMock(return_value={})
    client.list_pools = AsyncMock(return_value=["Waterair Celebris 440 — pool-abc123"])
    client.set_bpc_manual = AsyncMock(return_value=True)
    client.set_filtration_mode = AsyncMock(return_value=True)
    client.set_filtration_mode_with_offset = AsyncMock(return_value=True)
    client.start_boost = AsyncMock(return_value=True)
    client.cancel_boost = AsyncMock(return_value=True)
    return client


def make_mock_config_entry():
    """Crée un MockConfigEntry standard pour l'intégration."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    return MockConfigEntry(
        domain=DOMAIN,
        unique_id="easycare_pool_1",
        title="easy·care Piscine 1",
        data={
            "username": "jean.testeur@example.com",
            CONF_REFRESH_TOKEN: FAKE_OAUTH_TOKENS.refresh_token,
            CONF_ID_TOKEN: FAKE_OAUTH_TOKENS.id_token,
            CONF_ID_TOKEN_EXPIRES_AT: FAKE_OAUTH_TOKENS.expires_at,
            CONF_BEARER: FAKE_BEARER.bearer,
            CONF_BEARER_EXPIRES_AT: FAKE_BEARER.expires_at,
            CONF_POOL_ID: 1,
        },
        options={},
    )


async def setup_integration(hass, mock_config_entry, mock_client):
    """Configure l'intégration dans hass avec un client mocké.

    Utilise async_setup_component pour que HA enregistre d'abord le domaine,
    puis forward_entry_setups pour que toutes les plateformes soient chargées.
    """
    from unittest.mock import patch

    from homeassistant.setup import async_setup_component

    mock_config_entry.add_to_hass(hass)
    mock_auth = MagicMock()
    mock_auth.bearer = FAKE_BEARER

    with patch(f"{MODULE_INIT}.EasyCareAuth", return_value=mock_auth), \
         patch(f"{MODULE_INIT}.EasyCareClient", return_value=mock_client):
        await async_setup_component(hass, "easycare_bywaterair", {})
        await hass.async_block_till_done()
        # Deuxième attente pour que les plateformes (sensor, select…) se chargent
        await hass.async_block_till_done()

    return mock_config_entry


def get_entity_id(hass, platform: str, entry_id: str, unique_id_suffix: str) -> str | None:
    """Retourne l'entity_id depuis l'entity registry via son unique_id."""
    from homeassistant.helpers import entity_registry as er
    ent_reg = er.async_get(hass)
    return ent_reg.async_get_entity_id(
        platform, "easycare_bywaterair", f"{entry_id}_{unique_id_suffix}"
    )
