"""Easy-care by Waterair — intégration Home Assistant."""

from __future__ import annotations

import logging
from typing import Final

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import device_registry as dr, issue_registry as ir
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

PLATFORMS: Final = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.LIGHT,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.UPDATE,
]

SERVICE_PUMP_ON_SCHEMA = vol.Schema({
    vol.Optional("duration_minutes", default=60): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=1440)
    ),
})

SERVICE_SET_FILTRATION_MODE_SCHEMA = vol.Schema({
    vol.Required("mode"): vol.In(FILTRATION_MODES),
})

SERVICE_START_BOOST_SCHEMA = vol.Schema({
    vol.Required("duration"): vol.In(BOOST_MODES),
})

# Identifiant de base du repair issue "BPC non standard" (issue #10).
ISSUE_BPC_VARIANT: Final = "bpc_variant"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialise une intégration Easy-care depuis un ConfigEntry."""
    _LOGGER.debug("Setup entry %s", entry.entry_id)

    try:
        oauth_tokens = _load_oauth_tokens(entry)
        bearer = _load_bearer(entry)
    except KeyError as err:
        _LOGGER.error("Corrupted ConfigEntry: missing field %s", err)
        return False

    session = async_get_clientsession(hass)

    async def _save_tokens(new_tokens: OAuthTokens, new_bearer: BearerToken) -> None:
        """Persiste les tokens rotés dans ConfigEntry.data."""
        new_data = {
            **entry.data,
            CONF_REFRESH_TOKEN: new_tokens.refresh_token,
            CONF_ID_TOKEN: new_tokens.id_token,
            CONF_ID_TOKEN_EXPIRES_AT: new_tokens.expires_at,
            CONF_BEARER: new_bearer.bearer,
            CONF_BEARER_EXPIRES_AT: new_bearer.expires_at,
        }
        hass.config_entries.async_update_entry(entry, data=new_data)

    auth = EasyCareAuth(session=session, oauth_tokens=oauth_tokens, bearer=bearer, on_tokens_updated=_save_tokens)
    pool_id = entry.data.get(CONF_POOL_ID, 1)
    client = EasyCareClient(session, auth, pool_id=pool_id)

    coordinators = EasyCareCoordinators(
        user=EasyCareUserCoordinator(hass, client, entry),
        modules=EasyCareModulesCoordinator(hass, client, entry),
        bpc=EasyCareBPCCoordinator(hass, client, None, entry),  # type: ignore[arg-type]
    )
    coordinators.bpc._modules = coordinators.modules  # noqa: SLF001

    try:
        await coordinators.async_first_refresh()
    except EasyCareTokenExpiredError as err:
        raise ConfigEntryNotReady(f"Azure tokens expired: {err}") from err
    except EasyCareError as err:
        raise ConfigEntryNotReady(f"First refresh failed: {err}") from err

    await _async_register_devices(hass, entry, coordinators)
    _async_manage_bpc_issue(hass, entry, coordinators)
    _async_log_bpc_diagnostics(coordinators)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    _LOGGER.info(
        "Easy-care by Waterair initialised (pool_id=%d, %d module(s))",
        pool_id, len(coordinators.modules.data or ()),
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Décharge une intégration Easy-care."""
    _LOGGER.debug("Unload entry %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            _async_unregister_services(hass)
    return unload_ok


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recharge l'intégration quand les options changent."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_devices(
    hass: HomeAssistant, entry: ConfigEntry, coordinators: EasyCareCoordinators,
) -> None:
    """Enregistre les appareils physiques dans le device registry HA."""
    device_registry = dr.async_get(hass)

    watbox = coordinators.modules.get_watbox()
    if watbox is not None:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}")},
            manufacturer=MANUFACTURER, model="WATBOX",
            name=watbox.name, serial_number=watbox.serial_number,
            hw_version=watbox.type,
        )

    bpc = coordinators.modules.get_bpc()
    if bpc is not None:
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_BPC}")},
            manufacturer=MANUFACTURER, model="BPC (Boîtier Piscine Connecté)",
            name=bpc.name, serial_number=bpc.serial_number,
            hw_version=bpc.type,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )

    ac1_modules = coordinators.modules.get_modules_by_type(MODULE_TYPE_AC1)
    if ac1_modules:
        ac1 = ac1_modules[0]
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_AC1}")},
            manufacturer=MANUFACTURER, model="AC1 (Analyseur Connecté)",
            name=ac1.name, serial_number=ac1.serial_number,
            hw_version=ac1.type,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )

    pressure_modules = coordinators.modules.get_modules_by_type(MODULE_TYPE_PRESSURE)
    if pressure_modules:
        lrpr = pressure_modules[0]
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_PRESSURE}")},
            manufacturer=MANUFACTURER, model="LR-PR (Capteur Pression)",
            name=lrpr.name, serial_number=lrpr.serial_number,
            hw_version=lrpr.type,
            via_device=(DOMAIN, f"{entry.entry_id}_{DEVICE_ID_WATBOX}"),
        )


def _async_manage_bpc_issue(
    hass: HomeAssistant, entry: ConfigEntry, coordinators: EasyCareCoordinators,
) -> None:
    """Crée ou supprime un repair issue selon l'état du BPC (issue #10).

    - BPC non standard (ex. BPC2/lr-ph) → issue d'avertissement « variante ».
    - Voie pompe (index 0) absente en plus → issue « commandes désactivées »
      (les entités de commande ne sont pas créées et les services sont refusés).
    """
    issue_id = f"{ISSUE_BPC_VARIANT}_{entry.entry_id}"
    nonstandard = coordinators.is_bpc_nonstandard()
    blocked = coordinators.is_bpc_commands_blocked()
    if not nonstandard and not blocked:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
        return
    bpc = coordinators.modules.get_bpc()
    ir.async_create_issue(
        hass, DOMAIN, issue_id,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key="bpc_commands_blocked" if blocked else "bpc_unsupported_variant",
        translation_placeholders={
            "bpc_type": bpc.type if bpc is not None else "?",
            "bpc_name": bpc.name if bpc is not None else "?",
            "issues_url": "https://github.com/adamotte/ha-easycare-bywaterair/issues",
        },
    )


def _async_log_bpc_diagnostics(coordinators: EasyCareCoordinators) -> None:
    """Logue l'inventaire des voies du BPC à des fins de diagnostic (issue #11).

    Pour les variantes non standard (BPC2 `lr-ph`), l'agencement des voies n'est
    pas garanti : les index codés en dur (pompe=0, spot=1, escalight=2) peuvent
    différer. Ce log expose les sorties réelles (`index:nom`) **et les clés brutes
    du module**, afin qu'un utilisateur BPC2 puisse les remonter — ce qui révèle
    l'index réel de la doseuse pH (`phOutput`) et les champs pH non encore parsés
    (`pHPumpFlow`, `pHSetpoint`…). Purement diagnostic : aucune commande n'est
    envoyée. Niveau INFO pour les variantes non standard (rare, ciblé), DEBUG
    sinon.
    """
    bpc = coordinators.modules.get_bpc()
    if bpc is None:
        return
    if bpc.outputs:
        channels = ", ".join(f"{o.index}:{o.name!r}" for o in bpc.outputs)
    else:
        channels = "<none returned by API>"
    if coordinators.is_bpc_nonstandard():
        raw_keys = ", ".join(sorted(bpc.raw)) if bpc.raw else "<empty>"
        _LOGGER.info(
            "BPC diagnostic (non-standard variant: type=%s, name=%s): "
            "%d input(s), output channels=[%s]. Module keys=[%s]. "
            "Please report these details to help add full BPC2 support (issue #11).",
            bpc.type, bpc.name, bpc.number_of_inputs, channels, raw_keys,
        )
    else:
        _LOGGER.debug(
            "BPC channel inventory (type=%s): %d input(s), output channels=[%s]",
            bpc.type, bpc.number_of_inputs, channels,
        )


def _ensure_bpc_commands_enabled(coords: EasyCareCoordinators) -> None:
    """Lève ServiceValidationError si les commandes BPC sont bloquées (issue #10)."""
    if coords.is_bpc_commands_blocked():
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="bpc_commands_blocked_service",
        )


def _async_register_services(hass: HomeAssistant) -> None:
    """Enregistre les services HA exposés par l'intégration (idempotent)."""
    if hass.services.has_service(DOMAIN, SERVICE_PUMP_ON):
        return

    async def _get_client_and_coords(call: ServiceCall) -> tuple[EasyCareClient, EasyCareCoordinators]:
        """Retourne le client et les coordinators de la première entrée active."""
        entries = hass.data.get(DOMAIN, {})
        if not entries:
            raise vol.Invalid("No active Easy-care integration")
        entry_id = next(iter(entries))
        coords: EasyCareCoordinators = entries[entry_id]
        client = coords.user._client  # noqa: SLF001
        return client, coords

    async def handle_pump_on(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        watbox = coords.modules.get_watbox()
        bpc = coords.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("pump_on: WATBOX or BPC not found")
            return
        _ensure_bpc_commands_enabled(coords)
        duration = call.data.get("duration_minutes", 60)
        await client.set_bpc_manual(watbox, bpc, index=0, action="on", duration_minutes=duration)
        await coords.bpc.async_request_immediate_refresh()

    async def handle_pump_off(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        watbox = coords.modules.get_watbox()
        bpc = coords.modules.get_bpc()
        if watbox is None or bpc is None:
            _LOGGER.error("pump_off: WATBOX or BPC not found")
            return
        _ensure_bpc_commands_enabled(coords)
        await client.set_bpc_manual(watbox, bpc, index=0, action="off")
        await coords.bpc.async_request_immediate_refresh()

    async def handle_set_filtration_mode(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        _ensure_bpc_commands_enabled(coords)
        await client.set_filtration_mode(call.data["mode"])
        await coords.bpc.async_request_immediate_refresh()

    async def handle_start_boost(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        _ensure_bpc_commands_enabled(coords)
        await client.start_boost(call.data["duration"])
        await coords.bpc.async_request_immediate_refresh()

    async def handle_cancel_boost(call: ServiceCall) -> None:
        client, coords = await _get_client_and_coords(call)
        _ensure_bpc_commands_enabled(coords)
        await client.cancel_boost()
        await coords.bpc.async_request_immediate_refresh()

    async def handle_refresh_data(call: ServiceCall) -> None:
        _, coords = await _get_client_and_coords(call)
        import asyncio
        await asyncio.gather(
            coords.user.async_request_refresh(),
            coords.modules.async_request_refresh(),
            coords.bpc.async_request_immediate_refresh(),
        )

    hass.services.async_register(DOMAIN, SERVICE_PUMP_ON, handle_pump_on, schema=SERVICE_PUMP_ON_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_PUMP_OFF, handle_pump_off)
    hass.services.async_register(DOMAIN, SERVICE_SET_FILTRATION_MODE, handle_set_filtration_mode, schema=SERVICE_SET_FILTRATION_MODE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_START_BOOST, handle_start_boost, schema=SERVICE_START_BOOST_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_CANCEL_BOOST, handle_cancel_boost)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_DATA, handle_refresh_data)
    _LOGGER.debug("HA services registered")


def _async_unregister_services(hass: HomeAssistant) -> None:
    """Retire les services HA quand plus aucune intégration n'est active."""
    for svc in (
        SERVICE_PUMP_ON, SERVICE_PUMP_OFF, SERVICE_SET_FILTRATION_MODE,
        SERVICE_START_BOOST, SERVICE_CANCEL_BOOST, SERVICE_REFRESH_DATA,
    ):
        if hass.services.has_service(DOMAIN, svc):
            hass.services.async_remove(DOMAIN, svc)


def _load_oauth_tokens(entry: ConfigEntry) -> OAuthTokens:
    """Reconstruit OAuthTokens depuis les données persistées de ConfigEntry."""
    return OAuthTokens(
        access_token="",
        id_token=entry.data[CONF_ID_TOKEN],
        refresh_token=entry.data[CONF_REFRESH_TOKEN],
        expires_at=entry.data.get(CONF_ID_TOKEN_EXPIRES_AT, 0.0),
    )


def _load_bearer(entry: ConfigEntry) -> BearerToken | None:
    """Reconstruit BearerToken depuis ConfigEntry, ou None si absent."""
    bearer = entry.data.get(CONF_BEARER)
    if not bearer:
        return None
    return BearerToken(bearer=bearer, expires_at=entry.data.get(CONF_BEARER_EXPIRES_AT, 0.0))
