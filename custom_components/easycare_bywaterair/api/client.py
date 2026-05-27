"""Client API asynchrone pour Easy-care by Waterair.

Encapsule toutes les opérations métier :
  - Lecture des données utilisateur, modules, état BPC
  - Commandes ON/OFF des voies BPC (pompe, lumières)
  - Changement de mode de filtration et gestion des offsets AUTO
  - Boost et annulation
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp
from aiohttp import ClientError

from ..const import (
    ADAPT_OFFSET_MINUS,
    ADAPT_OFFSET_NEUTRAL,
    ADAPT_OFFSET_PLUS,
    API_HOST_EASYCARE,
    API_PATH_BPC_MANUAL,
    API_PATH_BPC_PROGRAMS,
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
    FILTRATION_MODES_WITH_OFFSET,
    HTTP_MAX_RETRIES,
    HTTP_RETRY_DELAY,
    HTTP_TIMEOUT,
    MODE_AUTO,
    MODE_AUTO_MINUS,
    MODE_AUTO_PLUS,
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

# Encodage du mode de filtration dans programCharacteristics (programme pompe index=0).
# Les valeurs proviennent du reverse engineering de l'app mobile.
# mode=2 + rule=0 → PROG (lecture seule, non exposé en écriture).
_MODE_TO_PROG: dict[str, tuple[int, int | None]] = {
    "MANUAL":     (0, None),
    "CONTINUOUS": (1, None),
    "AUTO":       (2, 1),
}


class EasyCareClient:
    """Client API pour l'écosystème Easy-care by Waterair.

    Une instance par ConfigEntry, réutilisée pendant toute la durée de vie
    de l'intégration. Ne fait aucun polling — c'est le rôle des coordinators.
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
            session : session aiohttp partagée.
            auth    : instance EasyCareAuth pour les bearer tokens.
            pool_id : index de la piscine dans le compte (1-based).
        """
        self._session = session
        self._auth = auth
        self._pool_id = pool_id
        self._pool_db_id: str = ""
        self._bpc_module_id: str = ""
        self._watbox: Module | None = None
        self._bpc: Module | None = None

    async def get_user(self) -> tuple[Client, Pool, Metrics, Alerts, Treatment]:
        """Récupère les données complètes de l'utilisateur et de sa piscine.

        Returns:
            Tuple (client, pool, metrics, alerts, treatment).

        Raises:
            EasyCareInvalidResponseError: si aucune piscine ou pool_id hors limites.
        """
        data = await self._request("GET", API_HOST_EASYCARE, API_PATH_GET_USER)
        client = Client.from_api(data)
        pools = data.get("pools") or []
        if not pools:
            raise EasyCareInvalidResponseError("Aucune piscine trouvée sur le compte Waterair")
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
        if pool.id:
            self._pool_db_id = pool.id
        return client, pool, metrics, alerts, treatment

    async def get_modules(self) -> tuple[Module, ...]:
        """Récupère la liste des modules de la piscine sélectionnée.

        Returns:
            Tuple immuable de tous les modules (WATBOX, BPC, AC1, LR-PR, etc.).
        """
        data = await self._request("GET", API_HOST_EASYCARE, API_PATH_GET_USER_MODULES)
        _LOGGER.debug("getUserWithHisModules — clés racine : %s", list(data.keys()))
        pools = (
            data.get("pools")
            or data.get("poolsWithModules")
            or (data.get("user") or {}).get("pools")
            or []
        )
        if not pools and "modules" in data:
            modules_raw = data.get("modules") or []
            modules: list[Module] = []
            for m in modules_raw:
                try:
                    modules.append(Module.from_api(m))
                except EasyCareInvalidResponseError as err:
                    _LOGGER.warning("Module ignoré : %s", err)
            return tuple(modules)
        if not pools:
            _LOGGER.warning("getUserWithHisModules — structure inattendue : %s", list(data.keys()))
            raise EasyCareInvalidResponseError("Aucune piscine trouvée (getUserWithHisModules)")
        idx = self._pool_id - 1
        if idx < 0 or idx >= len(pools):
            raise EasyCareInvalidResponseError(
                f"pool_id={self._pool_id} hors limites ({len(pools)} piscine(s))"
            )
        pool_data = pools[idx]
        modules_raw = pool_data.get("modules") or pool_data.get("modulesList") or []
        modules = []
        for m in modules_raw:
            try:
                modules.append(Module.from_api(m))
            except EasyCareInvalidResponseError as err:
                _LOGGER.warning("Module ignoré : %s", err)
        return tuple(modules)

    async def get_bpc_status(self, watbox: Module, bpc: Module) -> tuple[BPCInput, ...]:
        """Récupère l'état des voies du BPC (pompe, lumières).

        Args:
            watbox: module WATBOX (passerelle).
            bpc   : module BPC.

        Returns:
            Tuple des voies BPC triées par index croissant.
        """
        self._validate_module_type(watbox, MODULE_TYPE_WATBOX, "watbox")
        self._validate_module_type(bpc, MODULE_TYPE_BPC, "bpc")
        path = API_PATH_BPC_STATUS.format(
            watbox_serial=watbox.serial_number, bpc_name=bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)
        if bpc.id:
            self._bpc_module_id = bpc.id
        self._watbox = watbox
        self._bpc = bpc
        pool_inputs = data.get("pool") or []
        inputs: list[BPCInput] = []
        for raw_input in pool_inputs:
            try:
                inputs.append(BPCInput.from_api(raw_input))
            except EasyCareInvalidResponseError as err:
                _LOGGER.warning("Voie BPC ignorée : %s", err)
        inputs.sort(key=lambda x: x.index)
        return tuple(inputs)

    async def get_pool_status(self) -> PoolStatus:
        """Récupère l'état complet de la filtration (mode, boost, compteurs)."""
        path = API_PATH_GET_POOL_STATUS
        if self._pool_db_id:
            path = f"{path}?poolId={self._pool_db_id}"
        data = await self._request("GET", API_HOST_EASYCARE, path)
        return PoolStatus.from_api(data)

    async def get_bpc_programs_data(self) -> tuple[str | None, int, dict | None, dict | None]:
        """Lit les programmes BPC pour la pompe et les lumières.

        Pompe (index 0) — mode de filtration et adaptOffset :
          mode=0 → MANUAL, mode=1 → CONTINUOUS,
          mode=2 + rule=1 → AUTO, mode=2 + rule=0 → PROG.

        Lumières (index 1=spot, index 2=escalight) — `programCharacteristics`
        brut retourné tel quel pour un parsing défensif côté coordinator.

        Returns:
            Tuple (filtration_mode, adapt_offset, spot_program, escalight_program).
            filtration_mode est None si les modules ne sont pas disponibles.
        """
        if self._watbox is None or self._bpc is None:
            return None, 0, None, None
        path = API_PATH_BPC_PROGRAMS.format(
            watbox_serial=self._watbox.serial_number, bpc_name=self._bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)
        programs = data.get("programs") or []

        filtration_mode: str | None = None
        adapt_offset: int = 0
        spot_program: dict | None = None
        escalight_program: dict | None = None

        for prog in programs:
            idx = prog.get("index")
            charac = prog.get("programCharacteristics") or {}
            if idx == 0:
                prog_mode = int(charac.get("mode", 0) or 0)
                prog_rule = int(charac.get("rule", 0) or 0)
                adapt_offset = int(charac.get("adaptOffset", 0) or 0)
                if prog_mode == 0:
                    filtration_mode = "MANUAL"
                elif prog_mode == 1:
                    filtration_mode = "CONTINUOUS"
                elif prog_mode == 2 and prog_rule == 1:
                    filtration_mode = "AUTO"
                else:
                    filtration_mode = "PROG"
            elif idx == 1:
                spot_program = dict(charac)
                _LOGGER.debug("BPC programmes — spot (index 1) programCharacteristics : %s", charac)
            elif idx == 2:
                escalight_program = dict(charac)
                _LOGGER.debug("BPC programmes — escalight (index 2) programCharacteristics : %s", charac)

        return filtration_mode, adapt_offset, spot_program, escalight_program

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

        Workflow obligatoire en 2 étapes : envoi de la commande puis confirmation.

        Args:
            watbox          : module WATBOX.
            bpc             : module BPC.
            index           : voie ciblée (0=pompe, 1=spot, 2=escalight).
            action          : 'on' ou 'off'.
            duration_minutes: durée de la session manuelle (ignorée pour 'off').

        Returns:
            True si la commande a été acceptée.
        """
        self._validate_module_type(watbox, MODULE_TYPE_WATBOX, "watbox")
        self._validate_module_type(bpc, MODULE_TYPE_BPC, "bpc")
        action_lower = action.lower().strip()
        if action_lower == "on":
            action_code = BPC_ACTION_ON
            payload_extra: dict[str, Any] = {"manualDuration": int(duration_minutes) * 60}
        elif action_lower == "off":
            action_code = BPC_ACTION_OFF
            payload_extra = {}
        else:
            raise ValueError(f"Action invalide : {action!r} (attendu 'on' ou 'off')")

        payload = {"pool": {"index": int(index), "action": action_code, **payload_extra}}
        path = API_PATH_BPC_MANUAL.format(
            watbox_serial=watbox.serial_number, bpc_name=bpc.short_name,
        )
        _LOGGER.debug("BPC commande : %s voie %d", action_lower.upper(), index)
        await self._request("POST", API_HOST_EASYCARE, path, json_payload=payload)

        pool_cmd: dict[str, Any] = {"index": int(index), "action": action_code}
        if action_code == BPC_ACTION_ON:
            pool_cmd["manualDuration"] = int(duration_minutes) * 60
        report_payload: dict[str, Any] = {
            "id": bpc.id,
            "command": {"pool": pool_cmd},
            "route": "http",
        }
        try:
            await self._request(
                "POST", API_HOST_EASYCARE, API_PATH_REPORT_MANUAL_SENT,
                json_payload=report_payload,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Échec reportManualCommandSent (non-critique) : %s", err)
        return True

    async def set_filtration_mode(self, mode: str) -> bool:
        """Change le mode de filtration de la pompe via les programmes BPC.

        Args:
            mode: AUTO, CONTINUOUS ou MANUAL.
        """
        mode_upper = mode.upper().strip()
        if mode_upper not in FILTRATION_MODES:
            raise ValueError(f"Mode invalide : {mode!r} (attendu : {', '.join(FILTRATION_MODES)})")
        await self._update_pump_program(mode=mode_upper)
        return True

    async def start_boost(self, boost_mode: str) -> bool:
        """Démarre un boost de filtration via l'endpoint programmes BPC.

        Args:
            boost_mode: BOOST4H, BOOST12H, BOOST24H, BOOST36H, BOOST48H ou BOOST72H.
        """
        boost_upper = boost_mode.upper().strip()
        if boost_upper not in BOOST_MODES:
            raise ValueError(f"Mode boost invalide : {boost_mode!r}")
        _boost_durations: dict[str, int] = {
            "BOOST4H": 240, "BOOST12H": 720, "BOOST24H": 1440,
            "BOOST36H": 2160, "BOOST48H": 2880, "BOOST72H": 4320,
        }
        duration_minutes = _boost_durations[boost_upper]
        _LOGGER.debug("Démarrage boost %s (%d min)", boost_upper, duration_minutes)
        await self._update_boost_via_programs(state="boost", remaining_minutes=duration_minutes)
        return True

    async def cancel_boost(self) -> bool:
        """Annule le boost de filtration en cours via l'endpoint programmes BPC."""
        _LOGGER.debug("Annulation boost en cours")
        await self._update_boost_via_programs(state="active", remaining_minutes=0)
        return True

    async def _update_boost_via_programs(self, *, state: str, remaining_minutes: int) -> None:
        """Modifie l'état boost du programme pompe (index 0) via GET + POST programmes BPC.

        Les champs `state` et `remainingDuration` sont modifiés au niveau racine
        de l'objet programme (pas dans programCharacteristics).

        Args:
            state             : "boost" pour démarrer, "active" pour annuler.
            remaining_minutes : durée restante en minutes (0 pour annuler).
        """
        if self._watbox is None or self._bpc is None:
            _LOGGER.warning("_update_boost_via_programs: modules non disponibles")
            return
        path = API_PATH_BPC_PROGRAMS.format(
            watbox_serial=self._watbox.serial_number, bpc_name=self._bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)
        programs = data.get("programs")
        if not programs:
            _LOGGER.warning("_update_boost_via_programs: aucun programme reçu")
            return
        modified = False
        for prog in programs:
            if prog.get("index") == 0:
                _LOGGER.debug(
                    "Boost — programme pompe avant modification : state=%s remainingDuration=%s",
                    prog.get("state"), prog.get("remainingDuration"),
                )
                prog["state"] = state
                prog["remainingDuration"] = remaining_minutes
                modified = True
                break
        if not modified:
            _LOGGER.warning("_update_boost_via_programs: programme pompe (index 0) absent")
            return
        post_payload: dict[str, Any] = {
            "programs": programs,
            "module": self._bpc_module_id,
            "programmationType": 1,
        }
        _LOGGER.debug(
            "Boost POST — state=%s remainingDuration=%d module=%s",
            state, remaining_minutes, self._bpc_module_id,
        )
        await self._request("POST", API_HOST_EASYCARE, path, json_payload=post_payload)

    async def set_filtration_mode_with_offset(self, mode_option: str) -> bool:
        """Change le mode de filtration avec gestion de l'offset AUTO.

        Toutes les options (mode + offset) sont appliquées en un seul GET+POST
        sur l'endpoint BPC programmes.

        Args:
            mode_option: AUTO-2H, AUTO, AUTO+2H, CONTINUOUS ou MANUAL.

        Returns:
            True si la commande a été acceptée.
        """
        if mode_option not in FILTRATION_MODES_WITH_OFFSET:
            raise ValueError(
                f"Mode invalide : {mode_option!r} "
                f"(attendu : {', '.join(FILTRATION_MODES_WITH_OFFSET)})"
            )
        if mode_option == MODE_AUTO_MINUS:
            await self._update_pump_program(mode=MODE_AUTO, adapt_offset=ADAPT_OFFSET_MINUS)
        elif mode_option == MODE_AUTO_PLUS:
            await self._update_pump_program(mode=MODE_AUTO, adapt_offset=ADAPT_OFFSET_PLUS)
        elif mode_option == MODE_AUTO:
            await self._update_pump_program(mode=MODE_AUTO, adapt_offset=ADAPT_OFFSET_NEUTRAL)
        else:
            await self._update_pump_program(mode=mode_option)
        return True

    async def _update_pump_program(
        self,
        *,
        mode: str | None = None,
        adapt_offset: int | None = None,
    ) -> None:
        """Modifie le programme pompe (index 0) via GET + POST sur l'endpoint BPC programmes.

        Encodage du mode dans programCharacteristics :
          MANUAL     → mode=0
          CONTINUOUS → mode=1
          AUTO       → mode=2, rule=1

        Args:
            mode        : "AUTO", "CONTINUOUS" ou "MANUAL" (None = conserver l'existant).
            adapt_offset: -60, 0 ou +60 minutes (None = conserver l'existant).
        """
        if self._watbox is None or self._bpc is None:
            _LOGGER.warning("_update_pump_program: modules non disponibles")
            return
        path = API_PATH_BPC_PROGRAMS.format(
            watbox_serial=self._watbox.serial_number, bpc_name=self._bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)
        programs = data.get("programs")
        if not programs:
            _LOGGER.warning("_update_pump_program: aucun programme reçu")
            return
        modified = False
        for prog in programs:
            if prog.get("index") == 0:
                charac = prog.get("programCharacteristics")
                if isinstance(charac, dict):
                    if mode is not None:
                        prog_mode, prog_rule = _MODE_TO_PROG[mode]
                        charac["mode"] = prog_mode
                        if prog_rule is not None:
                            charac["rule"] = prog_rule
                    if adapt_offset is not None:
                        charac["adaptOffset"] = adapt_offset
                    modified = True
                break
        if not modified:
            _LOGGER.warning("_update_pump_program: programme pompe (index 0) absent")
            return
        _LOGGER.debug("_update_pump_program: mode=%s adaptOffset=%s", mode, adapt_offset)
        post_payload: dict[str, Any] = {
            "programs": programs,
            "module": self._bpc_module_id,
            "programmationType": 1,
        }
        await self._request("POST", API_HOST_EASYCARE, path, json_payload=post_payload)

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

        Gère le retry sur 401 et les erreurs réseau transitoires.

        Args:
            method      : 'GET' ou 'POST'.
            host        : URL de base.
            path        : chemin relatif.
            json_payload: corps JSON (POST uniquement).

        Returns:
            dict décodé depuis la réponse JSON.

        Raises:
            EasyCareUnauthorizedError: bearer toujours rejeté après refresh.
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

        last_exc: Exception | None = None
        for attempt in range(HTTP_MAX_RETRIES):
            try:
                async with self._session.request(
                    method, url, json=json_payload, headers=headers,
                    timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
                ) as response:
                    body = await response.text()

                    if response.status == 401:
                        if _retry_count >= 1:
                            raise EasyCareUnauthorizedError(
                                f"Bearer rejeté même après refresh : {url}"
                            )
                        _LOGGER.info("HTTP 401 sur %s — invalidation et retry", url)
                        await self._auth.invalidate_bearer()
                        return await self._request(
                            method, host, path,
                            json_payload=json_payload,
                            _retry_count=_retry_count + 1,
                        )

                    if response.status >= 400:
                        _LOGGER.warning("HTTP %d sur %s %s", response.status, method, url)
                        raise EasyCareApiError(
                            f"Échec {method} {path}",
                            status_code=response.status, body=body,
                        )

                    if not body.strip():
                        return {}

                    try:
                        return await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise EasyCareInvalidResponseError(
                            f"Réponse non-JSON depuis {url} : {err}"
                        ) from err

            except asyncio.TimeoutError:
                last_exc = EasyCareTimeoutError(f"Timeout sur {method} {url}")
                _LOGGER.debug("Tentative %d/%d : timeout", attempt + 1, HTTP_MAX_RETRIES)
            except ClientError as err:
                last_exc = EasyCareConnectionError(f"Erreur réseau : {err}")
                _LOGGER.debug("Tentative %d/%d : %s", attempt + 1, HTTP_MAX_RETRIES, err)

            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))

        assert last_exc is not None
        raise last_exc

    @staticmethod
    def _validate_module_type(module: Module, expected: str, role: str) -> None:
        """Vérifie qu'un module a le bon type.

        Raises:
            ValueError: si le module n'a pas le type attendu.
        """
        if module.type != expected:
            raise ValueError(
                f"Module '{role}' a le type {module.type!r}, attendu {expected!r}"
            )
