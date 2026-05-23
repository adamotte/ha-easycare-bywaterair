# Easy-care by Waterair — Intégration Home Assistant

Intégration Home Assistant moderne pour les piscines équipées de l'écosystème
**Easy-care by Waterair** (WATBOX + BPC + AC1).

> ⚠️ **Cette intégration n'est pas officielle.** Elle est développée de manière
> indépendante par reverse-engineering de l'application Android officielle.
> Waterair n'est pas affilié à ce projet.

## ✨ Fonctionnalités

### Lecture des données
- 🌡️ Température de l'eau, pH, chlore (redox/ORP)
- 🔋 Niveau de batterie de l'analyseur AC1
- 📊 Pression de filtration (si capteur LR-PR présent)
- 🔔 Notifications et traitements en cours
- ⚙️ Mode de filtration actuel et compteurs de la pompe

### Pilotage
- 💡 **Lumières** : projecteur (spot) et éclairage des marches (escalight)
- 💧 **Pompe de filtration** : marche/arrêt
- 🔄 **Mode de filtration** : AUTO / Marche forcée / Arrêt / Programmation
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
| `easycare_bywaterair.set_filtration_mode` | Change le mode | `mode` (AUTO/CONTINUOUS/MANUAL/PROG) |
| `easycare_bywaterair.start_boost` | Lance un boost | `duration` (BOOST4H/BOOST12H/BOOST24H/BOOST36H/BOOST48H/BOOST72H) |
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
- **Programmation horaire** (mode PROG) : lecture/écriture des plages horaires
  pas encore exposée — l'utilisateur configure via l'app mobile.
- **Mode de filtration illisible pompe à l'arrêt** — lorsque la pompe est
  éteinte et qu'aucun boost n'est actif, le mode (AUTO/PROG/CONTINUOUS) ne
  peut pas être déterminé depuis l'API ; l'entité select affiche "Inconnu"
  jusqu'à la prochaine mise en marche.

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
