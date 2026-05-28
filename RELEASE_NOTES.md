**Correction : plages de filtration décalées par rapport à l'app mobile**

Les capteurs `filtration_next_start`, `filtration_next_end` et `filtration_daily_duration` affichaient des plages horaires incorrectes (ex. 10h–16h au lieu de 9h–19h).

**Cause :** l'algorithme de sélection du seuil de température utilisait un plancher (le seuil le plus bas ≤ température actuelle), alors que le BPC utilise un plafond (le seuil le plus bas ≥ température **maximale de la veille**, champ `maxTemperatureTheDayBefore`).

**Correction :**
- Algorithme mis à jour pour utiliser la logique plafond, conforme au reverse engineering de l'app mobile (méthode `getTemperatureThresholdIndexFrom`).
- Le champ `maxTemperatureTheDayBefore` est désormais lu depuis la réponse de l'API BPC et exposé en attribut du capteur `filtration_daily_duration` (`max_temp_yesterday_c`).
- En l'absence de ce champ dans la réponse API, la température courante de l'eau est utilisée comme fallback.
