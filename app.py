"""app.py — Flask server. Dashboard + JSON API. Bound to 0.0.0.0:8000."""
import json
import time
from functools import wraps

from flask import Flask, request, jsonify, render_template, Response

import db
from config import SENSOR_ID, PEER_TOKEN, ACTIVE_WINDOW_S, API_TOKEN
from position import compute_position

app = Flask(__name__)


# Auth: when API_TOKEN is set, all /api/* routes + /stream require a token.
# Accept Authorization: Bearer <token> (integrations) or ?token=<token>
# (browser — the dashboard URL carries it, since EventSource and navigations
# can't set headers). Fail closed (401) on mismatch or missing token. When
# unset (dev), auth is off. Dashboard HTML routes (/, /device) stay open.
# Constant-time compare to avoid timing leaks.
import hmac
def _check_token():
    tok = request.headers.get('Authorization', '').removeprefix('Bearer ').strip()
    if not tok:
        tok = request.args.get('token', '').strip()
    return hmac.compare_digest(tok, API_TOKEN) if API_TOKEN else True

@app.before_request
def _api_auth():
    if not API_TOKEN:
        return  # dev mode — no token set, auth off
    if request.path not in ('/stream',) and not request.path.startswith('/api/'):
        return  # dashboard HTML routes stay open
    if not _check_token():
        return jsonify({"error": "unauthorized"}), 401


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None


def _int_arg(name, default):
    """Parse a query int; bad/missing → default. Never raises."""
    v = request.args.get(name)
    if v is None or not v.lstrip("-").isdigit():
        return default
    try:
        return int(v)
    except (ValueError, TypeError):
        return default


def _peer_auth(f):
    @wraps(f)
    def wrapped(*a, **kw):
        tok = request.headers.get("X-Peer-Token", "")
        if PEER_TOKEN and tok != PEER_TOKEN:
            return jsonify({"error": "unauthorized"}), 401
        return f(*a, **kw)
    return wrapped


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    # tiny inline radar emoji as SVG -> ICO-ish data URI; no file needed.
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
           '<circle cx="50" cy="50" r="44" fill="#0d1117" stroke="#58a6ff" stroke-width="4"/>'
           '<circle cx="50" cy="50" r="28" fill="none" stroke="#30363d" stroke-width="2"/>'
           '<circle cx="50" cy="50" r="12" fill="none" stroke="#30363d" stroke-width="2"/>'
           '<line x1="50" y1="50" x2="82" y2="28" stroke="#56d364" stroke-width="4" stroke-linecap="round"/>'
           '<circle cx="50" cy="50" r="4" fill="#58a6ff"/></svg>')
    return Response(svg, mimetype="image/svg+xml")


@app.route("/device/<path:mac>")
def device_page(mac):
    return render_template("device.html", mac=mac)


@app.route("/api/now")
def api_now():
    cutoff = time.time() - ACTIVE_WINDOW_S  # seen in last 10 min
    site_id = request.args.get("site_id")  # multi-tenant filter
    with db.get_db() as conn:
        rows = db.latest_sighting_per_device(conn, cutoff)
        devices = [dict(r) for r in rows]
        if site_id:
            devices = [d for d in devices if d.get("site_id") == site_id]
        # alias count per device (how many MACs/keys are linked to this one
        # physical device by the fingerprinter) — the standout feature.
        for d in devices:
            if d.get("fingerprint_id"):
                n = conn.execute(
                    "SELECT COUNT(*) c FROM device_aliases WHERE fingerprint_id=?",
                    (d["fingerprint_id"],)).fetchone()["c"]
                d["alias_count"] = n
            else:
                d["alias_count"] = 1
    if request.args.get("format") == "csv":
        import csv as csvmod, io
        buf = io.StringIO()
        w = csvmod.writer(buf)
        cols = ["mac", "oui_name", "last_label", "last_type", "source",
                "rssi", "distance", "first_seen", "last_seen", "sighting_count",
                "is_mine", "alias_count"]
        w.writerow(cols)
        for d in devices:
            w.writerow([d.get(c) for c in cols])
        resp = Response(buf.getvalue(), mimetype="text/csv")
        resp.headers["Content-Disposition"] = 'attachment; filename="devices.csv"'
        return resp
    return jsonify({"ts": time.time(), "sensor_id": SENSOR_ID, "devices": devices})


@app.route("/api/rhythm")
def api_rhythm():
    hours = _int_arg("hours", 24)
    since = time.time() - hours * 3600
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT mac, ts FROM sightings WHERE ts >= ? ORDER BY ts""", (since,)
        ).fetchall()
    # bucket by hour. Key on the UTC epoch hour (stable, DST-proof) but
    # label it in local time for display — avoids the DST fall-back collision
    # where the same local "01:00" label occurs twice and merges two hours.
    buckets = {}
    for r in rows:
        hour = int(r["ts"] // 3600) * 3600
        label = time.strftime("%Y-%m-%d %H:00", time.localtime(hour))
        buckets.setdefault(hour, (set(), label))[0].add(r["mac"])
    series = [{"t": lbl, "count": len(macs)} for _, (macs, lbl) in sorted(buckets.items())]
    return jsonify({"hours": hours, "series": series})


@app.route("/api/device/<mac>")
def api_device(mac):
    from behavior import classify_behavior, detect_time_pattern
    with db.get_db() as conn:
        dev = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
        sightings = conn.execute(
            "SELECT * FROM sightings WHERE mac=? ORDER BY ts", (mac,)
        ).fetchall()
        behavior = classify_behavior(conn, mac) if dev else None
        time_pattern = detect_time_pattern(conn, mac) if dev else None
        # the fingerprint cluster: this device's fingerprint_id + all aliases
        # (other MACs linked to the same physical device)
        fp = None
        if dev and dev["fingerprint_id"]:
            fp_id = dev["fingerprint_id"]
            aliases = conn.execute(
                "SELECT mac, source, link_method FROM device_aliases WHERE fingerprint_id=?",
                (fp_id,)).fetchall()
            fp = {"fingerprint_id": fp_id, "aliases": [dict(a) for a in aliases]}
    if not dev:
        return jsonify({"error": "not found"}), 404
    return jsonify({"device": dict(dev), "sightings": [dict(s) for s in sightings],
                    "behavior": behavior, "fingerprint": fp,
                    "time_pattern": time_pattern})


@app.route("/api/wifi")
def api_wifi():
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM wifi_aps ORDER BY last_signal DESC").fetchall()
    return jsonify({"aps": [dict(r) for r in rows]})


@app.route("/api/device/<mac>/tag", methods=["POST"])
def api_tag(mac):
    body = request.get_json(force=True, silent=True) or {}
    with db.get_db() as conn:
        conn.execute(
            "UPDATE devices SET is_mine=?, my_label=? WHERE mac=?",
            (1 if body.get("is_mine") else 0, body.get("my_label"), mac),
        )
    return jsonify({"ok": True})


@app.route("/api/device/<mac>/track", methods=["POST"])
def api_track(mac):
    """Toggle tracking on a device. Body {tracked: 0/1, note: str}.
    A tracked device gets a timeline + state-change alerts."""
    body = request.get_json(force=True, silent=True) or {}
    tracked = 1 if body.get("tracked") else 0
    note = body.get("note")
    with db.get_db() as conn:
        if note is not None:
            conn.execute("UPDATE devices SET tracked=?, watch_note=? WHERE mac=?",
                         (tracked, note, mac))
        else:
            conn.execute("UPDATE devices SET tracked=? WHERE mac=?", (tracked, mac))
    return jsonify({"ok": True})


@app.route("/api/tracked")
def api_tracked():
    """Tracked devices + their sighting timeline (presence over time)."""
    with db.get_db() as conn:
        devs = conn.execute(
            "SELECT mac, oui_name, last_type, last_label, watch_note, "
            "first_seen, last_seen, sighting_count FROM devices WHERE tracked=1"
        ).fetchall()
        out = []
        for d in devs:
            # presence timeline: sightings bucketed to the scan (5-min) level,
            # last 24h, so you can see when it's present vs absent.
            rows = conn.execute(
                "SELECT ts, rssi FROM sightings WHERE mac=? AND ts >= ? ORDER BY ts",
                (d["mac"], time.time() - 86400)).fetchall()
            timeline = [{"ts": r["ts"], "rssi": r["rssi"]} for r in rows]
            out.append({**dict(d), "timeline": timeline})
    return jsonify({"tracked": out})


@app.route("/api/copresence")
def api_copresence():
    """Pairs of devices almost always seen together — likely one physical
    unit. A suggestion to merge, not an auto-merge."""
    from fingerprint import detect_copresence
    with db.get_db() as conn:
        pairs = detect_copresence(conn)
        # enrich with device labels (must be inside the with — conn closes after)
        out = []
        for a, b, overlap, ac, bc, ratio in pairs[:30]:
            da = conn.execute("SELECT oui_name, last_type, last_label FROM devices WHERE mac=?", (a,)).fetchone()
            db_row = conn.execute("SELECT oui_name, last_type, last_label FROM devices WHERE mac=?", (b,)).fetchone()
            out.append({"a": a, "b": b, "ratio": ratio, "co_scans": overlap,
                        "a_label": (da["last_label"] or da["oui_name"] or a) if da else a,
                        "b_label": (db_row["last_label"] or db_row["oui_name"] or b) if db_row else b,
                        "a_type": da["last_type"] if da else None,
                        "b_type": db_row["last_type"] if db_row else None})
    return jsonify({"pairs": out})


@app.route("/api/correlation")
def api_correlation():
    """Cross-site device correlation — the same physical device (fingerprint)
    seen at more than one site. The 10x feature: fleet intelligence from a
    per-site presence sensor."""
    from fingerprint import detect_cross_site
    with db.get_db() as conn:
        cross = detect_cross_site(conn)
    return jsonify({"correlations": cross})


@app.route("/api/positions")
def api_positions():
    now = time.time()
    cutoff = now - ACTIVE_WINDOW_S  # match /api/now: devices seen in last 10 min
    with db.get_db() as conn:
        macs = [r["mac"] for r in conn.execute(
            "SELECT DISTINCT mac FROM sightings WHERE ts >= ?", (cutoff,)
        ).fetchall()]
    out = {}
    for mac in macs:
        # Use the same 10-min window so a device seen minutes ago still gets a ring.
        p = compute_position(mac, at_time=now, tolerance_s=ACTIVE_WINDOW_S)
        if p:
            out[mac] = p
    return jsonify({"positions": out})


@app.route("/api/sighting", methods=["POST"])
@_peer_auth
def api_sighting():
    """Accept a sighting from another Pi. The multi-Pi sync path."""
    body = request.get_json(force=True, silent=True) or {}
    mac = body.get("mac")
    if not mac:
        return jsonify({"error": "mac required"}), 400
    ts = body.get("ts", time.time())
    sensor_id = body.get("sensor_id", "unknown")
    with db.get_db() as conn:
        db.register_sensor(conn, sensor_id, body.get("hostname", sensor_id))
        db.insert_sighting(conn, mac, sensor_id, ts, body.get("rssi"),
                           body.get("distance"), body.get("name"),
                           body.get("services", ""), body.get("source", "peer"))
        db.upsert_device(conn, mac, body.get("oui_name"), ts,
                         body.get("type"), body.get("label"))
    return jsonify({"ok": True})


@app.route("/api/sensor", methods=["POST"])
@_peer_auth
def api_sensor():
    body = request.get_json(force=True, silent=True) or {}
    sid = body.get("sensor_id")
    if not sid:
        return jsonify({"error": "sensor_id required"}), 400
    with db.get_db() as conn:
        db.register_sensor(conn, sid, body.get("hostname", sid),
                           body.get("location_label"), body.get("x"), body.get("y"))
    return jsonify({"ok": True})


@app.route("/api/sensors")
def api_sensors():
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM sensors ORDER BY last_seen DESC").fetchall()
    return jsonify({"sensors": [dict(r) for r in rows]})


@app.route("/api/sites", methods=["GET", "POST"])
def api_sites():
    """GET: list sites. POST {label}: create a site. Multi-tenant grouping —
    each site groups one or more sensors (Pis) and their devices."""
    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        label = body.get("label")
        if not label:
            return jsonify({"error": "label required"}), 400
        import uuid
        site_id = str(uuid.uuid4())
        with db.get_db() as conn:
            conn.execute("INSERT INTO sites (site_id, label, created_ts) VALUES (?,?,?)",
                         (site_id, label, time.time()))
        return jsonify({"site_id": site_id, "label": label})
    with db.get_db() as conn:
        rows = conn.execute("SELECT * FROM sites ORDER BY created_ts DESC").fetchall()
        # count sensors + devices per site. Devices/sensors created before the
        # site_id column have NULL site_id — if there's only one site, count
        # the unassigned ones as belonging to it (the default site).
        out = []
        n_sites = len(rows)
        for r in rows:
            if n_sites == 1:
                n_sensors = conn.execute("SELECT COUNT(*) c FROM sensors WHERE site_id=? OR site_id IS NULL OR site_id=''", (r["site_id"],)).fetchone()["c"]
                n_devices = conn.execute("SELECT COUNT(*) c FROM devices WHERE site_id=? OR site_id IS NULL OR site_id=''", (r["site_id"],)).fetchone()["c"]
            else:
                n_sensors = conn.execute("SELECT COUNT(*) c FROM sensors WHERE site_id=?", (r["site_id"],)).fetchone()["c"]
                n_devices = conn.execute("SELECT COUNT(*) c FROM devices WHERE site_id=?", (r["site_id"],)).fetchone()["c"]
            out.append({**dict(r), "sensors": n_sensors, "devices": n_devices})
    return jsonify({"sites": out})


@app.route("/stream")
def stream():
    """SSE: push new sightings to the dashboard live."""
    # Read since inside the request context (the generator outlives it).
    # since=0 = "don't replay history" — seed to current max, else we'd
    # replay thousands of old sightings and exhaust the browser.
    since = _int_arg("since", 0)
    if since == 0:
        with db.get_db() as conn:
            row = conn.execute("SELECT MAX(id) m FROM sightings").fetchone()
            since = row["m"] if row and row["m"] else 0
    cursor = [since]

    def event_stream():
        # One connection for the life of the generator — not per 2s loop.
        # Otherwise each open dashboard tab holds a gunicorn worker thread
        # and churns a connection forever; enough tabs exhaust the pool.
        import sqlite3
        from config import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            while True:
                rows = conn.execute(
                    "SELECT id, mac, name, rssi, distance, ts, source FROM sightings WHERE id > ? ORDER BY id LIMIT 50",
                    (cursor[0],),
                ).fetchall()
                for r in rows:
                    cursor[0] = r["id"]
                    yield f"data: {json.dumps(dict(r))}\n\n"
                yield ": ping\n\n"  # heartbeat
                time.sleep(2)
        finally:
            conn.close()

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/fingerprints")
def api_fingerprints():
    """Merged device fingerprints — shows which MACs were linked as one
    physical device (cross-radio + rotation). Only clusters with >1 MAC."""
    with db.get_db() as conn:
        rows = conn.execute("""
            SELECT f.fingerprint_id, f.device_class, f.label, f.sighting_count,
                   f.confidence, f.first_seen, f.last_seen,
                   COUNT(a.mac) AS n_aliases
            FROM device_fingerprints f
            JOIN device_aliases a ON f.fingerprint_id = a.fingerprint_id
            GROUP BY f.fingerprint_id
            HAVING n_aliases > 1
            ORDER BY n_aliases DESC
            LIMIT 50
        """).fetchall()
        out = []
        for r in rows:
            aliases = [dict(a) for a in conn.execute(
                "SELECT mac, source, link_method, link_confidence FROM device_aliases "
                "WHERE fingerprint_id=?", (r["fingerprint_id"],)).fetchall()]
            out.append({**dict(r), "aliases": aliases})
    return jsonify({"fingerprints": out})


@app.route("/api/rogue")
def api_rogue():
    """Unresolved rogue-device alerts — new stable-MAC devices not in the
    known baseline. Enriched with the device's live signal (rssi, distance,
    last_seen, sighting_count) + behavior so each alert is triageable."""
    from behavior import classify_behavior
    site_id = request.args.get("site_id")  # multi-tenant filter
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM rogue_events WHERE resolved=0 ORDER BY ts DESC"
        ).fetchall()
        if site_id:
            # filter rogues to devices at this site
            rows = [r for r in rows if conn.execute(
                "SELECT site_id FROM devices WHERE mac=?", (r["mac"],)).fetchone()
                and conn.execute("SELECT site_id FROM devices WHERE mac=?", (r["mac"],)).fetchone()["site_id"] == site_id]
        out = []
        for r in rows:
            d = dict(r)
            dev = conn.execute(
                "SELECT last_seen, sighting_count FROM devices WHERE mac=?",
                (r["mac"],)).fetchone()
            if dev:
                d["device_last_seen"] = dev["last_seen"]
                d["sighting_count"] = dev["sighting_count"]
            # latest sighting for live rssi + distance + source
            s = conn.execute(
                "SELECT rssi, distance, source FROM sightings WHERE mac=? "
                "ORDER BY ts DESC LIMIT 1", (r["mac"],)).fetchone()
            if s:
                d["rssi"] = s["rssi"]
                d["distance"] = s["distance"]
                d["source"] = s["source"]
            d["behavior"] = classify_behavior(conn, r["mac"])
            out.append(d)
    return jsonify({"rogues": out})


@app.route("/api/rogue/known", methods=["GET", "POST"])
def api_known():
    """GET: the known-device baseline. POST {mac, label, note}: add to it
    (resolves any open rogue event for that MAC)."""
    if request.method == "POST":
        body = request.get_json(force=True, silent=True) or {}
        mac = body.get("mac")
        if not mac:
            return jsonify({"error": "mac required"}), 400
        from rogue import mark_known
        with db.get_db() as conn:
            mark_known(conn, mac, body.get("label"), body.get("note"))
        return jsonify({"ok": True})
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM known_devices ORDER BY added_ts DESC").fetchall()
    return jsonify({"known": [dict(r) for r in rows]})


@app.route("/api/rogue/<mac>/resolve", methods=["POST"])
def api_resolve_rogue(mac):
    """Dismiss a rogue alert (one-off visitor) without adding to known."""
    body = request.get_json(force=True, silent=True) or {}
    from rogue import resolve_rogue
    with db.get_db() as conn:
        resolve_rogue(conn, mac, body.get("note"))
    return jsonify({"ok": True})


@app.route("/api/stats")
def api_stats():
    now = time.time()
    current_cutoff = now - ACTIVE_WINDOW_S  # 10 min, matches /api/now
    with db.get_db() as conn:
        # current (active now)
        current = conn.execute(
            "SELECT COUNT(DISTINCT mac) c FROM sightings WHERE ts >= ?", (current_cutoff,)
        ).fetchone()["c"]
        # all-time
        total = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        # distinct WiFi networks (not radios): one Xfinity box advertises many
        # BSSIDs. Empty/hidden SSIDs collapse to a single "(hidden)" network.
        n_ap = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(NULLIF(ssid,''), '(hidden)')) c FROM wifi_aps"
        ).fetchone()["c"]
        n_sensors = conn.execute("SELECT COUNT(*) c FROM sensors").fetchone()["c"]
        # dedup'd device count (fingerprints merge rotated MACs + cross-radio)
        n_fp = conn.execute("SELECT COUNT(*) c FROM device_fingerprints").fetchone()["c"]
        # "real" devices: seen 3+ times (not a drive-by). The headline total
        # counts every MAC ever seen; this is the stable-device count.
        real = conn.execute("SELECT COUNT(*) c FROM devices WHERE sighting_count >= 3").fetchone()["c"]
        # stable devices: seen 2+ times (the KPI tile threshold — "multiple times")
        stable = conn.execute("SELECT COUNT(*) c FROM devices WHERE sighting_count >= 2").fetchone()["c"]
        last = conn.execute("SELECT MAX(ts) m FROM sightings").fetchone()["m"]
        # chart data: 24h activity rhythm (unique devices per hour, last 24h).
        # sightings_hourly dedups per (hour, mac, sensor, source) — one phone awake
        # 3h = 3 rows, not 180. A device seen multiple times in the same hour counts once.
        import collections
        rhythm = [0] * 24
        for r in conn.execute(
            "SELECT hour, COUNT(DISTINCT mac) c FROM sightings_hourly "
            "WHERE hour >= ? GROUP BY hour",
            (int((now - 86400) // 3600),)).fetchall():
            rhythm[time.localtime(r["hour"] * 3600).tm_hour] += r["c"]
        # device-type distribution (active now)
        type_counts = collections.Counter()
        for r in conn.execute("SELECT last_type FROM devices WHERE last_seen >= ?", (current_cutoff,)).fetchall():
            type_counts[r["last_type"] or "unknown"] += 1
        # signal-strength buckets (active now)
        rssi_buckets = {"near": 0, "mid": 0, "far": 0, "very far": 0}
        for r in conn.execute("SELECT rssi FROM sightings WHERE ts >= ? AND rssi IS NOT NULL", (current_cutoff,)).fetchall():
            v = r["rssi"]
            if v >= -60: rssi_buckets["near"] += 1
            elif v >= -70: rssi_buckets["mid"] += 1
            elif v >= -80: rssi_buckets["far"] += 1
            else: rssi_buckets["very far"] += 1
        # distinct active devices per signal source (last 10 min)
        source_counts = {"ble": 0, "wifi": 0, "mdns": 0}
        for r in conn.execute(
            "SELECT source, COUNT(DISTINCT mac) c FROM sightings "
            "WHERE ts >= ? AND source IS NOT NULL GROUP BY source",
            (current_cutoff,)).fetchall():
            src = r["source"]
            if src in ("ble", "bt"): source_counts["ble"] += r["c"]
            elif src in ("wifi", "mdns"): source_counts[src] = r["c"]
    return jsonify({
        "current": current, "total": total, "real": real, "stable": stable,
        "wifi": n_ap, "sensors": n_sensors, "fingerprints": n_fp,
        "last_scan": last, "source_counts": source_counts,
        "rhythm": rhythm, "type_counts": dict(type_counts), "rssi_buckets": rssi_buckets,
    })


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=8000)
