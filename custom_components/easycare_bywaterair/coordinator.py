"""DataUpdateCoordinators pour Easy-care by Waterair.

Trois coordinators avec des fréquences de polling adaptées aux types de données :

    EasyCareUserCoordinator    (toutes les 30 min)
        → Métriques piscine (pH, chlore, température, pression)
        → Propriétaire, modèle de piscine, notifications, traitements
        → Données peu volatiles : mesure typiquement toutes les 30 min côté Waterair

    EasyCareModulesCoordinator (toutes les 24h)
        → Liste des modules physiques (WATBOX, BPC, AC1, LR-PR)
        → Métadonnées : noms, serials, niveaux batterie
        → Quasi-statique : nouveau module = action manuelle rare

    EasyCareBPCCoordinator     (1 min en activité, 10 min en idle)
        → État des voies BPC (pompe ON/OFF, lumières + temps restant)
        → Statut de filtration (mode, boost, compteurs depuis Solem)
        → Polling adaptatif : haute fréquence si quelque chose tourne,
          basse fréquence sinon, pour économiser les requêtes API.

Tous les coordinators :
  - Sont indépendants — une erreur sur l'un ne bloque pas les autres
  - Convertissent les exceptions API en `UpdateFailed` standard HA
  - Détectent les erreurs d'auth fatales et déclenchent un `ConfigEntryAuthFailed`
    qui lance le reauth_flow HA (utilisateur notifié pour fournir un nouveau code)

Les coordinators ne stockent QUE des dataclasses (de `api/models.py`), jamais
des dicts bruts — garantit que les entités HA travaillent sur des données
fortement typées.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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
    Metrics,
    Module,
    Pool,
    PoolStatus,
    Treatment,
)
from .const import (
    DOMAIN,
    MODULE_TYPE_BPC,
    MODULE_TYPE_WATBOX,
    SCAN_INTERVAL_BPC,
    SCAN_INTERVAL_BPC_IDLE_FACTOR,
    SCAN_INTERVAL_MODULES,
    SCAN_INTERVAL_USER,
)

_LOGGER = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Containers de données pour chaque coordinator
# ─────────────────────────────────────────────────────────────────────────────


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

    Combine l'état des voies BPC (depuis easycare.waterair.com) et le statut
    de filtration. Les données sont récupérées à chaque cycle réel.

    pool_status peut être None si la dérivation BPC échoue (pompe absente).
    filtration_mode est le mode dérivé des programmes BPC (AUTO/CONTINUOUS/MANUAL/PROG).
    adapt_offset est l'offset AUTO (en minutes) lu depuis les programmes BPC :
      -60 → AUTO-2H, 0 → AUTO standard, +60 → AUTO+2H.
    """

    inputs: tuple[BPCInput, ...]
    pool_status: PoolStatus | None = None
    filtration_mode: str | None = None
    adapt_offset: int = 0

    def get_input(self, index: int) -> BPCInput | None:
        """Retourne la voie BPC d'index donné, ou None si absente."""
        for inp in self.inputs:
            if inp.index == index:
                return inp
        return None

    @property
    def any_input_active(self) -> bool:
        """Vrai si au moins une voie BPC est active (pompe ou lumière)."""
        return any(inp.is_on for inp in self.inputs)


# ─────────────────────────────────────────────────────────────────────────────
# Helper commun : conversion exceptions API → exceptions HA
# ─────────────────────────────────────────────────────────────────────────────


def _wrap_api_error(err: Exception, context: str) -> Exception:
    """Convertit une exception du client API en exception HA appropriée.

    Args:
        err     : exception levée par le client.
        context : nom de l'opération (pour le message d'erreur HA).

    Returns:
        - ConfigEntryAuthFailed si le refresh_token est expiré (déclenche reauth)
        - UpdateFailed sinon (déclenche un retry au prochain cycle)
    """
    if isinstance(err, EasyCareTokenExpiredError):
        # Critique : pousse HA à demander à l'utilisateur de re-saisir un code
        return ConfigEntryAuthFailed(
            f"{context} : refresh_token Azure expiré, ré-authentification requise"
        )
    if isinstance(err, EasyCareUnauthorizedError):
        # 401 persistant après refresh → équivalent token expiré
        return ConfigEntryAuthFailed(
            f"{context} : bearer rejeté de manière persistante"
        )
    if isinstance(err, (EasyCareConnectionError, EasyCareTimeoutError)):
        return UpdateFailed(f"{context} : erreur réseau : {err}")
    if isinstance(err, EasyCareApiError):
        return UpdateFailed(
            f"{context} : erreur API HTTP {err.status_code}"
        )
    if isinstance(err, EasyCareInvalidResponseError):
        return UpdateFailed(f"{context} : réponse API invalide : {err}")
    if isinstance(err, EasyCareError):
        return UpdateFailed(f"{context} : {err}")
    # Pour toute autre exception inattendue, on remonte UpdateFailed
    return UpdateFailed(f"{context} : erreur inattendue : {err}")


# ═════════════════════════════════════════════════════════════════════════════
# COORDINATORS
# ═════════════════════════════════════════════════════════════════════════════


class EasyCareUserCoordinator(DataUpdateCoordinator[UserData]):
    """Coordinator pour les données utilisateur et métriques piscine.

    Refresh toutes les 30 min — les capteurs Waterair mesurent typiquement
    pH/chlore/température toutes les 30 min, inutile de poller plus souvent.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: EasyCareClient,
        entry: ConfigEntry,
    ) -> None:
        """Initialise le coordinator.

        Args:
            hass  : instance HomeAssistant.
            client: client API partagé.
            entry : ConfigEntry pour le nommage du coordinator dans les logs.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_user_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_USER,
        )
        self._client = client

    async def _async_update_data(self) -> UserData:
        """Récupère les données utilisateur et métriques.

        Returns:
            UserData avec client, pool, metrics, alerts, treatment.

        Raises:
            UpdateFailed          : erreur récupérable (HA réessaiera).
            ConfigEntryAuthFailed : tokens expirés, reauth flow nécessaire.
        """
        try:
            client, pool, metrics, alerts, treatment = await self._client.get_user()
        except Exception as err:  # noqa: BLE001 — on les traite toutes
            raise _wrap_api_error(err, "get_user") from err

        _LOGGER.debug(
            "User update OK : pH=%s, T=%s°C, chlorine=%s",
            metrics.ph_value, metrics.temperature_value, metrics.chlorine_value,
        )
        return UserData(
            client=client,
            pool=pool,
            metrics=metrics,
            alerts=alerts,
            treatment=treatment,
        )


class EasyCareModulesCoordinator(DataUpdateCoordinator[tuple[Module, ...]]):
    """Coordinator pour la liste des modules physiques.

    Refresh quotidien — la liste des modules est quasi-statique. On la
    rafraîchit principalement pour récupérer les niveaux de batterie qui
    évoluent lentement.

    Expose également des helpers `get_watbox()` et `get_bpc()` utilisés par
    le BPCCoordinator pour construire les URLs d'API.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: EasyCareClient,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_modules_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_MODULES,
        )
        self._client = client

    async def _async_update_data(self) -> tuple[Module, ...]:
        """Récupère la liste des modules."""
        try:
            modules = await self._client.get_modules()
        except Exception as err:  # noqa: BLE001
            raise _wrap_api_error(err, "get_modules") from err

        _LOGGER.debug(
            "Modules update OK : %d module(s) — types=%s",
            len(modules),
            sorted({m.type for m in modules}),
        )
        return modules

    # ──────── Helpers utilitaires pour les autres coordinators ────────

    def get_watbox(self) -> Module | None:
        """Retourne le module WATBOX, ou None si pas encore chargé."""
        if not self.data:
            return None
        return next(
            (m for m in self.data if m.type == MODULE_TYPE_WATBOX),
            None,
        )

    def get_bpc(self) -> Module | None:
        """Retourne le module BPC, ou None si pas encore chargé ou absent."""
        if not self.data:
            return None
        return next(
            (m for m in self.data if m.type == MODULE_TYPE_BPC),
            None,
        )

    def get_modules_by_type(self, module_type: str) -> tuple[Module, ...]:
        """Retourne tous les modules d'un type donné (utile pour AC1, LR-PR)."""
        if not self.data:
            return ()
        return tuple(m for m in self.data if m.type == module_type)


def _pool_status_from_inputs(inputs: tuple[BPCInput, ...]) -> PoolStatus | None:
    """Construit un PoolStatus depuis les voies BPC, sans appel réseau.

    La source de vérité pour l'état ON/OFF de la pompe et le boost est la
    voie pompe (index 0) du tableau `pool` de la réponse BPC :
      - value=1/0        : pompe ON/OFF
      - info=['boost']   : boost actif
      - time='HH:MM'     : temps restant (boost ou commande manuelle)

    Note : le mode de filtration (AUTO/CONTINUOUS/MANUAL/PROG) n'est PAS
    dans le tableau BPC — il vient des programmes BPC (endpoint programs).
    Le champ `mode` est donc laissé à None ici ; il est renseigné via
    BPCData.filtration_mode par le coordinator.

    Returns:
        PoolStatus dérivé, ou None si la voie pompe est absente.
    """
    pump = next((i for i in inputs if i.index == 0), None)
    if pump is None:
        return None

    return PoolStatus(
        mode=None,  # lu depuis les programmes BPC — cf. BPCData.filtration_mode
        power_state="on" if pump.is_on else "off",
        boost_remaining_time=pump.remaining_time if pump.is_boosting else "00:00",
        is_pool_power=pump.is_on,
    )


class EasyCareBPCCoordinator(DataUpdateCoordinator[BPCData]):
    """Coordinator pour l'état temps réel du BPC (pompe + lumières + filtration).

    Stratégie de polling adaptative :

      - Intervalle de base : SCAN_INTERVAL_BPC (1 min par défaut)
      - Si AUCUNE voie BPC active à la dernière mesure : on saute les appels
        intermédiaires et on n'appelle l'API qu'une fois toutes les N minutes
        (N = SCAN_INTERVAL_BPC * SCAN_INTERVAL_BPC_IDLE_FACTOR = 10 min)
      - Si au moins une voie active : on revient à 1 min pour la réactivité
        du temps restant affiché

    Cette logique est inspirée du plugin yyrkoon94 (très efficace) mais portée
    proprement dans le pattern DataUpdateCoordinator standard HA.

    En complément du status BPC (host easycare.waterair.com), on tente aussi
    de récupérer le pool_status (host Solem) pour les compteurs et le mode
    de filtration. Si Solem n'est pas joignable on garde au moins le BPC.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: EasyCareClient,
        modules_coordinator: EasyCareModulesCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialise le coordinator BPC.

        Args:
            hass               : instance HomeAssistant.
            client             : client API.
            modules_coordinator: coordinator des modules — fournit watbox/bpc.
            entry              : ConfigEntry pour le nommage.
        """
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_bpc_{entry.entry_id[:8]}",
            update_interval=SCAN_INTERVAL_BPC,
        )
        self._client = client
        self._modules = modules_coordinator

        # Compteur de cycles « skippés » quand rien n'est actif
        # (logique de polling adaptatif)
        self._skipped_cycles: int = 0

        # Timestamp du dernier vrai appel API — pour debug et stats
        self._last_real_update: datetime | None = None

    async def _async_update_data(self) -> BPCData:
        """Récupère l'état du BPC, avec logique de polling adaptatif.

        Si aucune voie BPC n'était active au dernier vrai poll ET qu'on n'a pas
        encore attendu SCAN_INTERVAL_BPC_IDLE_FACTOR cycles, on renvoie les
        données précédentes sans appeler l'API.

        Returns:
            BPCData avec les voies BPC et (si disponible) le pool_status.
        """
        # Polling adaptatif : si rien n'était actif et qu'on est en mode idle,
        # on skippe l'appel API et on renvoie les données précédentes.
        if self._should_skip_cycle():
            self._skipped_cycles += 1
            _LOGGER.debug(
                "BPC update SKIPPÉ (idle %d/%d cycles)",
                self._skipped_cycles, SCAN_INTERVAL_BPC_IDLE_FACTOR,
            )
            # On retourne les dernières données connues
            return self.data  # type: ignore[return-value]

        # Reset compteur — on va faire un vrai appel
        self._skipped_cycles = 0

        # Récupération du WATBOX et BPC depuis le modules coordinator
        watbox = self._modules.get_watbox()
        bpc = self._modules.get_bpc()
        if watbox is None or bpc is None:
            raise UpdateFailed(
                "BPC ou WATBOX absent de la liste des modules — "
                "vérifiez votre installation Waterair"
            )

        # Appel principal : état des voies BPC
        try:
            inputs = await self._client.get_bpc_status(watbox, bpc)
        except Exception as err:  # noqa: BLE001
            raise _wrap_api_error(err, "get_bpc_status") from err

        self._last_real_update = datetime.now(tz=timezone.utc)

        # Dérive le PoolStatus depuis la voie pompe (index 0) du BPC.
        # L'API getPoolStatus renvoie uniquement la configuration de la piscine
        # (modèle, volume, pH attendu…) et non l'état de filtration.
        # L'état réel (boost, pompe ON/OFF, temps restant) vient du tableau
        # `pool` de la réponse BPC.
        pool_status = _pool_status_from_inputs(inputs)

        # Lecture du mode de filtration et de l'adaptOffset depuis les programmes BPC.
        # Non critique : un échec ne doit pas bloquer le coordinator principal.
        filtration_mode: str | None = None
        adapt_offset = 0
        try:
            filtration_mode, adapt_offset = await self._client.get_bpc_programs_data()
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "get_bpc_programs_data ignoré (non-fatal) : %s", err
            )
            # On garde None/0 comme valeurs par défaut.

        _LOGGER.debug(
            "BPC update OK : %d voie(s), active=%s, boost=%s, mode=%s, adaptOffset=%d",
            len(inputs),
            [inp.index for inp in inputs if inp.is_on],
            pool_status.is_boosting if pool_status else False,
            filtration_mode,
            adapt_offset,
        )

        return BPCData(
            inputs=inputs,
            pool_status=pool_status,
            filtration_mode=filtration_mode,
            adapt_offset=adapt_offset,
        )

    def _should_skip_cycle(self) -> bool:
        """Détermine s'il faut sauter ce cycle de polling.

        Retourne True si :
          - On a déjà des données du dernier appel
          - Aucune voie BPC n'était active à ce moment-là
          - On n'a pas encore skippé SCAN_INTERVAL_BPC_IDLE_FACTOR cycles
        """
        if self.data is None:
            return False  # premier appel — toujours faire

        if self.data.any_input_active:
            return False  # quelque chose tourne — on poll à fréquence haute

        if self._skipped_cycles >= SCAN_INTERVAL_BPC_IDLE_FACTOR - 1:
            return False  # quota de skip atteint — on fait un vrai appel

        return True

    # ──────── Helpers pour forcer un refresh immédiat ────────

    async def async_request_immediate_refresh(self) -> None:
        """Force un rafraîchissement immédiat, en bypassant le polling adaptatif.

        À appeler après une commande utilisateur (ex : pompe ON) pour avoir
        l'état réel rapidement, sans attendre le prochain cycle.
        """
        self._skipped_cycles = 0  # reset pour forcer un vrai appel
        await self.async_request_refresh()


# ═════════════════════════════════════════════════════════════════════════════
# CONTAINER GLOBAL DES COORDINATORS
# ═════════════════════════════════════════════════════════════════════════════


@dataclass
class EasyCareCoordinators:
    """Agrégat des 3 coordinators d'une intégration.

    Stocké dans `hass.data[DOMAIN][entry.entry_id]` pour permettre aux
    plateformes (sensor, switch, etc.) d'y accéder facilement.
    """

    user: EasyCareUserCoordinator
    modules: EasyCareModulesCoordinator
    bpc: EasyCareBPCCoordinator

    async def async_first_refresh(self) -> None:
        """Effectue le premier refresh de tous les coordinators.

        Ordre important :
          1. modules d'abord (les autres en dépendent pour identifier WATBOX/BPC)
          2. user et bpc ensuite, en parallèle

        Lève les exceptions HA standard (ConfigEntryAuthFailed, UpdateFailed)
        si le premier refresh échoue — HA décidera comment le gérer.
        """
        # 1. Modules en premier (bloquant)
        await self.modules.async_config_entry_first_refresh()

        # 2. User et BPC en parallèle
        import asyncio
        await asyncio.gather(
            self.user.async_config_entry_first_refresh(),
            self.bpc.async_config_entry_first_refresh(),
        )
