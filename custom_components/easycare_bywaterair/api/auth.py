"""Gestion de l'authentification OAuth2 Azure B2C pour Easy-care by Waterair.

Orchestre le cycle de vie des tokens :
  - Échange initial du code OAuth2 → tokens Azure → bearer EasyCare
  - Renouvellement automatique avant expiration
  - Rotation du refresh_token persistée via callback
  - Point d'entrée unique `get_valid_bearer()` pour le client API
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode, quote

import aiohttp
from aiohttp import ClientError

from ..const import (
    BEARER_BASIC_AUTH,
    BEARER_REFRESH_MARGIN_SECONDS,
    API_HOST_EASYCARE,
    API_PATH_TOKEN_FROM_B2C,
    HTTP_TIMEOUT_AUTH,
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
    EasyCareInvalidCredentialsError,
    EasyCareInvalidResponseError,
    EasyCareLoginError,
    EasyCareTimeoutError,
    EasyCareTokenExpiredError,
)
from .models import BearerToken, OAuthTokens

_LOGGER = logging.getLogger(__name__)

TokensUpdatedCallback = Callable[[OAuthTokens, BearerToken], Awaitable[None]]

# User-Agent Safari iOS — cohérent avec l'app Waterair (iPad) et le profil TLS impersonné.
_UA_BROWSER = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_3 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.3 Mobile/15E148 Safari/604.1"
)


def _import_curl_session() -> type:
    """Importe curl_cffi.AsyncSession avec un message clair si la dépendance manque.

    curl_cffi est indispensable pour contourner le WAF Azure Front Door (fingerprint
    TLS). Si HA n'a pas installé la dépendance (ex. environnement de dev lancé depuis
    les sources), on remonte une erreur explicite plutôt qu'une stacktrace brute.
    """
    try:
        from curl_cffi.requests import AsyncSession as CurlSession  # noqa: PLC0415
    except ImportError as err:
        raise EasyCareLoginError(
            "The 'curl_cffi' dependency is missing. Install it in the Home Assistant "
            "environment (\"pip install curl_cffi\") or check that the integration "
            "was able to install its dependencies."
        ) from err
    return CurlSession


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

    async def login_with_credentials(self, email: str, password: str) -> OAuthTokens:
        """Authentifie silencieusement via curl_cffi qui contourne le WAF Azure Front Door.

        curl_cffi impersonne le profil TLS Safari iOS, ce qui permet de passer le
        fingerprinting TLS d'Azure Front Door qui bloque les clients Python standard.

        Args:
            email   : adresse email du compte Waterair.
            password: mot de passe du compte Waterair.

        Returns:
            Les tokens OAuth obtenus après login réussi.

        Raises:
            EasyCareInvalidCredentialsError: email ou mot de passe incorrect.
            EasyCareLoginError: flow de login inattendu (MFA, CAPTCHA, page inconnue).
            EasyCareConnectionError: erreur réseau.
            EasyCareTimeoutError: timeout.
        """
        CurlSession = _import_curl_session()
        _LOGGER.debug("Starting silent Azure B2C login for %s", email)
        authorize_url = self.build_authorize_url()
        try:
            async with CurlSession(impersonate="safari15_5") as curl:
                settings, page_url = await self._fetch_b2c_settings(curl, authorize_url)
                await self._post_selfasserted(curl, settings, page_url, email, password)
                redirect_url = await self._get_confirmed(curl, settings, page_url)
        except (EasyCareInvalidCredentialsError, EasyCareLoginError,
                EasyCareTimeoutError, EasyCareConnectionError):
            raise
        except Exception as err:
            raise EasyCareLoginError(f"Unexpected error during login: {err}") from err
        code = self._extract_code_from_url(redirect_url)
        return await self.exchange_code(code)

    @staticmethod
    async def _fetch_b2c_settings(curl: Any, authorize_url: str) -> tuple[dict, str]:
        """Charge la page Azure B2C et extrait SETTINGS depuis le JS inline.

        Returns:
            Tuple (settings_dict, url_finale_après_redirections).
        """
        headers = {
            "User-Agent": _UA_BROWSER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        resp = await curl.get(
            authorize_url, headers=headers, allow_redirects=True,
            timeout=HTTP_TIMEOUT_AUTH,
        )
        if resp.status_code != 200:
            raise EasyCareLoginError(
                f"Page Azure B2C inaccessible (HTTP {resp.status_code})"
            )
        m = re.search(r"var SETTINGS = (\{.*?\});", resp.text, re.DOTALL)
        if not m:
            raise EasyCareLoginError(
                "SETTINGS not found in the Azure B2C page — unexpected structure"
            )
        try:
            settings = json.loads(m.group(1))
        except json.JSONDecodeError as err:
            raise EasyCareLoginError(f"Invalid SETTINGS JSON: {err}") from err
        return settings, str(resp.url)

    @staticmethod
    async def _post_selfasserted(
        curl: Any, settings: dict, page_url: str, email: str, password: str
    ) -> None:
        """Soumet email/password au endpoint SelfAsserted et vérifie le statut JSON.

        Raises:
            EasyCareInvalidCredentialsError: identifiants incorrects (AADB2C90054).
            EasyCareLoginError: autre erreur B2C (MFA, etc.).
        """
        tenant = settings["hosts"]["tenant"]
        trans_id = settings["transId"]
        policy = settings["hosts"]["policy"]
        csrf = settings["csrf"]
        sa_url = f"https://sso.waterair.com{tenant}/SelfAsserted?tx={trans_id}&p={policy}"
        payload = f"request_type=RESPONSE&signInName={quote(email)}&password={quote(password)}"
        headers = {
            "User-Agent": _UA_BROWSER,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-CSRF-TOKEN": csrf,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://sso.waterair.com",
            "Referer": page_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
        }
        resp = await curl.post(
            sa_url, data=payload, headers=headers, allow_redirects=False,
            timeout=HTTP_TIMEOUT_AUTH,
        )
        if resp.status_code != 200:
            raise EasyCareLoginError(
                f"SelfAsserted : réponse inattendue HTTP {resp.status_code}"
            )
        try:
            j = json.loads(resp.text)
        except json.JSONDecodeError as err:
            raise EasyCareLoginError(f"SelfAsserted: non-JSON response: {err}") from err
        if j.get("status") == "400":
            error_code = j.get("errorCode", "")
            if error_code == "AADB2C90054":
                raise EasyCareInvalidCredentialsError("Email ou mot de passe incorrect")
            raise EasyCareLoginError(
                f"Échec SelfAsserted (code {error_code}) : {j.get('message', j)}"
            )
        if j.get("status") != "200":
            raise EasyCareLoginError(f"SelfAsserted: unexpected status: {j}")
        _LOGGER.debug("SelfAsserted: credentials accepted")

    @staticmethod
    async def _get_confirmed(curl: Any, settings: dict, page_url: str) -> str:
        """GET confirmed → intercepte la redirection 302 vers msauth://.

        Returns:
            L'URL msauth://... contenant le code OAuth.
        """
        tenant = settings["hosts"]["tenant"]
        policy = settings["hosts"]["policy"]
        trans_id = settings["transId"]
        csrf = settings["csrf"]
        api = settings.get("api", "")
        confirmed_url = (
            f"https://sso.waterair.com{tenant}/api/{api}/confirmed"
            f"?rememberMe=false&csrf_token={quote(csrf)}&tx={trans_id}&p={policy}"
        )
        headers = {
            "User-Agent": _UA_BROWSER,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Referer": page_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        resp = await curl.get(
            confirmed_url, headers=headers, allow_redirects=False,
            timeout=HTTP_TIMEOUT_AUTH,
        )
        location = resp.headers.get("Location", "")
        if resp.status_code in (301, 302, 303, 307, 308) and (
            location.startswith("msauth") or "code=" in location
        ):
            _LOGGER.debug("OAuth code intercepted from confirmed")
            return location
        raise EasyCareLoginError(
            f"Confirmed: msauth:// redirect not intercepted "
            f"(HTTP {resp.status_code}, Location={location[:80]!r})"
        )

    @staticmethod
    def _extract_code_from_url(redirect_url: str) -> str:
        """Extrait le code OAuth depuis l'URL de redirection msauth://.

        Raises:
            EasyCareLoginError: paramètre code= absent de l'URL.
        """
        if "code=" not in redirect_url:
            raise EasyCareLoginError(
                f"Paramètre code= absent de l'URL de redirection : {redirect_url[:120]}"
            )
        try:
            after = redirect_url.split("code=", 1)[1]
            return after.split("&", 1)[0].strip()
        except IndexError as err:
            raise EasyCareLoginError(
                f"Impossible d'extraire le code OAuth : {redirect_url[:120]}"
            ) from err

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
        _LOGGER.debug("Exchanging OAuth code for Azure tokens")
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
            _LOGGER.warning("Code exchange rejected — HTTP %s", err.status_code)
            raise EasyCareInvalidCodeError(
                f"Code rejected by Azure B2C (HTTP {err.status_code})"
            ) from err

        if "error" in data:
            _LOGGER.warning("OAuth error in response: %s", data.get("error"))
            raise EasyCareInvalidCodeError(f"Azure B2C error: {data.get('error')}")

        try:
            tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            raise EasyCareInvalidCodeError(
                "La réponse OAuth ne contient pas de refresh_token"
            ) from err

        self._oauth_tokens = tokens
        _LOGGER.info("Azure tokens obtained successfully")
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
            raise EasyCareAuthError("No refresh_token available")

        _LOGGER.debug("Refreshing Azure tokens via refresh_token")
        params = {
            "grant_type": "refresh_token",
            "refresh_token": self._oauth_tokens.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }
        try:
            data = await self._post_token_endpoint(params)
        except EasyCareApiError as err:
            if err.status_code == 400 and err.body and "invalid_grant" in err.body:
                _LOGGER.warning("Refresh token expired — re-authentication required")
                raise EasyCareTokenExpiredError(
                    "The Azure B2C refresh_token is expired or revoked."
                ) from err
            raise
        except EasyCareInvalidResponseError as err:
            # Azure B2C retourne parfois une page HTML (HTTP 200) au lieu d'un JSON
            # {"error": "invalid_grant"} quand le refresh_token est expiré.
            _LOGGER.warning(
                "Non-JSON response from Azure B2C token endpoint (HTML page?) — "
                "refresh_token probably expired → re-authentication required"
            )
            raise EasyCareTokenExpiredError(
                "Azure B2C returned a non-JSON response: "
                "refresh_token expired or invalid session."
            ) from err

        try:
            new_tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            raise EasyCareAuthError(f"Unexpected refresh response: {err}") from err

        self._oauth_tokens = new_tokens
        _LOGGER.info("Azure tokens refreshed successfully")
        await self._refresh_bearer_from_id_token(new_tokens.id_token)
        await self._notify_tokens_updated()
        return new_tokens

    async def _refresh_bearer_from_id_token(self, id_token: str) -> BearerToken:
        """Échange un id_token Azure contre un bearer EasyCare."""
        _LOGGER.debug("Getting EasyCare bearer from Azure id_token")
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
                    _LOGGER.error("EasyCare bearer failed: HTTP %s", response.status)
                    raise EasyCareApiError(
                        "Could not obtain EasyCare bearer",
                        status_code=response.status, body=body,
                    )
                try:
                    data = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EasyCareInvalidResponseError(
                        f"Réponse non-JSON de tokenFromAzureADB2CIdToken : {err}"
                    ) from err
        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Timeout (%ds) on tokenFromAzureADB2CIdToken — Waterair server unreachable",
                HTTP_TIMEOUT_AUTH,
            )
            raise EasyCareTimeoutError("Timeout lors de l'obtention du bearer") from err
        except ClientError as err:
            _LOGGER.error(
                "Network error on tokenFromAzureADB2CIdToken: %s: %s",
                type(err).__name__, err,
            )
            raise EasyCareConnectionError(f"Network error: {err}") from err

        bearer = BearerToken.from_api(data)
        self._bearer = bearer
        _LOGGER.info(
            "EasyCare bearer obtained (expires in ~%ds)",
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
                raise EasyCareAuthError("No Azure tokens available")

            # Bearer encore valide → retour immédiat, sans aucun appel Azure B2C.
            # On ne touche pas à l'id_token tant que le bearer tient : si le bearer
            # EasyCare dure plusieurs heures/jours, inutile de rafraîchir les tokens
            # Azure toutes les heures.
            if self._bearer is not None and not self._bearer.is_expired(
                margin_seconds=BEARER_REFRESH_MARGIN_SECONDS
            ):
                return self._bearer.bearer

            # Bearer expiré ou absent — renouvellement nécessaire.
            # Si l'id_token est encore utilisable, on renouvelle le bearer directement
            # sans passer par le refresh_token Azure B2C.
            if not self._oauth_tokens.is_expired(margin_seconds=0):
                _LOGGER.debug("EasyCare bearer expired → renewing from existing id_token")
                await self._refresh_bearer_from_id_token(self._oauth_tokens.id_token)
                await self._notify_tokens_updated()
                return self._bearer.bearer  # type: ignore[union-attr]

            # id_token également expiré → refresh Azure B2C nécessaire.
            _LOGGER.debug("Bearer and id_token expired → Azure B2C refresh via refresh_token")
            await self.refresh_tokens()
            return self._bearer.bearer  # type: ignore[union-attr]

    async def invalidate_bearer(self) -> None:
        """Force l'invalidation du bearer (à appeler sur réception d'un 401)."""
        async with self._refresh_lock:
            _LOGGER.debug("Forced invalidation of EasyCare bearer")
            self._bearer = None

    async def _post_token_endpoint(self, params: dict[str, Any]) -> dict[str, Any]:
        """Appelle l'endpoint /oauth2/v2.0/token d'Azure B2C via curl_cffi.

        Le token endpoint est sur sso.waterair.com, derrière le même Azure Front
        Door WAF qui bloque le fingerprint TLS d'aiohttp. On impersonne donc Safari
        comme pour les étapes du login (sinon HTTP 400 « Bad Request » du WAF).

        Args:
            params: paramètres OAuth2 (grant_type, code/refresh_token, etc.).

        Returns:
            La réponse JSON décodée.
        """
        CurlSession = _import_curl_session()
        headers = {
            "User-Agent": _UA_BROWSER,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            async with CurlSession(impersonate="safari15_5") as curl:
                response = await curl.post(
                    OAUTH_TOKEN_URL, data=params, headers=headers,
                    timeout=HTTP_TIMEOUT_AUTH,
                )
        except Exception as err:  # curl_cffi : erreurs réseau/TLS/timeout
            raise EasyCareConnectionError(f"Network error on OAuth /token: {err}") from err

        body = response.text
        if response.status_code != 200:
            _LOGGER.warning("OAuth /token: HTTP %s", response.status_code)
            raise EasyCareApiError(
                "OAuth /token endpoint failed",
                status_code=response.status_code, body=body,
            )
        if not body.strip():
            raise EasyCareInvalidResponseError(
                "Réponse OAuth vide (corps HTTP vide, endpoint Azure B2C transitoire)"
            )
        try:
            return json.loads(body)
        except ValueError as err:
            _LOGGER.warning("OAuth /token raw body (non-JSON): %r", body[:200])
            raise EasyCareInvalidResponseError(f"Non-JSON OAuth response: {err}") from err

    async def _notify_tokens_updated(self) -> None:
        """Notifie le callback de mise à jour des tokens si défini."""
        if self._on_tokens_updated is None:
            return
        if self._oauth_tokens is None or self._bearer is None:
            return
        try:
            await self._on_tokens_updated(self._oauth_tokens, self._bearer)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Error in token persistence callback: %s", err)
