**Correction critique : l'intégration ne se chargeait pas (NameError à l'import)**

Une constante `BOOST_MODE_*` était référencée avant sa définition dans `const.py`, ce qui provoquait une erreur à l'import et empêchait l'intégration de se charger complètement.

Mise à jour depuis v1.0.1 recommandée pour tous les utilisateurs.
