**Correction des plages de filtration (next_start / next_end / durée journalière)**

Les capteurs `filtration_next_start`, `filtration_next_end` et `filtration_daily_duration` affichent maintenant les bonnes valeurs, stables toute la journée, et cohérentes avec l'application mobile Waterair.

**Cause du bug :** les versions précédentes déduisaient le seuil de filtration depuis la température ambiante lue par le capteur BPC (`temperature` racine de la réponse status) — valeur qui fluctue avec la chaleur et provoquait des oscillations entre plusieurs plages (ex. 21h00 / 22h00).

**Correction :** utilisation du champ `tempRef` de la voie pompe, qui contient l'index de seuil committé par le BPC **une seule fois au démarrage du cycle matinal**. Cet index (ex. 6 → seuil 27°C → 9h–19h) reste stable toute la journée, indépendamment des variations de température.

**Ce qui change :**
- Les trois capteurs de filtration utilisent désormais directement l'index BPC (`bpc_temp_ref_idx` dans les attributs de `filtration_daily_duration`) plutôt qu'une comparaison de température
- L'attribut de diagnostic `bpc_temp_reference_c` (température air incorrecte) est remplacé par `bpc_temp_ref_idx` (index direct, ex. `6`)
- Fallback sur la température eau AC1 uniquement si `tempRef` est absent (démarrage à froid)
