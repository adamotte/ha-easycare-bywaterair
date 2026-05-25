# Easy-care by Waterair — Intégration Home Assistant

Intégration Home Assistant pour les piscines équipées de l'écosystème
**Easy-care by Waterair** (WATBOX + BPC + AC1).

> ⚠️ **Cette intégration n'est pas officielle.** Elle est développée de manière
> indépendante. Waterair n'est pas affilié à ce projet.

## ✨ Fonctionnalités

### Lecture des données
- 🌡️ Température de l'eau, pH, chlore (redox/ORP)
- 🔋 Niveau de batterie de l'analyseur AC1
- 📊 Pression de filtration (si capteur LR-PR présent)
- 🔔 Notifications et traitements en cours
- ⚙️ Mode de filtration actuel et compteurs de la pompe
- 💡 **Mode des lumières** : AUTO / MANUEL / ETEINT / PAUSE (avec plages horaires et durée de pause en attributs)

### Pilotage
- 💡 **Lumières** : projecteur (spot) et éclairage des marches (escalight) — allumage MANUEL (1h à 6h max)
- 🔄 **Mode de filtration** : AUTO (-2h / standard / +2h) / Marche forcée / Arrêt (pilote la pompe)
- ⚡ **Boost** : 4h / 12h / 24h / 36h / 48h / 72h / annulation

### Avantages techniques
- 🔐 **Refresh token automatique** — plus besoin de re-saisir le token tous les 2 mois
- 🏛️ **Architecture HA standard** : ConfigEntry, DataUpdateCoordinator, Device Registry
- 📱 **Configuration via l'UI** (pas de YAML)
- 🌐 **Multi-langues** (français, anglais)
- 🧩 **6 services HA** appelables depuis automations
- 🏠 **Appareils correctement modélisés** : WATBOX → BPC, AC1, LR-PR

## 📦 Installation

### Via HACS (recommandé)
1. Dans HACS → Intégrations → menu (⋮) → Dépôts personnalisés
2. Ajouter l'URL de ce dépôt comme type "Integration"
3. Installer "Easy-care by Waterair"
4. Redémarrer Home Assistant

### Manuelle
Copier le dossier `custom_components/easycare_bywaterair` dans le dossier
`custom_components` de votre installation HA, puis redémarrer.

## 🔧 Configuration

1. **Paramètres → Appareils & Services → Ajouter une intégration**
2. Rechercher "Easy-care by Waterair"
3. Cliquer sur le lien d'autorisation affiché
4. Se connecter avec son compte Waterair
5. Le navigateur affichera une erreur (redirection `msauth://`) — c'est normal
6. **Copier l'URL complète** de la barre d'adresse (ou juste la valeur après `code=`)
7. La coller dans HA et valider

L'intégration s'occupe ensuite du renouvellement automatique des tokens.

## 🎛️ Services exposés

| Service | Description | Paramètres |
|---|---|---|
| `easycare_bywaterair.pump_on` | Démarre la pompe | `duration_minutes` (1-1440, défaut 60) |
| `easycare_bywaterair.pump_off` | Arrête la pompe | — |
| `easycare_bywaterair.set_filtration_mode` | Change le mode | `mode` (AUTO / CONTINUOUS / MANUAL) |
| `easycare_bywaterair.start_boost` | Lance un boost | `duration` (BOOST4H / BOOST12H / BOOST24H / BOOST36H / BOOST48H / BOOST72H) |
| `easycare_bywaterair.cancel_boost` | Annule le boost | — |
| `easycare_bywaterair.refresh_data` | Force un refresh | — |

## 📋 Exemple d'automation

```yaml
# Lancer un boost de 12h chaque dimanche matin
automation:
  - alias: "Piscine — Boost dominical"
    trigger:
      - platform: time
        at: "09:00:00"
    condition:
      - condition: time
        weekday: [sun]
    action:
      - service: easycare_bywaterair.start_boost
        data:
          duration: BOOST12H

# Alerte chlore bas
  - alias: "Piscine — Alerte chlore bas"
    trigger:
      - platform: numeric_state
        entity_id: sensor.easycare_bywaterair_chlorine
        below: 600  # mV
    action:
      - service: notify.notify
        data:
          message: "Chlore bas : {{ states('sensor.easycare_bywaterair_chlorine') }} mV"
```

## ⚠️ Limitations connues

- **Mode BOOST avec durée personnalisée** non supporté — les durées disponibles
  sont 4h, 12h, 24h, 36h, 48h et 72h.
- **Mode PROG de la pompe (programmation horaire)** : détecté en lecture (capteur
  `filtration_mode`), mais pas proposé comme option dans le sélecteur.
  La configuration des plages horaires reste dans l'app mobile.
- **Modes AUTO et PAUSE des lumières** : visibles en lecture (capteurs `spot_mode`
  et `escalight_mode`) mais non modifiables depuis HA. La configuration des plages
  horaires (AUTO) et la durée de suspension (PAUSE, 1–15 jours) restent dans
  l'app mobile. Seul le mode MANUEL (allumage forcé 1h–6h) est pilotable via
  `light.turn_on`.

## 🐛 Debug

Pour activer les logs détaillés :

```yaml
logger:
  default: warning
  logs:
    custom_components.easycare_bywaterair: debug
```

## 📄 Licence

MIT
