"""Client API asynchrone pour Easy-care by Waterair.

Ce client encapsule toutes les opérations métier de l'écosystème Waterair :

  - Lecture des données utilisateur et piscine (`get_user`, `get_modules`)
  - Lecture de l'état du BPC (`get_bpc_status`) — pompe, lumières
  - Commandes ON/OFF des voies BPC (`set_bpc_manual`) — pompe, lumières
  - Lecture du statut de filtration (`get_pool_status`) — mode, boost, compteurs
  - Changement de mode de filtration (`set_filtration_mode`) — AUTO/CONTINUOUS/...
  - Boost et annulation (`start_boost`, `cancel_boost`)

Toutes les méthodes :
  - Sont asynchrones (compatibles HA `await client.xxx()`)
  - Utilisent `EasyCareAuth.get_valid_bearer()` pour avoir un bearer toujours frais
  - Implémentent un retry automatique sur 401 (bearer rejeté en cours de route)
  - Retournent des dataclasses fortement typées (de `api/models.py`)
  - Lèvent des exceptions spécifiques (de `api/exceptions.py`)

Architecture :

    EasyCareAuth (auth.py)
         ↓ get_valid_bearer()
    EasyCareClient (ce fichier)
         ↓ retourne des dataclasses
    Coordinators HA (coordinator.py)
         ↓ exposent les données
    Entités HA (sensor.py, switch.py, etc.)

Le client ne fait AUCUN polling/cache : c'est le rôle des coordinators.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from aiohttp import ClientError

from ..const import (
    API_HOST_EASYCARE,
    API_PATH_BPC_MANUAL,
    API_PATH_BPC_STATUS,
    API_PATH_GET_POOL_STATUS,
    API_PATH_GET_USER,
    API_PATH_GET_USER_MODULES,
    API_PATH_REPORT_MANUAL_SENT,
    API_PATH_SET_STATUS_COMMAND,
    BOOST_CANCEL,
    BOOST_MODES,
    BPC_ACTION_OFF,
    BPC_ACTION_ON,
    FILTRATION_MODES,
    HTTP_MAX_RETRIES,
    HTTP_RETRY_DELAY,
    HTTP_TIMEOUT,
    MODULE_TYPE_BPC,
    MODULE_TYPE_WATBOX,
    USER_AGENT,
)
from .auth import EasyCareAuth
from .exceptions import (
    EasyCareApiError,
    EasyCareConnectionError,
    EasyCareInvalidResponseError,
    EasyCareTimeoutError,
    EasyCareUnauthorizedError,
)
from .models import (
    Alerts,
    BPCInput,
    Client,
    Metrics,
    Module,
    Pool,
    PoolStatus,
    Treatment,
)

_LOGGER = logging.getLogger(__name__)


class EasyCareClient:
    """Client API pour l'écosystème Easy-care by Waterair.

    Une instance par ConfigEntry HA, réutilisée pendant toute la durée de vie
    de l'intégration. Maintient une référence à `EasyCareAuth` pour la gestion
    transparente des tokens.

    Usage typique :

        client = EasyCareClient(session, auth, pool_id=1)

        # Données piscine
        metrics, alerts, treatment, client_info, pool = await client.get_user()

        # Modules
        modules = await client.get_modules()

        # État BPC
        bpc_inputs = await client.get_bpc_status(watbox, bpc)

        # Commande pompe
        await client.set_bpc_manual(watbox, bpc, index=0, action="on", duration_minutes=60)

        # Mode filtration
        status = await client.get_pool_status()
        await client.set_filtration_mode("AUTO")

        # Boost
        await client.start_boost("BOOST12H")
        await client.cancel_boost()
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        auth: EasyCareAuth,
        *,
        pool_id: int = 1,
    ) -> None:
        """Initialise le client.

        Args:
            session  : session aiohttp partagée (créée par HA).
            auth     : instance EasyCareAuth pour les bearer tokens.
            pool_id  : index de la piscine dans le compte (1-based, première par défaut).
        """
        self._session = session
        self._auth = auth
        self._pool_id = pool_id
        # ID MongoDB de la piscine — renseigné après le premier get_user()
        # et transmis à get_pool_status via ?poolId=
        self._pool_db_id: str = ""
        # IDs MongoDB des modules — renseignés après le premier get_bpc_status()
        # et injectés dans les payloads setStatusCommandToSend / reportManualCommandSent.
        # On essaiera watbox.id en priorité (passerelle = candidat principal pour
        # setStatusCommandToSend), puis bpc.id en fallback si watbox échoue.
        self._bpc_module_id: str = ""
        self._watbox_module_id: str = ""

    # ════════════════════════════════════════════════════════════════════════
    # MÉTHODES PUBLIQUES — LECTURE
    # ════════════════════════════════════════════════════════════════════════

    async def get_user(self) -> tuple[Client, Pool, Metrics, Alerts, Treatment]:
        """Récupère les données complètes de l'utilisateur et de sa piscine.

        Endpoint : GET /api/getUser?attributesToPopulate[]=pools

        Returns:
            Tuple (client, pool, metrics, alerts, treatment) :
              - client    : propriétaire du compte
              - pool      : modèle et caractéristiques de la piscine
              - metrics   : dernières mesures pH/chlore/température/pression
              - alerts    : notifications du système
              - treatment : traitement en cours

        Raises:
            EasyCareInvalidResponseError: si pas de piscine dans le compte
                ou si le pool_id est hors limites.
        """
        data = await self._request(
            "GET",
            API_HOST_EASYCARE,
            API_PATH_GET_USER,
        )

        client = Client.from_api(data)

        # Le compte contient une liste "pools" — on prend celle indexée par pool_id
        pools = data.get("pools") or []
        if not pools:
            raise EasyCareInvalidResponseError(
                "Aucune piscine trouvée sur le compte Waterair"
            )

        # pool_id est 1-based dans l'UI/config — on convertit en 0-based
        idx = self._pool_id - 1
        if idx < 0 or idx >= len(pools):
            raise EasyCareInvalidResponseError(
                f"pool_id={self._pool_id} hors limites (le compte a {len(pools)} piscine(s))"
            )

        pool_data = pools[idx]
        pool = Pool.from_api(pool_data)
        metrics = Metrics.from_api(pool_data)
        alerts = Alerts.from_api(pool_data)
        treatment = Treatment.from_api(pool_data)

        # Mise en cache de l'ID MongoDB pour get_pool_status
        if pool.id:
            self._pool_db_id = pool.id

        return client, pool, metrics, alerts, treatment

    async def get_modules(self) -> tuple[Module, ...]:
        """Récupère la liste des modules de la piscine sélectionnée.

        Endpoint : GET /api/getUserWithHisModules

        Returns:
            Tuple immuable de tous les modules (WATBOX, BPC, AC1, LR-PR, etc.)
            de la piscine indexée par self._pool_id.

        Raises:
            EasyCareInvalidResponseError: structure inattendue ou piscine absente.
        """
        data = await self._request(
            "GET",
            API_HOST_EASYCARE,
            API_PATH_GET_USER_MODULES,
        )

        _LOGGER.debug(
            "getUserWithHisModules — clés racine : %s", list(data.keys())
        )

        # L'API peut retourner les pools sous différentes clés selon la version
        pools = (
            data.get("pools")
            or data.get("poolsWithModules")
            or (data.get("user") or {}).get("pools")
            or []
        )

        # Cas où les modules sont directement à la racine (pas de nesting pools)
        if not pools and "modules" in data:
            _LOGGER.debug(
                "getUserWithHisModules — modules à la racine (pas de pools)"
            )
            modules_raw = data.get("modules") or []
            modules: list[Module] = []
            for m in modules_raw:
                try:
                    modules.append(Module.from_api(m))
                except EasyCareInvalidResponseError as err:
                    _LOGGER.warning("Module ignoré (données invalides) : %s", err)
            return tuple(modules)

        if not pools:
            _LOGGER.warning(
                "getUserWithHisModules — structure inattendue, clés reçues : %s",
                list(data.keys()),
            )
            raise EasyCareInvalidResponseError(
                "Aucune piscine trouvée sur le compte (getUserWithHisModules)"
            )

        idx = self._pool_id - 1
        if idx < 0 or idx >= len(pools):
            raise EasyCareInvalidResponseError(
                f"pool_id={self._pool_id} hors limites ({len(pools)} piscine(s))"
            )

        pool_data = pools[idx]
        _LOGGER.debug(
            "getUserWithHisModules — clés pool[%d] : %s", idx, list(pool_data.keys())
        )
        modules_raw = (
            pool_data.get("modules")
            or pool_data.get("modulesList")
            or []
        )

        modules: list[Module] = []
        for m in modules_raw:
            try:
                modules.append(Module.from_api(m))
            except EasyCareInvalidResponseError as err:
                # Un module malformé ne doit pas tout casser — on log et on continue.
                _LOGGER.warning("Module ignoré (données invalides) : %s", err)

        return tuple(modules)

    async def get_bpc_status(
        self,
        watbox: Module,
        bpc: Module,
    ) -> tuple[BPCInput, ...]:
        """Récupère l'état des voies du BPC (pompe, lumières).

        Endpoint : GET /api/module/{watbox_serial}/status/{bpc_short_name}

        Args:
            watbox: module WATBOX (passerelle).
            bpc   : module BPC (boîtier piscine connecté).

        Returns:
            Tuple des voies BPC, triées par index croissant.
            Conventionnellement :
              - index 0 = pompe de filtration
              - index 1 = projecteur (spot)
              - index 2 = éclairage des marches (escalight)
        """
        self._validate_module_type(watbox, MODULE_TYPE_WATBOX, "watbox")
        self._validate_module_type(bpc, MODULE_TYPE_BPC, "bpc")

        path = API_PATH_BPC_STATUS.format(
            watbox_serial=watbox.serial_number,
            bpc_name=bpc.short_name,
        )

        data = await self._request("GET", API_HOST_EASYCARE, path)

        # Mise en cache des IDs pour les commandes.
        # On essaie aussi l'ID du WATBOX (passerelle) car setStatusCommandToSend
        # adresse peut-être le WATBOX plutôt que le BPC directement.
        if watbox.id:
            self._watbox_module_id = watbox.id
        if bpc.id:
            self._bpc_module_id = bpc.id

        # ── Log diagnostic — dump des champs ID disponibles ───────────────────
        # Clés potentiellement utiles dans les données brutes du module
        bpc_extra_ids = {k: bpc.raw.get(k) for k in ("programId", "connectedModule", "gatewayId", "linkedModule") if bpc.raw.get(k)}
        watbox_extra_ids = {k: watbox.raw.get(k) for k in ("programId", "connectedModule", "gatewayId", "linkedModule") if watbox.raw.get(k)}
        _LOGGER.warning(
            "[DIAG moduleId] watbox.id=%r | bpc.id=%r "
            "| pool_db_id=%r "
            "| bpc_extra=%s | watbox_extra=%s "
            "| status keys=%s",
            watbox.id,
            bpc.id,
            self._pool_db_id,
            bpc_extra_ids or "<none>",
            watbox_extra_ids or "<none>",
            sorted(data.keys()),
        )
        # ─────────────────────────────────────────────────────────────────────

        pool_inputs = data.get("pool") or []
        inputs: list[BPCInput] = []
        for raw_input in pool_inputs:
            try:
                inputs.append(BPCInput.from_api(raw_input))
            except EasyCareInvalidResponseError as err:
                _LOGGER.warning("Voie BPC ignorée (données invalides) : %s", err)

        # Tri par index croissant pour garantir un ordre déterministe
        inputs.sort(key=lambda x: x.index)
        return tuple(inputs)

    async def get_pool_status(self) -> PoolStatus:
        """Récupère l'état complet de la filtration (mode, boost, compteurs).

        Endpoint : GET /api/getPoolStatus?poolId={id}

        Returns:
            PoolStatus avec mode, boost, compteurs (tous optionnels).
        """
        path = API_PATH_GET_POOL_STATUS
        if self._pool_db_id:
            path = f"{path}?poolId={self._pool_db_id}"
        data = await self._request(
            "GET",
            API_HOST_EASYCARE,
            path,
        )
        return PoolStatus.from_api(data)

    # ════════════════════════════════════════════════════════════════════════
    # MÉTHODES PUBLIQUES — COMMANDES (ÉCRITURE)
    # ════════════════════════════════════════════════════════════════════════

    async def set_bpc_manual(
        self,
        watbox: Module,
        bpc: Module,
        *,
        index: int,
        action: str,
        duration_minutes: int = 60,
    ) -> bool:
        """Envoie une commande manuelle ON/OFF à une voie du BPC.

        Workflow obligatoire en 2 étapes :
          1. POST /api/module/{watbox}/manual/{bpc} avec le payload de commande
          2. POST /api/reportManualCommandSent pour confirmer l'envoi

        Si l'étape 2 est omise, la commande peut être ignorée côté serveur.

        Args:
            watbox          : module WATBOX (passerelle).
            bpc             : module BPC.
            index           : voie ciblée (0=pompe, 1=spot, 2=escalight).
            action          : 'on' ou 'off' (insensible à la casse).
            duration_minutes: durée de la session manuelle (ignorée pour 'off').
                Le serveur attend des secondes, on convertit.

        Returns:
            True si la commande a été acceptée (étape 1 = HTTP 200).

        Raises:
            ValueError: action invalide.
        """
        self._validate_module_type(watbox, MODULE_TYPE_WATBOX, "watbox")
        self._validate_module_type(bpc, MODULE_TYPE_BPC, "bpc")

        action_lower = action.lower().strip()
        if action_lower == "on":
            action_code = BPC_ACTION_ON
            payload_extra: dict[str, Any] = {
                "manualDuration": int(duration_minutes) * 60,
            }
        elif action_lower == "off":
            action_code = BPC_ACTION_OFF
            payload_extra = {}
        else:
            raise ValueError(
                f"Action invalide : {action!r} (attendu 'on' ou 'off')"
            )

        payload = {
            "pool": {
                "index": int(index),
                "action": action_code,
                **payload_extra,
            }
        }

        path = API_PATH_BPC_MANUAL.format(
            watbox_serial=watbox.serial_number,
            bpc_name=bpc.short_name,
        )

        _LOGGER.debug(
            "BPC commande : %s voie %d (%s) durée=%dm",
            action_lower.upper(), index, bpc.short_name, duration_minutes,
        )

        # Étape 1 — envoi de la commande
        await self._request(
            "POST",
            API_HOST_EASYCARE,
            path,
            json_payload=payload,
        )

        # Étape 2 — confirmation obligatoire (sinon le serveur peut ignorer la commande)
        try:
            report_payload: dict[str, Any] = {}
            if bpc.id:
                report_payload["moduleId"] = bpc.id
            await self._request(
                "POST",
                API_HOST_EASYCARE,
                API_PATH_REPORT_MANUAL_SENT,
                json_payload=report_payload,
            )
        except Exception as err:  # noqa: BLE001 — étape 2 non-critique
            _LOGGER.warning(
                "Échec étape 2 (reportManualCommandSent) — la commande a peut-être "
                "été ignorée par le serveur : %s", err,
            )
            # On ne lève pas : la commande peut tout de même avoir fonctionné.
            # Le coordinator détectera l'état réel au prochain poll.

        return True

    async def set_filtration_mode(self, mode: str) -> bool:
        """Change le mode de filtration de la pompe.

        Endpoint : POST /api/setStatusCommandToSend

        Modes valides : AUTO, CONTINUOUS, MANUAL, PROG.
        """
        mode_upper = mode.upper().strip()
        if mode_upper not in FILTRATION_MODES:
            raise ValueError(
                f"Mode invalide : {mode!r} (attendu : {', '.join(FILTRATION_MODES)})"
            )
        # WATBOX id en priorité (passerelle), BPC id en fallback, pool id en dernier recours
        module_id_candidate = self._watbox_module_id or self._bpc_module_id or self._pool_db_id
        _LOGGER.warning(
            "[DIAG setStatusCommandToSend] watbox_id=%r | bpc_id=%r | pool_db_id=%r → utilise=%r",
            self._watbox_module_id or "<vide>",
            self._bpc_module_id or "<vide>",
            self._pool_db_id or "<vide>",
            module_id_candidate or "<vide>",
        )
        payload: dict[str, Any] = {"mode": mode_upper}
        if module_id_candidate:
            payload["moduleId"] = module_id_candidate
        await self._request(
            "POST",
            API_HOST_EASYCARE,
            API_PATH_SET_STATUS_COMMAND,
            json_payload=payload,
        )
        return True

    async def start_boost(self, boost_mode: str) -> bool:
        """Démarre un boost de filtration (BOOST12H ou BOOST24H)."""
        boost_upper = boost_mode.upper().strip()
        if boost_upper not in BOOST_MODES:
            raise ValueError(
                f"Mode boost invalide : {boost_mode!r} "
                f"(attendu : {', '.join(BOOST_MODES)})"
            )
        _LOGGER.debug("Démarrage boost %s", boost_upper)
        module_id_candidate = self._watbox_module_id or self._bpc_module_id or self._pool_db_id
        payload: dict[str, Any] = {"mode": boost_upper}
        if module_id_candidate:
            payload["moduleId"] = module_id_candidate
        await self._request(
            "POST",
            API_HOST_EASYCARE,
            API_PATH_SET_STATUS_COMMAND,
            json_payload=payload,
        )
        return True

    async def cancel_boost(self) -> bool:
        """Annule le boost de filtration en cours."""
        _LOGGER.debug("Annulation boost en cours")
        module_id_candidate = self._watbox_module_id or self._bpc_module_id or self._pool_db_id
        payload: dict[str, Any] = {"mode": BOOST_CANCEL}
        if module_id_candidate:
            payload["moduleId"] = module_id_candidate
        await self._request(
            "POST",
            API_HOST_EASYCARE,
            API_PATH_SET_STATUS_COMMAND,
            json_payload=payload,
        )
        return True

    # ════════════════════════════════════════════════════════════════════════
    # COUCHE HTTP INTERNE — REQUEST AVEC RETRY 401
    # ════════════════════════════════════════════════════════════════════════

    async def _request(
        self,
        method: str,
        host: str,
        path: str,
        *,
        json_payload: dict[str, Any] | None = None,
        _retry_count: int = 0,
    ) -> dict[str, Any]:
        """Effectue une requête HTTP authentifiée et retourne la réponse JSON.

        Gère automatiquement :
          - L'ajout du bearer dans Authorization (via EasyCareAuth)
          - Le retry sur 401 (refresh forcé du bearer + reessai 1 fois max)
          - Le retry sur erreur réseau transitoire (max HTTP_MAX_RETRIES)
          - Le parsing JSON tolérant (content-type ignoré)

        Args:
            method      : 'GET' ou 'POST'.
            host        : URL de base (sans path).
            path        : chemin relatif (commençant par /).
            json_payload: corps JSON (POST uniquement).
            _retry_count: usage interne pour limiter les retries 401.

        Returns:
            dict décodé depuis la réponse JSON.

        Raises:
            EasyCareUnauthorizedError: après refresh, le bearer reste rejeté.
            EasyCareApiError         : HTTP 4xx/5xx hors 401.
            EasyCareConnectionError  : erreur réseau persistante.
            EasyCareTimeoutError     : timeout après tous les retries.
        """
        url = f"{host}{path}"
        bearer = await self._auth.get_valid_bearer()

        headers = {
            "Authorization": f"Bearer {bearer}",
            "User-Agent": USER_AGENT,
            "accept": "version=2.5",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        # Boucle de retry pour les erreurs réseau (PAS pour les 401, géré séparément)
        last_exc: Exception | None = None
        for attempt in range(HTTP_MAX_RETRIES):
            try:
                async with self._session.request(
                    method,
                    url,
                    json=json_payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
                ) as response:
                    body = await response.text()

                    # 401 → bearer rejeté → on refresh et on retry UNE FOIS
                    if response.status == 401:
                        if _retry_count >= 1:
                            raise EasyCareUnauthorizedError(
                                f"Bearer rejeté même après refresh : {url}"
                            )
                        _LOGGER.info(
                            "HTTP 401 sur %s — invalidation du bearer et retry",
                            url,
                        )
                        await self._auth.invalidate_bearer()
                        return await self._request(
                            method, host, path,
                            json_payload=json_payload,
                            _retry_count=_retry_count + 1,
                        )

                    if response.status >= 400:
                        _LOGGER.warning(
                            "HTTP %d sur %s %s — %s",
                            response.status, method, url, body[:300],
                        )
                        raise EasyCareApiError(
                            f"Échec {method} {path}",
                            status_code=response.status,
                            body=body,
                        )

                    # Tolérant aux réponses vides (POST de confirmation peuvent
                    # retourner un corps vide avec un 200)
                    if not body.strip():
                        return {}

                    try:
                        return await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise EasyCareInvalidResponseError(
                            f"Réponse non-JSON depuis {url} : {err}"
                        ) from err

            except asyncio.TimeoutError as err:
                last_exc = EasyCareTimeoutError(f"Timeout sur {method} {url}")
                _LOGGER.debug(
                    "Tentative %d/%d : timeout sur %s",
                    attempt + 1, HTTP_MAX_RETRIES, url,
                )
            except ClientError as err:
                last_exc = EasyCareConnectionError(
                    f"Erreur réseau sur {method} {url} : {err}"
                )
                _LOGGER.debug(
                    "Tentative %d/%d : %s",
                    attempt + 1, HTTP_MAX_RETRIES, err,
                )

            # Backoff avant le prochain essai (sauf dernier tour)
            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))

        # Toutes les tentatives ont échoué
        assert last_exc is not None
        raise last_exc

    # ════════════════════════════════════════════════════════════════════════
    # HELPERS INTERNES
    # ════════════════════════════════════════════════════════════════════════

    @staticmethod
    def _validate_module_type(module: Module, expected: str, role: str) -> None:
        """Vérifie qu'un module a le bon type — sécurité contre les inversions.

        Args:
            module   : le module à valider.
            expected : type attendu (ex: 'lr-pc').
            role     : nom logique pour le message d'erreur ('watbox', 'bpc'...).

        Raises:
            ValueError: si le module n'a pas le type attendu.
        """
        if module.type != expected:
            raise ValueError(
                f"Module fourni pour '{role}' a le type {module.type!r}, "
                f"attendu {expected!r}"
            )
