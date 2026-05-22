"""Config flow pour Easy-care by Waterair.

Workflow utilisateur (deux étapes) :

    ┌─ Étape 1 : Authorize ─────────────────────────────────────────────┐
    │                                                                     │
    │  Affichage :                                                        │
    │   • Lien à cliquer (URL OAuth2 Waterair)                            │
    │   • Instructions pour copier le code après login                    │
    │                                                                     │
    │  Action utilisateur :                                               │
    │   • Cliquer sur le lien                                             │
    │   • Se connecter avec ses identifiants Waterair                     │
    │   • Le navigateur tente de rediriger vers msauth://... (erreur)     │
    │   • Copier le `code` depuis la barre d'adresse                      │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘
                                  ↓
    ┌─ Étape 2 : User input ────────────────────────────────────────────┐
    │                                                                     │
    │  Affichage :                                                        │
    │   • Champ "Code OAuth" (saisie)                                     │
    │   • Champ "Pool ID" optionnel (défaut: 1)                           │
    │                                                                     │
    │  Action utilisateur :                                               │
    │   • Coller le code, valider                                         │
    │                                                                     │
    │  Backend :                                                          │
    │   • Échange code → tokens Azure (access + id + refresh)             │
    │   • Échange id_token → bearer EasyCare                              │
    │   • Test d'un appel API (get_user) pour validation                  │
    │   • Création de ConfigEntry avec les tokens persistés               │
    │                                                                     │
    └─────────────────────────────────────────────────────────────────────┘

Reauth flow :

    Si plus tard le refresh_token expire (14j+ d'inactivité), HA déclenche
    automatiquement `async_step_reauth` qui réutilise le même formulaire,
    mais sans recréer le ConfigEntry — on met juste à jour les tokens.

Single-instance :
    Une seule intégration Easy-care par compte est suggérée (unique_id =
    pool_id). L'utilisateur peut ajouter plusieurs comptes en utilisant
    différents pool_id ou différents emails.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api.auth import EasyCareAuth
from .api.client import EasyCareClient
from .api.exceptions import (
    EasyCareConnectionError,
    EasyCareError,
    EasyCareInvalidCodeError,
    EasyCareInvalidResponseError,
    EasyCareTimeoutError,
)
from .const import (
    CONF_AUTH_CODE,
    CONF_BEARER,
    CONF_BEARER_EXPIRES_AT,
    CONF_ID_TOKEN,
    CONF_ID_TOKEN_EXPIRES_AT,
    CONF_POOL_ID,
    CONF_REFRESH_TOKEN,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


# Schéma de saisie de l'étape 2 — code OAuth + pool_id optionnel
STEP_USER_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_AUTH_CODE): str,
    vol.Optional(CONF_POOL_ID, default=1): vol.All(
        vol.Coerce(int), vol.Range(min=1, max=10)
    ),
})

# Schéma pour le reauth — pas de pool_id (on garde l'existant)
STEP_REAUTH_DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_AUTH_CODE): str,
})


class EasyCareConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow pour Easy-care by Waterair."""

    VERSION = 1
    """Version du schéma de ConfigEntry. À incrémenter lors de migrations futures."""

    # ────────────────────────────────────────────────────────────────────────
    # État interne (entre les étapes)
    # ────────────────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        """Initialise un nouveau flow."""
        self._reauth_entry: ConfigEntry | None = None
        """Pour le flow reauth : l'entry à mettre à jour (pas à créer)."""

    # ────────────────────────────────────────────────────────────────────────
    # Étape 1 — Présentation du lien d'autorisation
    # ────────────────────────────────────────────────────────────────────────

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Première étape : affichage du lien + saisie du code.

        On utilise un seul step combiné (Auth URL affichée en description +
        formulaire de saisie) pour éviter de demander un "Suivant" inutile à
        l'utilisateur. HA affichera la `description_placeholders` dans le texte
        d'instruction du formulaire.
        """
        errors: dict[str, str] = {}

        # Si l'utilisateur a soumis le formulaire, on traite
        if user_input is not None:
            return await self._async_validate_and_create(user_input, errors)

        # Sinon, on affiche le formulaire avec l'URL d'autorisation
        authorize_url = EasyCareAuth.build_authorize_url()

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            description_placeholders={
                "authorize_url": authorize_url,
                "authorize_url_raw": authorize_url,
            },
            errors=errors,
        )

    # ────────────────────────────────────────────────────────────────────────
    # Reauth — déclenché par HA quand le refresh_token expire
    # ────────────────────────────────────────────────────────────────────────

    async def async_step_reauth(
        self,
        entry_data: dict[str, Any],
    ) -> ConfigFlowResult:
        """Point d'entrée du reauth flow (appelé par HA automatiquement)."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Étape de confirmation du reauth — l'utilisateur fournit un nouveau code."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # On garde le pool_id existant
            assert self._reauth_entry is not None
            user_input[CONF_POOL_ID] = self._reauth_entry.data.get(CONF_POOL_ID, 1)
            return await self._async_validate_and_create(user_input, errors)

        authorize_url = EasyCareAuth.build_authorize_url()
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_REAUTH_DATA_SCHEMA,
            description_placeholders={
                "authorize_url": authorize_url,
                "authorize_url_raw": authorize_url,
            },
            errors=errors,
        )

    # ────────────────────────────────────────────────────────────────────────
    # Logique commune setup / reauth : valider le code et créer/MAJ l'entry
    # ────────────────────────────────────────────────────────────────────────

    async def _async_validate_and_create(
        self,
        user_input: dict[str, Any],
        errors: dict[str, str],
    ) -> ConfigFlowResult:
        """Valide le code OAuth, échange contre tokens, et crée/met à jour l'entry.

        Args:
            user_input: données du formulaire (code + pool_id).
            errors    : dict mutable pour accumuler les erreurs à afficher.

        Returns:
            ConfigFlowResult — création/mise à jour réussie OU réaffichage du
            formulaire avec erreurs.
        """
        code = user_input[CONF_AUTH_CODE].strip()
        pool_id = user_input.get(CONF_POOL_ID, 1)

        # Nettoyer si l'utilisateur a collé une URL complète au lieu du code seul
        code = self._extract_code(code)

        session = async_get_clientsession(self.hass)
        auth = EasyCareAuth(session=session)

        try:
            # 1. Échange code → tokens (Azure) → bearer (EasyCare)
            tokens = await auth.exchange_code(code)
            bearer = auth.bearer

            # 2. Test : appel get_user pour vérifier que le pool_id est valide
            client = EasyCareClient(session, auth, pool_id=pool_id)
            try:
                await client.get_user()
            except EasyCareInvalidResponseError as err:
                if "hors limites" in str(err) or "Aucune piscine" in str(err):
                    errors["base"] = "invalid_pool_id"
                    return self._show_form(errors)
                raise

        except EasyCareInvalidCodeError:
            errors[CONF_AUTH_CODE] = "invalid_auth_code"
        except EasyCareTimeoutError:
            errors["base"] = "timeout"
        except EasyCareConnectionError:
            errors["base"] = "cannot_connect"
        except EasyCareError as err:
            _LOGGER.exception("Erreur inattendue pendant le config flow")
            errors["base"] = "unknown"
        else:
            # 3. Succès — création (ou mise à jour si reauth) de l'entry
            data_to_save = {
                CONF_REFRESH_TOKEN: tokens.refresh_token,
                CONF_ID_TOKEN: tokens.id_token,
                CONF_ID_TOKEN_EXPIRES_AT: tokens.expires_at,
                CONF_BEARER: bearer.bearer if bearer else "",
                CONF_BEARER_EXPIRES_AT: bearer.expires_at if bearer else 0.0,
                CONF_POOL_ID: pool_id,
            }

            if self._reauth_entry is not None:
                # Reauth — mise à jour de l'entry existante
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry, data=data_to_save,
                )
                await self.hass.config_entries.async_reload(self._reauth_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

            # Setup initial — création d'un nouvel entry
            # Unique ID pour éviter les doublons (même pool_id = même piscine)
            await self.async_set_unique_id(f"easycare_pool_{pool_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Easy-care Piscine {pool_id}",
                data=data_to_save,
            )

        # En cas d'erreur, ré-afficher le formulaire avec les messages
        return self._show_form(errors)

    # ────────────────────────────────────────────────────────────────────────
    # Helpers privés
    # ────────────────────────────────────────────────────────────────────────

    def _show_form(self, errors: dict[str, str]) -> ConfigFlowResult:
        """Ré-affiche le bon formulaire (setup ou reauth) avec les erreurs."""
        authorize_url = EasyCareAuth.build_authorize_url()
        placeholders = {
            "authorize_url": authorize_url,
            "authorize_url_raw": authorize_url,
        }

        if self._reauth_entry is not None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=STEP_REAUTH_DATA_SCHEMA,
                description_placeholders=placeholders,
                errors=errors,
            )
        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            description_placeholders=placeholders,
            errors=errors,
        )

    @staticmethod
    def _extract_code(input_str: str) -> str:
        """Extrait le code OAuth si l'utilisateur a collé une URL complète.

        Accepte :
          - Code brut : 'eyJrxxx...'
          - URL avec ?code=... : 'msauth.com.waterair.easycare://auth?code=eyJrxxx&state=...'
          - URL avec #code=... (fragment, fallback)
        """
        input_str = input_str.strip()

        # Si ça ressemble à une URL avec un code dans les params
        if "code=" in input_str:
            try:
                # Récupère ce qui suit "code=" jusqu'au prochain & ou fin
                after = input_str.split("code=", 1)[1]
                code = after.split("&", 1)[0]
                return code.strip()
            except IndexError:
                pass
        return input_str
