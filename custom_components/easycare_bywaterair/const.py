"""Constantes pour l'intégration Easy-care by Waterair."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "easycare_bywaterair"
MANUFACTURER: Final = "Waterair"

CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_ID_TOKEN: Final = "id_token"
CONF_ACCESS_TOKEN: Final = "access_token"
CONF_ID_TOKEN_EXPIRES_AT: Final = "id_token_expires_at"
CONF_BEARER: Final = "bearer"
CONF_BEARER_EXPIRES_AT: Final = "bearer_expires_at"
CONF_POOL_ID: Final = "pool_id"
CONF_AUTH_CODE: Final = "auth_code"
CONF_PUMP_POWER_W: Final = "pump_power_w"

API_HOST_EASYCARE: Final = "https://easycare.waterair.com"
API_PATH_TOKEN_FROM_B2C: Final = "/oauth2/tokenFromAzureADB2CIdToken"
API_PATH_GET_USER: Final = "/api/getUser?attributesToPopulate%5B%5D=pools"
API_PATH_GET_USER_MODULES: Final = "/api/getUserWithHisModules"
API_PATH_BPC_STATUS: Final = "/api/module/{watbox_serial}/status/{bpc_name}"
API_PATH_BPC_MANUAL: Final = "/api/module/{watbox_serial}/manual/{bpc_name}"
API_PATH_REPORT_MANUAL_SENT: Final = "/api/reportManualCommandSent"
API_PATH_GET_POOL_STATUS: Final = "/api/getPoolStatus"
API_PATH_SET_STATUS_COMMAND: Final = "/api/setStatusCommandToSend"
API_PATH_BPC_PROGRAMS: Final = "/api/module/{watbox_serial}/programs/{bpc_name}"

SSO_HOST: Final = "https://sso.waterair.com"
SSO_TENANT: Final = "waterairexternb2c.onmicrosoft.com"
SSO_POLICY: Final = "b2c_1a_signup_signin_inter"
OAUTH_AUTHORITY_URL: Final = f"{SSO_HOST}/{SSO_TENANT}/{SSO_POLICY}"
OAUTH_AUTHORIZE_URL: Final = f"{OAUTH_AUTHORITY_URL}/oauth2/v2.0/authorize"
OAUTH_TOKEN_URL: Final = f"{OAUTH_AUTHORITY_URL}/oauth2/v2.0/token"
OAUTH_CLIENT_ID: Final = "6c015150-c33f-463e-89bc-6ad5614bdc15"
OAUTH_REDIRECT_URI: Final = "msauth.com.waterair.easycare://auth"
OAUTH_CODE_VERIFIER: Final = "w-j6efyTpo1umXD0hFZPRM8l7kD9yScwZ3E5rAHJuE4"
OAUTH_CODE_CHALLENGE: Final = "nKnk64mx1G_lEG5cshhNggBm-PAf9UZnZayLNtux2Bc"
OAUTH_SCOPES: Final = (
    "openid offline_access profile "
    "https://sso.waterair.com/api/openid "
    "https://sso.waterair.com/api/offline_access"
)
BEARER_BASIC_AUTH: Final = "NWQwMjFkYzI0NzhjMjE3MDc3MzI0NDEwOkNtVmZxNDNiZE5hUUZjWA=="

ID_TOKEN_REFRESH_MARGIN_SECONDS: Final = 600
BEARER_REFRESH_MARGIN_SECONDS: Final = 300
REFRESH_TOKEN_LIFETIME_DAYS: Final = 14

SCAN_INTERVAL_USER: Final = timedelta(minutes=30)
SCAN_INTERVAL_MODULES: Final = timedelta(hours=24)
SCAN_INTERVAL_BPC: Final = timedelta(minutes=1)
SCAN_INTERVAL_BPC_IDLE_FACTOR: Final = 10
SCAN_INTERVAL_POOL_STATUS: Final = timedelta(minutes=5)

MODULE_TYPE_WATBOX: Final = "lr-bst-compact"
MODULE_TYPE_BPC: Final = "lr-pc"
MODULE_TYPE_AC1: Final = "lr-mas"
MODULE_TYPE_PRESSURE: Final = "lr-pr"

KNOWN_MODULE_TYPES: Final = frozenset({
    MODULE_TYPE_WATBOX,
    MODULE_TYPE_BPC,
    MODULE_TYPE_AC1,
    MODULE_TYPE_PRESSURE,
    "lr-ag", "lr-can", "lr-fl", "lr-ip", "lr-is",
    "lr-light", "lr-mb", "lr-mpc", "lr-ms", "lr-niv",
    "lr-ol", "lr-pg",
})

BPC_INDEX_PUMP: Final = 0
BPC_INDEX_SPOT: Final = 1
BPC_INDEX_ESCALIGHT: Final = 2

BPC_ACTION_OFF: Final = 1
BPC_ACTION_ON: Final = 2

DEFAULT_DURATION_PUMP_HOURS: Final = 1
DEFAULT_DURATION_LIGHT_HOURS: Final = 1

MODE_AUTO: Final = "AUTO"
MODE_AUTO_MINUS: Final = "AUTO-2H"
MODE_AUTO_PLUS: Final = "AUTO+2H"
MODE_CONTINUOUS: Final = "CONTINUOUS"
MODE_MANUAL: Final = "MANUAL"
MODE_PROG: Final = "PROG"

FILTRATION_MODES: Final = (MODE_AUTO, MODE_CONTINUOUS, MODE_MANUAL)
"""Modes de filtration disponibles pour les commandes API."""

FILTRATION_MODES_WITH_OFFSET: Final = (
    MODE_AUTO_MINUS, MODE_AUTO, MODE_AUTO_PLUS,
    MODE_CONTINUOUS, MODE_MANUAL,
)
"""Modes exposés dans le sélecteur HA — inclut les 3 variantes AUTO."""

# Clés HA valides (hassfest : [a-z0-9-_]+, pas de majuscules ni de +)
HA_MODE_AUTO_MINUS: Final = "auto_minus_2h"
HA_MODE_AUTO: Final = "auto"
HA_MODE_AUTO_PLUS: Final = "auto_plus_2h"
HA_MODE_CONTINUOUS: Final = "continuous"
HA_MODE_MANUAL: Final = "manual"
HA_MODE_PROG: Final = "prog"
HA_MODE_ON: Final = "on"
HA_MODE_OFF: Final = "off"

HA_FILTRATION_MODES: Final = (
    HA_MODE_AUTO_MINUS, HA_MODE_AUTO, HA_MODE_AUTO_PLUS,
    HA_MODE_CONTINUOUS, HA_MODE_MANUAL,
)

HA_TO_API_FILTRATION_MODE: Final[dict[str, str]] = {
    HA_MODE_AUTO_MINUS: MODE_AUTO_MINUS,
    HA_MODE_AUTO: MODE_AUTO,
    HA_MODE_AUTO_PLUS: MODE_AUTO_PLUS,
    HA_MODE_CONTINUOUS: MODE_CONTINUOUS,
    HA_MODE_MANUAL: MODE_MANUAL,
}

HA_BOOST_OFF: Final = "off"
HA_BOOST_ACTIVE: Final = "active"
HA_BOOST_4H: Final = "boost_4h"
HA_BOOST_12H: Final = "boost_12h"
HA_BOOST_24H: Final = "boost_24h"
HA_BOOST_36H: Final = "boost_36h"
HA_BOOST_48H: Final = "boost_48h"
HA_BOOST_72H: Final = "boost_72h"

HA_BOOST_OPTIONS: Final = (
    HA_BOOST_OFF, HA_BOOST_ACTIVE,
    HA_BOOST_4H, HA_BOOST_12H, HA_BOOST_24H,
    HA_BOOST_36H, HA_BOOST_48H, HA_BOOST_72H,
)

HA_TO_API_BOOST: Final[dict[str, str]] = {
    HA_BOOST_4H: BOOST_MODE_4H,
    HA_BOOST_12H: BOOST_MODE_12H,
    HA_BOOST_24H: BOOST_MODE_24H,
    HA_BOOST_36H: BOOST_MODE_36H,
    HA_BOOST_48H: BOOST_MODE_48H,
    HA_BOOST_72H: BOOST_MODE_72H,
}

ADAPT_OFFSET_MINUS: Final = -60
ADAPT_OFFSET_NEUTRAL: Final = 0
ADAPT_OFFSET_PLUS: Final = 60

# Schedules AUTO — matrice de référence (7 jours × 12 seuils de température).
# Chaque entier est un masque 24 bits : le bit N vaut 1 si la pompe filtre à l'heure N
# (bit 0 = 0h, bit 23 = 23h). Capturés par reverse engineering de l'API Waterair.
# Les 7 lignes (jours) sont identiques en mode AUTO — la matrice est uniforme.
SCHED_AUTO_ROW_MINUS: Final[tuple[int, ...]] = (
    32, 32, 3072, 7168, 15360, 64512, 261120,
    1048064, 2097024, 8388544, 8388600, 16777212,
)
SCHED_AUTO_ROW_STD: Final[tuple[int, ...]] = (
    4194336, 4194400, 15360, 31744, 64512, 261120, 523776,
    2096896, 4194240, 16777184, 16777212, 16777215,
)
SCHED_AUTO_ROW_PLUS: Final[tuple[int, ...]] = (
    12583008, 12583136, 64512, 130048, 261120, 523776, 1048320,
    2097088, 8388576, 16777208, 16777215, 16777215,
)

BOOST_MODE_4H: Final = "BOOST4H"
BOOST_MODE_12H: Final = "BOOST12H"
BOOST_MODE_24H: Final = "BOOST24H"
BOOST_MODE_36H: Final = "BOOST36H"
BOOST_MODE_48H: Final = "BOOST48H"
BOOST_MODE_72H: Final = "BOOST72H"

BOOST_CANCEL: Final = "CANCELCURRENTBOOST"

BOOST_MODES: Final = (
    BOOST_MODE_4H,
    BOOST_MODE_12H,
    BOOST_MODE_24H,
    BOOST_MODE_36H,
    BOOST_MODE_48H,
    BOOST_MODE_72H,
)

DEVICE_ID_ACCOUNT: Final = "account"
DEVICE_ID_WATBOX: Final = "watbox"
DEVICE_ID_BPC: Final = "bpc"
DEVICE_ID_AC1: Final = "ac1"
DEVICE_ID_PRESSURE: Final = "pressure"

SERVICE_PUMP_ON: Final = "pump_on"
SERVICE_PUMP_OFF: Final = "pump_off"
SERVICE_SET_FILTRATION_MODE: Final = "set_filtration_mode"
SERVICE_START_BOOST: Final = "start_boost"
SERVICE_CANCEL_BOOST: Final = "cancel_boost"
SERVICE_REFRESH_DATA: Final = "refresh_data"

USER_AGENT: Final = "connected-pool-waterair/2.4.6 (iPad; iOS 16.3; Scale/2.00)"

HTTP_TIMEOUT: Final = 15
HTTP_TIMEOUT_AUTH: Final = 20
HTTP_MAX_RETRIES: Final = 3
HTTP_RETRY_DELAY: Final = 1.0
