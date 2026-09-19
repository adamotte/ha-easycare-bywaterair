**Fix: compatibility with the latest Home Assistant versions**

This release removes the use of `via_device`, a device registry parameter that Home Assistant deprecates and will **stop supporting in 2027.8**. Since the recent HA updates it triggered warnings on startup:

> Detected that custom integration 'easycare_bywaterair' calls `device_registry.async_get_or_create` with a deprecated `via_device` parameter…

- The device hierarchy is unchanged: BPC, AC1 and LR-PR stay linked under the WATBOX gateway.
- No action is required after updating — behaviour is exactly the same, without the warning.

**Note:** Home Assistant **2024.6** or later required.

---

**Correctif : compatibilité avec les dernières versions de Home Assistant**

Cette version supprime l'utilisation de `via_device`, un paramètre du device registry que Home Assistant déprécie et **retirera en 2027.8**. Depuis les dernières mises à jour de HA, il générait des avertissements au démarrage :

> Detected that custom integration 'easycare_bywaterair' calls `device_registry.async_get_or_create` with a deprecated `via_device` parameter…

- La hiérarchie des appareils est inchangée : BPC, AC1 et LR-PR restent rattachés à la passerelle WATBOX.
- Aucune action requise après la mise à jour — comportement identique, sans l'avertissement.

**À noter :** Home Assistant **2024.6** minimum requis.