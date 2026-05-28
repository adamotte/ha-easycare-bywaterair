"""Config flow pour Easy-care by Waterair.

Étape unique : saisie de l'email et du mot de passe Waterair. L'intégration
gère silencieusement le flow OAuth2 Azure B2C (PKCE, redirection msauth://).
Le reauth flow réutilise le même formulaire sans recréer le ConfigEntry.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.auth import EasyCareAuth
from .api.client import EasyCareClient
from .api.exceptions import (
    EasyCareConnectionError,
    EasyCareError,
    EasyCareInvalidCredentialsError,
    EasyCareInvalidResponseError,
    EasyCareLoginError,
    EasyCareTimeoutError,
)
from .const import (
    CONF_BEARER,
    CONF_BEARER_EXPIRES_AT,
    CONF_ID_TOKEN,
    CONF_ID_TOKEN_EXPIRES_AT,
    CONF_POOL_ID,
    CONF_PUMP_POWER_W,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
    vol.Optional(CONF_POOL_ID, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
})

STEP_REAUTH_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


class EasyCareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow pour Easy-care by Waterair."""

    VERSION = 1

    def __init__(self) -> None:
        self._reauth_entry: ConfigEntry | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "EasyCareOptionsFlow":
        return EasyCareOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape principale : saisie email/mot de passe."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._async_validate_and_create(user_input, errors)
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Point d'entrée du reauth flow (appelé par HA automatiquement)."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape de confirmation du reauth — l'utilisateur fournit ses identifiants."""
        errors: dict[str, str] = {}
        if user_input is not None:
            assert self._reauth_entry is not None
            user_input[CONF_POOL_ID] = self._reauth_entry.data.get(CONF_POOL_ID, 1)
            return await self._async_validate_and_create(user_input, errors)
        return self.async_show_form(step_id="reauth_confirm", data_schema=STEP_REAUTH_DATA_SCHEMA)

    async def _async_validate_and_create(
        self, user_input: dict[str, Any], errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Valide les identifiants via le flow OAuth2 Azure B2C et crée/met à jour l'entry."""
        email = user_input[CONF_USERNAME].strip()
        password = user_input[CONF_PASSWORD]
        pool_id = user_input.get(CONF_POOL_ID, 1)
        session = async_get_clientsession(self.hass)
        auth = EasyCareAuth(session=session)
        try:
            tokens = await auth.login_with_credentials(email, password)
            bearer = auth.bearer
            client = EasyCareClient(session, auth, pool_id=pool_id)
            try:
                await client.get_user()
            except EasyCareInvalidResponseError as err:
                if "hors limites" in str(err) or "Aucune piscine" in str(err):
                    errors["base"] = "invalid_pool_id"
                    return self._show_form(errors)
                raise
        except EasyCareInvalidCredentialsError:
            errors["base"] = "invalid_credentials"
        except EasyCareLoginError:
            _LOGGER.exception("Échec du flow de login Azure B2C")
            errors["base"] = "login_failed"
        except EasyCareTimeoutError:
            errors["base"] = "timeout"
        except EasyCareConnectionError:
            errors["base"] = "cannot_connect"
        except EasyCareError:
            _LOGGER.exception("Erreur inattendue pendant le config flow")
            errors["base"] = "unknown"
        else:
            data_to_save = {
                CONF_REFRESH_TOKEN: tokens.refresh_token,
                CONF_ID_TOKEN: tokens.id_token,
                CONF_ID_TOKEN_EXPIRES_AT: tokens.expires_at,
                CONF_BEARER: bearer.bearer if bearer else "",
                CONF_BEARER_EXPIRES_AT: bearer.expires_at if bearer else 0.0,
                CONF_POOL_ID: pool_id,
            }
            if self._reauth_entry is not None:
                self.hass.config_entries.async_update_entry(self._reauth_entry, data=data_to_save)
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            await self.async_set_unique_id(f"easycare_pool_{pool_id}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"easy·care Piscine {pool_id}", data=data_to_save)
        return self._show_form(errors)

    def _show_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        """Ré-affiche le bon formulaire avec les erreurs."""
        if self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=STEP_REAUTH_DATA_SCHEMA, errors=errors,
            )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
        )


class EasyCareOptionsFlow(OptionsFlow):
    """Options flow pour configurer la puissance de la pompe."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape unique : saisie de la puissance nominale de la pompe."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current_power = self.config_entry.options.get(CONF_PUMP_POWER_W, 0)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_PUMP_POWER_W, default=current_power): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10000)
                ),
            }),
        )
