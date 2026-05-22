"""Gestion de l'authentification OAuth2 Azure B2C pour Easy-care by Waterair.

Cette classe orchestre tout le cycle de vie des tokens :

    1. Login initial via un code OAuth2 (étape unique pour l'utilisateur)
       → exchange_code() — appelé une seule fois depuis le config_flow

    2. Renouvellement automatique de l'id_token Azure
       → refresh_tokens() — appelé toutes les ~50 minutes en interne

    3. Échange id_token Azure ↔ bearer EasyCare
       → obtain_bearer() — appelé après chaque refresh ou sur 401

    4. Point d'entrée unique pour le client API
       → get_valid_bearer() — retourne un bearer toujours valide

    5. Construction du lien d'autorisation pour le config_flow
       → build_authorize_url() — utilisé par le config_flow étape 1

L'objet `EasyCareAuth` est conçu pour être créé une fois par ConfigEntry et
réutilisé pendant toute la durée de vie de l'intégration.

Stratégie de refresh :
  - On rafraîchit `id_token` 10 minutes AVANT son expiration (1h par défaut)
  - On rafraîchit le bearer 5 minutes AVANT son expiration
  - À chaque refresh d'Azure, le `refresh_token` est ROTATÉ
    → on doit IMPÉRATIVEMENT persister le nouveau via le callback `on_tokens_updated`
  - Si le refresh_token est rejeté (expiré, révoqué) → EasyCareTokenExpiredError
    → HA déclenche le reauth flow → l'utilisateur fournit un nouveau code

Concurrence :
  Toutes les opérations de refresh sont protégées par un `asyncio.Lock` pour
  éviter qu'un afflux simultané de requêtes ne déclenche N refreshs en parallèle.
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

# Callback type — appelé après chaque refresh réussi pour persister les nouveaux tokens.
# Le ConfigEntry HA doit être mis à jour pour conserver le refresh_token rotaté.
TokensUpdatedCallback = Callable[[OAuthTokens, BearerToken], Awaitable[None]]


class EasyCareAuth:
    """Orchestrateur de l'authentification Azure B2C + bearer EasyCare.

    Cycle de vie typique :

        # 1. Création (chargement depuis ConfigEntry ou config_flow)
        auth = EasyCareAuth(
            session=aiohttp_session,
            oauth_tokens=oauth_tokens_or_None,
            bearer=bearer_or_None,
            on_tokens_updated=async_save_to_config_entry,
        )

        # 2. Login initial (config_flow uniquement, première fois)
        if oauth_tokens is None:
            await auth.exchange_code(code_saisi_par_utilisateur)

        # 3. À chaque requête API : récupérer un bearer valide
        bearer = await auth.get_valid_bearer()
        headers = {"Authorization": f"Bearer {bearer}"}
        ...

    L'instance est thread-safe (asyncio) : plusieurs coroutines peuvent appeler
    `get_valid_bearer()` simultanément sans déclencher de refresh multiples.
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
            session           : session aiohttp partagée par toute l'intégration.
            oauth_tokens      : tokens Azure (depuis ConfigEntry), None pour login initial.
            bearer            : bearer EasyCare (depuis ConfigEntry), None pour le générer.
            on_tokens_updated : callback async appelé à chaque rafraîchissement réussi.
                                Doit persister les nouveaux tokens dans ConfigEntry.
        """
        self._session = session
        self._oauth_tokens = oauth_tokens
        self._bearer = bearer
        self._on_tokens_updated = on_tokens_updated
        self._refresh_lock = asyncio.Lock()

    # ────────────────────────────────────────────────────────────────────────
    # Propriétés publiques (lecture seule)
    # ────────────────────────────────────────────────────────────────────────

    @property
    def oauth_tokens(self) -> OAuthTokens | None:
        """Tokens Azure courants (peut être None avant le premier login)."""
        return self._oauth_tokens

    @property
    def bearer(self) -> BearerToken | None:
        """Bearer EasyCare courant (peut être None avant initialisation)."""
        return self._bearer

    @property
    def is_authenticated(self) -> bool:
        """Vrai si on a un refresh_token (donc on peut produire un bearer valide).

        Note : ne garantit pas que les tokens courants sont non-expirés —
        utiliser `get_valid_bearer()` pour avoir une garantie de validité.
        """
        return self._oauth_tokens is not None

    # ────────────────────────────────────────────────────────────────────────
    # Construction de l'URL d'autorisation (config_flow étape 1)
    # ────────────────────────────────────────────────────────────────────────

    @staticmethod
    def build_authorize_url() -> str:
        """Construit l'URL OAuth2 que l'utilisateur doit ouvrir.

        L'utilisateur ouvre cette URL dans son navigateur, se connecte avec
        ses identifiants Waterair, puis est redirigé vers une URL de la forme :

            msauth.com.waterair.easycare://auth?code=XXX&...

        Cette URL n'aboutit nulle part (le schéma `msauth://` est réservé à
        l'app mobile), mais le navigateur va l'afficher en erreur tout en
        révélant le code dans la barre d'adresse. L'utilisateur copie ce code
        et le colle dans le config_flow HA.

        Returns:
            URL complète prête à être ouverte.
        """
        params = {
            "response_type": "code",
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": OAUTH_SCOPES,
            "code_challenge": OAUTH_CODE_CHALLENGE,
            "code_challenge_method": "S256",
        }
        return f"{OAUTH_AUTHORIZE_URL}?{urlencode(params)}"

    # ────────────────────────────────────────────────────────────────────────
    # Login initial — échange du code OAuth2 contre des tokens
    # ────────────────────────────────────────────────────────────────────────

    async def exchange_code(self, code: str) -> OAuthTokens:
        """Échange un code d'autorisation OAuth2 contre des tokens Azure.

        Appelé une seule fois par config_flow lors du setup initial.

        Args:
            code: code retourné par l'URL `msauth://...?code=XXX` après login.

        Returns:
            Les tokens fraîchement obtenus (déjà stockés dans `self._oauth_tokens`).

        Raises:
            EasyCareInvalidCodeError: code invalide ou expiré (généralement
                quand l'utilisateur met trop de temps entre l'autorisation et
                la saisie du code dans HA).
            EasyCareConnectionError: problème réseau.
            EasyCareApiError       : autre erreur HTTP.
        """
        _LOGGER.debug("Échange du code OAuth contre des tokens Azure")

        # Note : Azure B2C accepte le code_verifier soit dans les params
        # query, soit dans le body. On utilise les params pour rester
        # compatible avec ce que fait l'app mobile (cf. plugin existant).
        params = {
            "code": code,
            "grant_type": "authorization_code",
            "code_verifier": OAUTH_CODE_VERIFIER,
            "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI,
        }

        data = await self._post_token_endpoint(params)

        try:
            tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            # Si la réponse n'a pas de refresh_token, c'est que le scope
            # `offline_access` est manquant ou que le code a déjà été utilisé.
            raise EasyCareInvalidCodeError(
                "La réponse OAuth ne contient pas de refresh_token — "
                "vérifiez que le code est récent et n'a pas déjà été utilisé"
            ) from err

        self._oauth_tokens = tokens
        _LOGGER.info("Tokens Azure obtenus avec succès (refresh_token disponible)")

        # On obtient immédiatement un bearer EasyCare pour valider le flow complet
        await self._refresh_bearer_from_id_token(tokens.id_token)

        await self._notify_tokens_updated()
        return tokens

    # ────────────────────────────────────────────────────────────────────────
    # Refresh des tokens Azure (grant_type=refresh_token)
    # ────────────────────────────────────────────────────────────────────────

    async def refresh_tokens(self) -> OAuthTokens:
        """Renouvelle les tokens Azure via le refresh_token.

        À l'issue de cet appel, le `refresh_token` est ROTATÉ : le nouveau
        doit remplacer l'ancien dans le ConfigEntry HA (via le callback).

        Returns:
            Les nouveaux tokens.

        Raises:
            EasyCareTokenExpiredError: refresh_token expiré ou révoqué.
                Déclenche le reauth_flow HA.
            EasyCareAuthError        : autre erreur d'auth.
            EasyCareConnectionError  : problème réseau.
        """
        if self._oauth_tokens is None:
            raise EasyCareAuthError(
                "Aucun refresh_token disponible — login initial requis"
            )

        _LOGGER.debug("Renouvellement des tokens Azure via refresh_token")

        params = {
            "grant_type": "refresh_token",
            "refresh_token": self._oauth_tokens.refresh_token,
            "client_id": OAUTH_CLIENT_ID,
        }

        try:
            data = await self._post_token_endpoint(params)
        except EasyCareApiError as err:
            # Azure B2C retourne 400 avec error="invalid_grant" si le refresh
            # token est expiré ou révoqué — c'est un cas particulier qui doit
            # déclencher le reauth flow HA, pas une simple erreur réseau.
            if err.status_code == 400 and err.body and "invalid_grant" in err.body:
                _LOGGER.warning(
                    "Le refresh_token est expiré ou révoqué — "
                    "ré-authentification requise"
                )
                raise EasyCareTokenExpiredError(
                    "Le refresh_token Azure B2C est expiré ou révoqué. "
                    "L'utilisateur doit fournir un nouveau code via le reauth flow."
                ) from err
            raise

        try:
            new_tokens = OAuthTokens.from_api(data)
        except EasyCareInvalidResponseError as err:
            raise EasyCareAuthError(
                f"Réponse de refresh inattendue : {err}"
            ) from err

        self._oauth_tokens = new_tokens
        _LOGGER.info("Tokens Azure rafraîchis avec succès (refresh_token rotaté)")

        # On rafraîchit aussi le bearer EasyCare immédiatement
        await self._refresh_bearer_from_id_token(new_tokens.id_token)

        await self._notify_tokens_updated()
        return new_tokens

    # ────────────────────────────────────────────────────────────────────────
    # Obtention du bearer EasyCare à partir de l'id_token Azure
    # ────────────────────────────────────────────────────────────────────────

    async def _refresh_bearer_from_id_token(self, id_token: str) -> BearerToken:
        """Échange un id_token Azure contre un bearer EasyCare.

        Endpoint :
            POST https://easycare.waterair.com/oauth2/tokenFromAzureADB2CIdToken
            Authorization: Basic NWQwMjFkYzI0NzhjMjE3MDc3MzI0NDEwOkNtVmZxNDNiZE5hUUZjWA==
            Body: {"idToken": "<id_token>"}

        Args:
            id_token: id_token Azure non expiré.

        Returns:
            Le bearer EasyCare prêt à être utilisé.
        """
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
                url,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
            ) as response:
                body = await response.text()

                if response.status != 200:
                    _LOGGER.error(
                        "Échec /oauth2/tokenFromAzureADB2CIdToken : HTTP %s — %s",
                        response.status, body[:300],
                    )
                    raise EasyCareApiError(
                        "Impossible d'obtenir le bearer EasyCare",
                        status_code=response.status,
                        body=body,
                    )

                try:
                    data = await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EasyCareInvalidResponseError(
                        f"Réponse non-JSON de tokenFromAzureADB2CIdToken : {err}"
                    ) from err

        except asyncio.TimeoutError as err:
            raise EasyCareTimeoutError(
                "Timeout lors de l'obtention du bearer EasyCare"
            ) from err
        except ClientError as err:
            raise EasyCareConnectionError(
                f"Erreur réseau lors de l'obtention du bearer : {err}"
            ) from err

        bearer = BearerToken.from_api(data)
        self._bearer = bearer
        _LOGGER.info("Bearer EasyCare obtenu (expire dans ~%ds)",
                     int(bearer.expires_at - datetime.now(tz=timezone.utc).timestamp()))
        return bearer

    # ────────────────────────────────────────────────────────────────────────
    # Méthode principale — utilisée par le client API
    # ────────────────────────────────────────────────────────────────────────

    async def get_valid_bearer(self) -> str:
        """Retourne un bearer EasyCare valide, en gérant tous les refreshs.

        C'est LA méthode à appeler depuis le client API avant chaque requête.
        Elle garantit que le bearer retourné est valide (non expiré).

        Logique :
            1. Si pas de tokens Azure du tout → EasyCareAuthError (login requis)
            2. Si tokens Azure expirés ou bientôt → refresh_tokens()
            3. Si bearer absent/expiré → _refresh_bearer_from_id_token()
            4. Retourne self._bearer.bearer

        Tout est protégé par un asyncio.Lock pour éviter les refreshs concurrents.

        Returns:
            La chaîne du bearer EasyCare prête à utiliser dans le header
            `Authorization: Bearer <chaîne>`.

        Raises:
            EasyCareAuthError        : pas de tokens disponibles
            EasyCareTokenExpiredError: refresh_token expiré, reauth requis
            EasyCareConnectionError  : problème réseau pendant le refresh
        """
        async with self._refresh_lock:
            # 1. Vérifier qu'on a au moins un refresh_token
            if self._oauth_tokens is None:
                raise EasyCareAuthError(
                    "Pas de tokens Azure disponibles — login initial requis"
                )

            # 2. Refresh id_token Azure si bientôt expiré
            if self._oauth_tokens.is_expired(
                margin_seconds=ID_TOKEN_REFRESH_MARGIN_SECONDS
            ):
                _LOGGER.debug(
                    "id_token Azure expire bientôt → refresh proactif"
                )
                await self.refresh_tokens()
                # refresh_tokens() rafraîchit aussi le bearer → on a tout
                return self._bearer.bearer  # type: ignore[union-attr]

            # 3. Bearer manquant ou bientôt expiré → on le rafraîchit
            if self._bearer is None or self._bearer.is_expired(
                margin_seconds=BEARER_REFRESH_MARGIN_SECONDS
            ):
                _LOGGER.debug(
                    "Bearer EasyCare expire bientôt → renouvellement"
                )
                await self._refresh_bearer_from_id_token(self._oauth_tokens.id_token)
                await self._notify_tokens_updated()

            # 4. Tout est bon
            return self._bearer.bearer  # type: ignore[union-attr]

    async def invalidate_bearer(self) -> None:
        """Force l'invalidation du bearer (à appeler sur réception d'un 401).

        Le prochain appel à `get_valid_bearer()` regénérera un bearer frais.
        Si même le nouveau bearer échoue, c'est que l'id_token est invalide
        et il faut passer par `refresh_tokens()`.
        """
        async with self._refresh_lock:
            _LOGGER.debug("Invalidation forcée du bearer EasyCare")
            self._bearer = None

    # ────────────────────────────────────────────────────────────────────────
    # Helpers privés
    # ────────────────────────────────────────────────────────────────────────

    async def _post_token_endpoint(self, params: dict[str, Any]) -> dict[str, Any]:
        """Appelle l'endpoint /oauth2/v2.0/token d'Azure B2C avec les params donnés.

        Encapsule la gestion des erreurs HTTP et le parsing JSON.

        Args:
            params: paramètres OAuth2 (grant_type, code/refresh_token, etc.).

        Returns:
            La réponse JSON décodée.

        Raises:
            EasyCareConnectionError : problème réseau.
            EasyCareTimeoutError    : timeout.
            EasyCareApiError        : HTTP 4xx/5xx.
        """
        headers = {
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        try:
            async with self._session.post(
                OAUTH_TOKEN_URL,
                data=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_AUTH),
            ) as response:
                body = await response.text()

                if response.status != 200:
                    _LOGGER.warning(
                        "OAuth /token : HTTP %s — %s",
                        response.status, body[:300],
                    )
                    raise EasyCareApiError(
                        f"Échec endpoint OAuth /token",
                        status_code=response.status,
                        body=body,
                    )

                try:
                    return await response.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise EasyCareInvalidResponseError(
                        f"Réponse OAuth non-JSON : {err}"
                    ) from err

        except asyncio.TimeoutError as err:
            raise EasyCareTimeoutError(
                "Timeout sur l'endpoint OAuth /token"
            ) from err
        except ClientResponseError as err:
            # Levé en cas de raise_for_status() — ne devrait pas arriver ici
            # car on lit le statut manuellement, mais on couvre.
            raise EasyCareApiError(
                f"Erreur HTTP sur OAuth /token : {err}",
                status_code=err.status,
            ) from err
        except ClientError as err:
            raise EasyCareConnectionError(
                f"Erreur réseau sur OAuth /token : {err}"
            ) from err

    async def _notify_tokens_updated(self) -> None:
        """Notifie le callback de mise à jour des tokens, si défini.

        Le callback est typiquement utilisé par `__init__.py` pour persister
        les nouveaux tokens dans `config_entry.data` (HA chiffre cette zone).

        Les erreurs du callback ne propagent pas — on log et on continue, car
        l'authentification reste valide en mémoire même si la persistance échoue.
        """
        if self._on_tokens_updated is None:
            return
        if self._oauth_tokens is None or self._bearer is None:
            return

        try:
            await self._on_tokens_updated(self._oauth_tokens, self._bearer)
        except Exception as err:  # noqa: BLE001 — on veut tout attraper
            _LOGGER.error(
                "Erreur lors du callback de persistance des tokens : %s", err
            )
