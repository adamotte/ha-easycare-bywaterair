**Correction : changement de mode de filtration**

Le sélecteur de mode de filtration (AUTO, AUTO±2H, CONTINUOUS, MANUAL) retournait une erreur silencieuse depuis la mise à jour de l'API Waterair. Le mode ne changeait pas côté piscine.

**Ce qui était cassé :** l'intégration utilisait un endpoint API (`setStatusCommandToSend`) que le module BPC refuse désormais avec une erreur HTTP 500.

**Ce qui est corrigé :** le changement de mode passe maintenant par l'endpoint des programmes BPC, qui est la voie officielle. Tous les modes et transitions sont couverts (y compris PROG → AUTO).
