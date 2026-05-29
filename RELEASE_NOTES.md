**Notifications complètes (issue #9)**

Le capteur **Dernière notification** gère désormais l'ensemble des types de notification de l'écosystème Waterair (calibration, hivernage, traitement chlore, piles faibles, fuite, filtre encrassé, vannes, perte de connectivité, niveau d'eau, électrolyseur, régulation pH…).

- Nouvel attribut **`notifications`** sur le capteur : la **liste complète** des alertes actives (`action` + `date`), de la plus récente à la plus ancienne — utile quand plusieurs alertes sont actives en même temps.
- **Une notification persistante par alerte** : chaque alerte apparaît comme une notification distincte, **fermable individuellement**. Une alerte fermée ne réapparaît pas tant qu'elle reste active ; une alerte résolue côté Waterair disparaît automatiquement.
- Libellés et messages en **français et anglais**, alignés sur la terminologie de l'application officielle.

---

**Correctif**

Message d'erreur clair si la dépendance `curl_cffi` n'a pas pu être installée (au lieu d'une erreur technique), avec la marche à suivre.
