"""Modèles de données du domaine Easy-care by Waterair.

Toutes les réponses API sont parsées en dataclasses immuables (`frozen=True`).
Chaque classe expose une méthode `from_api(data)` qui valide et convertit
un dict JSON brut. Les champs critiques manquants lèvent `EasyCareInvalidResponseError`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from .exceptions import EasyCareInvalidResponseError


def _require(data: dict[str, Any], key: str, model_name: str) -> Any:
    """Récupère une clé obligatoire ou lève EasyCareInvalidResponseError."""
    if key not in data or data[key] is None:
        raise EasyCareInvalidResponseError(
            f"Champ obligatoire '{key}' absent dans la réponse {model_name}"
        )
    return data[key]


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse un timestamp en datetime UTC, tolérant aux formats Unix et ISO 8601."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _parse_measure(raw: dict[str, Any] | None) -> tuple[float | None, datetime | None]:
    """Parse une mesure {value, date|timestamp} en (valeur, datetime)."""
    if raw is None:
        return None, None
    value: float | None = None
    if "value" in raw and raw["value"] is not None:
        try:
            value = float(raw["value"])
        except (TypeError, ValueError):
            value = None
    date = _parse_timestamp(raw.get("date") or raw.get("timestamp"))
    return value, date


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    """Réponse complète de l'endpoint OAuth2 Azure B2C."""

    access_token: str
    id_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"

    @classmethod
    def from_api(cls, data: dict[str, Any], *, now: float | None = None) -> OAuthTokens:
        """Parse la réponse JSON brute en OAuthTokens."""
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()
        expires_in = data.get("expires_in") or data.get("id_token_expires_in", 3600)
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600.0
        return cls(
            access_token=data.get("access_token", ""),
            id_token=_require(data, "id_token", "OAuthTokens"),
            refresh_token=_require(data, "refresh_token", "OAuthTokens"),
            expires_at=now + expires_in,
            token_type=data.get("token_type", "Bearer"),
        )

    def is_expired(self, *, margin_seconds: float = 0, now: float | None = None) -> bool:
        """Vérifie si les tokens sont expirés.

        Args:
            margin_seconds: considérer comme expiré N secondes avant l'expiration réelle.
            now           : timestamp Unix de référence.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()
        return (now + margin_seconds) >= self.expires_at


@dataclass(frozen=True, slots=True)
class BearerToken:
    """Bearer EasyCare utilisé dans les en-têtes Authorization."""

    bearer: str
    expires_at: float

    @classmethod
    def from_api(cls, data: dict[str, Any], *, now: float | None = None) -> BearerToken:
        """Parse la réponse JSON brute en BearerToken."""
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()
        bearer = data.get("bearer") or data.get("access_token")
        if not bearer:
            raise EasyCareInvalidResponseError(
                "Champ 'bearer' ou 'access_token' absent dans la réponse BearerToken"
            )
        expires_in = data.get("expires_in", 3600)
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600.0
        return cls(bearer=bearer, expires_at=now + expires_in)

    def is_expired(self, *, margin_seconds: float = 0, now: float | None = None) -> bool:
        """Vérifie si le bearer est expiré.

        Args:
            margin_seconds: considérer comme expiré N secondes avant l'expiration réelle.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()
        return (now + margin_seconds) >= self.expires_at


@dataclass(frozen=True, slots=True)
class Client:
    """Propriétaire du compte Waterair."""

    first_name: str
    last_name: str
    email: str
    address_line1: str = ""
    address_line2: str = ""
    postal_code: str = ""
    city: str = ""

    @property
    def full_name(self) -> str:
        """Nom complet 'Prénom Nom'."""
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def full_address(self) -> str:
        """Adresse formatée sur une ligne."""
        parts = [self.address_line1, self.address_line2, f"{self.postal_code} {self.city}".strip()]
        return ", ".join(p for p in parts if p)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Client:
        """Parse les données client depuis /api/getUser."""
        return cls(
            first_name=data.get("firstName", ""),
            last_name=data.get("lastName", ""),
            email=data.get("email", ""),
            address_line1=data.get("addressLine1", ""),
            address_line2=data.get("addressLine2", ""),
            postal_code=data.get("postalCode", ""),
            city=data.get("city", ""),
        )


@dataclass(frozen=True, slots=True)
class Pool:
    """Caractéristiques physiques de la piscine."""

    model: str
    id: str = ""
    volume: float = 0.0
    address: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    custom_photo: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Pool:
        """Parse les données d'une piscine."""
        def _to_float(v: Any, default: float = 0.0) -> float:
            try:
                return float(v) if v is not None else default
            except (TypeError, ValueError):
                return default

        return cls(
            model=data.get("model", "Unknown"),
            id=str(data.get("_id") or data.get("id") or ""),
            volume=_to_float(data.get("volume")),
            address=data.get("address", ""),
            latitude=_to_float(data.get("latitude")),
            longitude=_to_float(data.get("longitude")),
            custom_photo=data.get("customPhoto", ""),
        )


@dataclass(frozen=True, slots=True)
class Metrics:
    """Dernières mesures de la piscine (pH, chlore, température, pression)."""

    ph_value: float | None = None
    ph_date: datetime | None = None
    chlorine_value: float | None = None
    chlorine_date: datetime | None = None
    temperature_value: float | None = None
    temperature_date: datetime | None = None
    pressure_value: float | None = None
    pressure_date: datetime | None = None

    @classmethod
    def from_api(cls, pool_data: dict[str, Any]) -> Metrics:
        """Parse les métriques depuis le bloc 'status' d'une piscine."""
        status = pool_data.get("status") or {}
        ph_value, ph_date = _parse_measure(status.get("lastPhMeasure"))
        chlorine_value, chlorine_date = _parse_measure(status.get("lastRedoxMeasure"))
        temperature_value, temperature_date = _parse_measure(status.get("lastTemperatureMeasure"))
        pressure_value, pressure_date = _parse_measure(status.get("lastPressureMeasure"))
        return cls(
            ph_value=ph_value, ph_date=ph_date,
            chlorine_value=chlorine_value, chlorine_date=chlorine_date,
            temperature_value=temperature_value, temperature_date=temperature_date,
            pressure_value=pressure_value, pressure_date=pressure_date,
        )


@dataclass(frozen=True, slots=True)
class Notification:
    """Une notification individuelle."""

    action: str
    date: datetime | None


@dataclass(frozen=True, slots=True)
class Alerts:
    """Notifications du système, triées de la plus récente à la plus ancienne."""

    notifications: tuple[Notification, ...] = ()

    @property
    def latest(self) -> Notification | None:
        """Notification la plus récente, ou None si aucune."""
        return self.notifications[0] if self.notifications else None

    @property
    def latest_action(self) -> str:
        """Action de la notification la plus récente ('None' si aucune)."""
        return self.latest.action if self.latest else "None"

    @classmethod
    def from_api(cls, pool_data: dict[str, Any]) -> Alerts:
        """Parse les notifications depuis le bloc 'notifications' d'une piscine."""
        notifications_raw = pool_data.get("notifications") or {}
        if not isinstance(notifications_raw, dict):
            return cls()
        parsed: list[Notification] = []
        for _, n in notifications_raw.items():
            if not isinstance(n, dict):
                continue
            parsed.append(Notification(action=str(n.get("action", "")), date=_parse_timestamp(n.get("date"))))
        parsed.sort(key=lambda x: x.date or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return cls(notifications=tuple(parsed))


@dataclass(frozen=True, slots=True)
class Treatment:
    """Traitement de l'eau en cours."""

    value: str = "None"
    date: datetime | None = None

    @classmethod
    def from_api(cls, pool_data: dict[str, Any]) -> Treatment:
        """Parse le traitement depuis 'waterChemistryCorrectionProtocol'."""
        proto = pool_data.get("waterChemistryCorrectionProtocol")
        if not isinstance(proto, dict):
            return cls()
        date = _parse_timestamp(proto.get("date") or proto.get("lastPHOutOfControlAlertSentDate"))
        return cls(value=str(proto.get("correctionProtocolType", "None")), date=date)


@dataclass(frozen=True, slots=True)
class ModuleOutput:
    """Voie de sortie d'un module BPC (pompe=0, spot=1, escalight=2).

    total_activation_time          : durée cumulée en minutes depuis la date de remise à zéro.
    total_activation_time_reset_date: date de remise à zéro du compteur.
    """

    index: int
    name: str
    id: str
    total_activation_time: int | None = None
    total_activation_time_reset_date: datetime | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> ModuleOutput:
        """Parse une sortie depuis le tableau 'outputs' du module BPC."""
        tat = data.get("totalActivationTime")
        return cls(
            index=int(data.get("index", 0)),
            name=str(data.get("name", "")),
            id=str(data.get("id", "")),
            total_activation_time=int(tat) if tat is not None else None,
            total_activation_time_reset_date=_parse_timestamp(
                data.get("totalActivationTimeResetDate")
            ),
        )


@dataclass(frozen=True, slots=True)
class Module:
    """Module physique de l'écosystème Waterair (WATBOX, BPC, AC1, LR-PR).

    Le `short_name` retire le préfixe du nom (ex: "BPC-XXXXXX" → "XXXXXX")
    pour construire les URLs API.
    """

    type: str
    name: str
    id: str
    serial_number: str
    number_of_inputs: int = 0
    battery_level: int | None = None
    image: str = ""
    static_pressure: float = 0.0
    outputs: tuple[ModuleOutput, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)
    software_version: str | None = None
    hardware_version: str | None = None
    firmware_available: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def short_name(self) -> str:
        """Nom du module sans son préfixe (utilisé dans les URLs API)."""
        if "-" in self.name:
            return self.name.split("-", 1)[1]
        return self.name

    def get_output(self, index: int) -> ModuleOutput | None:
        """Retourne la sortie d'index donné, ou None si absente."""
        return next((o for o in self.outputs if o.index == index), None)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Module:
        """Parse les données d'un module depuis /api/getUserWithHisModules."""
        type_ = _require(data, "type", "Module")
        name = _require(data, "name", "Module")
        id_ = _require(data, "id", "Module")
        serial = _require(data, "serialNumber", "Module")
        battery = data.get("getBatteryLevel")
        if battery is not None:
            try:
                battery = int(battery)
            except (TypeError, ValueError):
                battery = None
        static_pressure = 0.0
        if type_ == "lr-pr":
            try:
                static_pressure = float(
                    data["inputs"][0]["poolPressureAlertsVariables"]["staticPressure"]
                )
            except (KeyError, IndexError, TypeError, ValueError):
                static_pressure = 0.0
        outputs = tuple(
            ModuleOutput.from_api(o)
            for o in (data.get("outputs") or [])
            if isinstance(o, dict)
        )
        return cls(
            type=type_, name=name, id=id_, serial_number=serial,
            number_of_inputs=int(data.get("numberOfInputs", 0) or 0),
            battery_level=battery, image=data.get("customPhoto", ""),
            static_pressure=static_pressure, outputs=outputs, raw=data,
            software_version=data.get("softwareVersion"),
            hardware_version=data.get("hardwareVersion"),
        )


@dataclass(frozen=True, slots=True)
class BPCInput:
    """Une voie du BPC : pompe (index 0), spot (index 1) ou escalight (index 2).

    Champs clés :
        value          : 1 = voie active, 0 = inactive
        remaining_time : temps restant au format "HH:MM"
        info           : tags — ['boost'] si boost actif
    """

    index: int
    value: int = 0
    remaining_time: str = "00:00"
    origin: int | None = None
    info: tuple[str, ...] = ()
    temp_ref: int | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_on(self) -> bool:
        """Vrai si la voie est active."""
        return self.value == 1

    @property
    def is_boosting(self) -> bool:
        """Vrai si la voie tourne en mode boost."""
        return "boost" in self.info

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BPCInput:
        """Parse une voie depuis la réponse /api/module/.../status/..."""
        origin_raw = data.get("origin")
        temp_ref_raw = data.get("tempRef")
        return cls(
            index=int(_require(data, "index", "BPCInput")),
            value=int(data.get("value", 0) or 0),
            remaining_time=str(data.get("time", "00:00") or "00:00"),
            origin=int(origin_raw) if origin_raw is not None else None,
            info=tuple(str(i) for i in (data.get("info") or [])),
            temp_ref=int(temp_ref_raw) if temp_ref_raw is not None else None,
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class CyclicRule:
    """Une règle cyclic de filtration pour un seuil de température.

    threshold_index : index dans le tableau `ths` du programCharacteristics.
    threshold_temp  : température seuil en °C (ths[threshold_index]), None si hors limites.
    duration_min    : durée de filtration par cycle (minutes).
    period_min      : période entre le début de deux cycles (minutes).
    """

    threshold_index: int
    threshold_temp: int | None
    duration_min: int
    period_min: int

    @property
    def daily_hours(self) -> float:
        """Durée de filtration journalière en heures."""
        if self.period_min <= 0:
            return 0.0
        return round((self.duration_min / self.period_min) * 24, 2)


@dataclass(frozen=True, slots=True)
class FilterSchedule:
    """Programme de filtration de la pompe (programme index=0).

    thresholds : tableau brut `ths` (seuils de température en °C).
                 Valeur sentinelle 127 (0x7F) = jamais actif.
    sched      : matrice 7×12 de masques 24 bits (7 jours × 12 seuils).
                 Bit N = 1 → la pompe filtre pendant l'heure N.
                 Toutes les lignes sont identiques en mode AUTO.
                 Source de vérité pour les plages horaires.
    rules      : règles cyclic brutes (champ `cyclic`) — info complémentaire.
    """

    thresholds: tuple[int, ...]
    sched: tuple[tuple[int, ...], ...] | None = None
    rules: tuple[CyclicRule, ...] = ()

    @classmethod
    def from_program_characteristics(
        cls, charac: dict[str, Any], *, sched: Any = None
    ) -> FilterSchedule:
        """Parse le bloc programCharacteristics du programme pompe (index=0).

        Args:
            charac: bloc programCharacteristics (contient ths, cyclic, mode, rule…).
            sched : matrice sched brute au niveau racine du programme (pas dans charac).
        """
        ths = tuple(int(t) for t in (charac.get("ths") or []))

        # Matrice sched — 7 lignes × 12 colonnes de masques 24 bits.
        # Transmise depuis la racine du programme (prog.get("sched")), pas depuis charac.
        parsed_sched: tuple[tuple[int, ...], ...] | None = None
        if isinstance(sched, list):
            parsed_sched = tuple(
                tuple(int(v) for v in row)
                for row in sched
                if isinstance(row, list)
            )

        # Règles cyclic — info complémentaire sur les durées/périodes
        rules: list[CyclicRule] = []
        for entry in (charac.get("cyclic") or []):
            th_idx = int(entry.get("th", 0))
            temp = ths[th_idx] if th_idx < len(ths) else None
            rules.append(CyclicRule(
                threshold_index=th_idx,
                threshold_temp=temp,
                duration_min=int(entry.get("dur", 0)),
                period_min=int(entry.get("per", 1)),
            ))

        return cls(thresholds=ths, sched=parsed_sched, rules=tuple(rules))

    def active_threshold_index_for_temp(self, ref_temp: float) -> int | None:
        """Retourne l'index du seuil actif dans `thresholds` pour une température de référence.

        Algorithme : seuil plafond — seuil le plus bas parmi ceux ≥ ref_temp.
        Correspond à l'algorithme du BPC (getTemperatureThresholdIndexFrom) qui utilise
        la température maximale de la veille (maxTemperatureTheDayBefore).
        Exclut la valeur sentinelle 127.
        Si ref_temp dépasse tous les seuils réels, retourne l'index du seuil le plus élevé.
        """
        best_idx: int | None = None
        best_temp: int | None = None
        # Seuil plafond : le plus bas ≥ ref_temp (hors sentinelle 127)
        for i, th in enumerate(self.thresholds):
            if th == 127:
                continue
            if th >= ref_temp:
                if best_temp is None or th < best_temp:
                    best_temp = th
                    best_idx = i
        # Fallback : ref_temp au-dessus de tous les seuils réels → seuil le plus élevé
        if best_idx is None:
            for i, th in enumerate(self.thresholds):
                if th == 127:
                    continue
                if best_temp is None or th > best_temp:
                    best_temp = th
                    best_idx = i
        return best_idx

    def active_bitmask_for_temp(
        self, temperature: float, *, threshold_idx: int | None = None
    ) -> int | None:
        """Retourne le masque 24 bits actif pour un seuil donné.

        Si `threshold_idx` est fourni, l'utilise directement (source BPC, stable).
        Sinon, dérive l'index depuis `temperature` via `active_threshold_index_for_temp`.
        Utilise la première ligne de `sched` (toutes identiques en mode AUTO).
        Retourne None si `sched` est absent ou l'index hors limites.
        """
        if not self.sched:
            return None
        if threshold_idx is None:
            threshold_idx = self.active_threshold_index_for_temp(temperature)
        if threshold_idx is None:
            return None
        row = self.sched[0]
        if threshold_idx >= len(row):
            return None
        return row[threshold_idx]

    def daily_hours_from_sched(
        self, temperature: float, *, threshold_idx: int | None = None
    ) -> float | None:
        """Durée de filtration journalière en heures depuis le masque sched (popcount).

        Si `threshold_idx` est fourni, l'utilise directement (source BPC, stable).
        Plus précis que le calcul dur/per : tient compte des plages horaires réelles.
        """
        mask = self.active_bitmask_for_temp(temperature, threshold_idx=threshold_idx)
        if mask is None:
            return None
        return float(bin(mask).count("1"))

    def filter_windows_from_sched(
        self, temperature: float, *, threshold_idx: int | None = None
    ) -> list[tuple[int, int]] | None:
        """Retourne les créneaux actifs [(début_h, fin_h), ...] depuis le masque sched.

        Si `threshold_idx` est fourni, l'utilise directement (source BPC, stable).
        fin_h est exclusive : (10, 16) = 10h→16h.
        Peut retourner plusieurs créneaux (ex. mode hors-gel : [(5, 7), (22, 23)]).
        """
        mask = self.active_bitmask_for_temp(temperature, threshold_idx=threshold_idx)
        if mask is None:
            return None
        windows: list[tuple[int, int]] = []
        start: int | None = None
        for h in range(24):
            if mask & (1 << h):
                if start is None:
                    start = h
            else:
                if start is not None:
                    windows.append((start, h))
                    start = None
        if start is not None:
            windows.append((start, 24))
        return windows

    def active_rule_for_temp(
        self, ref_temp: float, *, threshold_idx: int | None = None
    ) -> CyclicRule | None:
        """Retourne la règle cyclic active (fallback si `sched` absent).

        Si `threshold_idx` est fourni, recherche directement par index.
        Sinon : seuil plafond (le plus bas ≥ ref_temp), fallback sur le plus élevé.
        """
        if threshold_idx is not None:
            for rule in self.rules:
                if rule.threshold_index == threshold_idx:
                    return rule
            return None
        best: CyclicRule | None = None
        for rule in self.rules:
            if rule.threshold_temp is not None and rule.threshold_temp >= ref_temp:
                if best is None or rule.threshold_temp < (best.threshold_temp or float("inf")):
                    best = rule
        # Fallback : si aucune règle ≥ ref_temp, prendre la règle avec le seuil le plus élevé
        if best is None:
            for rule in self.rules:
                if rule.threshold_temp is not None:
                    if best is None or rule.threshold_temp > (best.threshold_temp or 0):
                        best = rule
        return best

    def next_filtration_events(
        self, temperature: float, now: datetime, *, threshold_idx: int | None = None
    ) -> tuple[datetime | None, datetime | None]:
        """Retourne (prochain_démarrage, prochain_arrêt) selon l'heure actuelle.

        Sémantique :
          - Si la pompe est actuellement dans une plage :
              prochain_démarrage = début de la plage suivante (demain si dernière du jour)
              prochain_arrêt     = fin de la plage courante
          - Si la pompe n'est pas dans une plage :
              prochain_démarrage = début de la prochaine plage (demain si toutes passées)
              prochain_arrêt     = fin de cette prochaine plage

        Args:
            temperature  : température de l'eau en °C (ignorée si threshold_idx fourni).
            now          : datetime courant (timezone-aware recommandé).
            threshold_idx: index direct dans `ths` (depuis BPCInput.temp_ref), prioritaire
                           sur la déduction par température.

        Returns:
            Tuple (next_start, next_end). Les deux sont None si sched absent ou vide.
        """
        windows = self.filter_windows_from_sched(temperature, threshold_idx=threshold_idx)
        if not windows:
            return None, None

        current_h = now.hour
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)

        def _make_dt(base: datetime, h: int) -> datetime:
            """Heure h dans la journée de base (h=24 → minuit du lendemain)."""
            if h >= 24:
                return base + timedelta(days=1)
            return base.replace(hour=h)

        # Cherche si on est dans une plage courante
        current_idx: int | None = None
        for i, (start_h, end_h) in enumerate(windows):
            if start_h <= current_h < end_h:
                current_idx = i
                break

        if current_idx is not None:
            # On est dans une plage — arrêt = fin courante, démarrage = plage suivante
            _, end_h = windows[current_idx]
            next_stop = _make_dt(today, end_h)
            if current_idx + 1 < len(windows):
                next_start = _make_dt(today, windows[current_idx + 1][0])
            else:
                next_start = _make_dt(tomorrow, windows[0][0])
            return next_start, next_stop

        # On n'est pas dans une plage — cherche la prochaine
        for start_h, end_h in windows:
            if start_h > current_h:
                return _make_dt(today, start_h), _make_dt(today, end_h)

        # Toutes les plages du jour sont passées → première plage de demain
        first_start, first_end = windows[0]
        return _make_dt(tomorrow, first_start), _make_dt(tomorrow, first_end)


@dataclass(frozen=True, slots=True)
class PoolStatus:
    """État de filtration de la piscine."""

    mode: str | None = None
    power_state: str | None = None
    boost_remaining_time: str = "00:00"
    boost_duration: int | None = None
    manual_duration: int | None = None
    total_activation_time: str | None = None
    total_activation_time_reset_date: datetime | None = None
    total_operating_time_for_today: str | None = None
    is_pool_power: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_boosting(self) -> bool:
        """Vrai si un boost est actuellement actif."""
        return self.boost_remaining_time not in (None, "", "00:00")

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PoolStatus:
        """Parse la réponse de getPoolStatus."""
        payload = data
        for nested_key in ("pool", "status"):
            if nested_key in data and isinstance(data[nested_key], dict):
                payload = data[nested_key]
                break

        def _opt_int(v: Any) -> int | None:
            if v is None:
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None

        boost_remaining = (
            payload.get("boostTimeLeft") or payload.get("boostRemainingTime") or "00:00"
        )
        return cls(
            mode=payload.get("mode") or payload.get("powerMode"),
            power_state=payload.get("powerState"),
            boost_remaining_time=str(boost_remaining),
            boost_duration=_opt_int(payload.get("boostDuration")),
            manual_duration=_opt_int(payload.get("manualDuration")),
            total_activation_time=payload.get("totalActivationTime"),
            total_activation_time_reset_date=_parse_timestamp(
                payload.get("totalActivationTimeResetDate")
            ),
            total_operating_time_for_today=payload.get("totalOperatingTimeForToday"),
            is_pool_power=payload.get("isPoolPower"),
            raw=data,
        )
