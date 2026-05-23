"""Exceptions levées par le client API Easy-care by Waterair.

Hiérarchie :
    EasyCareError
    ├── EasyCareAuthError
    │   ├── EasyCareInvalidCodeError
    │   ├── EasyCareTokenExpiredError
    │   └── EasyCareUnauthorizedError
    ├── EasyCareConnectionError
    ├── EasyCareTimeoutError
    ├── EasyCareApiError
    └── EasyCareInvalidResponseError
"""

from __future__ import annotations


class EasyCareError(Exception):
    """Erreur générique du domaine Easy-care."""


class EasyCareAuthError(EasyCareError):
    """Problème d'authentification (tokens, login, refresh)."""


class EasyCareInvalidCodeError(EasyCareAuthError):
    """Code d'autorisation OAuth invalide ou expiré."""


class EasyCareTokenExpiredError(EasyCareAuthError):
    """Refresh token expiré ou révoqué — ré-authentification manuelle requise."""


class EasyCareUnauthorizedError(EasyCareAuthError):
    """Requête API rejetée avec 401 (bearer invalide)."""


class EasyCareConnectionError(EasyCareError):
    """Impossible de joindre les serveurs Waterair."""


class EasyCareTimeoutError(EasyCareError):
    """La requête HTTP a dépassé le timeout configuré."""


class EasyCareApiError(EasyCareError):
    """Erreur HTTP 4xx ou 5xx (hors 401).

    Attributes:
        status_code: code HTTP retourné.
        body       : corps de la réponse pour le debug.
    """

    def __init__(self, message: str, status_code: int, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body[:500] if body else None

    def __str__(self) -> str:
        base = super().__str__()
        if self.body:
            return f"{base} (HTTP {self.status_code}): {self.body}"
        return f"{base} (HTTP {self.status_code})"


class EasyCareInvalidResponseError(EasyCareError):
    """Réponse du serveur syntaxiquement valide mais sémantiquement invalide."""
