# Neighborhood Rhythm

**A passive BLE / WiFi / mDNS environment scanner with a live radar dashboard, built for a Raspberry Pi.**

Neighborhood Rhythm listens to the radio neighborhood around your Pi, classifies every device it hears, and draws the "rhythm" of devices coming and going on a live web dashboard. It scans passively (no BLE connections), decodes Apple Continuity and BLE sensor payloads, estimates distance from RSSI, and is multi-Pi-ready: one Pi gives honest distance rings, two or more give real trilateration.

---

## Features

- **Passive scanning** — BLE (via `bleak`), WiFi APs (via `iw`), and mDNS (via `zeroconf`). No connections, no probing.
- **Device classification** — rules-based, by mDNS model/category (highest confidence) > name patterns > service UUIDs > OUI vendor > random-MAC fallback.
- **Apple Continuity decoding** — AirPods model + battery, AirTag, Find My, iBeacon, Nearby Info. All from manufacturer data, passively.
- **BLE sensor decoding** — BTHome v2, RuuviTag v5, Govee. Decoded payloads stored as JSON in `sightings.extra`.
- **RSSI → distance** — log-path-loss model with per-class TX power defaults and rolling-median RSSI smoothing (cuts ±50% per-sample noise).
- **Multi-sensor trilateration** — 1 sensor = honest ring, 2 = ring pair, 3+ = least-squares trilaterated point (via `numpy`).
- **SQLite WAL + hourly rollup + retention** — WAL mode with `synchronous=NORMAL` (SD-card friendly), raw sightings pruned after 14 days, hourly rollup kept forever.
- **SSE live updates** — new sightings pushed to the dashboard the moment they land, throttled to one refresh per burst.
- **Auto-update via GitHub releases** — a systemd timer checks for a new release tag every 5 min and self-updates.

---

## How it works

```
collector.py (oneshot, systemd timer, every 5 min)
   │  BLE + WiFi + mDNS scan
   ▼
SQLite (WAL, hourly rollup, 14-day raw retention)
   │
   ▼
Flask / gunicorn web server (port 8000)
   │  JSON API + SSE /stream
   ▼
Dashboard (vanilla JS, Chart.js bundled locally, no CDN)
```

The collector runs as a `oneshot` systemd service on a 5-minute timer, independent of the web process. It scans, classifies, enriches, and writes to SQLite. The web server reads from the same DB and pushes new sightings to the dashboard over SSE.

**Multi-Pi path:** one Pi reports honest radial distance rings (it knows *how far*, not *where*). Add a second Pi and you get a ring pair. Add a third and the least-squares solver in `position.py` produces a trilaterated point. Peers sync sightings via `POST /api/sighting` (authenticated with `PEER_TOKEN`).

---

## Requirements

- **Raspberry Pi 3 or newer** with Raspberry Pi OS
- **Python 3.9+**
- **Onboard WiFi + BLE** (Pi 3 has both; Pi 4/5 recommended)
- **Root** for the WiFi scan (`iw dev wlan0 scan` requires it — the collector runs as root and hands the DB back to your user)
- **numpy** for trilateration (only needed with 3+ sensors): `sudo apt install python3-numpy` or `pip install numpy`

---

## Quick start

```bash
# 1. clone on the Pi
cd ~
git clone https://github.com/siropkin/neighborhood-rhythm.git
cd neighborhood-rhythm

# 2. create a venv and install deps
python3 -m venv ~/lightcontrol_venv
source ~/lightcontrol_venv/bin/activate
pip install -r requirements.txt

# 3. install systemd units (edit the sensor ID inside first if you have multiple Pis)
sudo cp systemd/neighborhood-rhythm-*.service systemd/neighborhood-rhythm-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now neighborhood-rhythm-web.service
sudo systemctl enable --now neighborhood-rhythm-collector.timer
sudo systemctl enable --now neighborhood-rhythm-update.timer

# 4. open the dashboard
open http://sivanpi.local:8000
```

The systemd units assume the venv at `~/lightcontrol_venv` and the app at `~/neighborhood-rhythm`. Set `RHYTHM_SENSOR_ID` in the unit files (it defaults to the hostname).

---

## Configuration

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `RHYTHM_SENSOR_ID` | `$HOSTNAME` | Identifies this Pi in multi-sensor setups. Set in the systemd unit. |
| `RHYTHM_PEER_TOKEN` | *(empty)* | Shared secret for peer-to-peer sighting sync. Set in `config_local.py` (gitignored). |
| `RHYTHM_DB` | `rhythm.db` (next to `config.py`) | SQLite database path. |

### Key constants in `config.py`

| Constant | Default | Purpose |
|---|---|---|
| `PATH_LOSS_N` | `2.7` | Path-loss exponent for RSSI → distance. Lower = less attenuation (open space), higher = more walls. Calibrate per environment. |
| `REF_RSSI_1M` | `-59` | Reference RSSI at 1 m. Used when a device doesn't advertise TX power. |
| `RETENTION_DAYS` | `14` | Raw sightings pruned after this many days. Hourly rollup is kept forever. |
| `DEDUP_WINDOW_S` | `2` | Same MAC + sensor within this window = one sighting (guards against bleak double-callbacks). |

For multi-Pi setups, put your shared peer token in `config_local.py` (gitignored):

```python
# config_local.py
PEER_TOKEN = "your-shared-secret"
```

---

## Auto-update

A systemd timer (`neighborhood-rhythm-update.timer`) fires every 5 min and runs `scripts/rhythm-update.sh`. The script:

1. Fetches the latest release tag from the GitHub API.
2. If it differs from the last applied tag, does `git fetch --tags`, `git reset --hard <tag>`, `git checkout <tag>`.
3. `chown`s the app dir back to your user (the script runs as root).
4. Restarts the web + collector services.
5. Re-runs `reclassify.py` to refresh device types with any new rules.

To trigger a manual update:

```bash
sudo systemctl start neighborhood-rhythm-update.service
```

To publish a new release (from your dev machine):

```bash
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
```

---

## Dashboard

Open `http://<pi>.local:8000` in a browser. You get:

- **Stats row** — devices ever seen, active now, WiFi networks, Pi count.
- **Radar** — a canvas radar with log-scale distance bands. Single-sensor devices show as rings (honest about the uncertainty), trilaterated devices show as points.
- **Device types** — a live breakdown bar beside the radar, color-coded by type.
- **Device table** — sortable, filterable, with distance, RSSI, and last-seen. Click a row for the per-device history page.
- **Live updates** — SSE pushes new sightings as they land; the dashboard refreshes within ~1.5 s.

---

## Project structure

```
neighborhood-rhythm/
├── collector.py          # one-shot BLE+WiFi+mDNS scanner (systemd timer, every 5 min)
├── enrich.py             # passive payload decoding (Apple Continuity, BLE sensors, mDNS)
├── apple_continuity.py   # Apple Continuity decoder (AirPods, AirTag, Find My, iBeacon)
├── sensors.py            # BLE sensor decoder (BTHome, RuuviTag, Govee)
├── classify.py           # rules-based device-type classifier
├── rules.py              # name / service / OUI classification rules
├── position.py           # RSSI→distance, ring / ring_pair / trilateration
├── db.py                 # SQLite schema, WAL, hourly rollup, retention, dedup
├── config.py             # paths, constants, peer token
├── app.py                # Flask + gunicorn web server, JSON API, SSE /stream
├── oui.py                # OUI vendor lookup (caches oui.txt from IEEE)
├── reclassify.py         # re-runs classification on existing devices
├── recompute_distances.py
├── templates/
│   ├── index.html        # dashboard page
│   └── device.html       # per-device history page
├── static/
│   ├── app.js            # radar + device table (vanilla JS, no framework)
│   └── style.css
├── scripts/
│   └── rhythm-update.sh  # GitHub-release-triggered self-update
├── systemd/
│   ├── neighborhood-rhythm-web.service
│   ├── neighborhood-rhythm-collector.service
│   ├── neighborhood-rhythm-collector.timer
│   ├── neighborhood-rhythm-update.service
│   └── neighborhood-rhythm-update.timer
└── requirements.txt
```

---

## License

MIT. See [LICENSE](LICENSE).
