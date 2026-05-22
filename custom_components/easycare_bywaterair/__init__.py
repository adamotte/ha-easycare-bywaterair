"""Easy-care by Waterair — intégration Home Assistant.

Point d'entrée du plugin :
  - async_setup_entry  : initialisation d'une intégration depuis un ConfigEntry
  - async_unload_entry : nettoyage à la suppression
  - Enregistrement des appareils dans le device registry (WATBOX, BPC, AC1)
  - Déclaration des services HA (pump_on, set_filtration_mode, etc.)

Architecture en couches :

    ConfigEntry (UI HA)
        ↓ async_setup_entry()
    EasyCareAuth + EasyCareClient (api/)
        ↓
    3 coordinators (coordinator.py)
        ↓ async_first_refresh()
    Device Registry (devices créés : WATBOX → BPC → AC1)
        ↓ forward_entry_setups
    Plateformes (sensor, switch, etc.)
"""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.auth import EasyCareAuth
from .api.client import EasyCareClient
from .api.exceptions import EasyCareError, EasyCareTokenExpiredError
from .api.models import BearerToken, OAuthTokens
from .const import (
    BOOST_MODES,
    CONF_BEARER,
    CONF_BEARER_EXPIRES_AT,
    CONF_ID_TOKEN,
    CONF_ID_TOKEN_EXPIRES_AT,
    CONF_POOL_ID,
    CONF_REFRESH_TOKEN,
    DEVICE_ID_AC1,
    DEVICE_ID_BPC,
    DEVICE_ID_PRESSURE,
    DEVICE_ID_WATBOX,
    DOMAIN,
    FILTRATION_MODES,
    MANUFACTURER,
    MODULE_TYPE_AC1,
    MODULE_TYPE_BPC,
    MODULE_TYPE_PRESSURE,
    MODULE_TYPE_WATBOX,
    SERVICE_CANCEL_BOOST,
    SERVICE_PUMP_OFF,
    SERVICE_PUMP_ON,
    SERVICE_REFRESH_DATA,
    SERVICE_SET_FILTRATION_MODE,
    SERVICE_START_BOOST,
)
from .coordinator import (
    EasyCareBPCCoordinator,
    EasyCareCoordinators,
    EasyCareModulesCoordinator,
    EasyCareUserCoordinator,
)

_LOGGER = logging.getLogger(__name__)

# Plateformes HA qui seront initialisées par cette intégration.
# Chaque plateforme correspond à un fichier {platform}.py dans le dossier.
PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# ─────────────────────────────────────────────────────────────────────────────
# Schémas de validation des données de service (vol = Voluptuous)
# ─────────────────────────────────────────────────────────────────────────────

# Service pump_on — optionnel : durée en minutes (défaut 60)
SERVICE_PUMP_ON_SCHEMA = vol.Schema({
    vol.Optional("duration_minutes", default=60): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=1440)
    ),
})

# Service set_filtration_mode — mode obligatoire
SERVICE_SET_FILTRATION_MODE_SCHEMA = vol.Schema({
    vol.Required("mode"): vol.In(FILTRATION_MODES),
})

# Service start_boost — durée obligatoire (BOOST12H ou BOOST24H)
SERVICE_START_BOOST_SCHEMA = vol.Schema({
    vol.Required("duration"): vol.In(BOOST_MODES),
})


# ═════════════════════════════════════════════════════════════════════════════
# SETUP / UNLOAD ENTRY
# ═════════════════════════════════════════════════════════════════════════════


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialise une intégration Easy-care depuis un ConfigEntry.

    Étapes :
      1. Charger les tokens depuis ConfigEntry.data (créés par le config_flow)
      2. Créer la session HTTP partagée
      3. Créer EasyCareAuth avec callback de persistance des tokens rotés
      4. Créer EasyCareClient
      5. Créer et démarrer les 3 coordinators
      6. Enregistrer les appareils dans le device registry
      7. Forward vers les plateformes (sensor, switch, etc.)
      8. Enregistrer les services HA (au premier setup uniquement)

    Args:
        hass : instance HomeAssistant.
        entry: ConfigEntry contenant les tokens et pool_id.

    Returns:
        True si l'initialisation a réussi, False sinon (HA réessaiera).

    Raises:
        ConfigEntryNotReady    : erreur transitoire (réseau, etc.), HA retentera.
        ConfigEntryAuthFailed  : tokens expirés (levé indirectement via coordinators).
    """
    _LOGGER.debug("Setup entry %s", entry.entry_id)

    # 1. Chargement des tokens persistés
    try:
        oauth_tokens = _load_oauth_tokens(entry)
        bearer = _load_bearer(entry)
    except KeyError as err:
        _LOGGER.error(
            "ConfigEntry corrompu : champ manquant %s. "
            "Suppression et reconfiguration nécessaires.", err,
        )
        return False

    # 2. Session HTTP partagée (recommandée par HA pour partager les connexions)
    session = async_get_clientsession(hass)

    # 3. Auth avec callback de persistance des nouveaux tokens
    async def _save_tokens(new_tokens: OAuthTokens, new_bearer: BearerToken) -> None:
        """Persiste les tokens rotés dans ConfigEntry.data (zone chiffrée HA)."""
        new_data = {
            **entry.data,
            CONF_REFRESH_TOKEN: new_tokens.refresh_token,
            CONF_ID_TOKEN: new_tokens.id_token,
            CONF_ID_TOKEN_EXPIRES_AT: new_tokens.expires_at,
            CONF_BEARER: new_bearer.bearer,
            CONF_BEARER_EXPIRES_AT: new_bearer.expires_at,
        }
        hass.config_entries.async_update_entry(entry, data=new_data)
        _LOGGER.debug("Tokens persistés dans ConfigEntry (refresh_token rotaté)")

    auth = EasyCareAuth(
        session=session,
        oauth_tokens=oauth_tokens,
        bearer=bearer,
        on_tokens_updated=_save_tokens,
    )

    # 4. Client API
    pool_id = entry.data.get(CONF_POOL_ID, 1)
    client = EasyCareClient(session, auth, pool_id=pool_id)

    # 5. Coordinators + premier refresh
    coordinators = EasyCareCoordinators(
        user=EasyCareUserCoordinator(hass, client, entry),
        modules=EasyCareModulesCoordinator(hass, client, entry),
        bpc=EasyCareBPCCoordinator(hass, client, None, entry),  # type: ignore[arg-type]
    )
    # Wire-up : le BPC coordinator dépend du modules coordinator
    coordinators.bpc._modules = coordinators.modules  # noqa: SLF001 — wire-up nécessaire

    try:
        await coordinators.async_first_refresh()
    except EasyCareTokenExpiredError as err:
        # Devrait normalement être déjà converti en ConfigEntryAuthFailed
        # par le coordinator, mais on capture par sécurité.
        raise ConfigEntryNotReady(
            f"Tokens Azure expirés : {err}"
        ) from err
    except EasyCareError as err:
        # Erreur API transitoire — HA réessaiera plus tard
        raise ConfigEntryNotReady(
            f"Échec du premier refresh : {err}"
        ) from err

    # 6. Enregistrement des appareils dans le device registry
    await _async_register_devices(hass, entry, coordinators)

    # 7. Stockage des coordinators pour les plateformes
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinators

    # 8. Forward vers les plateformes (sensor.py, switch.py, etc.)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # 9. Enregistrement des services HA (une seule fois)
    _async_register_services(hass)

    # 10. Listener pour les options (si l'utilisateur change pool_id dans l'UI)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    _LOGGER.info(
        "Easy-care by Waterair initialisé (pool_id=%d, %d module(s))",
        pool_id,
        len(coordinators.modules.data or ()),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une intégration Easy-care lors de la suppression depuis l'UI."""
    _LOGGER.debug("Unload entry %s", entry.entry_id)

    # Unload des plateformes (sensor, switch, etc.)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

        # Si plus aucun entry actif, on retire les services
        if not hass.data.get(DOMAIN):
            _async_unregister_services(hass)

    return unload_ok


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'intégration quand les options changent (ex: pool_id)."""
    _LOGGER.debug("Options modifiées, reload de l'entry %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


# ═════════════════════════════════════════════════════════════════════════════
# DEVICE REGISTRY — création des appareils WATBOX / BPC / AC1
# ═════════════════════════════════════════════════════════════════════════════


async def _async_register_devices(
    hass: HomeAssistant,
    entry: ConfigEntry,
    coordinators: EasyCareCoordinators,
) -> None:
    """Enregistre les appareils physiques dans le device registry HA.

    Hiérarchie créée :

        WATBOX  (passerelle)
          ├── BPC      via_device=WATBOX
          ├── AC1      via_device=WATBOX
          └── LR-PR    via_device=WATBOX  (si présent)

    Chaque appareil aura ses propres entités rattachées (via DeviceInfo dans
    les classes d'entités). HA affiche alors une UI propre avec l'arbre des
    appareils dans Settings → Devices & Services.
    """
    device_registry = dr.async_get(hass)
    modules = coordinators.modules.data or ()

    # 1. WATBOX (passerelle) — doit être enregistré en premier (les autres ont via_device)
    watbox = coordinators.modules.get_watbox()
    if watbox is not None:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}")},
            manufacturer=MANUFACTURER,
            model="WATBOX",
            name=watbox.name,
            serial_number=watbox.serial_number,
            sw_version=None,  # pas exposé par l'API actuellement
        )
        _LOGGER.debug("Device enregistré : WATBOX %s", watbox.name)

    # 2. BPC — pilote pompe et lumières
    bpc = coordinators.modules.get_bpc()
    if bpc is not None:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}")},
            manufacturer=MANUFACTURER,
            model="BPC (Boîtier Piscine Connecté)",
            name=bpc.name,
            serial_number=bpc.serial_number,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )
        _LOGGER.debug("Device enregistré : BPC %s", bpc.name)

    # 3. AC1 — analyseur (peut être absent dans certaines installations)
    ac1_modules = coordinators.modules.get_modules_by_type(MODULE_TYPE_AC1)
    if ac1_modules:
        ac1 = ac1_modules[0]  # une seule AC1 par installation typiquement
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_AC1}")},
            manufacturer=MANUFACTURER,
            model="AC1 (Analyseur Connecté)",
            name=ac1.name,
            serial_number=ac1.serial_number,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )
        _LOGGER.debug("Device enregistré : AC1 %s", ac1.name)

    # 4. LR-PR — capteur de pression (optionnel)
    pressure_modules = coordinators.modules.get_modules_by_type(MODULE_TYPE_PRESSURE)
    if pressure_modules:
        lrpr = pressure_modules[0]
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_PRESSURE}")},
            manufacturer=MANUFACTURER,
            model="LR-PR (Capteur Pression)",
            name=lrpr.name,
            serial_number=lrpr.serial_number,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )
        _LOGGER.debug("Device enregistré : LR-PR %s", lrpr.name)


# ═════════════════════════════════════════════════════════════════════════════
# SERVICES HA — pump_on, pump_off, set_filtration_mode, etc.
# ═════════════════════════════════════════════════════════════════════════════


def _async_register_services(hass: HomeAssistant) -> None:
    """Enregistre les services HA exposés par l'intégration.

    Cette fonction est idempotente : si les services sont déjà enregistrés
    (autre ConfigEntry de la même intégration), elle ne fait rien.
    """
    if hass.services.has_service(DOMAIN, SERVICE_PUMP_ON):
        return  # déjà enregistré

    # Helpers internes pour obtenir les coordinators d'un entry
    async def _get_client_and_coords(call: ServiceCall) -> tuple[EasyCareClient, EasyCareCoordinators]:
        """Retourne le client et coordinators de la première entrée active.

        Si plusieurs entries existent (rare : plusieurs comptes Waterair),
        on prend la première — l'utilisateur peut être plus précis en passant
        un `entry_id` dans les données du service (TODO si demandé).
        """
        entries = hass.data.get(DOMAIN, {})
        if not entries:
            raise vol.Invalid("Aucune intégration Easy-care active")
        entry_id = next(iter(entries))
        coords: EasyCareCoordinators = entries[entry_id]
        # Le client est embarqué dans l'auth, accessible via les coordinators
        # via leur attribut interne _client. On utilise une référence stable :
        client = coords.user._client  # noqa: SLF001 — accès interne légitime ici
        return client, coords

    # ─── Service : pump_on ───
    async def handle_pump_on(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        watbox = coords.modules.get_watbox()
        bpc = coords.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("pump_on : WATBOX ou BPC introuvable")
            return
        duration = call.data.get("duration_minutes", 60)
        await client.set_bpc_manual(
            watbox, bpc, index=0, action="on", duration_minutes=duration
        )
        await coords.bpc.async_request_immediate_refresh()
        _LOGGER.info("Service pump_on exécuté (durée=%d min)", duration)

    # ─── Service : pump_off ───
    async def handle_pump_off(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        watbox = coords.modules.get_watbox()
        bpc = coords.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("pump_off : WATBOX ou BPC introuvable")
            return
        await client.set_bpc_manual(watbox, bpc, index=0, action="off")
        await coords.bpc.async_request_immediate_refresh()
        _LOGGER.info("Service pump_off exécuté")

    # ─── Service : set_filtration_mode ───
    async def handle_set_filtration_mode(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        mode = call.data["mode"]
        await client.set_filtration_mode(mode)
        await coords.bpc.async_request_immediate_refresh()
        _LOGGER.info("Service set_filtration_mode exécuté (mode=%s)", mode)

    # ─── Service : start_boost ───
    async def handle_start_boost(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        duration = call.data["duration"]
        await client.start_boost(duration)
        await coords.bpc.async_request_immediate_refresh()
        _LOGGER.info("Service start_boost exécuté (durée=%s)", duration)

    # ─── Service : cancel_boost ───
    async def handle_cancel_boost(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        await client.cancel_boost()
        await coords.bpc.async_request_immediate_refresh()
        _LOGGER.info("Service cancel_boost exécuté")

    # ─── Service : refresh_data ───
    async def handle_refresh_data(call: ServiceCall) -> None:
        _, coords = await _get_client_and_coords(call)
        import asyncio
        await asyncio.gather(
            coords.user.async_request_refresh(),
            coords.modules.async_request_refresh(),
            coords.bpc.async_request_immediate_refresh(),
        )
        _LOGGER.info("Service refresh_data exécuté (tous coordinators)")

    # Enregistrement effectif
    hass.services.async_register(
        DOMAIN, SERVICE_PUMP_ON, handle_pump_on, schema=SERVICE_PUMP_ON_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_PUMP_OFF, handle_pump_off)
    hass.services.async_register(
        DOMAIN, SERVICE_SET_FILTRATION_MODE, handle_set_filtration_mode,
        schema=SERVICE_SET_FILTRATION_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_START_BOOST, handle_start_boost,
        schema=SERVICE_START_BOOST_SCHEMA,
    )
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_BOOST, handle_cancel_boost)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_DATA, handle_refresh_data)

    _LOGGER.debug("Services HA enregistrés (6 services)")


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Retire les services HA quand plus aucune intégration n'est active."""
    for svc in (
        SERVICE_PUMP_ON,
        SERVICE_PUMP_OFF,
        SERVICE_SET_FILTRATION_MODE,
        SERVICE_START_BOOST,
        SERVICE_CANCEL_BOOST,
        SERVICE_REFRESH_DATA,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)
    _LOGGER.debug("Services HA retirés")


# ═════════════════════════════════════════════════════════════════════════════
# HELPERS PRIVÉS — chargement des tokens depuis ConfigEntry
# ═════════════════════════════════════════════════════════════════════════════


def _load_oauth_tokens(entry: ConfigEntry) -> OAuthTokens:
    """Reconstruit OAuthTokens depuis les données persistées de ConfigEntry.

    Note : access_token n'est pas persisté car non utilisé directement par nous
    (on passe par id_token → bearer). On stocke un placeholder.

    Raises:
        KeyError: si refresh_token ou id_token manquent.
    """
    return OAuthTokens(
        access_token="",  # non utilisé en aval, OK
        id_token=entry.data[CONF_ID_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data.get(CONF_ID_TOKEN_EXPIRES_AT, 0.0),
    )


def _load_bearer(entry: ConfigEntry) -> BearerToken | None:
    """Reconstruit BearerToken depuis ConfigEntry, ou None si absent.

    Si le bearer n'a jamais été persisté (ex : premier démarrage après
    config_flow qui ne l'aurait pas sauvé), il sera regénéré au premier
    appel à `auth.get_valid_bearer()`.
    """
    bearer = entry.data.get(CONF_BEARER)
    if not bearer:
        return None
    return BearerToken(
        bearer=bearer,
        expires_at=entry.data.get(CONF_BEARER_EXPIRES_AT, 0.0),
    )
