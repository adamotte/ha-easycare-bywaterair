# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant custom integration for Waterair pool systems (Easy-care ecosystem: WATBOX + BPC + AC1 + LR-PR), developed by reverse-engineering the official Android APK. Not affiliated with Waterair.

The integration lives entirely in `easycare_bywaterair/custom_components/easycare_bywaterair/`. There is no build system — development consists of copying this folder into a HA instance's `custom_components/` directory.

## Development setup

**Running locally in HA:**
```
cp -r easycare_bywaterair/custom_components/easycare_bywaterair /config/custom_components/
# restart Home Assistant
```

**Enable debug logs in HA `configuration.yaml`:**
```yaml
logger:
  default: warning
  logs:
    custom_components.easycare_bywaterair: debug
```

There are no automated tests or linters configured. HA integration validation can be run with `hassfest` from the `homeassistant` dev environment.

## Architecture

### Single API backend

All constants (hosts, paths, credentials) are in `const.py`.

- **`https://easycare.waterair.com`** — sole Waterair backend: user/pool data, module list, BPC control (pump/lights), filtration mode, boost commands.

The Solem backend (`apiwf.solem.fr`) was removed after analysis confirmed all filtration state is readable from the BPC status endpoint (`/api/module/{watbox}/status/{bpc}`) via the `pool` array items.

### Authentication chain (two-step)

OAuth2 Azure B2C → EasyCare bearer. Both tokens are stored in `ConfigEntry.data` with their expiry timestamps and refreshed proactively before each API call (`auth.py`).

Critical detail: **the Azure refresh_token rotates on every use** — the new value must be persisted back to ConfigEntry immediately via the callback passed to `EasyCareAuth`. If the refresh_token is ever lost, the user must re-authenticate via the config flow.

The PKCE code_verifier/challenge and the OAuth client ID are fixed values extracted from the APK. The redirect URI (`msauth.com.waterair.easycare://auth`) is the mobile app's scheme, so the user must manually copy the auth code from the failed redirect URL.

### Three coordinators with different cadences

`coordinator.py` defines three `DataUpdateCoordinator` subclasses:

| Coordinator | Interval | Data |
|---|---|---|
| `EasyCareUserCoordinator` | 30 min | pH, chlorine, temperature, alerts, treatment, owner |
| `EasyCareModulesCoordinator` | 24 h | Module list (WATBOX, BPC, AC1, LR-PR) |
| `EasyCareBPCCoordinator` | 1 min / 10 min (idle) | BPC pool inputs (pump/lights), derived filtration state |

The BPC coordinator has adaptive polling: when no BPC input is active, it skips real API calls and returns cached data, only forcing a live call every `SCAN_INTERVAL_BPC_IDLE_FACTOR` (10) cycles. This reduces load when the pump and lights are all off.

### Entity/device hierarchy

HA Device Registry structure:
```
WATBOX (passerelle)
├── BPC (via_device=WATBOX) — pump switch, light entities, filtration select, boost buttons
├── AC1 (via_device=WATBOX) — pH, chlorine, temperature, battery, treatment sensors
└── LR-PR (via_device=WATBOX) — pressure sensor (only if module present)
```

Entities are only created if the corresponding module is present in the modules coordinator response. BPC light entities additionally require `numberOfInputs >= 1` (spot) or `>= 2` (escalight).

### BPC manual commands require two API calls

Sending a pump/light command (`switch.py`, `light.py`) always calls:
1. `POST /api/module/{watbox}/manual/{bpc}` with `{"pool": {"index": N, "action": 2, "manualDuration": D}}` — send the command
2. `POST /api/reportManualCommandSent` with `{"id": bpc.id, "command": {"pool": {"index": N, "action": 2, "manualDuration": D}}, "route": "http"}` — confirm the command (mandatory second step)

Missing step 2 leaves the command un-acknowledged on the server side.

### Filtration mode / boost commands — confirmed payload structure (APK)

`POST /api/setStatusCommandToSend` requires this exact envelope (confirmed from Solem SDK source,
`Networking.java` + `NetworkingModule.java`):

```json
{"id": "<bpc_ijc_id>", "command": {"mode": "AUTO"}, "wakeUp": false}
```

- `"id"` = `bpc.id` = `Module.id` = champ `"id"` (sans underscore) de la réponse API module = `ManufacturerData.mIDIJC` côté Solem SDK
- `"command"` = objet JSON passé au SDK ; `"mode"` = chaîne (AUTO/CONTINUOUS/MANUAL/PROG/BOOST12H/etc.)
- `"wakeUp"` = false pour le BPC WiFi (pas de réveil SMS)

`bpc.id` est mis en cache dans `EasyCareClient._bpc_module_id` après le premier `get_bpc_status()`.

### BPC input indices (from APK analysis)

- Index 0 → pump (filtration)
- Index 1 → spot (main light)
- Index 2 → escalight (stair lights)

### Data models

All API responses are parsed into frozen dataclasses (`models.py`). Parsing helpers `_require()` and `_parse_timestamp()` enforce mandatory fields and handle both Unix epoch and ISO 8601 timestamps. Parsing failures raise `EasyCareInvalidResponseError`.

### Exception hierarchy

`exceptions.py` defines a hierarchy under `EasyCareError`. Coordinators map these to HA standard exceptions:
- `EasyCareTokenExpiredError` / `EasyCareUnauthorizedError` → `ConfigEntryAuthFailed` (triggers reauth UI)
- All other errors → `UpdateFailed` (HA retries later)

## Key files

| File | Purpose |
|---|---|
| `const.py` | All constants: API hosts/paths, OAuth credentials, polling intervals, module types, BPC indices |
| `api/auth.py` | Token lifecycle: proactive refresh, rotation, concurrency lock |
| `api/client.py` | All HTTP calls, retry logic, response parsing dispatch |
| `api/models.py` | Frozen dataclasses for all API responses |
| `coordinator.py` | Three coordinators including adaptive BPC polling logic |
| `config_flow.py` | OAuth2 setup (user step + reauth flow) |
| `__init__.py` | Integration setup, device registry, service registration |
