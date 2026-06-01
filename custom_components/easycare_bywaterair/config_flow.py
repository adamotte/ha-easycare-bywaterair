"""Config flow pour Easy-care by Waterair.

Étape 1 : saisie de l'email et du mot de passe Waterair. L'intégration gère
silencieusement le flow OAuth2 Azure B2C (PKCE, redirection msauth://).
Étape 2 (uniquement si le compte gère plusieurs piscines) : choix de la piscine
à configurer dans une liste déroulante. Les comptes mono-piscine (cas courant)
ne voient jamais cette étape.
Le reauth flow réutilise le même formulaire et conserve la piscine déjà choisie.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import section
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import DateSelector

from .api.auth import EasyCareAuth
from .api.client import EasyCareClient
from .api.exceptions import (
    EasyCareConnectionError,
    EasyCareError,
    EasyCareInvalidCredentialsError,
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
    CONF_PUMP_REPLACEMENT_DATE,
    CONF_PUMP_REPLACEMENT_PREVIOUS_POWER_W,
    CONF_PUMP_REPLACEMENT_RUNTIME_H,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
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
        # Tokens obtenus à l'étape 1, conservés en mémoire pour l'étape 2.
        self._pending_data: dict[str, Any] | None = None
        # Libellés des piscines (index 0 = pool_id 1), pour la liste déroulante.
        self._pool_labels: list[str] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "EasyCareOptionsFlow":
        return EasyCareOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape 1 : saisie email/mot de passe."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._async_login(user_input, errors)
        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Point d'entrée du reauth flow (appelé par HA automatiquement)."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape de confirmation du reauth — l'utilisateur fournit ses identifiants."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return await self._async_login(user_input, errors)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
        )

    async def async_step_pool(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape 2 : choix de la piscine (uniquement si le compte en gère plusieurs)."""
        if user_input is not None:
            pool_id = self._pool_labels.index(user_input[CONF_POOL_ID]) + 1
            return await self._async_finalize(pool_id)
        return self.async_show_form(
            step_id="pool",
            data_schema=vol.Schema({vol.Required(CONF_POOL_ID): vol.In(self._pool_labels)}),
        )

    async def _async_login(
        self, user_input: dict[str, Any], errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Valide les identifiants via le flow OAuth2 et oriente vers l'étape suivante."""
        email = user_input[CONF_USERNAME].strip()
        password = user_input[CONF_PASSWORD]
        session = async_get_clientsession(self.hass)
        auth = EasyCareAuth(session=session)
        try:
            tokens = await auth.login_with_credentials(email, password)
            bearer = auth.bearer
            client = EasyCareClient(session, auth, pool_id=1)
            pool_labels = await client.list_pools()
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
            if not pool_labels:
                errors["base"] = "invalid_pool_id"
                return self._show_form(errors)
            self._pending_data = {
                CONF_USERNAME: email,
                CONF_REFRESH_TOKEN: tokens.refresh_token,
                CONF_ID_TOKEN: tokens.id_token,
                CONF_ID_TOKEN_EXPIRES_AT: tokens.expires_at,
                CONF_BEARER: bearer.bearer if bearer else "",
                CONF_BEARER_EXPIRES_AT: bearer.expires_at if bearer else 0.0,
            }
            self._pool_labels = pool_labels
            # Reauth : on conserve la piscine déjà configurée, sans redemander.
            if self._reauth_entry is not None:
                return await self._async_finalize(self._reauth_entry.data.get(CONF_POOL_ID, 1))
            # Mono-piscine (cas courant) : on termine directement.
            if len(pool_labels) == 1:
                return await self._async_finalize(1)
            # Multi-piscines : on demande à l'utilisateur de choisir.
            return await self.async_step_pool()
        return self._show_form(errors)

    async def _async_finalize(self, pool_id: int) -> ConfigFlowResult:
        """Crée ou met à jour l'entry avec les tokens obtenus et la piscine choisie."""
        assert self._pending_data is not None
        data_to_save = {**self._pending_data, CONF_POOL_ID: pool_id}
        if self._reauth_entry is not None:
            self.hass.config_entries.async_update_entry(self._reauth_entry, data=data_to_save)
            await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
            return self.async_abort(reason="reauth_successful")
        await self.async_set_unique_id(f"easycare_pool_{pool_id}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=f"easy·care Piscine {pool_id}", data=data_to_save)

    def _show_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        """Ré-affiche le bon formulaire d'identifiants avec les erreurs."""
        if self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm", data_schema=STEP_REAUTH_DATA_SCHEMA, errors=errors,
            )
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors,
        )


class EasyCareOptionsFlow(OptionsFlow):
    """Options flow : puissance de la pompe et suivi de remplacement de pompe."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Étape unique : puissance pompe + section « remplacement de pompe »."""
        if user_input is not None:
            # La section imbrique ses champs ; on aplatit pour garder des options plates
            # (les capteurs lisent les options à plat, sans connaître la section).
            replacement = user_input.pop("pump_replacement", {})
            return self.async_create_entry(data={**user_input, **replacement})
        opts = self.config_entry.options
        current_power = opts.get(CONF_PUMP_POWER_W, 0)
        current_baseline = opts.get(CONF_PUMP_REPLACEMENT_RUNTIME_H, 0)
        current_prev_power = opts.get(CONF_PUMP_REPLACEMENT_PREVIOUS_POWER_W, 0)
        current_date = opts.get(CONF_PUMP_REPLACEMENT_DATE)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_PUMP_POWER_W, default=current_power): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=10000)
                ),
                vol.Required("pump_replacement"): section(
                    vol.Schema({
                        vol.Optional(
                            CONF_PUMP_REPLACEMENT_RUNTIME_H, default=current_baseline
                        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=100000)),
                        vol.Optional(
                            CONF_PUMP_REPLACEMENT_PREVIOUS_POWER_W, default=current_prev_power
                        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10000)),
                        vol.Optional(
                            CONF_PUMP_REPLACEMENT_DATE,
                            description={"suggested_value": current_date},
                        ): DateSelector(),
                    }),
                    # Repliée par défaut tant qu'aucun remplacement n'est configuré.
                    {"collapsed": current_baseline <= 0},
                ),
            }),
        )
