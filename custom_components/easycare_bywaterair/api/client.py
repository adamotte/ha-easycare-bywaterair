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
    SCHED_AUTO_ROW_MINUS,
    SCHED_AUTO_ROW_STD,
    SCHED_AUTO_ROW_PLUS,
    API_HOST_EASYCARE,
    API_PATH_BPC_MANUAL,
    API_PATH_BPC_PROGRAMS,
    API_PATH_BPC_STATUS,
    API_PATH_FIRMWARE,
    API_PATH_GET_POOL_STATUS,
    API_PATH_GET_USER,
    API_PATH_GET_USER_MODULES,
    API_PATH_REPORT_MANUAL_SENT,
    BOOST_MODES,
    BPC_ACTION_BOOST,
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
    MODULE_TYPE_ALIASES,
    MODULE_TYPE_BPC,
    MODULE_TYPE_PREFIX_BPC,
    MODULE_TYPE_PREFIX_WATBOX,
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
    FilterSchedule,
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
            raise EasyCareInvalidResponseError("No pool found on the Waterair account")
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

    async def list_pools(self) -> list[str]:
        """Liste les piscines du compte pour le config flow.

        Utilisé à la configuration pour décider s'il faut demander à l'utilisateur
        de choisir une piscine (compte multi-piscines) ou non (cas le plus courant).

        Returns:
            Liste ordonnée de libellés lisibles, un par piscine.
            L'index 0 correspond à pool_id=1, l'index 1 à pool_id=2, etc.
        """
        data = await self._request("GET", API_HOST_EASYCARE, API_PATH_GET_USER)
        pools = data.get("pools") or []
        labels: list[str] = []
        for i, pool in enumerate(pools, start=1):
            model = pool.get("model") or "Piscine"
            address = pool.get("address") or ""
            label = f"{i} — {model}"
            if address:
                label += f" ({address})"
            labels.append(label)
        return labels

    async def get_modules(self) -> tuple[Module, ...]:
        """Récupère la liste des modules de la piscine sélectionnée.

        Returns:
            Tuple immuable de tous les modules (WATBOX, BPC, AC1, LR-PR, etc.).
        """
        data = await self._request("GET", API_HOST_EASYCARE, API_PATH_GET_USER_MODULES)
        _LOGGER.debug("getUserWithHisModules — root keys: %s", list(data.keys()))
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
                    _LOGGER.warning("Module skipped: %s", err)
            return tuple(modules)
        if not pools:
            _LOGGER.warning("getUserWithHisModules — unexpected structure: %s", list(data.keys()))
            raise EasyCareInvalidResponseError("No pool found (getUserWithHisModules)")
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
                _LOGGER.warning("Module skipped: %s", err)
        return tuple(modules)

    async def get_bpc_status(
        self, watbox: Module, bpc: Module
    ) -> tuple[tuple[BPCInput, ...], int | None]:
        """Récupère l'état des voies du BPC (pompe, lumières).

        Args:
            watbox: module WATBOX (passerelle).
            bpc   : module BPC.

        Returns:
            Tuple (inputs, bpc_temperature) :
              inputs          : voies BPC triées par index croissant.
              bpc_temperature : température de référence commitée par le BPC pour la journée
                                (champ racine `temperature` de la réponse status), en °C entiers.
                                Correspond au seuil de la matrice sched que le BPC a sélectionné
                                au démarrage du cycle. None si absent de la réponse.
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

        # Température de référence commitée par le BPC pour la journée en cours.
        # Correspond au seuil (en °C) que le BPC a validé au démarrage du cycle matinal,
        # déterminé à partir de la température max de la veille. Ex : 27 → seuil 27°C → 9h-19h.
        bpc_temperature: int | None = None
        raw_temp = data.get("temperature")
        if raw_temp is not None:
            try:
                bpc_temperature = int(raw_temp)
            except (TypeError, ValueError):
                bpc_temperature = None
        _LOGGER.debug("BPC status — temperature (threshold ref): %s°C", bpc_temperature)

        pool_inputs = data.get("pool") or []
        inputs: list[BPCInput] = []
        for raw_input in pool_inputs:
            try:
                inputs.append(BPCInput.from_api(raw_input))
            except EasyCareInvalidResponseError as err:
                _LOGGER.warning("BPC channel skipped: %s", err)
        inputs.sort(key=lambda x: x.index)
        # Diagnostic boost/marche forcée : champs discriminants par voie.
        # Permet d'identifier la signature d'une marche forcée (origin/info)
        # afin de distinguer un boost d'une filtration AUTO planifiée.
        _LOGGER.debug(
            "BPC status — channels: %s",
            [
                {
                    "index": i.index, "value": i.value, "time": i.remaining_time,
                    "origin": i.origin, "info": list(i.info),
                }
                for i in inputs
            ],
        )
        return tuple(inputs), bpc_temperature

    async def get_firmware_update(self, watbox_serial: str, module_short_name: str) -> dict[str, Any]:
        """Vérifie si une mise à jour firmware est disponible pour un module.

        Returns:
            Dict vide si aucune mise à jour, sinon AvailableDeviceVersion JSON.
        """
        path = API_PATH_FIRMWARE.format(
            watbox_serial=watbox_serial, module_name=module_short_name,
        )
        return await self._request("GET", API_HOST_EASYCARE, path)

    async def get_pool_status(self) -> PoolStatus:
        """Récupère l'état complet de la filtration (mode, boost, compteurs)."""
        path = API_PATH_GET_POOL_STATUS
        if self._pool_db_id:
            path = f"{path}?poolId={self._pool_db_id}"
        data = await self._request("GET", API_HOST_EASYCARE, path)
        return PoolStatus.from_api(data)

    async def get_bpc_programs_data(
        self,
    ) -> tuple[
        str | None, int, dict | None, dict | None, FilterSchedule | None,
        float | None, str | None, int | None,
    ]:
        """Lit les programmes BPC pour la pompe et les lumières.

        Pompe (index 0) — mode de filtration, adaptOffset et planning de filtration :
          mode=0 → MANUAL, mode=1 → CONTINUOUS,
          mode=2 + rule=1 → AUTO, mode=2 + rule=0 → PROG.
          sched (racine du programme) → FilterSchedule pour les plages horaires.
          state (racine du programme) → état boost ("boost" si boost actif, sinon
          "active"/"inactive"/…), remainingDuration → durée restante en minutes.
          Ces deux champs reflètent un boost déclenché depuis l'app mobile.

        Lumières (index 1=spot, index 2=escalight) — `programCharacteristics`
        brut retourné tel quel pour un parsing défensif côté coordinator.

        Returns:
            Tuple (filtration_mode, adapt_offset, spot_program, escalight_program,
                   filter_schedule, max_temp_day_before, pump_state,
                   pump_remaining_duration).
            filtration_mode est None si les modules ne sont pas disponibles.
            max_temp_day_before : température maximale de la veille (°C) utilisée par le BPC
            pour sélectionner le seuil de la matrice sched. None si absente de la réponse.
            pump_state : état racine du programme pompe (ex. "boost"), None si absent.
            pump_remaining_duration : durée restante du programme pompe en minutes, None si absent.
        """
        if self._watbox is None or self._bpc is None:
            return None, 0, None, None, None, None, None, None
        path = API_PATH_BPC_PROGRAMS.format(
            watbox_serial=self._watbox.serial_number, bpc_name=self._bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)

        # Log diagnostic : toutes les clés racine de la réponse (hors programs, trop verbeux).
        _LOGGER.debug(
            "BPC programs — root response: %s",
            {k: v for k, v in data.items() if k != "programs"},
        )

        # Température max de la veille — utilisée par le BPC pour choisir le seuil de filtration.
        max_temp_day_before: float | None = None
        raw_max_temp = data.get("maxTemperatureTheDayBefore")
        if raw_max_temp is not None:
            try:
                max_temp_day_before = float(raw_max_temp)
            except (TypeError, ValueError):
                max_temp_day_before = None
        _LOGGER.debug("BPC programs — maxTemperatureTheDayBefore: %s", max_temp_day_before)

        programs = data.get("programs") or []

        filtration_mode: str | None = None
        adapt_offset: int = 0
        spot_program: dict | None = None
        escalight_program: dict | None = None
        filter_schedule: FilterSchedule | None = None
        pump_state: str | None = None
        pump_remaining_duration: int | None = None

        for prog in programs:
            idx = prog.get("index")
            charac = prog.get("programCharacteristics") or {}
            if idx == 0:
                prog_mode = int(charac.get("mode", 0) or 0)
                prog_rule = int(charac.get("rule", 0) or 0)
                # Log COMPLET avant tout parsing (crash-safe — s'affiche même si la suite plante).
                _LOGGER.debug(
                    "BPC programs — pump (index 0) raw program: %s", prog
                )
                # État boost — `state` et `remainingDuration` sont à la racine du programme.
                # Reflète un boost déclenché depuis l'app mobile (state == "boost").
                state_raw = prog.get("state")
                pump_state = str(state_raw) if state_raw is not None else None
                rem_raw = prog.get("remainingDuration")
                if rem_raw is not None:
                    try:
                        pump_remaining_duration = int(rem_raw)
                    except (TypeError, ValueError):
                        pump_remaining_duration = None
                _LOGGER.debug(
                    "BPC programs — pump (index 0): state=%s remainingDuration=%s",
                    pump_state, pump_remaining_duration,
                )
                # L'offset AUTO est encodé dans sched (masques de bits 24h par seuil de temp).
                # On identifie l'offset en comparant sched[0] aux tables de référence.
                sched_val = prog.get("sched")
                adapt_offset = ADAPT_OFFSET_NEUTRAL
                if isinstance(sched_val, list) and sched_val:
                    first = sched_val[0]
                    if isinstance(first, list):
                        if first == list(SCHED_AUTO_ROW_MINUS):
                            adapt_offset = ADAPT_OFFSET_MINUS
                        elif first == list(SCHED_AUTO_ROW_PLUS):
                            adapt_offset = ADAPT_OFFSET_PLUS
                        # else : standard ou inconnu → ADAPT_OFFSET_NEUTRAL
                _LOGGER.debug(
                    "BPC programs — pump (index 0): mode=%s rule=%s → adapt_offset=%d",
                    prog_mode, prog_rule, adapt_offset,
                )
                if prog_mode == 0:
                    filtration_mode = "MANUAL"
                elif prog_mode == 1:
                    filtration_mode = "CONTINUOUS"
                elif prog_mode == 2 and prog_rule == 1:
                    filtration_mode = "AUTO"
                else:
                    filtration_mode = "PROG"
                # Planning de filtration — sched est à la racine du programme, pas dans charac.
                filter_schedule = FilterSchedule.from_program_characteristics(
                    charac, sched=sched_val
                )
                _LOGGER.debug(
                    "BPC programs — FilterSchedule: ths=%s sched_rows=%s rules=%d",
                    filter_schedule.thresholds,
                    len(filter_schedule.sched) if filter_schedule.sched else 0,
                    len(filter_schedule.rules),
                )
            elif idx == 1:
                spot_program = dict(charac)
                _LOGGER.debug("BPC programs — spot (index 1) programCharacteristics: %s", charac)
            elif idx == 2:
                escalight_program = dict(charac)
                _LOGGER.debug("BPC programs — escalight (index 2) programCharacteristics: %s", charac)

        return (
            filtration_mode, adapt_offset, spot_program, escalight_program,
            filter_schedule, max_temp_day_before, pump_state, pump_remaining_duration,
        )

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
        elif action_lower == "boost":
            action_code = BPC_ACTION_BOOST
            payload_extra = {"manualDuration": int(duration_minutes) * 60}
        elif action_lower == "off":
            action_code = BPC_ACTION_OFF
            payload_extra = {}
        else:
            raise ValueError(f"Invalid action: {action!r} (expected 'on', 'boost' or 'off')")

        payload = {"pool": {"index": int(index), "action": action_code, **payload_extra}}
        path = API_PATH_BPC_MANUAL.format(
            watbox_serial=watbox.serial_number, bpc_name=bpc.short_name,
        )
        _LOGGER.debug("BPC command: %s channel %d", action_lower.upper(), index)
        await self._request("POST", API_HOST_EASYCARE, path, json_payload=payload)

        pool_cmd: dict[str, Any] = {"index": int(index), "action": action_code}
        if action_code in (BPC_ACTION_ON, BPC_ACTION_BOOST):
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
            _LOGGER.warning("reportManualCommandSent failed (non-critical): %s", err)
        return True

    async def set_filtration_mode(self, mode: str) -> bool:
        """Change le mode de filtration de la pompe via les programmes BPC.

        Args:
            mode: AUTO, CONTINUOUS ou MANUAL.
        """
        mode_upper = mode.upper().strip()
        if mode_upper not in FILTRATION_MODES:
            raise ValueError(f"Invalid mode: {mode!r} (expected: {', '.join(FILTRATION_MODES)})")
        await self._update_pump_program(mode=mode_upper)
        return True

    async def start_boost(self, boost_mode: str) -> bool:
        """Démarre le boost via l'endpoint manuel BPC, action=boost (code 3).

        Le status pompe expose `origin` = code d'action envoyé (on=2 → origin=2) ;
        le vrai boost montre origin=3. On envoie donc action 'boost' (3) + manualDuration
        sur la voie pompe (index 0), via le même endpoint manuel que les lumières.

        boost_mode : BOOST4H, BOOST12H, BOOST24H, BOOST36H, BOOST48H ou BOOST72H.
        """
        boost_upper = boost_mode.upper().strip()
        if boost_upper not in BOOST_MODES:
            raise ValueError(f"Invalid boost mode: {boost_mode!r}")
        _boost_durations: dict[str, int] = {
            "BOOST4H": 240, "BOOST12H": 720, "BOOST24H": 1440,
            "BOOST36H": 2160, "BOOST48H": 2880, "BOOST72H": 4320,
        }
        duration_minutes = _boost_durations[boost_upper]
        if self._watbox is None or self._bpc is None:
            _LOGGER.warning("start_boost: modules unavailable")
            return False
        _LOGGER.debug("Starting boost %s (%d min) via action=boost", boost_upper, duration_minutes)
        return await self.set_bpc_manual(
            self._watbox, self._bpc,
            index=0, action="boost", duration_minutes=duration_minutes,
        )

    async def cancel_boost(self) -> bool:
        """Annule le boost en cours (OFF manuel sur la voie pompe)."""
        if self._watbox is None or self._bpc is None:
            _LOGGER.warning("cancel_boost: modules unavailable")
            return False
        _LOGGER.debug("Cancelling current boost via manual OFF")
        return await self.set_bpc_manual(
            self._watbox, self._bpc, index=0, action="off",
        )

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
                f"Invalid mode: {mode_option!r} "
                f"(expected: {', '.join(FILTRATION_MODES_WITH_OFFSET)})"
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
            _LOGGER.warning("_update_pump_program: modules unavailable")
            return
        path = API_PATH_BPC_PROGRAMS.format(
            watbox_serial=self._watbox.serial_number, bpc_name=self._bpc.short_name,
        )
        data = await self._request("GET", API_HOST_EASYCARE, path)
        _LOGGER.debug("_update_pump_program GET — response keys: %s", list(data.keys()))
        programs = data.get("programs")
        if not programs:
            _LOGGER.warning("_update_pump_program: no program received — response: %s", data)
            return
        _LOGGER.debug(
            "_update_pump_program: %d program(s), indices=%s, bpc_module_id=%r",
            len(programs), [p.get("index") for p in programs], self._bpc_module_id,
        )
        modified = False
        for prog in programs:
            if prog.get("index") == 0:
                charac = prog.get("programCharacteristics")
                sched = prog.get("sched")
                _LOGGER.debug(
                    "_update_pump_program — pump program before edit: "
                    "root_keys=%s adaptOffset_root=%s sched=%s programCharacteristics=%s",
                    list(prog.keys()),
                    prog.get("adaptOffset"),
                    sched,
                    charac,
                )
                if isinstance(charac, dict):
                    if mode is not None:
                        prog_mode, prog_rule = _MODE_TO_PROG[mode]
                        charac["mode"] = prog_mode
                        if prog_rule is not None:
                            charac["rule"] = prog_rule
                    if adapt_offset is not None:
                        # L'offset AUTO est encodé dans la matrice sched (masques 24 bits).
                        # On remplace sched entier par la table de référence correspondante.
                        if adapt_offset == ADAPT_OFFSET_MINUS:
                            prog["sched"] = [list(SCHED_AUTO_ROW_MINUS)] * 7
                            label = "AUTO-2H"
                        elif adapt_offset == ADAPT_OFFSET_PLUS:
                            prog["sched"] = [list(SCHED_AUTO_ROW_PLUS)] * 7
                            label = "AUTO+2H"
                        else:
                            prog["sched"] = [list(SCHED_AUTO_ROW_STD)] * 7
                            label = "AUTO-Standard"
                        _LOGGER.debug("adaptOffset=%d → sched replaced by table %s", adapt_offset, label)
                    modified = True
                else:
                    _LOGGER.warning(
                        "_update_pump_program: programCharacteristics missing or non-dict: %r", charac
                    )
                break
        if not modified:
            _LOGGER.warning(
                "_update_pump_program: pump program (index 0) missing among %s",
                [p.get("index") for p in programs],
            )
            return
        post_payload: dict[str, Any] = {
            "programs": programs,
            "module": self._bpc_module_id,
            "programmationType": 1,
        }
        _LOGGER.debug(
            "_update_pump_program POST — mode=%s adaptOffset=%s module=%r payload=%s",
            mode, adapt_offset, self._bpc_module_id,
            [{k: v for k, v in p.items() if k in ("index", "state", "adaptOffset", "programCharacteristics")} for p in programs],
        )
        await self._request("POST", API_HOST_EASYCARE, path, json_payload=post_payload)
        _LOGGER.debug("_update_pump_program POST sent successfully")

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
                                f"Bearer rejected even after refresh: {url}"
                            )
                        _LOGGER.info("HTTP 401 on %s — invalidating and retrying", url)
                        await self._auth.invalidate_bearer()
                        return await self._request(
                            method, host, path,
                            json_payload=json_payload,
                            _retry_count=_retry_count + 1,
                        )

                    if response.status >= 400:
                        _LOGGER.warning("HTTP %d on %s %s", response.status, method, url)
                        raise EasyCareApiError(
                            f"{method} {path} failed",
                            status_code=response.status, body=body,
                        )

                    if not body.strip():
                        return {}

                    try:
                        return await response.json(content_type=None)
                    except (ValueError, aiohttp.ContentTypeError) as err:
                        raise EasyCareInvalidResponseError(
                            f"Non-JSON response from {url}: {err}"
                        ) from err

            except asyncio.TimeoutError:
                last_exc = EasyCareTimeoutError(f"Timeout on {method} {url}")
                _LOGGER.debug("Attempt %d/%d: timeout", attempt + 1, HTTP_MAX_RETRIES)
            except ClientError as err:
                last_exc = EasyCareConnectionError(f"Network error: {err}")
                _LOGGER.debug("Attempt %d/%d: %s", attempt + 1, HTTP_MAX_RETRIES, err)

            if attempt < HTTP_MAX_RETRIES - 1:
                await asyncio.sleep(HTTP_RETRY_DELAY * (attempt + 1))

        assert last_exc is not None
        raise last_exc

    # Préfixe de type acceptable par famille (issue #10) : une variante dont le
    # `type` commence par ce préfixe est une déclinaison connue (gateway lr-bst-*,
    # BPC lr-pc-*) → tolérée silencieusement, pas de warning à chaque poll.
    _TYPE_FAMILY_PREFIX = {
        MODULE_TYPE_WATBOX: MODULE_TYPE_PREFIX_WATBOX,
        MODULE_TYPE_BPC: MODULE_TYPE_PREFIX_BPC,
    }

    @staticmethod
    def _validate_module_type(module: Module, expected: str, role: str) -> None:
        """Vérifie qu'un module a le bon type (warning si variante inconnue).

        Type exact ou alias reconnu (ex. `lr-ph` = BPC2) → OK. Variante de la même
        famille (préfixe connu) → debug. Type vraiment inattendu → warning, mais on
        tente quand même l'appel.
        """
        if module.type == expected or module.type in MODULE_TYPE_ALIASES.get(expected, ()):
            return
        prefix = EasyCareClient._TYPE_FAMILY_PREFIX.get(expected)
        if prefix and module.type.startswith(prefix):
            _LOGGER.debug(
                "Module '%s': type variant %r (family %r) — tolerated",
                role, module.type, expected,
            )
            return
        _LOGGER.warning(
            "Module '%s' has type %r instead of %r — unreferenced hardware "
            "variant, attempting anyway. Please report this type in an issue.",
            role, module.type, expected,
        )
