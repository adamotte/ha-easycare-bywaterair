**Correction : plages de filtration incorrectes — suite (source de température)**

La v1.0.4 corrigeait l'algorithme de sélection du seuil (plafond au lieu de plancher), mais utilisait la mauvaise température de référence car le champ `maxTemperatureTheDayBefore` est absent de l'API.

**Correction v1.0.5 :**  
Le champ `temperature` de la réponse status BPC (ex. `27`) est utilisé comme référence. Il correspond au seuil (en °C) que le BPC a committé au démarrage du cycle journalier. Avec ce champ, l'algorithme plafond donne le bon résultat (ex. 27°C → seuil 27°C → 9h–19h).

Le capteur `filtration_daily_duration` expose désormais l'attribut `bpc_temp_reference_c` pour faciliter le débogage.
