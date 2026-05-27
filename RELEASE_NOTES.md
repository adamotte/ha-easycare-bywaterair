**Correction critique : l'intégration ne se chargeait pas (ImportError sur select.py)**

Un import incorrect (`HAHA_BOOST_ACTIVE` / `HAHA_BOOST_OFF` au lieu de `HA_BOOST_ACTIVE` / `HA_BOOST_OFF`) dans `select.py` empêchait le chargement de la plateforme select et bloquait le démarrage de l'intégration.

Mise à jour depuis v1.0.2 recommandée pour tous les utilisateurs.
