"""Exceptions levées par le client API Easy-care by Waterair.

Hiérarchie :

    EasyCareError                       (base)
    ├── EasyCareAuthError               (problèmes d'authentification)
    │   ├── EasyCareInvalidCodeError    (code OAuth initial invalide/expiré)
    │   ├── EasyCareTokenExpiredError   (refresh_token expiré, reauth requis)
    │   └── EasyCareUnauthorizedError   (401 sur une requête API)
    ├── EasyCareConnectionError         (problème réseau / serveur down)
    ├── EasyCareTimeoutError            (timeout HTTP)
    ├── EasyCareApiError                (erreur HTTP 4xx/5xx hors 401)
    └── EasyCareInvalidResponseError    (réponse JSON malformée ou champ manquant)

Toutes les exceptions héritent d'`EasyCareError`, ce qui permet aux appelants
de capturer toute la famille avec `except EasyCareError`.
"""

from __future__ import annotations


class EasyCareError(Exception):
    """Erreur générique du domaine Easy-care.

    Classe de base de toutes les exceptions levées par le client API.
    Ne pas instancier directement, utiliser une sous-classe.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Erreurs d'authentification
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareAuthError(EasyCareError):
    """Problème d'authentification générique.

    Sous-classe pour tout ce qui touche aux tokens (login, refresh, bearer).
    """


class EasyCareInvalidCodeError(EasyCareAuthError):
    """Le code d'autorisation OAuth fourni est invalide ou expiré.

    Levé pendant le config_flow initial quand l'utilisateur colle un code
    qui ne fonctionne pas. Le code OAuth a typiquement une durée de vie
    très courte (~quelques minutes).
    """


class EasyCareTokenExpiredError(EasyCareAuthError):
    """Le refresh_token a expiré ou a été révoqué — reauth manuelle requise.

    Cette erreur déclenche le flow `async_step_reauth` de HA, qui demandera
    à l'utilisateur de fournir un nouveau code OAuth.

    Cas typiques :
    - HA arrêté pendant plus de 14 jours (durée du refresh_token Azure B2C)
    - Mot de passe Waterair changé par l'utilisateur
    - Compte révoqué côté Waterair
    """


class EasyCareUnauthorizedError(EasyCareAuthError):
    """Une requête API a retourné 401 (bearer EasyCare invalide).

    Doit déclencher un refresh forcé du bearer puis un retry de la requête.
    Si le retry échoue à nouveau, on remonte l'erreur.
    """


# ─────────────────────────────────────────────────────────────────────────────
# Erreurs réseau / serveur
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareConnectionError(EasyCareError):
    """Impossible de joindre les serveurs Waterair (DNS, TCP, TLS, serveur down).

    Distincte d'un timeout : ici la connexion n'a même pas pu s'établir.
    """


class EasyCareTimeoutError(EasyCareError):
    """La requête HTTP a dépassé le timeout configuré.

    Pas forcément critique : peut indiquer une latence ponctuelle.
    Les coordinators HA gèreront le retry automatiquement.
    """


class EasyCareApiError(EasyCareError):
    """Erreur HTTP 4xx ou 5xx (hors 401 qui a son propre type).

    Attributs :
        status_code (int) : code HTTP retourné
        body (str | None) : corps de la réponse pour le debug
    """

    def __init__(
        self,
        message: str,
        status_code: int,
        body: str | None = None,
    ) -> None:
        """Initialise l'erreur API.

        Args:
            message    : description lisible de l'erreur.
            status_code: code HTTP retourné par le serveur.
            body       : corps de la réponse (tronqué si trop long).
        """
        super().__init__(message)
        self.status_code = status_code
        self.body = body[:500] if body else None

    def __str__(self) -> str:
        """Représentation lisible incluant le code HTTP."""
        base = super().__str__()
        if self.body:
            return f"{base} (HTTP {self.status_code}): {self.body}"
        return f"{base} (HTTP {self.status_code})"


# ─────────────────────────────────────────────────────────────────────────────
# Erreurs de données
# ─────────────────────────────────────────────────────────────────────────────


class EasyCareInvalidResponseError(EasyCareError):
    """La réponse du serveur est syntaxiquement OK mais sémantiquement invalide.

    Cas typiques :
    - JSON malformé
    - Champs obligatoires manquants
    - Type de données inattendu (ex : string là où on attend un int)
    - Liste vide là où au moins un élément est attendu (ex : aucune piscine
      sur le compte)

    Cette erreur n'est généralement pas récupérable par retry — elle indique
    un changement de format API côté Waterair.
    """
