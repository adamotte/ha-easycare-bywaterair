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
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlencode, urljoin

import aiohttp
from aiohttp import ClientError, ClientResponseError

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

# Mots-clés utilisés pour identifier le champ email dans le formulaire Azure B2C.
# Couvre les id/name courants observés sur les pages de login Microsoft B2C.
_EMAIL_FIELD_KEYWORDS: frozenset[str] = frozenset({
    "email", "signin", "login", "username", "logonidentifier", "signinemail",
})


class _LoginFormParser(HTMLParser):
    """Parser HTML minimaliste pour extraire les formulaires de la page de login Azure B2C.

    Collecte tous les <form> avec leurs <input>, sans hypothèse sur la structure.
    La sélection du bon formulaire (celui avec type="password") est faite en dehors.
    """

    def __init__(self) -> None:
        super().__init__()
        self.forms: list[dict[str, Any]] = []
        self._current_form: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict: dict[str, str] = {k: (v or "") for k, v in attrs}
        if tag == "form":
            self._current_form = {
                "action": attrs_dict.get("action", ""),
                "method": attrs_dict.get("method", "post").lower(),
                "inputs": [],
            }
        elif tag == "input" and self._current_form is not None:
            self._current_form["inputs"].append(attrs_dict)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._current_form is not None:
            self.forms.append(self._current_form)
            self._current_form = None

    def find_password_form(self) -> dict[str, Any] | None:
        """Retourne le premier formulaire contenant un champ type='password', ou None."""
        for form in self.forms:
            if any(inp.get("type", "").lower() == "password" for inp in form["inputs"]):
                return form
        return None


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
        """Authentifie silencieusement en simulant le flow browser Azure B2C.

        L'utilisateur n'a pas à ouvrir de navigateur : la méthode charge la page
        de login, soumet les identifiants et intercepte la redirection msauth://.
        Le PKCE statique et l'exchange de code restent inchangés.

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
        _LOGGER.debug("Début du login silencieux Azure B2C pour %s", email)
        authorize_url = self.build_authorize_url()
        html, page_url = await self._fetch_login_page(authorize_url)
        form_action, payload = self._parse_and_build_payload(html, page_url, email, password)
        redirect_url = await self._submit_credentials(form_action, payload, page_url)
        code = self._extract_code_from_url(redirect_url)
        return await self.exchange_code(code)

    async def _fetch_login_page(self, authorize_url: str) -> tuple[str, str]:
        """Charge la page de login Azure B2C en suivant les redirections HTTP normalement.

        Returns:
            Tuple (html, url_finale_après_redirections).
        """
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        }
        try:
            async with self._session.get(
                authorize_url,
                headers=headers,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
            ) as response:
                if response.status != 200:
                    raise EasyCareLoginError(
                        f"Page de login Azure B2C inaccessible (HTTP {response.status})"
                    )
                html = await response.text()
                return html, str(response.url)
        except asyncio.TimeoutError as err:
            raise EasyCareTimeoutError(
                "Timeout lors du chargement de la page de login Azure B2C"
            ) from err
        except ClientError as err:
            raise EasyCareConnectionError(
                f"Erreur réseau lors du chargement de la page de login : {err}"
            ) from err

    @staticmethod
    def _parse_and_build_payload(
        html: str, page_url: str, email: str, password: str
    ) -> tuple[str, dict[str, str]]:
        """Parse le formulaire de login et construit le payload POST.

        Stratégie robuste face aux changements de structure Azure B2C :
        - Localise le formulaire par la présence d'un champ type="password"
        - Extrait TOUS les champs cachés sans hypothèse sur leurs noms
        - Identifie le champ email par type="email" ou id/name contenant des mots-clés connus
        - Identifie le champ password par type="password"

        Returns:
            Tuple (url_action_du_formulaire, payload_complet).

        Raises:
            EasyCareLoginError: formulaire introuvable ou champs email/password manquants.
        """
        parser = _LoginFormParser()
        parser.feed(html)
        login_form = parser.find_password_form()

        if login_form is None:
            raise EasyCareLoginError(
                "Formulaire de login introuvable dans la page Azure B2C "
                "(MFA, CAPTCHA ou structure de page inattendue)"
            )

        form_action = login_form["action"]
        if not form_action.startswith("http"):
            form_action = urljoin(page_url, form_action)

        payload: dict[str, str] = {}
        email_field: str | None = None
        password_field: str | None = None

        for inp in login_form["inputs"]:
            inp_type = inp.get("type", "text").lower()
            inp_name = inp.get("name", "")
            inp_id = inp.get("id", "").lower()
            inp_value = inp.get("value", "")

            if not inp_name:
                continue

            if inp_type == "hidden":
                payload[inp_name] = inp_value
            elif inp_type in ("email", "text") and email_field is None:
                if inp_type == "email" or (
                    any(k in inp_id for k in _EMAIL_FIELD_KEYWORDS)
                    or any(k in inp_name.lower() for k in _EMAIL_FIELD_KEYWORDS)
                ):
                    email_field = inp_name
            elif inp_type == "password" and password_field is None:
                password_field = inp_name

        if email_field is None:
            raise EasyCareLoginError(
                "Champ email introuvable dans le formulaire Azure B2C — "
                "la structure de la page a peut-être changé"
            )
        if password_field is None:
            raise EasyCareLoginError(
                "Champ mot de passe introuvable dans le formulaire Azure B2C"
            )

        payload[email_field] = email
        payload[password_field] = password
        _LOGGER.debug(
            "Formulaire de login parsé : action=%s, %d champs cachés, email=%s, password=%s",
            form_action, len(payload) - 2, email_field, password_field,
        )
        return form_action, payload

    async def _submit_credentials(
        self, form_action: str, payload: dict[str, str], base_url: str, max_redirects: int = 10
    ) -> str:
        """Soumet le formulaire et suit les redirections jusqu'à intercepter msauth://.

        Returns:
            L'URL de redirection finale (msauth://... contenant le code OAuth).

        Raises:
            EasyCareInvalidCredentialsError: identifiants incorrects (serveur retourne
                une page HTML avec le formulaire de login toujours présent).
            EasyCareLoginError: flow inattendu (MFA, trop de redirections, etc.).
        """
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": base_url,
        }
        current_url = form_action
        current_data: dict[str, str] | None = payload
        method = "POST"

        for step in range(max_redirects):
            try:
                if method == "POST" and current_data is not None:
                    resp_cm = self._session.post(
                        current_url, data=current_data, headers=headers,
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
                    )
                else:
                    resp_cm = self._session.get(
                        current_url, headers=headers,
                        allow_redirects=False,
                        timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
                    )

                async with resp_cm as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location", "")
                        if not location:
                            raise EasyCareLoginError(
                                "Redirection sans en-tête Location"
                            )
                        # Cible finale : URL msauth:// ou contenant le paramètre code=
                        if location.startswith("msauth") or "code=" in location:
                            _LOGGER.debug("Code OAuth intercepté à l'étape %d", step + 1)
                            return location
                        # Redirection HTTP ordinaire : résoudre et continuer
                        if not location.startswith("http"):
                            location = urljoin(current_url, location)
                        current_url = location
                        # 303 et 302/301 en POST → GET selon RFC 7231
                        method = "GET" if response.status in (301, 302, 303) else method
                        current_data = None

                    elif response.status == 200:
                        # Réponse HTML : soit credentials incorrects, soit étape inattendue
                        html = await response.text()
                        reparser = _LoginFormParser()
                        reparser.feed(html)
                        if reparser.find_password_form() is not None:
                            raise EasyCareInvalidCredentialsError(
                                "Email ou mot de passe incorrect"
                            )
                        raise EasyCareLoginError(
                            "Étape de connexion inattendue (double authentification MFA ?) — "
                            "vérifiez que votre compte Waterair n'a pas de 2FA activé"
                        )

                    else:
                        raise EasyCareLoginError(
                            f"Réponse inattendue à l'étape {step + 1} : HTTP {response.status}"
                        )

            except asyncio.TimeoutError as err:
                raise EasyCareTimeoutError(
                    "Timeout lors de la soumission des identifiants"
                ) from err
            except ClientError as err:
                raise EasyCareConnectionError(
                    f"Erreur réseau lors du login : {err}"
                ) from err

        raise EasyCareLoginError(
            f"Trop de redirections pendant le login (max {max_redirects})"
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
        except EasyCareInvalidResponseError as err:
            # Azure B2C retourne parfois une page HTML (HTTP 200) au lieu d'un JSON
            # {"error": "invalid_grant"} quand le refresh_token est expiré.
            _LOGGER.warning(
                "Réponse non-JSON du token endpoint Azure B2C (page HTML ?) — "
                "refresh_token probablement expiré → ré-authentification requise"
            )
            raise EasyCareTokenExpiredError(
                "Azure B2C a retourné une réponse non-JSON : "
                "refresh_token expiré ou session invalide."
            ) from err

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
            _LOGGER.error(
                "Timeout (%ds) sur tokenFromAzureADB2CIdToken — serveur Waterair injoignable",
                HTTP_TIMEOUT_AUTH,
            )
            raise EasyCareTimeoutError("Timeout lors de l'obtention du bearer") from err
        except ClientError as err:
            _LOGGER.error(
                "Erreur réseau sur tokenFromAzureADB2CIdToken : %s: %s",
                type(err).__name__, err,
            )
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
                _LOGGER.debug("Bearer EasyCare expiré → renouvellement depuis id_token existant")
                await self._refresh_bearer_from_id_token(self._oauth_tokens.id_token)
                await self._notify_tokens_updated()
                return self._bearer.bearer  # type: ignore[union-attr]

            # id_token également expiré → refresh Azure B2C nécessaire.
            _LOGGER.debug("Bearer et id_token expirés → refresh Azure B2C via refresh_token")
            await self.refresh_tokens()
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
                if not body.strip():
                    raise EasyCareInvalidResponseError(
                        "Réponse OAuth vide (corps HTTP vide, endpoint Azure B2C transitoire)"
                    )
                try:
                    return json.loads(body)
                except ValueError as err:
                    _LOGGER.warning("OAuth /token corps brut (non-JSON) : %r", body[:200])
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
