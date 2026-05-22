"""Modèles de données du domaine Easy-care by Waterair.

Toutes les données reçues du serveur sont parsées en dataclasses immuables
(`frozen=True`) pour garantir leur stabilité dans le temps et faciliter le
typage. Les classes implémentent toutes une méthode `from_api(data)` qui
prend en entrée un dict JSON brut et retourne une instance validée.

Si un champ critique manque, on lève `EasyCareInvalidResponseError`.
Si un champ optionnel manque, on utilise une valeur par défaut sensée.

Hiérarchie des modèles :

    OAuth/Auth
    ├── OAuthTokens     (réponse de /oauth2/v2.0/token Azure B2C)
    └── BearerToken     (bearer EasyCare avec son expiration)

    Compte / Piscine
    ├── Client          (propriétaire — nom, adresse)
    ├── Pool            (modèle de piscine, volume, géolocalisation)
    ├── Metrics         (dernières mesures : pH, chlore, température, pression)
    ├── Alerts          (notifications du système)
    └── Treatment       (traitements en cours)

    Modules physiques
    ├── Module          (BPC, WATBOX, AC1, LR-PR) — données module
    ├── BPCInput        (une voie du BPC : pompe / spot / escalight)
    └── PoolStatus      (mode filtration + boost + compteurs pompe — depuis Solem)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .exceptions import EasyCareInvalidResponseError


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internes de parsing
# ─────────────────────────────────────────────────────────────────────────────


def _require(data: dict[str, Any], key: str, model_name: str) -> Any:
    """Récupère une clé obligatoire ou lève EasyCareInvalidResponseError.

    Args:
        data       : dictionnaire JSON brut reçu de l'API.
        key        : nom de la clé à extraire.
        model_name : nom du modèle (pour le message d'erreur).

    Returns:
        La valeur associée à la clé.

    Raises:
        EasyCareInvalidResponseError: si la clé est absente ou None.
    """
    if key not in data or data[key] is None:
        raise EasyCareInvalidResponseError(
            f"Champ obligatoire '{key}' absent dans la réponse {model_name}"
        )
    return data[key]


def _parse_timestamp(value: Any) -> datetime | None:
    """Parse un timestamp en datetime UTC, tolérant aux formats.

    Le serveur Waterair retourne tantôt un timestamp Unix (int/float),
    tantôt une chaîne ISO 8601 (ex: "2024-09-05T14:30:00.123Z").

    Args:
        value: int, float, str ou None.

    Returns:
        datetime aware (UTC) ou None si la valeur ne peut pas être parsée.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    if isinstance(value, str):
        # Tolérer le suffixe Z (Zulu time)
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            # Tenter le format date seul (ex : "2024-09-05")
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _parse_measure(
    raw: dict[str, Any] | None,
) -> tuple[float | None, datetime | None]:
    """Parse une mesure {value, date|timestamp} en (valeur, datetime).

    Args:
        raw: dict avec au moins une clé 'value' et soit 'date' soit 'timestamp'.

    Returns:
        (valeur_float, date) — chaque élément peut être None si absent.
    """
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


# ═════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class OAuthTokens:
    """Réponse complète de l'endpoint OAuth2 Azure B2C.

    Retournée par `/oauth2/v2.0/token` aussi bien pour l'échange initial
    (grant_type=authorization_code) que pour le refresh
    (grant_type=refresh_token).

    Champs :
        access_token   : utilisé pour les ressources protégées Azure (peu utile chez nous)
        id_token       : JWT contenant l'identité — sera échangé contre le bearer EasyCare
        refresh_token  : permet de renouveler les tokens (durée ~14j, rotaté)
        expires_at     : timestamp Unix d'expiration de l'id_token et access_token
        token_type     : toujours 'Bearer'
    """

    access_token: str
    id_token: str
    refresh_token: str
    expires_at: float
    token_type: str = "Bearer"

    @classmethod
    def from_api(cls, data: dict[str, Any], *, now: float | None = None) -> OAuthTokens:
        """Parse la réponse JSON brute en OAuthTokens.

        Args:
            data: dict JSON de la réponse OAuth2.
            now : timestamp Unix de référence (défaut : datetime.now()).
                  Paramétrable pour faciliter les tests.

        Raises:
            EasyCareInvalidResponseError: si access_token, id_token ou
                refresh_token est absent. expires_in défaut à 3600.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()

        expires_in = data.get("expires_in", 3600)
        try:
            expires_in = float(expires_in)
        except (TypeError, ValueError):
            expires_in = 3600.0

        return cls(
            access_token=_require(data, "access_token", "OAuthTokens"),
            id_token=_require(data, "id_token", "OAuthTokens"),
            refresh_token=_require(data, "refresh_token", "OAuthTokens"),
            expires_at=now + expires_in,
            token_type=data.get("token_type", "Bearer"),
        )

    def is_expired(self, *, margin_seconds: float = 0, now: float | None = None) -> bool:
        """Vérifie si les tokens sont expirés (id_token et access_token).

        Args:
            margin_seconds: considérer comme expiré N secondes avant l'expiration réelle.
            now           : timestamp Unix de référence.
        """
        if now is None:
            now = datetime.now(tz=timezone.utc).timestamp()
        return (now + margin_seconds) >= self.expires_at


@dataclass(frozen=True, slots=True)
class BearerToken:
    """Bearer EasyCare obtenu via /oauth2/tokenFromAzureADB2CIdToken.

    Ce token est utilisé dans le header `Authorization: Bearer <token>` pour
    toutes les requêtes vers `/api/*` sur easycare.waterair.com.

    Sa durée de vie n'est pas formellement documentée mais semble suivre
    expires_in de la réponse JSON. On gère son refresh comme l'id_token.
    """

    bearer: str
    expires_at: float

    @classmethod
    def from_api(cls, data: dict[str, Any], *, now: float | None = None) -> BearerToken:
        """Parse la réponse JSON brute en BearerToken.

        Le serveur peut retourner soit `bearer`, soit `access_token` selon
        la version d'API — on accepte les deux.
        """
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


# ═════════════════════════════════════════════════════════════════════════════
# COMPTE UTILISATEUR ET PISCINE
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Client:
    """Propriétaire du compte Waterair (utilisé pour l'affichage UI uniquement)."""

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
        parts = [
            self.address_line1,
            self.address_line2,
            f"{self.postal_code} {self.city}".strip(),
        ]
        return ", ".join(p for p in parts if p)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Client:
        """Parse les données client depuis la réponse de /api/getUser."""
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
            volume=_to_float(data.get("volume")),
            address=data.get("address", ""),
            latitude=_to_float(data.get("latitude")),
            longitude=_to_float(data.get("longitude")),
            custom_photo=data.get("customPhoto", ""),
        )


@dataclass(frozen=True, slots=True)
class Metrics:
    """Dernières mesures de la piscine (pH, chlore, température, pression).

    Chaque mesure est un tuple (valeur, date_de_mesure). La date peut être
    None si l'API n'a jamais reçu de mesure pour ce paramètre.
    """

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
        """Parse les métriques depuis le bloc 'status' d'une piscine.

        L'API retourne les mesures sous /pools[i]/status/lastXxxMeasure avec
        soit un timestamp Unix dans `date`, soit une chaîne ISO dans `timestamp`.
        """
        status = pool_data.get("status") or {}

        ph_value, ph_date = _parse_measure(status.get("lastPhMeasure"))
        chlorine_value, chlorine_date = _parse_measure(status.get("lastRedoxMeasure"))
        temperature_value, temperature_date = _parse_measure(
            status.get("lastTemperatureMeasure")
        )
        pressure_value, pressure_date = _parse_measure(status.get("lastPressureMeasure"))

        return cls(
            ph_value=ph_value,
            ph_date=ph_date,
            chlorine_value=chlorine_value,
            chlorine_date=chlorine_date,
            temperature_value=temperature_value,
            temperature_date=temperature_date,
            pressure_value=pressure_value,
            pressure_date=pressure_date,
        )


@dataclass(frozen=True, slots=True)
class Notification:
    """Une notification individuelle (alerte chlore, alerte pH, etc.)."""

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
        """Action de la notification la plus récente ('None' si aucune).

        Compatible avec le plugin existant qui retourne 'None' (str) par défaut.
        """
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
            parsed.append(
                Notification(
                    action=str(n.get("action", "")),
                    date=_parse_timestamp(n.get("date")),
                )
            )
        # Tri décroissant par date (None en dernier)
        parsed.sort(key=lambda x: x.date or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True)
        return cls(notifications=tuple(parsed))


@dataclass(frozen=True, slots=True)
class Treatment:
    """Traitement de l'eau en cours (correction pH, choc chlore, etc.)."""

    value: str = "None"
    date: datetime | None = None

    @classmethod
    def from_api(cls, pool_data: dict[str, Any]) -> Treatment:
        """Parse le traitement depuis 'waterChemistryCorrectionProtocol'."""
        proto = pool_data.get("waterChemistryCorrectionProtocol")
        if not isinstance(proto, dict):
            return cls()

        date = _parse_timestamp(
            proto.get("date") or proto.get("lastPHOutOfControlAlertSentDate")
        )
        return cls(
            value=str(proto.get("correctionProtocolType", "None")),
            date=date,
        )


# ═════════════════════════════════════════════════════════════════════════════
# MODULES PHYSIQUES (WATBOX, BPC, AC1, LR-PR)
# ═════════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True, slots=True)
class Module:
    """Représente un module physique de l'écosystème Waterair.

    Identification via `type` :
      - 'lr-bst-compact' → WATBOX (passerelle)
      - 'lr-pc'          → BPC (boîtier piscine connecté)
      - 'lr-mas'         → AC1 (analyseur connecté)
      - 'lr-pr'          → capteur de pression (optionnel)

    Le `name` contient un préfixe (ex: "BPC-06DFC6", "WATBOX-071781") :
    pour construire les URLs API on retire ce préfixe via `short_name`.
    """

    type: str
    name: str
    id: str
    serial_number: str
    number_of_inputs: int = 0
    battery_level: int | None = None
    image: str = ""
    static_pressure: float = 0.0  # uniquement pour les LR-PR
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def short_name(self) -> str:
        """Nom du module sans son préfixe (utilisé dans les URLs API).

        Exemples :
            "BPC-06DFC6"     → "06DFC6"
            "WATBOX-071781"  → "071781"
            "AC1-06FC2C"     → "06FC2C"

        Le préfixe (3 lettres + '-') fait toujours 4 caractères dans
        l'écosystème Waterair, mais on coupe au premier '-' pour rester
        robuste si le préfixe change.
        """
        if "-" in self.name:
            return self.name.split("-", 1)[1]
        return self.name

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Module:
        """Parse les données d'un module depuis /api/getUserWithHisModules."""
        # Champs obligatoires : type, name, id, serialNumber
        type_ = _require(data, "type", "Module")
        name = _require(data, "name", "Module")
        id_ = _require(data, "id", "Module")
        serial = _require(data, "serialNumber", "Module")

        # Battery level — le plugin existant utilise "getBatteryLevel"
        battery = data.get("getBatteryLevel")
        if battery is not None:
            try:
                battery = int(battery)
            except (TypeError, ValueError):
                battery = None

        # Pression statique : uniquement pour les LR-PR, structure imbriquée
        static_pressure = 0.0
        if type_ == "lr-pr":
            try:
                static_pressure = float(
                    data["inputs"][0]["poolPressureAlertsVariables"]["staticPressure"]
                )
            except (KeyError, IndexError, TypeError, ValueError):
                static_pressure = 0.0

        return cls(
            type=type_,
            name=name,
            id=id_,
            serial_number=serial,
            number_of_inputs=int(data.get("numberOfInputs", 0) or 0),
            battery_level=battery,
            image=data.get("customPhoto", ""),
            static_pressure=static_pressure,
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class BPCInput:
    """Une voie (input) du BPC : pompe, projecteur ou éclairage de marches.

    Le champ `time` contient le temps restant au format "HH:MM" :
      - "00:00"   → voie inactive
      - autre val → voie en marche, temps restant indiqué

    Index conventionnels (confirmés par l'APK et le code source du plugin) :
      - 0 = pompe de filtration
      - 1 = projecteur (spot)
      - 2 = éclairage des marches (escalight)
    """

    index: int
    remaining_time: str = "00:00"
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_on(self) -> bool:
        """Vrai si la voie est actuellement active."""
        return self.remaining_time != "00:00"

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> BPCInput:
        """Parse une voie depuis la réponse /api/module/.../status/..."""
        return cls(
            index=int(_require(data, "index", "BPCInput")),
            remaining_time=str(data.get("time", "00:00") or "00:00"),
            raw=data,
        )


@dataclass(frozen=True, slots=True)
class PoolStatus:
    """État de filtration de la piscine — récupéré depuis Solem.

    Source : `GET /api/getPoolStatus` sur apiwf.solem.fr
    Tous les champs sont optionnels car l'API peut omettre certaines clés
    selon l'état du système.

    Champs clés (confirmés dans l'APK) :
      - mode : AUTO / CONTINUOUS / MANUAL / PROG
      - boost_time_left / boost_remaining_time : "HH:MM"
      - total_activation_time : "HHH:MM" (cumul depuis reset_date)
      - total_activation_time_reset_date : date d'installation/remplacement
      - total_operating_time_for_today : durée du jour
    """

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
        """Parse la réponse de getPoolStatus.

        L'API Solem peut renvoyer les champs au niveau racine ou imbriqués
        sous une clé 'pool' / 'status'. On essaie plusieurs profondeurs.
        """
        # Si la réponse a une clé "pool" ou "status", on plonge dedans
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
            payload.get("boostTimeLeft")
            or payload.get("boostRemainingTime")
            or "00:00"
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
