**Fix: setups without a BPC controller now start correctly (issue #12)**

A bug-fix release for pools that have a WATBOX and an AC1 water analyser **but no BPC** pump controller.

- **The integration now starts normally on BPC-less installations.** Previously, setup failed in a loop with a "BPC or WATBOX not found" error and no entities were created.
- Your **water measurements (pH, chlorine, temperature) and the AC1 battery** are created as usual. No pump, filtration or lighting entities are added, since those require a BPC — this is expected on such a setup.
- **Nothing changes for installations that do include a BPC.**

No action is required on your part after updating.

**Note:** Home Assistant **2024.6** or later required.

---

**Correctif : les installations sans contrôleur BPC démarrent désormais correctement (issue #12)**

Une version corrective pour les piscines équipées d'un WATBOX et d'un analyseur d'eau AC1 **mais sans** contrôleur de pompe BPC.

- **L'intégration démarre désormais normalement sur les installations sans BPC.** Auparavant, le démarrage échouait en boucle avec une erreur « BPC or WATBOX not found » et aucune entité n'était créée.
- Vos **mesures d'eau (pH, chlore, température) et la batterie de l'AC1** sont créées comme d'habitude. Aucune entité de pompe, de filtration ou d'éclairage n'est ajoutée, car elles nécessitent un BPC — c'est le comportement attendu sur ce type d'installation.
- **Rien ne change pour les installations qui comportent un BPC.**

Aucune action n'est requise de votre part après la mise à jour.

**À noter :** Home Assistant **2024.6** minimum requis.
