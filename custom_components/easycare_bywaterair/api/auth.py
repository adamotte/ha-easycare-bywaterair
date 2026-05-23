"""Gestion de l'authentification OAuth2 Azure B2C pour Easy-care by Waterair.

Orchestre le cycle de vie des tokens :
  - Échange initial du code OAuth2 → tokens Azure → bearer EasyCare
  - Renouvellement automatique avant expiration
  - Rotation du refresh_token persistée via callback
  - Point d'entrée unique `get_valid_bearer()` pour le client API
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import aiohttp
from aiohttp import ClientError, ClientResponseError

from ..const import (
    BEARER_BASIC_AUTH,
    BEARER_REFRESH_MARGIN_SECONDS,
    API_HOST_EASYCARE,
    API_PATH_TOKEN_FROM_B2C,
    HTTP_TIMEOUT_AUTH,
    ID_TOKEN_REFRESH_MARGIN_SECONDS,
    OAUTH_AUTHORIZE_URL,
    OAUTH_CLIENT_ID,
    OAUTH_CODE_CHALLENGE,
    OAUTH_CODE_VERIFIER,
    OAUTH_REDIRECT_URI,
    OAUTH_SCOPES,
    OAUTH_TOKEN_URL,
    USER_AGENT,
)
from .exceptions import (
    EasyCareApiError,
    EasyCareAuthError,
    EasyCareConnectionError,
    EasyCareInvalidCodeError,
    EasyCareInvalidResponseError,
    EasyCareTimeoutError,
    EasyCareTokenExpiredError,
)
from .models import BearerToken, OAuthTokens

_LOGGER = logging.getLogger(__name__)

TokensUpdatedCallback = Callable[[OAuthTokens, BearerToken], Awaitable[None]]


class EasyCareAuth:
    """Orchestrateur de l'authentification Azure B2C + bearer EasyCare.

    Une instance par ConfigEntry, réutilisée pendant toute la durée de vie
    de l'intégration. Toutes les opérations de refresh sont protégées par
    un asyncio.Lock pour éviter les refreshs concurrents.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        oauth_tokens: OAuthTokens | None = None,
        bearer: BearerToken | None = None,
        on_tokens_updated: TokensUpdatedCallback | None = None,
    ) -> None:
        """Initialise le gestionnaire d'authentification.

        Args:
            session           : session aiohttp partagée.
            oauth_tokens      : tokens Azure existants, None pour login initial.
            bearer            : bearer EasyCare existant, None pour le générer.
            on_tokens_updated : callback async appelé après chaque refresh réussi.
        """
        self._session = session
        self._oauth_tokens = oauth_tokens
        self._bearer = bearer
        self._on_tokens_updated = on_tokens_updated
        self._refresh_lock = asyncio.Lock()

    @property
    def oauth_tokens(self) -> OAuthTokens | None:
        """Tokens Azure courants."""
        return self._oauth_tokens

    @property
    def bearer(self) -> BearerToken | None:
        """Bearer EasyCare courant."""
        return self._bearer

    @property
    def is_authenticated(self) -> bool:
        """Vrai si un refresh_token est disponible."""
        return self._oauth_tokens is not None

    @staticmethod
    def build_authorize_url() -> str:
        """Construit l'URL OAuth2 que l'utilisateur doit ouvrir pour se connecter."""
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": OAUTH_SCOPES,
            "code_challenge": OAUTH_CODE_CHALLENGE,
            "code_challenge_method": "S256",
            "response_mode": "query",
        }
        return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        """Échange un code d'autorisation OAuth2 contre des tokens Azure.

        Args:
            code: code retourné par l'URL de redirection après login.

        Returns:
            Les tokens fraîchement obtenus.

        Raises:
            EasyCareInvalidCodeError: code invalide ou expiré.
            EasyCareConnectionError : problème réseau.
        """
        _LOGGER.debug("Échange du code OAuth contre des tokens Azure")
        params = {
            "code": code,
            "grant_type": "authorization_code",
            "code_verifier": OAUTH_CODE_VERIFIER,
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
        }
        try:
            data = await self._post_token_endpoint(params)
        except EasyCareApiError as err:
            _LOGGER.warning("Échange de code rejeté — HTTP %s", err.status_code)
            raise EasyCareInvalidCodeError(
                f"Code rejeté par Azure B2C (HTTP {err.status_code})"
            ) from err

        if "error" in data:
            _LOGGER.warning("Erreur OAuth dans la réponse : %s", data.get("error"))
            raise EasyCareInvalidCodeError(f"Erreur Azure B2C: {data.get('error')}")

        try:
            tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            raise EasyCareInvalidCodeError(
                "La réponse OAuth ne contient pas de refresh_token"
            ) from err

        self._oauth_tokens = tokens
        _LOGGER.info("Tokens Azure obtenus avec succès")
        await self._refresh_bearer_from_id_token(tokens.id_token)
        await self._notify_tokens_updated()
        return tokens

    async def refresh_tokens(self) -> OAuthTokens:
        """Renouvelle les tokens Azure via le refresh_token.

        Returns:
            Les nouveaux tokens.

        Raises:
            EasyCareTokenExpiredError: refresh_token expiré ou révoqué.
            EasyCareAuthError        : autre erreur d'auth.
        """
        if self._oauth_tokens is None:
            raise EasyCareAuthError("Aucun refresh_token disponible")

        _LOGGER.debug("Renouvellement des tokens Azure via refresh_token")
        params = {
            "grant_type": "refresh_token",
            "refresh_token": self._oauth_tokens.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }
        try:
            data = await self._post_token_endpoint(params)
        except EasyCareApiError as err:
            if err.status_code == 400 and err.body and "invalid_grant" in err.body:
                _LOGGER.warning("Refresh token expiré — ré-authentification requise")
                raise EasyCareTokenExpiredError(
                    "Le refresh_token Azure B2C est expiré ou révoqué."
                ) from err
            raise

        try:
            new_tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            raise EasyCareAuthError(f"Réponse de refresh inattendue : {err}") from err

        self._oauth_tokens = new_tokens
        _LOGGER.info("Tokens Azure rafraîchis avec succès")
        await self._refresh_bearer_from_id_token(new_tokens.id_token)
        await self._notify_tokens_updated()
        return new_tokens

    async def _refresh_bearer_from_id_token(self, id_token: str) -> BearerToken:
        """Échange un id_token Azure contre un bearer EasyCare."""
        _LOGGER.debug("Obtention du bearer EasyCare depuis l'id_token Azure")
        url = f"{API_HOST_EASYCARE}{API_PATH_TOKEN_FROM_B2C}"
        headers = {
            "Authorization": f"Basic {BEARER_BASIC_AUTH}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        }
        payload = {"idToken": id_token}
        try:
            async with self._session.post(
                url, json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    _LOGGER.error("Échec bearer EasyCare : HTTP %s", response.status)
                    raise EasyCareApiError(
                        "Impossible d'obtenir le bearer EasyCare",
                        status_code=response.status, body=body,
                    )
                try:
                    data = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EasyCareInvalidResponseError(
                        f"Réponse non-JSON de tokenFromAzureADB2CIdToken : {err}"
                    ) from err
        except asyncio.TimeoutError as err:
            raise EasyCareTimeoutError("Timeout lors de l'obtention du bearer") from err
        except ClientError as err:
            raise EasyCareConnectionError(f"Erreur réseau : {err}") from err

        bearer = BearerToken.from_api(data)
        self._bearer = bearer
        _LOGGER.info(
            "Bearer EasyCare obtenu (expire dans ~%ds)",
            int(bearer.expires_at - datetime.now(tz=timezone.utc).timestamp()),
        )
        return bearer

    async def get_valid_bearer(self) -> str:
        """Retourne un bearer EasyCare valide, en gérant tous les refreshs.

        Returns:
            La chaîne du bearer prête à utiliser dans Authorization: Bearer.

        Raises:
            EasyCareAuthError        : pas de tokens disponibles.
            EasyCareTokenExpiredError: refresh_token expiré, reauth requis.
        """
        async with self._refresh_lock:
            if self._oauth_tokens is None:
                raise EasyCareAuthError("Pas de tokens Azure disponibles")

            if self._oauth_tokens.is_expired(margin_seconds=ID_TOKEN_REFRESH_MARGIN_SECONDS):
                _LOGGER.debug("id_token Azure expire bientôt → refresh proactif")
                await self.refresh_tokens()
                return self._bearer.bearer  # type: ignore[union-attr]

            if self._bearer is None or self._bearer.is_expired(
                margin_seconds=BEARER_REFRESH_MARGIN_SECONDS
            ):
                _LOGGER.debug("Bearer EasyCare expire bientôt → renouvellement")
                await self._refresh_bearer_from_id_token(self._oauth_tokens.id_token)
                await self._notify_tokens_updated()

            return self._bearer.bearer  # type: ignore[union-attr]

    async def invalidate_bearer(self) -> None:
        """Force l'invalidation du bearer (à appeler sur réception d'un 401)."""
        async with self._refresh_lock:
            _LOGGER.debug("Invalidation forcée du bearer EasyCare")
            self._bearer = None

    async def _post_token_endpoint(self, params: dict[str, Any]) -> dict[str, Any]:
        """Appelle l'endpoint /oauth2/v2.0/token d'Azure B2C.

        Args:
            params: paramètres OAuth2 (grant_type, code/refresh_token, etc.).

        Returns:
            La réponse JSON décodée.
        """
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            async with self._session.post(
                OAUTH_TOKEN_URL, data=params, headers=headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
            ) as response:
                body = await response.text()
                if response.status != 200:
                    _LOGGER.warning("OAuth /token : HTTP %s", response.status)
                    raise EasyCareApiError(
                        "Échec endpoint OAuth /token",
                        status_code=response.status, body=body,
                    )
                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EasyCareInvalidResponseError(f"Réponse OAuth non-JSON : {err}") from err
        except asyncio.TimeoutError as err:
            raise EasyCareTimeoutError("Timeout sur l'endpoint OAuth /token") from err
        except ClientResponseError as err:
            raise EasyCareApiError(
                f"Erreur HTTP sur OAuth /token : {err}", status_code=err.status,
            ) from err
        except ClientError as err:
            raise EasyCareConnectionError(f"Erreur réseau sur OAuth /token : {err}") from err

    async def _notify_tokens_updated(self) -> None:
        """Notifie le callback de mise à jour des tokens si défini."""
        if self._on_tokens_updated is None:
            return
        if self._oauth_tokens is None or self._bearer is None:
            return
        try:
            await self._on_tokens_updated(self._oauth_tokens, self._bearer)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Erreur lors du callback de persistance des tokens : %s", err)
