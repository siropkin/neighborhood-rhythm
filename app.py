"""app.py — Flask server. Dashboard + JSON API. Bound to 0.0.0.0:8000."""
import json
import time
from functools import wraps

from flask import Flask, request, jsonify, render_template, Response

import db
from config import SENSOR_ID, PEER_TOKEN, ACTIVE_WINDOW_S
from position import compute_position

app = Flask(__name__)


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
    with db.get_db() as conn:
        rows = db.latest_sighting_per_device(conn, cutoff)
        devices = [dict(r) for r in rows]
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
    with db.get_db() as conn:
        dev = conn.execute("SELECT * FROM devices WHERE mac=?", (mac,)).fetchone()
        sightings = conn.execute(
            "SELECT * FROM sightings WHERE mac=? ORDER BY ts", (mac,)
        ).fetchall()
    if not dev:
        return jsonify({"error": "not found"}), 404
    return jsonify({"device": dict(dev), "sightings": [dict(s) for s in sightings]})


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
        by_type = {r["last_type"]: r["c"] for r in conn.execute(
            "SELECT last_type, COUNT(*) c FROM devices GROUP BY last_type").fetchall()}
        n_ap = conn.execute("SELECT COUNT(*) c FROM wifi_aps").fetchone()["c"]
        n_sensors = conn.execute("SELECT COUNT(*) c FROM sensors").fetchone()["c"]
        last = conn.execute("SELECT MAX(ts) m FROM sightings").fetchone()["m"]
    return jsonify({
        "current": current, "total": total, "by_type": by_type,
        "wifi": n_ap, "sensors": n_sensors, "last_scan": last,
    })


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=8000)
