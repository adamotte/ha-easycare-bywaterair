**Fix: WATBOX/BPC hardware not recognized at startup (issue #10)**

On some devices (hardware variants whose type identifier differs), the integration refused to start with the error "BPC ou WATBOX absent de la liste des modules".

- **More robust detection**: if the type returned by the API is unknown, the module is now recognized by its name (WATBOX, BPC, AC1, LR-PR). No more need to patch the code for new hardware.
- **Clearer logs**: when hardware is not recognized, the available modules (name + type) are now written to the logs, making it easier to report the problem.
- **Extra safeguard**: a warning is emitted if the expected pump channel is missing from a BPC, instead of failing silently.

No action is required on your part after updating.

**Note:** Home Assistant **2024.6** or later required.

---

**Correction : matériel WATBOX/BPC non reconnu au démarrage (issue #10)**

Sur certains équipements (variantes matérielles dont l'identifiant de type diffère), l'intégration refusait de démarrer avec l'erreur « BPC ou WATBOX absent de la liste des modules ».

- **Détection plus robuste** : si le type renvoyé par l'API est inconnu, le module est désormais reconnu d'après son nom (WATBOX, BPC, AC1, LR-PR). Plus besoin de modifier le code pour un nouveau matériel.
- **Journaux plus parlants** : en cas de matériel non reconnu, les modules disponibles (nom + type) sont désormais écrits dans les logs, ce qui permet de signaler le problème plus facilement.
- **Garde-fou supplémentaire** : un avertissement est émis si la voie pompe attendue est absente d'un BPC, au lieu d'échouer en silence.

Aucune action n'est requise de votre part après la mise à jour.

**À noter :** Home Assistant **2024.6** minimum requis.
