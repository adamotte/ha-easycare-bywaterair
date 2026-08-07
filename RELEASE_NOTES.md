**New: electrolyzer switch with configurable duration (issue #13)**

The second auxiliary channel of your BPC is often used to drive an electrolyzer (salt chlorine generator). Until now the integration treated it as "step lighting". This release lets you declare the channel's real equipment type in **Configure** → integration options, and adds a manual control for the electrolyzer.

- **Channel type option**: in the integration options, choose **Step lighting** (default, unchanged), **Electrolyzer** or **Disabled** for the second channel.
- **Electrolyzer switch**: a manual override to run chlorine production. When enabled, the BPC turns the channel on for the configured duration.
- **Configurable duration**: a new number entity `electrolyzer_duration` (1–6 h, step 1 h) sets how long the electrolyzer runs when turned on. The value is kept across restarts.
- **As usual, chlorine production stays automatic** by default (the BPC manages it from your AC1 readings). The switch is only a manual override.
- **Note:** a "treatment" channel only works while filtration is running — that dependency is handled by the BPC itself, not the integration.

No action is required on your part after updating. If you don't change anything, your setup behaves exactly as before.

**Note:** Home Assistant **2024.6** or later required.

---

**Nouveau : interrupteur électrolyseur avec durée configurable (issue #13)**

La deuxième voie auxiliaire du BPC sert souvent à piloter un électrolyseur (générateur de chlore au sel). Jusqu'ici, l'intégration la traitait comme un « éclairage de marches ». Cette version permet de déclarer le vrai type d'équipement de la voie dans **Configurer** → options de l'intégration, et ajoute une commande manuelle pour l'électrolyseur.

- **Option de type de voie** : dans les options de l'intégration, choisissez **Éclairage des marches** (défaut, inchangé), **Électrolyseur** ou **Désactivée** pour la deuxième voie.
- **Interrupteur électrolyseur** : un override manuel pour lancer la production de chlore. Une fois activé, le BPC allume la voie pendant la durée configurée.
- **Durée configurable** : une nouvelle entité number `electrolyzer_duration` (1–6 h, pas de 1 h) règle la durée de fonctionnement de l'électrolyseur à l'allumage. La valeur est conservée après redémarrage.
- **La production de chlore reste automatique par défaut** (le BPC la gère à partir des relevés de votre AC1). L'interrupteur n'est qu'un override manuel.
- **À noter :** une voie « traitement » ne fonctionne que lorsque la filtration tourne — cette dépendance est gérée par le BPC lui-même, pas par l'intégration.

Aucune action n'est requise de votre part après la mise à jour. Si vous ne changez rien, votre installation se comporte exactement comme avant.

**À noter :** Home Assistant **2024.6** minimum requis.
