## ⚠️ Changement important — mise à jour des automations requise

Cette version renomme les valeurs d'état des entités `select` et `sensor` pour se conformer aux exigences de hassfest (validation officielle Home Assistant). Les nouvelles valeurs sont en minuscules et sans caractères spéciaux.

**Si vous avez des automations qui comparent ces valeurs, mettez-les à jour :**

| Ancienne valeur | Nouvelle valeur |
|---|---|
| `AUTO-2H` | `auto_minus_2h` |
| `AUTO` | `auto` |
| `AUTO+2H` | `auto_plus_2h` |
| `CONTINUOUS` | `continuous` |
| `MANUAL` | `manual` |
| `BOOST4H` | `boost_4h` |
| `BOOST12H` | `boost_12h` |
| `BOOST24H` | `boost_24h` |
| `BOOST36H` | `boost_36h` |
| `BOOST48H` | `boost_48h` |
| `BOOST72H` | `boost_72h` |
| `ACTIVE` | `active` |

---

## Autres changements

- **Manifest corrigé** : ordre des clés conforme à la spécification HA
- **CI ajoutée** : workflows GitHub Actions pour la validation HACS et hassfest, exécutés à chaque push
