**Nouvelles entités : mise à jour logicielle BPC et AC1**

L'intégration détecte désormais les mises à jour logicielles disponibles pour les modules BPC et AC1 et les expose nativement dans Home Assistant via la plateforme `update`.

**Ce que ça apporte :**
- Deux nouvelles entités *Mise à jour* apparaissent dans HA (une par module présent) — visibles dans **Paramètres → Mises à jour** avec un badge de notification
- La version installée (lue depuis les données du module) et la version disponible (interrogée toutes les 24 h via l'API Waterair) sont exposées comme attributs d'état
- Aucune installation depuis HA — la mise à jour s'effectue toujours via l'app mobile Waterair (Bluetooth). L'entité sert uniquement à notifier qu'une mise à jour est disponible
