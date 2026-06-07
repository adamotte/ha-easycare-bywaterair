"""DataUpdateCoordinators pour Easy-care by Waterair.

Trois coordinators avec des fréquences de polling adaptées :

    EasyCareUserCoordinator    (30 min) — métriques, propriétaire, traitements
    EasyCareModulesCoordinator (24 h)  — liste des modules physiques
    EasyCareBPCCoordinator     (1 min / 10 min idle) — pompe, lumières, filtration
"""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from homeassistant.components.persistent_notification import (
    async_create as pn_create,
    async_dismiss as pn_dismiss,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api.client import EasyCareClient
from .api.exceptions import (
    EasyCareApiError,
    EasyCareConnectionError,
    EasyCareInvalidResponseError,
    EasyCareTimeoutError,
    EasyCareTokenExpiredError,
    EasyCareUnauthorizedError,
)
from .api.models import (
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
from .const import (
    DOMAIN,
    KNOWN_MODULE_TYPES,
    MODULE_TYPE_AC1,
    MODULE_TYPE_BPC,
    MODULE_TYPE_PRESSURE,
    MODULE_TYPE_WATBOX,
    SCAN_INTERVAL_BPC,
    SCAN_INTERVAL_BPC_IDLE_FACTOR,
    SCAN_INTERVAL_MODULES,
    SCAN_INTERVAL_USER,
)

_LOGGER = logging.getLogger(__name__)

# Messages lisibles pour les notifications persistantes HA.
# Clé = valeur brute du champ `action` retournée par l'API Waterair.
# Messages des notifications persistantes HA, par action (clé = valeur API camelCase).
# Phrases reprises/adaptées des chaînes officielles de l'app mobile Waterair.
# Localisées FR/EN selon la langue de l'instance Home Assistant.
_POOL_ACTION_MESSAGES: dict[str, dict[str, str]] = {
    "shouldBeCalibrated": {
        "fr": "Votre AC1 devrait être calibré.",
        "en": "Your AC1 should be calibrated.",
    },
    "shouldBeWintered": {
        "fr": "Votre AC1 devrait être hiverné.",
        "en": "Your AC1 should be wintered.",
    },
    "shouldBePutBackIntoOperation": {
        "fr": "Votre piscine devrait être remise en service.",
        "en": "Your pool should be put back into operation.",
    },
    "shouldDoChlorineTreatment": {
        "fr": "Un traitement chlore est recommandé pour votre piscine.",
        "en": "A chlorine treatment is recommended for your pool.",
    },
    "severalInsufficientFillings": {
        "fr": "Plusieurs remplissages insuffisants ont été détectés.",
        "en": "Several insufficient fillings have been detected.",
    },
    "pHCanShouldBeReplaced": {
        "fr": "Le bidon de pH devrait être remplacé.",
        "en": "The pH can should be replaced.",
    },
    "pHCalibrationNecessary": {
        "fr": "Une calibration du pH est nécessaire.",
        "en": "pH calibration is required.",
    },
    "batteryLow": {
        "fr": "Les piles sont bientôt vides.",
        "en": "The batteries are running low.",
    },
    "batteryTooLowToMeasure": {
        "fr": "Les piles de votre AC1 sont trop faibles, les mesures sont suspendues.",
        "en": "The battery is too low, measurements are suspended until you change it.",
    },
    "gatewayConnectivityLost": {
        "fr": "La WATBOX est déconnectée.",
        "en": "The gateway (WATBOX) has been disconnected.",
    },
    "canShouldBeReplaced": {
        "fr": "Le bidon devrait être remplacé.",
        "en": "The can should be replaced.",
    },
    "connectivityLost": {
        "fr": "La connexion a été perdue.",
        "en": "Connectivity has been lost.",
    },
    "loraConnectivityLost": {
        "fr": "La connexion LoRa a été perdue.",
        "en": "LoRa connectivity has been lost.",
    },
    "heatPumpConnectivityLost": {
        "fr": "La connexion avec la pompe à chaleur a été perdue.",
        "en": "Connection to the heat pump has been lost.",
    },
    "poolLevelSensorConnectivityLost": {
        "fr": "La connexion avec le capteur de niveau d'eau a été perdue.",
        "en": "Connection to the water level sensor has been lost.",
    },
    "poolLevelSensorHighDailyThresholdExceeded": {
        "fr": "Le seuil quotidien de niveau d'eau a été dépassé.",
        "en": "The daily water level threshold has been exceeded.",
    },
    "leakDetected": {
        "fr": "Une fuite a été détectée.",
        "en": "A leak has been detected.",
    },
    "probeUnplugged": {
        "fr": "Une sonde semble débranchée. Vérifiez son raccordement.",
        "en": "A probe appears to be unplugged. Check its connection.",
    },
    "pumpHasStartedAlert": {
        "fr": "La pompe a démarré sans que le BPC l'ordonne. Est-ce volontaire ?",
        "en": "The pump started when your BPC did not order it. Is this intentional?",
    },
    "backwashReminder": {
        "fr": "Pensez à effectuer un contre-lavage régulièrement pour maintenir le bon fonctionnement de votre filtration.",
        "en": "Remember to perform a backwash regularly to maintain proper filtration.",
    },
    "filterCloggedAlert": {
        "fr": "Attention, votre filtre est encrassé, vous devez le nettoyer.",
        "en": "Warning, your filter is clogged, you must clean it.",
    },
    "filterAlmostCloggedAlert": {
        "fr": "Attention, votre filtre est en train de s'encrasser, pensez à le nettoyer bientôt.",
        "en": "Warning, your filter is getting clogged, remember to clean it soon.",
    },
    "preFilterBasketCloggedAlert": {
        "fr": "Le panier du préfiltre est encrassé.",
        "en": "The prefilter basket is clogged.",
    },
    "suctionValveClosedAlert": {
        "fr": "La vanne d'aspiration est fermée ou la pompe n'a pas démarré.",
        "en": "The suction valve is closed or the pump has not started.",
    },
    "dischargeValveClosedAlert": {
        "fr": "La vanne de refoulement est fermée.",
        "en": "The discharge valve is closed.",
    },
    "waterLevelLowAlert": {
        "fr": "Le niveau d'eau de la piscine est bas.",
        "en": "The water level in the pool is low.",
    },
    "electrolyserShouldBeStoppedDueToLowTemperature": {
        "fr": "La température de l'eau est basse, éteignez votre électrolyseur en passant en mode OFF.",
        "en": "The water temperature is low, please switch off your electrolyser by changing the mode to OFF.",
    },
    "pHRegulationAlgorithmInhibited": {
        "fr": "L'algorithme de traitement automatique du pH a été mis en pause. Veuillez effectuer une correction manuelle.",
        "en": "The automatic pH processing algorithm has been paused. Please perform a manual correction.",
    },
    "pHRegulationInformation": {
        "fr": "Information sur la régulation du pH.",
        "en": "pH regulation information.",
    },
}

# Actions non actionnables → pas de notification persistante.
_NON_ACTIONABLE_ACTIONS: frozenset[str] = frozenset({"", "None", "unknown"})


@dataclass(frozen=True, slots=True)
class UserData:
    """Données retournées par EasyCareUserCoordinator."""

    client: Client
    pool: Pool
    metrics: Metrics
    alerts: Alerts
    treatment: Treatment


@dataclass(frozen=True, slots=True)
class BPCData:
    """Données retournées par EasyCareBPCCoordinator.

    filtration_mode              : mode dérivé des programmes BPC (AUTO/CONTINUOUS/MANUAL/PROG).
    adapt_offset                 : offset AUTO en minutes (-60=AUTO-2H, 0=standard, +60=AUTO+2H).
    pool_status                  : état pompe et boost (None si voie pompe absente).
    spot_program                 : programCharacteristics brut du spot (index 1), None si absent.
    escalight_program            : programCharacteristics brut de l'escalight (index 2), None si absent.
    pump_total_activation_minutes: durée cumulée de la pompe en minutes (depuis reset_date).
    pump_activation_reset_date   : date de remise à zéro du compteur pompe.
    filter_schedule              : planning cyclic de filtration (programme pompe index=0).
    max_temp_day_before          : température maximale de la veille (°C) fournie par le BPC.
                                   Actuellement toujours None (champ absent de l'API).
    bpc_temp_reference           : température de référence commitée par le BPC pour la journée.
                                   Lue depuis le champ `temperature` de la réponse status BPC.
                                   Correspond au seuil (°C entier) que le BPC a sélectionné
                                   au démarrage du cycle (ex : 27 → seuil 27°C → 9h–19h).
                                   Source primaire pour la sélection du seuil de filtration.
                                   None si absente de la réponse API.
    """

    inputs: tuple[BPCInput, ...]
    pool_status: PoolStatus | None = None
    filtration_mode: str | None = None
    adapt_offset: int = 0
    spot_program: dict | None = None
    escalight_program: dict | None = None
    pump_total_activation_minutes: int | None = None
    pump_activation_reset_date: datetime | None = None
    filter_schedule: FilterSchedule | None = None
    max_temp_day_before: float | None = None
    bpc_temp_reference: int | None = None
    pump_program_state: str | None = None
    pump_program_remaining_minutes: int | None = None

    @property
    def is_boost_active(self) -> bool:
        """Vrai si un boost de filtration est actif.

        Combine deux sources pour couvrir tous les déclencheurs :
        - voie pompe (status) avec le tag 'boost' dans `info` ;
        - état racine du programme pompe (`state == "boost"`), qui reflète
          notamment un boost déclenché depuis l'app mobile.
        """
        if self.pump_program_state == "boost":
            return True
        pump = self.get_input(0)
        return pump is not None and pump.is_boosting

    def get_input(self, index: int) -> BPCInput | None:
        """Retourne la voie BPC d'index donné, ou None si absente."""
        for inp in self.inputs:
            if inp.index == index:
                return inp
        return None

    @property
    def any_input_active(self) -> bool:
        """Vrai si au moins une voie BPC est active."""
        return any(inp.is_on for inp in self.inputs)


def _wrap_api_error(err: Exception, context: str) -> Exception:
    """Convertit une exception du client API en exception HA appropriée."""
    if isinstance(err, EasyCareTokenExpiredError):
        return ConfigEntryAuthFailed(f"{context} : refresh_token expiré")
    if isinstance(err, EasyCareUnauthorizedError):
        return ConfigEntryAuthFailed(f"{context} : bearer rejeté de manière persistante")
    if isinstance(err, (EasyCareConnectionError, EasyCareTimeoutError)):
        return UpdateFailed(f"{context} : erreur réseau : {err}")
    if isinstance(err, EasyCareApiError):
        return UpdateFailed(f"{context} : erreur API HTTP {err.status_code}")
    if isinstance(err, EasyCareInvalidResponseError):
        return UpdateFailed(f"{context} : réponse API invalide : {err}")
    return UpdateFailed(f"{context} : erreur inattendue : {err}")


class EasyCareUserCoordinator(DataUpdateCoordinator[UserData]):
    """Coordinator pour les données utilisateur et métriques piscine (30 min)."""

    def __init__(self, hass: HomeAssistant, client: EasyCareClient, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER,
            name=f"{DOMAIN}_user_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_USER,
        )
        self._client = client
        self._last_fetched_at: datetime | None = None
        # Actions déjà notifiées et encore actives (clés API camelCase), pour
        # créer une notif par alerte sans la recréer si l'utilisateur l'a fermée.
        self._notified_actions: set[str] = set()

    @property
    def last_fetched_at(self) -> datetime | None:
        """Horodatage du dernier fetch réussi auprès de l'API."""
        return self._last_fetched_at

    async def _async_update_data(self) -> UserData:
        """Récupère les données utilisateur et métriques."""
        try:
            client, pool, metrics, alerts, treatment = await self._client.get_user()
        except Exception as err:  # noqa: BLE001
            raise _wrap_api_error(err, "get_user") from err

        # Garde "dernière valeur connue" : si l'API retourne des métriques toutes
        # None (réponse vide transitoire) mais que des valeurs précédentes existent,
        # on les conserve plutôt que d'afficher "inconnu" pendant 30 min.
        prev = self.data
        if (
            metrics.ph_value is None
            and metrics.temperature_value is None
            and metrics.chlorine_value is None
            and prev is not None
            and (
                prev.metrics.ph_value is not None
                or prev.metrics.temperature_value is not None
                or prev.metrics.chlorine_value is not None
            )
        ):
            _LOGGER.warning(
                "Métriques AC1 toutes None (réponse API vide ?) — "
                "conservation des valeurs précédentes (pH=%s, T=%s°C, Cl=%s mV)",
                prev.metrics.ph_value,
                prev.metrics.temperature_value,
                prev.metrics.chlorine_value,
            )
            metrics = prev.metrics

        self._last_fetched_at = datetime.now(tz=timezone.utc)
        _LOGGER.debug("User update OK : pH=%s, T=%s°C", metrics.ph_value, metrics.temperature_value)
        result = UserData(client=client, pool=pool, metrics=metrics, alerts=alerts, treatment=treatment)
        self._sync_pool_action_notifications(alerts)
        return result

    def _sync_pool_action_notifications(self, alerts: Alerts) -> None:
        """Synchronise une notification HA persistante par alerte piscine active.

        Stratégie (une notif par alerte, fermable individuellement) :
          - une alerte qui apparaît → création d'une notif dédiée ;
          - une alerte qui disparaît (résolue côté serveur) → suppression de sa notif ;
          - une alerte déjà notifiée puis fermée par l'utilisateur n'est PAS recréée
            tant qu'elle reste active (elle reste dans `_notified_actions`).
        Au redémarrage de HA la mémoire est perdue : les alertes actives sont
        re-notifiées une fois.
        """
        active = {
            n.action for n in alerts.notifications
            if n.action not in _NON_ACTIONABLE_ACTIONS
        }
        lang = (self.hass.config.language or "en").lower()
        msg_lang = "fr" if lang.startswith("fr") else "en"

        for action in active - self._notified_actions:
            messages = _POOL_ACTION_MESSAGES.get(action)
            message = messages[msg_lang] if messages else action
            _LOGGER.info("Nouvelle action piscine détectée : %s", action)
            pn_create(
                self.hass,
                message=message,
                title="easy·care by Waterair",
                notification_id=f"easycare_bywaterair_pool_action_{action}",
            )

        for action in self._notified_actions - active:
            _LOGGER.debug("Action piscine résolue : %s", action)
            pn_dismiss(self.hass, notification_id=f"easycare_bywaterair_pool_action_{action}")

        self._notified_actions = active


# Préfixe attendu du champ `name` des modules (format TYPE-SERIAL), par type API.
# Sert de repli quand le `type` retourné par l'API ne correspond à aucune valeur
# connue (variantes matérielles dont le type diffère — issue #10).
_MODULE_NAME_PREFIX: dict[str, str] = {
    MODULE_TYPE_WATBOX: "WATBOX",
    MODULE_TYPE_BPC: "BPC",
    MODULE_TYPE_AC1: "AC1",
    MODULE_TYPE_PRESSURE: "LR-PR",
}


def _match_modules(
    modules: tuple[Module, ...], module_type: str
) -> tuple[tuple[Module, ...], bool]:
    """Résout les modules d'un type, avec repli par préfixe de nom.

    Match d'abord sur le `type` officiel ; si aucun module ne correspond, repli
    sur le préfixe attendu du champ `name` (`_MODULE_NAME_PREFIX`) pour gérer les
    variantes matérielles dont le `type` diffère de la valeur attendue (issue #10).

    Fonction pure (ne logge rien) pour être utilisable aussi bien sur `self.data`
    que sur la liste locale d'un cycle de refresh en cours.

    Returns:
        (modules trouvés, repli_utilisé). `repli_utilisé` vaut True uniquement si
        le match par `type` a échoué et que le repli par nom a produit un résultat.
    """
    matched = tuple(m for m in modules if m.type == module_type)
    if matched:
        return matched, False
    prefix = _MODULE_NAME_PREFIX.get(module_type)
    if not prefix:
        return (), False
    fallback = tuple(m for m in modules if m.name.upper().startswith(prefix))
    return fallback, bool(fallback)


class EasyCareModulesCoordinator(DataUpdateCoordinator[tuple[Module, ...]]):
    """Coordinator pour la liste des modules physiques (24h)."""

    def __init__(self, hass: HomeAssistant, client: EasyCareClient, entry: ConfigEntry) -> None:
        super().__init__(
            hass, _LOGGER,
            name=f"{DOMAIN}_modules_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_MODULES,
        )
        self._client = client

    async def _async_update_data(self) -> tuple[Module, ...]:
        """Récupère la liste des modules et enrichit avec les données firmware."""
        try:
            modules = await self._client.get_modules()
        except Exception as err:  # noqa: BLE001
            raise _wrap_api_error(err, "get_modules") from err

        unknown = [(m.name, m.type) for m in modules if m.type not in KNOWN_MODULE_TYPES]
        if unknown:
            _LOGGER.warning(
                "Module(s) de type inconnu détecté(s) : %s — non géré(s) par "
                "l'intégration. Merci de signaler ces types dans une issue.",
                unknown,
            )

        watbox_matched, _ = _match_modules(modules, MODULE_TYPE_WATBOX)
        watbox = watbox_matched[0] if watbox_matched else None
        if watbox is None:
            _LOGGER.debug("Modules update OK : %d module(s), pas de WATBOX pour check firmware", len(modules))
            return modules

        enriched: list[Module] = []
        for module in modules:
            if module.type in (MODULE_TYPE_BPC, MODULE_TYPE_AC1, MODULE_TYPE_PRESSURE):
                try:
                    fw_data = await self._client.get_firmware_update(
                        watbox.serial_number, module.short_name
                    )
                    if fw_data:
                        module = dataclasses.replace(module, firmware_available=fw_data)
                        _LOGGER.debug(
                            "Firmware check %s : mise à jour disponible → %s", module.name, fw_data
                        )
                    else:
                        _LOGGER.debug("Firmware check %s : à jour", module.name)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Firmware check %s ignoré : %s", module.name, err)
            enriched.append(module)

        _LOGGER.debug("Modules update OK : %d module(s)", len(enriched))
        return tuple(enriched)

    def _resolve_modules(self, module_type: str) -> tuple[Module, ...]:
        """Comme `_match_modules` sur `self.data`, en loggant le repli éventuel."""
        if not self.data:
            return ()
        modules, used_fallback = _match_modules(self.data, module_type)
        if used_fallback:
            _LOGGER.warning(
                "Module(s) %s détecté(s) par repli sur le nom : %s — type "
                "inattendu (attendu %r). Merci de signaler ce type dans une issue.",
                _MODULE_NAME_PREFIX.get(module_type),
                [(m.name, m.type) for m in modules],
                module_type,
            )
        return modules

    def get_watbox(self) -> Module | None:
        """Retourne le module WATBOX, ou None si absent (repli par nom — issue #10)."""
        modules = self._resolve_modules(MODULE_TYPE_WATBOX)
        return modules[0] if modules else None

    def get_bpc(self) -> Module | None:
        """Retourne le module BPC, ou None si absent (repli par nom — issue #10)."""
        modules = self._resolve_modules(MODULE_TYPE_BPC)
        return modules[0] if modules else None

    def get_modules_by_type(self, module_type: str) -> tuple[Module, ...]:
        """Retourne tous les modules d'un type donné (repli par nom — issue #10)."""
        return self._resolve_modules(module_type)


def _pool_status_from_inputs(inputs: tuple[BPCInput, ...]) -> PoolStatus | None:
    """Construit un PoolStatus depuis les voies BPC.

    Dérive l'état ON/OFF de la pompe et le boost depuis la voie 0.
    Le mode de filtration n'est pas dérivé ici — il vient des programmes BPC
    et est stocké dans BPCData.filtration_mode.

    Returns:
        PoolStatus, ou None si la voie pompe est absente.
    """
    pump = next((i for i in inputs if i.index == 0), None)
    if pump is None:
        return None
    return PoolStatus(
        mode=None,
        power_state="on" if pump.is_on else "off",
        boost_remaining_time=pump.remaining_time if pump.is_boosting else "00:00",
        is_pool_power=pump.is_on,
    )


class EasyCareBPCCoordinator(DataUpdateCoordinator[BPCData]):
    """Coordinator pour l'état temps réel du BPC (pompe + lumières + filtration).

    Polling adaptatif : 1 min si une voie est active, 10 min sinon.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: EasyCareClient,
        modules_coordinator: EasyCareModulesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass, _LOGGER,
            name=f"{DOMAIN}_bpc_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_BPC,
        )
        self._client = client
        self._modules = modules_coordinator
        self._skipped_cycles: int = 0
        self._last_real_update: datetime | None = None

    async def _async_update_data(self) -> BPCData:
        """Récupère l'état du BPC avec logique de polling adaptatif."""
        if self._should_skip_cycle():
            self._skipped_cycles += 1
            _LOGGER.debug("BPC update SKIPPÉ (idle %d/%d)", self._skipped_cycles, SCAN_INTERVAL_BPC_IDLE_FACTOR)
            return self.data  # type: ignore[return-value]

        self._skipped_cycles = 0
        watbox = self._modules.get_watbox()
        bpc = self._modules.get_bpc()
        if watbox is None or bpc is None:
            available = [(m.name, m.type) for m in (self._modules.data or ())]
            _LOGGER.warning(
                "BPC ou WATBOX introuvable — modules disponibles (name, type) : %s",
                available,
            )
            raise UpdateFailed("BPC ou WATBOX absent de la liste des modules")

        bpc_temp_reference: int | None = None
        try:
            inputs, bpc_temp_reference = await self._client.get_bpc_status(watbox, bpc)
        except Exception as err:  # noqa: BLE001
            raise _wrap_api_error(err, "get_bpc_status") from err

        self._last_real_update = datetime.now(tz=timezone.utc)

        # Garde-fou variantes matérielles (issue #10) : le BPC est bien résolu,
        # mais on vérifie que son contenu expose la voie pompe attendue (index 0).
        # Sans ce log, un BPC qui réorganise ses index rendrait pompe/boost muets
        # en silence (les index BPC sont codés en dur dans tout le code).
        if not any(i.index == 0 for i in inputs):
            _LOGGER.warning(
                "BPC %s : voie pompe (index 0) absente des voies status %s — "
                "pompe et boost indisponibles. Variante matérielle ? "
                "Merci de signaler ce cas dans une issue.",
                bpc.name, [i.index for i in inputs],
            )

        pool_status = _pool_status_from_inputs(inputs)
        try:
            pool_status = await self._client.get_pool_status()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("get_pool_status échoué (non-fatal) : %s", err)

        # Compteurs pompe — lus depuis les modules (getUserWithHisModules, 24h)
        pump_total_minutes: int | None = None
        pump_reset_date: datetime | None = None
        bpc_mod = self._modules.get_bpc()
        if bpc_mod is not None:
            output0 = bpc_mod.get_output(0)
            if output0 is not None:
                pump_total_minutes = output0.total_activation_time
                pump_reset_date = output0.total_activation_time_reset_date
                _LOGGER.debug(
                    "Compteurs pompe : %s min depuis %s",
                    pump_total_minutes, pump_reset_date,
                )

        filtration_mode: str | None = None
        adapt_offset = 0
        spot_program: dict | None = None
        escalight_program: dict | None = None
        filter_schedule: FilterSchedule | None = None
        max_temp_day_before: float | None = None
        pump_program_state: str | None = None
        pump_program_remaining: int | None = None
        try:
            (
                filtration_mode,
                adapt_offset,
                spot_program,
                escalight_program,
                filter_schedule,
                max_temp_day_before,
                pump_program_state,
                pump_program_remaining,
            ) = await self._client.get_bpc_programs_data()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("get_bpc_programs_data ignoré (non-fatal) : %s", err)

        _LOGGER.debug(
            "BPC update OK : %d voie(s), mode=%s, adaptOffset=%d, bpc_temp_ref=%s°C",
            len(inputs), filtration_mode, adapt_offset, bpc_temp_reference,
        )
        return BPCData(
            inputs=inputs,
            pool_status=pool_status,
            filtration_mode=filtration_mode,
            adapt_offset=adapt_offset,
            spot_program=spot_program,
            escalight_program=escalight_program,
            pump_total_activation_minutes=pump_total_minutes,
            pump_activation_reset_date=pump_reset_date,
            filter_schedule=filter_schedule,
            max_temp_day_before=max_temp_day_before,
            bpc_temp_reference=bpc_temp_reference,
            pump_program_state=pump_program_state,
            pump_program_remaining_minutes=pump_program_remaining,
        )

    def _should_skip_cycle(self) -> bool:
        """Détermine s'il faut sauter ce cycle de polling."""
        if self.data is None:
            return False
        if self.data.any_input_active:
            return False
        if self._skipped_cycles >= SCAN_INTERVAL_BPC_IDLE_FACTOR - 1:
            return False
        return True

    async def async_request_immediate_refresh(self) -> None:
        """Force un rafraîchissement immédiat, en bypassant le polling adaptatif."""
        self._skipped_cycles = 0
        await self.async_request_refresh()


@dataclass
class EasyCareCoordinators:
    """Agrégat des 3 coordinators d'une intégration.

    Stocké dans `hass.data[DOMAIN][entry.entry_id]`.
    """

    user: EasyCareUserCoordinator
    modules: EasyCareModulesCoordinator
    bpc: EasyCareBPCCoordinator

    async def async_first_refresh(self) -> None:
        """Effectue le premier refresh de tous les coordinators.

        Ordre : modules d'abord (les autres en dépendent), puis user et bpc en parallèle.
        """
        await self.modules.async_config_entry_first_refresh()
        import asyncio
        await asyncio.gather(
            self.user.async_config_entry_first_refresh(),
            self.bpc.async_config_entry_first_refresh(),
        )
