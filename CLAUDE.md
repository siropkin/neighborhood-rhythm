# Neighborhood Rhythm — project context for Claude Code

This file gives a fresh agent session the context needed to work on this project.
Read it before doing anything.

## What this is
A passive BLE/WiFi/mDNS environment scanner on a Raspberry Pi 3, with a web
dashboard. The Pi scans its surroundings every 5 min, classifies devices,
fingerprints them across MAC rotations and radios, flags rogue (unknown stable)
devices, stores history in SQLite, and shows a "Neighborhood Rhythm" dashboard.
Designed to be device-agnostic (works anywhere it boots) and multi-Pi-ready
(1 Pi = honest radial distance rings; 2+ Pis = real trilateration). The product
direction is an IoT device-inventory + rogue-device-detection security tool —
"find every transmitting device in this space" — positioned to complement
Verkada (cameras/access, but NOT device detection).

## Architecture
- `collector.py` — one-shot scanner (BLE via bleak + classic BT via hcitool +
  WiFi APs via iw + **LAN clients via ARP-table `scan_lan`** + mDNS via
  zeroconf). Runs on a systemd timer every 5 min. Captures tx_power,
  manufacturer_data, service_data per BLE device. After storing, recomputes
  fingerprints and runs rogue detection.
- `enrich.py` — passive payload decoding: Apple Continuity (AirPods/AirTag/Find
  My/Nearby), BLE sensors (BTHome/RuuviTag/Govee), mDNS model/category. Stores
  decoded fields as JSON in `sightings.extra`.
- `apple_continuity.py` / `sensors.py` — the decoders. Apple decoder now
  extracts the Nearby **auth tag** (offsets 16–18, stable per device across MAC
  rotations — the Apple device ID) and rejects short 0x07 TLVs (AirPods
  false-positive fix: real AirPods payloads are ≥25 bytes).
- `fingerprint.py` — **device fingerprinting**: derives a stable identity above
  the rotating MAC layer so one physical device is one row, not many. Three
  linking passes: A) Apple Nearby auth tag (0.95), B) cross-radio — mDNS
  hostname serial / OUI+name match across BLE/WiFi/mDNS (0.95), C) MAC-rotation
  clustering — same class+signature, sequential, within 15-min window (0.7).
  Writes `device_fingerprints` + `device_aliases` tables. Idempotent; run after
  every scan.
- `rogue.py` — **rogue-device detection**: flags new stable-MAC devices (not
  random/rotating phones) seen 2+ times that aren't in the `known_devices`
  baseline. Inventory + diff, not a threat classifier — "something new is here",
  a human decides if it belongs.
- `classify.py` + `rules.py` — device-type brain. Rules-based: mDNS model/category
  (highest conf) > name patterns > service UUIDs > OUI > random-MAC fallback.
- `db.py` — SQLite schema + helpers. Tables: `devices`, `sightings`,
  `sightings_hourly`, `sensors`, `wifi_aps`, `device_fingerprints`,
  `device_aliases`, `known_devices`, `rogue_events`. Composite (mac, ts) index,
  WAL + synchronous=NORMAL, hourly rollup + 14-day raw retention, dedup guard.
- `position.py` — 1 sensor → ring, 2 → ring_pair, 3+ → trilaterated point.
  Single-sensor distance uses a rolling-median RSSI (cuts ±50% per-sample noise).
- `app.py` — Flask + gunicorn web server + JSON API + SSE `/stream`.
- `templates/` + `static/` — the dashboard (vanilla JS, no framework; Chart.js
  bundled locally, no CDN).
- `scripts/rhythm-update.sh` — self-update script (release-triggered).
- `systemd/` — service + timer units.

## API endpoints (app.py)
- `/api/now`, `/api/rhythm`, `/api/device/<mac>`, `/api/wifi`, `/api/positions`,
  `/api/stats`, `/api/sensors` — existing dashboard data.
- `/api/sighting` (POST, peer-auth) — multi-Pi sync.
- `/api/fingerprints` — merged device fingerprints (clusters with >1 MAC).
- `/api/rogue` — unresolved rogue-device alerts.
- `/api/rogue/known` (GET/POST) — known-device baseline; POST adds a MAC and
  resolves its open rogue event.
- `/api/rogue/<mac>/resolve` (POST) — dismiss a rogue alert without adding to known.
- `/stream` — SSE live sightings.

## The Pi
- Hostname: `sivanpi` (reachable as `sivanpi.local` on the home/office WiFi).
- SSH: `ssh siropkin@sivanpi.local` (key auth is set up from the Mac — no password).
- The Pi's app dir is a git checkout of this repo: `~/neighborhood-rhythm/`.
- Python venv with deps: `~/lightcontrol_venv/` (bleak, flask, gunicorn, numpy, zeroconf).

## How to connect to the Pi
```bash
ssh siropkin@sivanpi.local
# run a one-shot scan:
sudo systemctl start neighborhood-rhythm-collector.service
# check the dashboard: http://sivanpi.local:8000
```

## How to publish changes to the Pi
The Pi self-updates from GitHub releases. **Do not manually copy files** unless
testing — the update pipeline handles deployment.
```bash
# 1. edit code locally (~/neighborhood-rhythm or ~/projects/neighborhood-rhythm)
# 2. commit + push
git add -A && git commit -m "..." && git push
# 3. tag a release — the Pi picks it up within 5 min
git tag -a vX.Y.Z -m "vX.Y.Z" && git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..."
# 4. (optional) force the Pi to update now instead of waiting:
ssh siropkin@sivanpi.local 'sudo systemctl start neighborhood-rhythm-update.service'
```
The update script (`scripts/rhythm-update.sh`) does `git reset --hard <tag>`,
restarts the web + collector services, and reclassifies all devices.

## Services on the Pi (all auto-start on boot)
- `neighborhood-rhythm-web.service` — gunicorn dashboard (port 8000)
- `neighborhood-rhythm-collector.timer` — scans every 5 min
- `neighborhood-rhythm-update.timer` — checks GitHub for new releases every 5 min

## Gotchas (read these — they've bitten us)
- **File ownership after update**: the update script runs as root and `git reset`
  rewrites files as root. The script `chown -R siropkin` after, but if you
  manually copy files and get "Permission denied", run:
  `ssh siropkin@sivanpi.local 'sudo chown -R siropkin:siropkin ~/neighborhood-rhythm/'`
- **DB locked during migration**: if you add a column and run `db.py` while the
  collector is scanning, you get "database is locked". Wait for the collector
  to finish, then run the migration.
- **Inline Python over SSH**: avoid `ssh pi 'python -c "..."'` with embedded
  quotes — they break. Write a script file, scp it, run it.
- **Flask dev server drops connections**: we use gunicorn (2 workers, 4 threads)
  because the Flask dev server is single-threaded and drops in-flight requests
  on restart. Don't switch back to `app.py` directly for production.
- **Distance is rough**: RSSI→distance is ±50% even with tx_power + smoothing.
  The radar shows rings (honest), not points. Don't over-trust the meter number.
- **MAC randomization**: phones rotate their BLE MAC every ~15 min. We can't
  reliably track a phone across rotations passively (by design). ~80% of devices
  (speakers/TVs/lights/beacons) have stable MACs and track fine. Fingerprinting
  (Pass C) links some rotations but only with a real device-identifying
  signature — empty-set phones (~340) stay un-mergeable noise.

## Data enrichment (what we decode passively, no BLE connection)
- Apple Continuity (0x004C): AirPods model+battery (0x07, ≥25-byte guard),
  AirTag (0x16), Find My (0x12), Nearby Info/iPhone-Mac (0x10 — **extracts the
  3-byte auth tag at offsets 16–18**, the stable per-device Apple ID), iBeacon (0x02).
- BLE sensors: BTHome v2 (0xFCD2), RuuviTag v5 (0x0499), Govee (0xEC88).
  (Xiaomi encrypted needs a bind key — not recoverable passively; skipped.)
- mDNS TXT: _airplay/_googlecast model, _hap (HomeKit) category, _ipp printer model.
- TX power (AD 0x0A) as the path-loss reference; rolling-median RSSI for smoothing.

## Fingerprinting — what the validation showed
Service-UUID sets are a **CLASS signal, not a UNIT signal**: 456/508 random MACs
share an empty set. So MAC-rotation clustering (Pass C) needs guards or it
over-merges: skip empty signatures, cap group cardinality (>4 = a population not
a rotation), pairwise links only (no transitive chaining A→B→C→D). The empty-set
phones stay un-merged — honest footfall noise, not linkable units. See
`docs/FINGERPRINTING.md` (design) + `docs/FINGERPRINTING-VALIDATION.md`.

## Rogue detection — the honest limits
Counts devices, not people. MAC randomization means ~340 empty-set phones are
un-mergeable noise. RSSI ±50% is the physics floor. Rogue detection filters to
stable MACs (registered OUI, not locally-administered) seen 2+ times — excludes
rotating-phone noise, catches a new camera/IoT device/planted hardware that
keeps its MAC.

## Repo
- GitHub: `siropkin/neighborhood-rhythm` (public — no secrets; DB/tokens/OUI cache gitignored)
- Local clones: `~/neighborhood-rhythm` (dev) and `~/projects/neighborhood-rhythm` (clean clone)
- `config_local.py` (gitignored) holds the peer token for multi-Pi sync.

## When extending
- New decoded payload type → add to `enrich.py`, store in `sightings.extra` (JSON).
  Don't widen the schema per ad type.
- New device-type rule → add to `rules.py` (NAME_RULES / SERVICE_RULES / OUI_RULES).
  Then run `python reclassify.py` to refresh existing devices.
- New fingerprint link signal → add a pass in `fingerprint.py`. Keep the guards
  (empty-set skip, cardinality cap, no transitive chaining) or you over-merge.
- New query → check `EXPLAIN QUERY PLAN` against the (mac, ts) composite index.
- WiFi probe-request capture (phones not on the network) is the next scan source
  — needs a USB monitor-mode adapter (AR9271, ordered). When it arrives, add a
  probe-request scan source to `collector.py`.
