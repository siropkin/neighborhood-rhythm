# Neighborhood Rhythm — project context for Claude Code

This file gives a fresh agent session the context needed to work on this project.
Read it before doing anything.

## What this is
A passive BLE/WiFi/mDNS environment scanner on a Raspberry Pi 3, with a web
dashboard. The Pi scans its surroundings every 5 min, classifies devices,
fingerprints them across MAC rotations and radios, flags rogue (unknown stable)
devices, stores history in SQLite, and shows a "Neighborhood Rhythm" dashboard.
Designed to be device-agnostic (works anywhere it boots) and multi-Pi-ready
(1 Pi = honest radial distance rings; 2+ Pis = real trilateration).

**Honest scope:** this is a hobbyist passive scanner that inventories devices
actively advertising BLE/WiFi/mDNS near the Pi and flags what's new since the
last sweep. It is NOT a "find every transmitting device in this space" tool —
passive scanning can't see devices that are asleep, off-cycle during the ~10 s
scan window, on radios the Pi lacks (cellular/Zigbee/Z-Wave/sub-GHz/UWB), or
that rotate their MAC (most modern phones). Coverage of actively-advertising
BLE/WiFi devices is roughly 30–40% of transmitters in a room, shrinking as MAC
randomization spreads. Rogue detection is an inventory diff, not a threat
classifier. See README "Honest limits".

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
  random/rotating phones — `is_random_mac` covers LA bits AND BLE static-random
  0xC0-with-no-OUI) seen 5+ times over ≥15 min (`MIN_SIGHTINGS=5`,
  `MIN_SIGHTING_SPAN_S=900`) that aren't in the `known_devices` baseline.
  `autoresolve_stale` (runs in the collector pass) auto-resolves open alerts
  whose device hasn't been seen in 48h — they re-flag if the device returns.
  Inventory + diff, not a threat classifier — "something new is here", a human
  decides if it belongs. Misses by design: randomizing MACs, brief advertisers,
  asleep/off-cycle devices.
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
- `cloudflared.service` — Cloudflare tunnel (exposes port 8000 at rhythm.srdkn.com)

## Public access (Cloudflare tunnel + token auth)
The dashboard is publicly reachable at `https://rhythm.srdkn.com/?t=<API_TOKEN>`
via a Cloudflare tunnel (no port forwarding, no exposed IP). Setup:
`bash scripts/setup_cloudflare_tunnel.sh` (uses a Cloudflare API token at
`~/.cloudflared_token` — not `cloudflared tunnel login`, which doesn't save the
cert on a headless Pi). The tunnel token is at `~/.cloudflared/tunnel_token`.
- **API auth**: when `RHYTHM_API_TOKEN` env is set on the web service, all
  `/api/*` + `/stream` routes require a token. Accept `Authorization: Bearer
  <token>` (integrations) or `?token=<token>` (browser — EventSource and
  navigations can't set headers). The dashboard URL carries `?t=<token>`, which
  app.js/device.js stash in localStorage and append to every call.
- **Prereq**: the `srdkn.com` zone must be **active** in Cloudflare (not
  `pending`). If it's pending, switch nameservers at GoDaddy from
  `ns13/14.domaincontrol.com` to Cloudflare's (`emily/pete.ns.cloudflare.com`).
  Until then the edge returns 403 for the zone.
- The API token on the Pi is in the web service's `Environment=RHYTHM_API_TOKEN`
  line. The dashboard URL with token is the "hidden URL".

## Gotchas (read these — they've bitten us)
- **File ownership after update**: the update script runs as root and `git reset`
  rewrites files as root. The script `chown -R siropkin` after, but if you
  manually copy files and get "Permission denied", run:
  `ssh siropkin@sivanpi.local 'sudo chown -R siropkin:siropkin ~/neighborhood-rhythm/'`
- **DB locked during migration**: if you add a column and run `db.py` while the
  collector is scanning, you get "database is locked". Wait for the collector
  to finish, then run the migration.
- **Inline Python over SSH**: avoid `ssh pi 'python -c "..."'` with embedded
  quotes — they break. Write a script file, scp it, run it. No `sqlite3` CLI
  on the Pi — use `~/lightcontrol_venv/bin/python` with the sqlite3 module.
- **Pi timezone vs viewers**: the Pi's tz may not match the browser's (it was
  America/New_York serving a PDT user until 2026-08-29). Never label
  user-facing hours with server `localtime()` — APIs take `?tzoff=` (minutes
  behind UTC, JS `getTimezoneOffset()`) and bucket/label in the viewer's tz.
- **Tests**: `python3 test_core.py` (framework-free, temp DB) — run after
  touching rules.py / behavior.py / rogue.py / position.py. Runs on the Pi too.
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
phones stay un-merged — honest footfall noise, not linkable units.

**Data profile (14-day analysis, 2026-08):** 98.9% of MACs are one-day
transients (median dwell 330s); ~24 resident devices; peak 20:00, quiet 11:00;
the "commute" shows in appliances waking, not phones. Night-only iPhones send
**short (5-byte) Nearby Info payloads — no auth tag**, so they're unlinkable
by design (Pass A needs ≥19-byte payloads; raw payload hex is stored in
`sightings.extra.apple.raw` for future decoders, e.g. 0x0F Nearby Action's
per-person SHA256 prefixes — rare but high-value). Rogue noise lessons now in
code: baseline-age guard (first_seen within 24h of the baseline snapshot ≠ new),
cohort collapse (≥5 same-OUI same-day = one infrastructure event).

**Researched and rejected (2026-08, don't re-research):** McMatcher-style
RSSI-shape matching (SAX + cosine, IEEE ICCE 2024) needs dense RSSI streams —
useless at our 5-min scan cadence (~3 samples per MAC rotation); revisit if the
probe-request adapter lands. BLE clock-skew fingerprinting dies on advDelay
dither + BlueZ timestamp jitter. **IRK enrollment** (ESPresense-style: emulate a
Heart Rate Monitor so household phones pair once, then resolve every rotated
RPA passively via AES `ah(IRK, prand)`) is the ONLY technique that de-noises the
empty-set phones — it's a pairing-flow feature, not a fix. Adopted from
ESPresense instead: Tukey IQR-fence RSSI smoothing (`db.smoothed_rssi`).

## Rogue detection — the honest limits
Counts devices, not people. MAC randomization means ~340 empty-set phones are
un-mergeable noise. RSSI ±50% is the physics floor. Rogue detection filters to
stable MACs (registered OUI, not locally-administered) seen 3+ times over ≥10
min — excludes rotating-phone noise and brief drive-bys, catches a new
camera/IoT device that keeps its MAC and advertises persistently. Misses any
device that randomizes, advertises briefly, or sleeps during the sweep.

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
