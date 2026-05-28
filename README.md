# easy·care by Waterair — Home Assistant Integration

[![Release](https://img.shields.io/github/v/release/adamotte/ha-easycare-bywaterair?style=flat-square)](https://github.com/adamotte/ha-easycare-bywaterair/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=flat-square)](https://hacs.xyz)
[![License](https://img.shields.io/github/license/adamotte/ha-easycare-bywaterair?style=flat-square)](LICENSE)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-%3E%3D2024.1-blue?style=flat-square&logo=home-assistant)](https://www.home-assistant.io)
[![Validate](https://github.com/adamotte/ha-easycare-bywaterair/actions/workflows/validate.yml/badge.svg)](https://github.com/adamotte/ha-easycare-bywaterair/actions/workflows/validate.yml)
[![hassfest](https://github.com/adamotte/ha-easycare-bywaterair/actions/workflows/hassfest.yml/badge.svg)](https://github.com/adamotte/ha-easycare-bywaterair/actions/workflows/hassfest.yml)
[![Last commit](https://img.shields.io/github/last-commit/adamotte/ha-easycare-bywaterair/main?style=flat-square)](https://github.com/adamotte/ha-easycare-bywaterair/commits/main)
[![Issues](https://img.shields.io/github/issues/adamotte/ha-easycare-bywaterair?style=flat-square)](https://github.com/adamotte/ha-easycare-bywaterair/issues)
[![Stars](https://img.shields.io/github/stars/adamotte/ha-easycare-bywaterair?style=flat-square)](https://github.com/adamotte/ha-easycare-bywaterair/stargazers)
[![Donate](https://img.shields.io/badge/Donate-PayPal-blue?logo=paypal&style=flat-square)](https://paypal.me/AnthonyDAMOTTE)

---

Enjoying this integration? A donation helps keep it going!

[![Donate](https://www.paypalobjects.com/en_US/i/btn/btn_donate_LG.gif)](https://paypal.me/AnthonyDAMOTTE)

---

Home Assistant integration for pools equipped with the
**easy·care by Waterair** ecosystem (WATBOX + BPC + AC1).

> ⚠️ **This integration is unofficial.** It is independently developed.
> Waterair is not affiliated with this project.

## ✨ Features

### Data reading
- 🌡️ Water temperature, pH, chlorine (redox/ORP)
- 🔋 AC1 analyser battery level
- 📊 Filtration pressure (if LR-PR sensor is present)
- 🔔 **Pool action notifications** — translated alerts (calibration required, wintering, chlorine treatment…) with automatic HA persistent notification on new event
- ⚙️ Current filtration mode and pump counters
- ⚡ **Energy monitoring**: pump power (W) and cumulative energy (kWh) — compatible with the HA Energy Dashboard
- 💡 **Light mode**: AUTO / MANUAL / OFF / PAUSE (with time slots and pause duration as attributes)
- 🕐 **Filtration schedule** — daily duration, next start and next stop derived from the BPC programme (temperature-aware)
- 🔄 **Software update notifications** — detects available firmware updates for BPC and AC1, exposed as native HA update entities (visible in Settings → Updates)

### Control
- 💡 **Lights**: spotlight (spot) and step lighting (escalight) — MANUAL on (1h to 6h max)
- 🔄 **Filtration mode**: AUTO (-2h / standard / +2h) / Continuous / Off (controls the pump)
- ⚡ **Boost**: 4h / 12h / 24h / 36h / 48h / 72h / cancel

### Technical highlights
- 🔐 **Automatic token refresh** — no more manual re-entry every 2 months
- 🏛️ **Standard HA architecture**: ConfigEntry, DataUpdateCoordinator, Device Registry
- 📱 **UI-based configuration** (no YAML)
- 🌐 **Multi-language** (French, English)
- 🧩 **6 HA services** callable from automations
- 🔔 **Native update notifications** — HA badge when BPC or AC1 has a software update available
- 🏠 **Properly modelled devices**: WATBOX → BPC, AC1, LR-PR

## 📦 Installation

### Via HACS (recommended)
1. In HACS → Integrations → menu (⋮) → Custom repositories
2. Add this repository URL as type "Integration"
3. Install "easy·care by Waterair"
4. Restart Home Assistant

### Manual
Copy the `custom_components/easycare_bywaterair` folder into the `custom_components`
directory of your HA installation, then restart.

## 🔧 Configuration

1. **Settings → Devices & Services → Add Integration**
2. Search for "easy·care by Waterair"
3. Click the authorization link displayed
4. Log in with your Waterair account
5. The browser will show an error (`msauth://` redirect) — this is normal
6. **Copy the full URL** from the address bar (or just the value after `code=`)
7. Paste it into HA and confirm

The integration then handles automatic token renewal.

## 🕐 Filtration schedule sensors

Three sensors expose the BPC programme schedule, calculated in real time from the water temperature:

| Sensor | Type | Description |
|---|---|---|
| `sensor.filtration_daily_duration` | Hours | Total filtration hours programmed for today |
| `sensor.filtration_next_start` | Timestamp | Next scheduled pump start |
| `sensor.filtration_next_end` | Timestamp | Next scheduled pump stop (end of current or next window) |

The BPC programme stores a 24-bit bitmask per temperature threshold. The integration selects the highest threshold below the current water temperature and reads the corresponding schedule directly — no guesswork.

**Semantics of `next_start` / `next_end`:**
- **Pump currently running**: `next_end` = end of the current window, `next_start` = beginning of the next window (tomorrow's first window if none remain today)
- **Pump currently stopped**: `next_start` / `next_end` = start and end of the next upcoming window (tomorrow's first window if all windows have passed)

Multiple non-contiguous windows per day are supported (e.g. anti-freeze mode: 05h–07h and 22h–24h).

The `filtration_daily_duration` sensor also exposes the following attributes:
- `thresholds_c` — full list of configured temperature thresholds
- `active_threshold_temp_c` — threshold currently active for the water temperature
- `filter_windows` — list of `{start_h, end_h}` time windows

## ⚡ Energy monitoring

To track pump energy consumption in the [HA Energy Dashboard](https://www.home-assistant.io/docs/energy/):

1. Go to **Settings → Devices & Services → easy·care by Waterair → Configure**
2. Enter the **rated power of your pump in watts** (e.g. `150` for a P35)
3. Confirm — the integration reloads and two new sensors appear on the BPC device:
   - **Pump power** (`sensor.*_pump_power`) — instantaneous consumption in W (rated power when running, 0 when stopped)
   - **Pump energy** (`sensor.*_pump_energy`) — cumulative energy in kWh since the last counter reset
4. In **Settings → Energy → Individual devices → Add device**, select **Pump energy**

> The energy sensor uses the cumulative runtime counter already provided by the BPC module.
> Setting the power to `0` disables both sensors.

## 🎛️ Available services

| Service | Description | Parameters |
|---|---|---|
| `easycare_bywaterair.pump_on` | Start the pump ⚠️ | `duration_minutes` (1-1440, default 60) |
| `easycare_bywaterair.pump_off` | Stop the pump ⚠️ | — |
| `easycare_bywaterair.set_filtration_mode` | Change the filtration mode ✅ | `mode` (AUTO / CONTINUOUS / MANUAL) |
| `easycare_bywaterair.start_boost` | Start a boost | `duration` (BOOST4H / BOOST12H / BOOST24H / BOOST36H / BOOST48H / BOOST72H) |
| `easycare_bywaterair.cancel_boost` | Cancel the boost | — |
| `easycare_bywaterair.refresh_data` | Force a refresh | — |

> ⚠️ **`pump_on` / `pump_off`** send a direct manual BPC command that bypasses
> the filtration mode configured in the EasyCare app. Prefer
> **`set_filtration_mode`** (mode `CONTINUOUS` to force on, `MANUAL`
> to force off, `AUTO` to return to automatic control) — this is the
> mechanism intended by the Waterair API and the only one that guarantees
> consistency with the mobile app.

## 📋 Automation examples

```yaml
# Start a 12h boost every Sunday morning
automation:
  - alias: "Pool — Sunday boost"
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

# Low chlorine alert
  - alias: "Pool — Low chlorine alert"
    trigger:
      - platform: numeric_state
        entity_id: sensor.easycare_bywaterair_chlorine
        below: 600  # mV
    action:
      - service: notify.notify
        data:
          message: "Low chlorine: {{ states('sensor.easycare_bywaterair_chlorine') }} mV"

# Notify when filtration is about to start (15 min before)
  - alias: "Pool — Filtration starting soon"
    trigger:
      - platform: template
        value_template: >
          {{ (as_timestamp(states('sensor.easycare_bywaterair_filtration_next_start')) - as_timestamp(now())) < 900 }}
    action:
      - service: notify.notify
        data:
          message: >
            Filtration starts at
            {{ states('sensor.easycare_bywaterair_filtration_next_start') | as_timestamp | timestamp_custom('%H:%M') }},
            ends at
            {{ states('sensor.easycare_bywaterair_filtration_next_end') | as_timestamp | timestamp_custom('%H:%M') }}
            ({{ state_attr('sensor.easycare_bywaterair_filtration_daily_duration', 'active_threshold_temp_c') }}°C threshold)
```

## ⚠️ Known limitations

- **BOOST with custom duration** not supported — available durations are
  4h, 12h, 24h, 36h, 48h and 72h.
- **Pump PROG mode (time schedule)**: detected in read mode (sensor
  `filtration_mode`), but not offered as an option in the selector.
  Time slot configuration remains in the mobile app.
- **AUTO and PAUSE light modes**: visible in read mode (sensors `spot_mode`
  and `escalight_mode`) but not configurable from HA. Time slot configuration
  (AUTO) and suspension duration (PAUSE, 1–15 days) remain in the mobile app.
  Only MANUAL mode (forced on 1h–6h) is controllable via `light.turn_on`.

## 🐛 Debug

To enable detailed logs:

```yaml
logger:
  default: warning
  logs:
    custom_components.easycare_bywaterair: debug
```

## 📄 License

MIT
