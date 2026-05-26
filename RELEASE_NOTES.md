**Correction : crash au démarrage introduit en v0.5.3**

L'attribut `last_update` utilisé dans v0.5.3 reposait sur un attribut interne de Home Assistant qui n'existe pas. Cela provoquait un crash empêchant le chargement des sensors et des lumières sur toutes les installations.

**Ce qui est corrigé :**
- `last_update` sur le sensor de détail piscine affiche maintenant la date de la mesure la plus récente retournée par l'API Waterair (parmi pH, chlore, température, pression) — fiable et indépendant de la version HA
- L'attribut `last_update` est retiré des entités lumières où il n'avait pas de source de données exploitable
