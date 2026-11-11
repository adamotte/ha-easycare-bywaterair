**Maintenance: coordinators are now stored in the config entry**

This is an internal refactor: nothing changes in the way you use the integration. Coordinators are now stored in the config entry itself (`entry.runtime_data`) instead of a shared dictionary, following Home Assistant's current guidelines. The data is typed per entry and cleaned up automatically when the entry is unloaded.

- **No action required.** Entities, unique IDs, options and services are unchanged.
- **Fixed:** the integration services (`pump_on`, `pump_off`, `start_boost`, `cancel_boost`, `set_filtration_mode`, `refresh_data`) are now removed when the last entry is deleted. On Home Assistant 2025.2 and older they could stay registered after the integration was removed.
- **Fixed:** `aiohttp` is no longer listed as a requirement (it is already provided by Home Assistant), which made the hassfest validation fail.

**Note:** Home Assistant **2024.9** or later required. The minimum was raised from 2024.6 because the integration now uses `async_loaded_entries`, available since 2024.9. If you are on 2024.6 to 2024.8, update Home Assistant first: HACS will not offer this update otherwise.

---

**Maintenance : les coordinateurs sont désormais stockés dans l'entrée de configuration**

Cette version est un refactor interne : rien ne change dans l'utilisation de l'intégration. Les coordinateurs sont maintenant stockés dans l'entrée de configuration elle-même (`entry.runtime_data`) plutôt que dans un dictionnaire partagé, conformément aux recommandations actuelles de Home Assistant. Les données sont typées par entrée et nettoyées automatiquement au déchargement.

- **Aucune action requise.** Entités, identifiants uniques, options et services sont inchangés.
- **Corrigé :** les services de l'intégration (`pump_on`, `pump_off`, `start_boost`, `cancel_boost`, `set_filtration_mode`, `refresh_data`) sont désormais retirés quand la dernière entrée est supprimée. Sur Home Assistant 2025.2 et antérieur, ils pouvaient rester enregistrés après la suppression de l'intégration.
- **Corrigé :** `aiohttp` n'est plus déclaré comme dépendance (il est déjà fourni par Home Assistant), ce qui faisait échouer la validation hassfest.

**À noter :** Home Assistant **2024.9** minimum requis. Le minimum passe de 2024.6 à 2024.9 car l'intégration utilise `async_loaded_entries`, disponible depuis 2024.9. Si vous êtes en 2024.6 à 2024.8, mettez à jour Home Assistant d'abord : sinon HACS ne proposera pas cette mise à jour.
