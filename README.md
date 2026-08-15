# Neighborhood Rhythm

Pi environment scanner + dashboard. Periodically scans BLE/BT/WiFi/mDNS, classifies devices, stores history, shows a "Neighborhood Rhythm" dashboard. Device-agnostic (no hardcoded devices), multi-Pi-ready (1 Pi = honest radial rings, 2+ = real triangulation).

## Deploy to the Pi

```bash
# on the Pi, in ~/neighborhood-rhythm/
pip3 install -r requirements.txt          # flask, bleak, numpy
sudo apt install -y bluez avahi-tools iw  # scanner tools

# shared peer token (for multi-Pi sync) — uncommitted
echo 'PEER_TOKEN = "your-secret-here"' > config_local.py

# install systemd units
sudo cp systemd/*.service systemd/*.timer /etc/systemd/system/
sudo systemctl enable --now neighborhood-rhythm-web.service
sudo systemctl enable --now neighborhood-rhythm-collector.timer
```

Open `http://<pi>.local:8000`.

## Manual run

```bash
python3 db.py          # init DB
python3 collector.py    # one scan
python3 app.py          # web server (dev only — production uses gunicorn)
python3 reclassify.py   # re-run the classifier over all existing devices (after rule changes)
```

## Auto-update (release-triggered)

Tagged releases on `main` trigger the Pi to self-update. The Pi runs an
`update-rhythm` systemd timer (every 5 min) that checks the GitHub releases
API for a new tag; if found, it `git pull`s, restarts the web + collector
services, and reclassifies. So: push to main → tag a release → the Pi picks
it up within 5 min. See `scripts/rhythm-update.sh`.

## Multi-Pi smoke test (no 2nd Pi needed)

```bash
curl -X POST http://localhost:8000/api/sighting \
  -H "Content-Type: application/json" \
  -H "X-Peer-Token: your-secret-here" \
  -d '{"mac":"AA:BB:CC:DD:EE:FF","sensor_id":"Pi2","hostname":"pi2.local","rssi":-70,"name":"TestPhone"}'
# /api/positions for that MAC now returns ring_pair (2 sensors) instead of ring.
```

## Files
- `collector.py` — scanner (BLE bleak + BT hcitool + WiFi iw + mDNS avahi-browse)
- `classify.py` / `rules.py` — device-type brain (pure functions + rule table)
- `db.py` — SQLite schema (devices, sightings[w/ sensor_id], sensors, wifi_aps)
- `position.py` — 1 sensor→ring, 2→ring_pair, 3+→trilaterated point
- `oui.py` — IEEE OUI manufacturer lookup (cached, weekly refresh)
- `app.py` — Flask server + JSON API
- `templates/index.html` + `static/{style.css,app.js,chart.min.js}` — dashboard
- `systemd/` — collector timer + web service
