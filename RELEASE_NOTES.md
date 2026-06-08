**Fix: unrecognised hardware no longer breaks the integration (issue #10)**

This release makes the integration robust to WATBOX/BPC hardware variants and improves diagnostics for unsupported devices.

- **No more startup failure** on an unexpected module type: WATBOX gateways and BPC controllers are now recognised across their whole hardware family (Compact, 4G, React, Autonomous, Outdoor… for WATBOX; v2, VS, VS2… for BPC).
- **Equipment type shown in the device page** (Settings → Devices), under the serial number, to make troubleshooting easier without digging through logs.
- **Logs are now in English** so they're easier to read and report.
- **Partial support for the BPC2 (`lr-ph`) controller**: its sensors work, but because its internal channel layout isn't verified yet, a warning is shown in **Settings → Repairs**. If the expected pump channel is missing, the pump/boost/lighting/filtration commands are automatically disabled to avoid sending incorrect commands — read-only sensors stay available. Full BPC2 support will come in a later release.

If you have an unrecognised device, please report its type (now visible on the device page) on the issue tracker.

No action is required on your part after updating.

**Note:** Home Assistant **2024.6** or later required.

---

**Correction : un matériel non reconnu ne casse plus l'intégration (issue #10)**

Cette version rend l'intégration robuste aux variantes matérielles WATBOX/BPC et améliore le diagnostic des appareils non pris en charge.

- **Plus d'échec au démarrage** sur un type de module inattendu : les passerelles WATBOX et les contrôleurs BPC sont désormais reconnus sur toute leur famille matérielle (Compact, 4G, React, Autonome, Outdoor… pour la WATBOX ; v2, VS, VS2… pour le BPC).
- **Type d'équipement affiché dans la fiche de l'appareil** (Paramètres → Appareils), sous le numéro de série, pour faciliter le diagnostic sans fouiller les logs.
- **Les logs sont maintenant en anglais**, plus faciles à lire et à nous remonter.
- **Prise en charge partielle du contrôleur BPC2 (`lr-ph`)** : ses capteurs fonctionnent, mais comme l'agencement interne de ses voies n'est pas encore vérifié, un avertissement s'affiche dans **Paramètres → Réparations**. Si la voie pompe attendue est absente, les commandes pompe/boost/éclairage/filtration sont automatiquement désactivées pour éviter d'envoyer des commandes erronées — les capteurs en lecture seule restent disponibles. La prise en charge complète du BPC2 viendra dans une version ultérieure.

Si vous avez un appareil non reconnu, merci de signaler son type (désormais visible dans la fiche de l'appareil) sur le suivi des tickets.

Aucune action n'est requise de votre part après la mise à jour.

**À noter :** Home Assistant **2024.6** minimum requis.
