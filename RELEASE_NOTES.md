**Les lumières et les modes de filtration ne rebasculent plus après une commande** *(#3)*

Après avoir allumé/éteint une lumière ou changé le mode de filtration, l'interface revenait à l'ancien état une seconde plus tard. La commande était bien envoyée, mais le rafraîchissement immédiat renvoyait encore l'ancien état avant que le boîtier ait eu le temps de traiter la commande. L'interface reflète maintenant le changement immédiatement et se stabilise à la prochaine mise à jour.

**Réduction drastique des appels aux serveurs Microsoft** *(#2)*

L'intégration contactait Azure B2C toutes les ~50 minutes pour renouveler les tokens, même quand la session Waterair était encore valide. Si votre session dure plusieurs semaines (comportement observé pouvant aller jusqu'à 2 mois), plus aucun appel inutile — ce qui élimine une source fréquente d'erreurs de connexion.

**Capteur de pression — valeur calibrée** *(#5)*

La valeur affichée est maintenant la différence entre la mesure brute et la pression statique de référence enregistrée lors de l'étalonnage du capteur LR-PR.

**Nouveaux attributs** *(#1, #4)*

- `volume_m3` et `last_update` sur le capteur de détail piscine (WATBOX)
- `custom_photo` — URL de la photo personnalisée configurée dans l'app Waterair
- `last_update` sur les entités lumières (utile quand le polling passe en mode ralenti)
