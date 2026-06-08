**Diagnostic logging to prepare full BPC2 support (issue #11)**

A small, behaviour-neutral release that adds diagnostic logging to help bring full support for the BPC2 (`lr-ph`) controller.

- **The BPC's output channels are now logged at startup** (pump, lighting…), along with the module's raw fields. For standard BPC controllers this stays at *debug* level (no noise); for unverified variants such as the BPC2 it is logged at *info* level, so the real channel layout can be reported.
- **Nothing changes in how the integration behaves**: no command is sent and nothing is modified — this purely captures the data needed to safely enable BPC2 controls (pump, boost, lighting, pH) in a future release.

If you own a **BPC2 (`lr-ph`)** device, enabling debug logging and sharing the “BPC diagnostic” line on the issue tracker will directly help add full support.

No action is required on your part after updating.

**Note:** Home Assistant **2024.6** or later required.

---

**Journalisation de diagnostic pour préparer la prise en charge complète du BPC2 (issue #11)**

Une petite version sans changement de comportement, qui ajoute de la journalisation de diagnostic pour aider à finaliser la prise en charge du contrôleur BPC2 (`lr-ph`).

- **Les voies de sortie du BPC sont désormais journalisées au démarrage** (pompe, éclairage…), avec les champs bruts du module. Pour les BPC standard, cela reste au niveau *debug* (aucun bruit) ; pour les variantes non vérifiées comme le BPC2, c'est journalisé au niveau *info*, afin que l'agencement réel des voies puisse être remonté.
- **Rien ne change dans le fonctionnement de l'intégration** : aucune commande n'est envoyée et rien n'est modifié — il s'agit uniquement de capturer les données nécessaires pour activer en toute sécurité les commandes du BPC2 (pompe, boost, éclairage, pH) dans une version ultérieure.

Si vous possédez un appareil **BPC2 (`lr-ph`)**, activer la journalisation debug et partager la ligne « BPC diagnostic » sur le suivi des tickets aidera directement à ajouter la prise en charge complète.

Aucune action n'est requise de votre part après la mise à jour.

**À noter :** Home Assistant **2024.6** minimum requis.
