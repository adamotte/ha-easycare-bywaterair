**Correction : attribut `last_update` sur le sensor de détail piscine**

L'attribut `last_update` reflète maintenant l'horodatage exact du dernier appel réussi de HA vers l'API Waterair (toutes les 30 minutes), et non plus les dates de mesure des capteurs.

Cela permet de vérifier que HA récupère bien les données régulièrement, même quand les valeurs des capteurs n'ont pas changé — ce qui est fréquent avec Waterair qui ne pousse de nouvelles mesures que sur changement pour préserver les piles LoRa.
