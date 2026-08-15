"""app.py — Flask server. Dashboard + JSON API. Bound to 0.0.0.0:8000."""
import time
from functools import wraps

from flask import Flask, request, jsonify, render_template, Response

import db
from config import SENSOR_ID, PEER_TOKEN
from position import compute_position

app = Flask(__name__)


def _ts(t):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t)) if t else None


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
    cutoff = time.time() - 600  # seen in last 10 min
    with db.get_db() as conn:
        rows = db.latest_sighting_per_device(conn, cutoff)
        devices = [dict(r) for r in rows]
    return jsonify({"ts": time.time(), "sensor_id": SENSOR_ID, "devices": devices})


@app.route("/api/rhythm")
def api_rhythm():
    hours = int(request.args.get("hours", 24))
    since = time.time() - hours * 3600
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT mac, ts FROM sightings WHERE ts >= ? ORDER BY ts""", (since,)
        ).fetchall()
    # bucket by hour
    buckets = {}
    for r in rows:
        b = time.strftime("%Y-%m-%d %H:00", time.localtime(r["ts"]))
        buckets.setdefault(b, set()).add(r["mac"])
    series = [{"t": k, "count": len(v)} for k, v in sorted(buckets.items())]
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
    cutoff = now - 600  # match /api/now: devices seen in last 10 min
    with db.get_db() as conn:
        macs = [r["mac"] for r in conn.execute(
            "SELECT DISTINCT mac FROM sightings WHERE ts >= ?", (cutoff,)
        ).fetchall()]
    out = {}
    for mac in macs:
        # Use the same 10-min window so a device seen minutes ago still gets a ring.
        p = compute_position(mac, at_time=now, tolerance_s=600)
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
    """Server-Sent Events: push new sightings to the dashboard live.
    Polls SQLite for new sighting IDs since the last one the client saw.
    One-way, auto-reconnects in the browser — no WebSocket framing needed."""
    import json as _json

    def event_stream():
        last_id = int(request.args.get("since", "0"))
        while True:
            with db.get_db() as conn:
                rows = conn.execute(
                    "SELECT id, mac, name, rssi, distance, ts, source FROM sightings WHERE id > ? ORDER BY id LIMIT 50",
                    (last_id,),
                ).fetchall()
            for r in rows:
                last_id = r["id"]
                yield f"data: {_json.dumps(dict(r))}\n\n"
            # heartbeat so the connection stays alive + the client knows we're here
            yield ": ping\n\n"
            time.sleep(2)

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.route("/api/stats")
def api_stats():
    # "current" = devices seen in the last 10 min (matches the table/radar).
    # "total" = all devices ever seen (since the DB started).
    # The stats row shows current by default; total is available too.
    now = time.time()
    current_cutoff = now - 600  # 10 min, same as /api/now
    with db.get_db() as conn:
        # current (active now)
        current = conn.execute(
            "SELECT COUNT(DISTINCT mac) c FROM sightings WHERE ts >= ?", (current_cutoff,)
        ).fetchone()["c"]
        current_named = conn.execute(
            """SELECT COUNT(DISTINCT s.mac) c FROM sightings s JOIN devices d ON d.mac=s.mac
               WHERE s.ts >= ? AND d.last_label IS NOT NULL""", (current_cutoff,)
        ).fetchone()["c"]
        # all-time
        total = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        named = conn.execute("SELECT COUNT(*) c FROM devices WHERE last_label IS NOT NULL").fetchone()["c"]
        mine = conn.execute("SELECT COUNT(*) c FROM devices WHERE is_mine=1").fetchone()["c"]
        by_type = {r["last_type"]: r["c"] for r in conn.execute(
            "SELECT last_type, COUNT(*) c FROM devices GROUP BY last_type").fetchall()}
        n_ap = conn.execute("SELECT COUNT(*) c FROM wifi_aps").fetchone()["c"]
        n_sensors = conn.execute("SELECT COUNT(*) c FROM sensors").fetchone()["c"]
        last = conn.execute("SELECT MAX(ts) m FROM sightings").fetchone()["m"]
    return jsonify({
        "current": current, "current_named": current_named,
        "total": total, "named": named, "mine": mine, "by_type": by_type,
        "wifi": n_ap, "sensors": n_sensors, "last_scan": last,
    })


if __name__ == "__main__":
    db.init_db()
    app.run(host="0.0.0.0", port=8000)
