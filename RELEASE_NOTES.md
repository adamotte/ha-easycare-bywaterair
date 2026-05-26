**Correction : ré-authentification automatique quand la session Azure expire**

Quand le token Azure B2C arrivait en fin de vie, l'intégration échouait silencieusement sans jamais demander de ré-authentification. HA affichait des entités indisponibles sans notification, et la seule solution était de supprimer/recréer l'intégration manuellement.

**Ce qui était cassé :** Azure B2C répond parfois avec une page HTML au lieu d'un JSON d'erreur quand la session expire. L'intégration ne reconnaissait pas ce cas et restait bloquée en erreur silencieuse.

**Ce qui est corrigé :** l'intégration détecte maintenant cette réponse HTML et déclenche correctement le flux de ré-authentification HA — une notification apparaît pour demander un nouveau code.
