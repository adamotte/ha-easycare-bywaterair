"""Constantes pour l'intégration Easy-care by Waterair.

Toutes les constantes (domaine, endpoints API, modes de filtration, types de
modules, identifiants d'appareils, intervalles de polling) sont centralisées
ici pour faciliter la maintenance.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Final

# ─────────────────────────────────────────────────────────────────────────────
# Identité du plugin
# ─────────────────────────────────────────────────────────────────────────────

DOMAIN: Final = "easycare_bywaterair"
"""Domaine HA — utilisé comme préfixe pour toutes les entités et services."""

MANUFACTURER: Final = "Waterair"
"""Fabricant affiché dans le Device Registry HA."""

# ─────────────────────────────────────────────────────────────────────────────
# Clés de configuration stockées dans ConfigEntry.data
# ─────────────────────────────────────────────────────────────────────────────

CONF_REFRESH_TOKEN: Final = "refresh_token"
"""Refresh token Azure B2C — clé du mécanisme de renouvellement automatique."""

CONF_ID_TOKEN: Final = "id_token"
"""ID token Azure B2C — échangé contre le bearer EasyCare."""

CONF_ACCESS_TOKEN: Final = "access_token"
"""Access token Azure B2C — généralement non utilisé directement, gardé pour debug."""

CONF_ID_TOKEN_EXPIRES_AT: Final = "id_token_expires_at"
"""Timestamp Unix d'expiration de l'id_token Azure."""

CONF_BEARER: Final = "bearer"
"""Bearer EasyCare — utilisé dans les en-têtes Authorization pour les /api/*."""

CONF_BEARER_EXPIRES_AT: Final = "bearer_expires_at"
"""Timestamp Unix d'expiration du bearer EasyCare."""

CONF_POOL_ID: Final = "pool_id"
"""Identifiant de la piscine dans le compte utilisateur (1-based)."""

CONF_AUTH_CODE: Final = "auth_code"
"""Code d'autorisation OAuth2 (étape 1 du config_flow uniquement)."""

# ─────────────────────────────────────────────────────────────────────────────
# Endpoints API — host principal Waterair (utilisé par l'app et le plugin existant)
# ─────────────────────────────────────────────────────────────────────────────

API_HOST_EASYCARE: Final = "https://easycare.waterair.com"
"""Host principal — toutes les opérations métier (modules, BPC, lumières, pompe)."""

API_PATH_TOKEN_FROM_B2C: Final = "/oauth2/tokenFromAzureADB2CIdToken"
"""Échange id_token Azure → bearer EasyCare."""

API_PATH_GET_USER: Final = "/api/getUser?attributesToPopulate%5B%5D=pools"
"""Récupère l'utilisateur avec ses piscines (métriques, alertes, traitements)."""

API_PATH_GET_USER_MODULES: Final = "/api/getUserWithHisModules"
"""Récupère la liste des modules (WATBOX, BPC, AC1, LR-PR, etc.)."""

API_PATH_BPC_STATUS: Final = "/api/module/{watbox_serial}/status/{bpc_name}"
"""Récupère l'état des voies du BPC (pompe + lumières)."""

API_PATH_BPC_MANUAL: Final = "/api/module/{watbox_serial}/manual/{bpc_name}"
"""Envoie une commande manuelle (ON/OFF) à une voie du BPC."""

API_PATH_REPORT_MANUAL_SENT: Final = "/api/reportManualCommandSent"
"""Confirmation de l'envoi d'une commande manuelle (étape 2/2 obligatoire)."""

API_PATH_GET_POOL_STATUS: Final = "/api/getPoolStatus"
"""État complet de la piscine — mode filtration, boost, compteurs."""

API_PATH_SET_STATUS_COMMAND: Final = "/api/setStatusCommandToSend"
"""Changement de mode de filtration (AUTO/CONTINUOUS/MANUAL/PROG/BOOST*)."""

# ─────────────────────────────────────────────────────────────────────────────
# Authentification OAuth2 Azure B2C Waterair
# ─────────────────────────────────────────────────────────────────────────────

SSO_HOST: Final = "https://sso.waterair.com"
SSO_TENANT: Final = "waterairexternb2c.onmicrosoft.com"
SSO_POLICY: Final = "b2c_1a_signup_signin_inter"

OAUTH_AUTHORITY_URL: Final = (
    f"{SSO_HOST}/{SSO_TENANT}/{SSO_POLICY}"
)
"""URL de base de l'autorité Azure B2C."""

OAUTH_AUTHORIZE_URL: Final = f"{OAUTH_AUTHORITY_URL}/oauth2/v2.0/authorize"
"""Endpoint d'autorisation OAuth2 — affiche le formulaire de login."""

OAUTH_TOKEN_URL: Final = f"{OAUTH_AUTHORITY_URL}/oauth2/v2.0/token"
"""Endpoint d'échange code↔tokens et de refresh."""

OAUTH_CLIENT_ID: Final = "6c015150-c33f-463e-89bc-6ad5614bdc15"
"""Client ID de l'app Waterair officielle (extrait de auth_config_b2c.json de l'APK)."""

OAUTH_REDIRECT_URI: Final = "msauth.com.waterair.easycare://auth"
"""Redirect URI déclaré dans Azure B2C pour l'app Waterair.

⚠️ On réutilise l'URI de l'app mobile car c'est le seul autorisé côté serveur.
L'utilisateur copiera manuellement le code depuis l'URL de redirection."""

OAUTH_CODE_VERIFIER: Final = "w-j6efyTpo1umXD0hFZPRM8l7kD9yScwZ3E5rAHJuE4"
"""Code verifier PKCE — figé dans l'APK (même valeur que le plugin yyrkoon94)."""

OAUTH_CODE_CHALLENGE: Final = "nKnk64mx1G_lEG5cshhNggBm-PAf9UZnZayLNtux2Bc"
"""Code challenge SHA256(code_verifier) en base64url — correspond au verifier ci-dessus."""

OAUTH_SCOPES: Final = (
    "openid offline_access profile "
    "https://sso.waterair.com/api/openid "
    "https://sso.waterair.com/api/offline_access"
)
"""Scopes OAuth2 demandés.

`offline_access` est critique : sans lui, Azure B2C ne retourne pas de refresh_token."""

BEARER_BASIC_AUTH: Final = "NWQwMjFkYzI0NzhjMjE3MDc3MzI0NDEwOkNtVmZxNDNiZE5hUUZjWA=="
"""Basic auth header pour l'endpoint /oauth2/tokenFromAzureADB2CIdToken.

Cette valeur est en dur dans tous les clients (app + plugin yyrkoon94).
Décodée : `5d021dc2478c217077324410:CmVfq43bdNaQFcX`."""

# ─────────────────────────────────────────────────────────────────────────────
# Stratégie de refresh des tokens
# ─────────────────────────────────────────────────────────────────────────────

ID_TOKEN_REFRESH_MARGIN_SECONDS: Final = 600
"""On rafraîchit l'id_token Azure 10 minutes AVANT son expiration (1h par défaut)
pour éviter toute coupure en cas de requête longue."""

BEARER_REFRESH_MARGIN_SECONDS: Final = 300
"""Marge de sécurité pour le bearer EasyCare (5 min)."""

REFRESH_TOKEN_LIFETIME_DAYS: Final = 14
"""Durée par défaut du refresh_token Azure B2C — informatif uniquement.

En usage normal, le refresh_token est rotaté avant expiration, donc la durée
réelle est illimitée tant que HA continue à appeler le refresh."""

# ─────────────────────────────────────────────────────────────────────────────
# Polling intervals (DataUpdateCoordinator)
# ─────────────────────────────────────────────────────────────────────────────

SCAN_INTERVAL_USER: Final = timedelta(minutes=30)
"""Polling des métriques piscine (température, pH, chlore). Données peu volatiles."""

SCAN_INTERVAL_MODULES: Final = timedelta(hours=24)
"""Polling de la liste des modules. Quasi-jamais modifié."""

SCAN_INTERVAL_BPC: Final = timedelta(minutes=1)
"""Polling de l'état des voies BPC (pompe, lumières). Fréquence élevée pour
la réactivité. Le coordinator skippe les appels API si rien n'est actif
(voir EasyCareBPCCoordinator pour la logique adaptative)."""

SCAN_INTERVAL_BPC_IDLE_FACTOR: Final = 10
"""Quand aucune voie BPC n'est active, on poll en réalité tous les
SCAN_INTERVAL_BPC * 10 = 10 minutes."""

SCAN_INTERVAL_POOL_STATUS: Final = timedelta(minutes=5)
"""Polling de getPoolStatus (mode filtration + boost + compteurs)."""

# ─────────────────────────────────────────────────────────────────────────────
# Types de modules connus (champ "type" retourné par /api/getUserWithHisModules)
# ─────────────────────────────────────────────────────────────────────────────

MODULE_TYPE_WATBOX: Final = "lr-bst-compact"
"""Passerelle WATBOX — concentre les communications LoRa des autres modules."""

MODULE_TYPE_BPC: Final = "lr-pc"
"""Boîtier Piscine Connecté — pilote pompe et lumières via le tableau électrique."""

MODULE_TYPE_AC1: Final = "lr-mas"
"""Analyseur Connecté — mesure pH, chlore (redox), température."""

MODULE_TYPE_PRESSURE: Final = "lr-pr"
"""Capteur de pression filtration (optionnel)."""

# Tous les types connus dans l'écosystème Waterair (depuis APK)
KNOWN_MODULE_TYPES: Final = frozenset({
    MODULE_TYPE_WATBOX,
    MODULE_TYPE_BPC,
    MODULE_TYPE_AC1,
    MODULE_TYPE_PRESSURE,
    "lr-ag", "lr-can", "lr-fl", "lr-ip", "lr-is",
    "lr-light", "lr-mb", "lr-mpc", "lr-ms", "lr-niv",
    "lr-ol", "lr-pg",
})

# ─────────────────────────────────────────────────────────────────────────────
# Voies du BPC (index dans bpc_modules[]) — confirmé par l'APK et le plugin existant
# ─────────────────────────────────────────────────────────────────────────────

BPC_INDEX_PUMP: Final = 0
"""Voie 0 = pompe de filtration."""

BPC_INDEX_SPOT: Final = 1
"""Voie 1 = projecteur principal (spot)."""

BPC_INDEX_ESCALIGHT: Final = 2
"""Voie 2 = éclairage des marches (escalight). Présent si numberOfInputs >= 2."""

# Actions pour l'endpoint /api/module/.../manual/...
BPC_ACTION_OFF: Final = 1
"""Action OFF dans le payload JSON."""

BPC_ACTION_ON: Final = 2
"""Action ON dans le payload JSON. Nécessite aussi `manualDuration` en secondes."""

# Durées par défaut pour les voies (en secondes)
DEFAULT_DURATION_PUMP_HOURS: Final = 1
"""Durée par défaut quand on active la pompe via le switch."""

DEFAULT_DURATION_LIGHT_HOURS: Final = 1
"""Durée par défaut quand on active une lumière via la commande light.turn_on."""

# ─────────────────────────────────────────────────────────────────────────────
# Modes de filtration (champ "mode" de getPoolStatus, valeurs setStatusCommand)
# ─────────────────────────────────────────────────────────────────────────────

MODE_AUTO: Final = "AUTO"
"""Mode automatique — durée ajustée selon la température de l'eau."""

MODE_CONTINUOUS: Final = "CONTINUOUS"
"""Marche forcée (= 'ON' dans l'UI mobile)."""

MODE_MANUAL: Final = "MANUAL"
"""Arrêt forcé (= 'OFF' dans l'UI mobile)."""

MODE_PROG: Final = "PROG"
"""Programmation horaire par l'utilisateur."""

FILTRATION_MODES: Final = (MODE_AUTO, MODE_CONTINUOUS, MODE_MANUAL, MODE_PROG)
"""Tous les modes principaux exposés via le select HA."""

# Modes Boost (durées prédéfinies)
BOOST_MODE: Final = "BOOST"
"""Boost avec durée custom (nécessite boostDuration en heures)."""

BOOST_MODE_12H: Final = "BOOST12H"
"""Boost 12 heures."""

BOOST_MODE_24H: Final = "BOOST24H"
"""Boost 24 heures."""

BOOST_CANCEL: Final = "CANCELCURRENTBOOST"
"""Annulation du boost en cours."""

BOOST_MODES: Final = (BOOST_MODE_12H, BOOST_MODE_24H)
"""Modes boost exposés comme boutons HA."""

# ─────────────────────────────────────────────────────────────────────────────
# Identifiants de devices pour le Device Registry HA
# ─────────────────────────────────────────────────────────────────────────────

DEVICE_ID_ACCOUNT: Final = "account"
"""Device racine — représente le compte Waterair de l'utilisateur."""

DEVICE_ID_WATBOX: Final = "watbox"
"""Device WATBOX — la passerelle."""

DEVICE_ID_BPC: Final = "bpc"
"""Device BPC — le boîtier de pilotage."""

DEVICE_ID_AC1: Final = "ac1"
"""Device AC1 — l'analyseur."""

DEVICE_ID_PRESSURE: Final = "pressure"
"""Device LR-PR — le capteur de pression (si présent)."""

# ─────────────────────────────────────────────────────────────────────────────
# Services HA (callable depuis automations/scripts)
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_PUMP_ON: Final = "pump_on"
SERVICE_PUMP_OFF: Final = "pump_off"
SERVICE_SET_FILTRATION_MODE: Final = "set_filtration_mode"
SERVICE_START_BOOST: Final = "start_boost"
SERVICE_CANCEL_BOOST: Final = "cancel_boost"
SERVICE_REFRESH_DATA: Final = "refresh_data"

# ─────────────────────────────────────────────────────────────────────────────
# User-Agent — on imite l'app mobile pour éviter d'éventuels blocages serveur
# ─────────────────────────────────────────────────────────────────────────────

USER_AGENT: Final = "connected-pool-waterair/2.4.6 (iPad; iOS 16.3; Scale/2.00)"
"""User-Agent envoyé dans toutes les requêtes. Identique à l'app officielle iOS
(valeur extraite du plugin yyrkoon94 / APK)."""

# ─────────────────────────────────────────────────────────────────────────────
# Timeouts réseau (en secondes)
# ─────────────────────────────────────────────────────────────────────────────

HTTP_TIMEOUT: Final = 15
"""Timeout par défaut pour les requêtes HTTP."""

HTTP_TIMEOUT_AUTH: Final = 20
"""Timeout plus généreux pour les opérations d'authentification (plus lentes)."""

HTTP_MAX_RETRIES: Final = 3
"""Nombre max de tentatives en cas d'échec réseau."""

HTTP_RETRY_DELAY: Final = 1.0
"""Délai entre tentatives (en secondes)."""
