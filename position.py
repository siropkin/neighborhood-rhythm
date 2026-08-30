"""compute_position(mac, at_time, tolerance_s) -> ring / ring_pair / point.
1 sensor -> honest ring (distance, no angle). 2 -> arc. 3+ -> trilaterated point.
"""
import math
import time

import db


def _distance_from_rssi(rssi, ref_rssi=-59, n=2.7):
    """d = 10^((ref - rssi)/(10n)). Sign matters: (ref - rssi), not (rssi - ref),
    or distance shrinks as signal weakens (the bug that put everything at <1m)."""
    if rssi is None:
        return None
    # Advertised tx_power is often a lie — 113 devices claim +17 dBm, which put
    # them at 6 km. Clamp the reference to the realistic BLE band and cap the
    # result: past ~100 m the model is pure noise for BLE/WiFi in a building.
    ref_rssi = min(ref_rssi, 8)
    return min(10 ** ((ref_rssi - rssi) / (10 * n)), 100.0)


def _latest_per_sensor(rows):
    """Collapse sightings to one (latest) distance per sensor."""
    by_sensor = {}
    for r in rows:
        sid = r["sensor_id"]
        if sid not in by_sensor or r["ts"] > by_sensor[sid]["ts"]:
            by_sensor[sid] = dict(r)
    return list(by_sensor.values())


def _sensor_xy(conn, sensor_id):
    row = conn.execute("SELECT x, y, location_label FROM sensors WHERE sensor_id=?", (sensor_id,)).fetchone()
    if row and row["x"] is not None and row["y"] is not None:
        return row["x"], row["y"]
    return None, None


def _trilaterate(sensors, distances):
    """Least-squares trilateration. sensors=[(x,y,d)...]. Returns (x,y,error)."""
    if len(sensors) < 3:
        return None
    x0, y0, d0 = sensors[0]
    A, b = [], []
    for x, y, d in sensors[1:]:
        A.append([2 * (x - x0), 2 * (y - y0)])
        b.append(d0**2 - d**2 - x0**2 + x**2 - y0**2 + y**2)
    # Normal equations: (A^T A) x = A^T b
    import numpy as np
    A_m, b_v = np.array(A), np.array(b, dtype=float)
    sol, *_ = np.linalg.lstsq(A_m, b_v, rcond=None)
    px, py = float(sol[0]), float(sol[1])
    # Error: mean residual of distance equations.
    err = 0.0
    for x, y, d in sensors:
        err += abs(math.hypot(px - x, py - y) - d)
    return px, py, err / len(sensors)


def compute_position(mac, at_time=None, tolerance_s=60):
    at_time = at_time if at_time is not None else time.time()
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT sensor_id, ts, rssi, distance, tx_power FROM sightings
               WHERE mac=? AND ts BETWEEN ? AND ? ORDER BY ts DESC""",
            (mac, at_time - tolerance_s, at_time + tolerance_s),
        ).fetchall()
        if not rows:
            return None
        latest = _latest_per_sensor(rows)
        # Prefer a smoothed distance (rolling-median rssi) over a single noisy
        # sighting. Falls back to the stored distance, then to deriving from rssi.
        def dist(r):
            if r["distance"] is not None:
                return r["distance"]
            if r["rssi"] is not None:
                return _distance_from_rssi(r["rssi"])
            return None
        sensors_with_xy = []
        for r in latest:
            d = dist(r)
            if d is None:
                continue
            x, y = _sensor_xy(conn, r["sensor_id"])
            sensors_with_xy.append((r["sensor_id"], x, y, d))

        n = len(sensors_with_xy)
        if n == 0:
            return None
        if n == 1:
            sid, x, y, d = sensors_with_xy[0]
            # Single sensor: smoothed (rolling-median) distance over the one-shot sighting.
            sr = db.smoothed_rssi(conn, mac)
            if sr is not None and latest:
                ref = latest[0]["tx_power"] if latest[0]["tx_power"] is not None else -59
                d = _distance_from_rssi(sr, ref)
            return {"type": "ring", "sensor": sid, "distance": round(d, 2), "error": None}
        if n == 2:
            (s1, x1, y1, d1), (s2, x2, y2, d2) = sensors_with_xy
            return {
                "type": "ring_pair",
                "sensors": [s1, s2],
                "distances": [round(d1, 2), round(d2, 2)],
                "error": None,
            }
        # 3+ -> trilaterate if all sensors placed, else ring_pair of best two.
        placed = [(x, y, d) for _, x, y, d in sensors_with_xy if x is not None]
        if len(placed) >= 3:
            res = _trilaterate(placed, None)
            if res:
                px, py, err = res
                return {"type": "point", "x": round(px, 2), "y": round(py, 2), "error": round(err, 2)}
        # Not enough placed sensors — fall back to ring_pair.
        (s1, _, _, d1), (s2, _, _, d2) = sensors_with_xy[0], sensors_with_xy[1]
        return {"type": "ring_pair", "sensors": [s1, s2], "distances": [round(d1, 2), round(d2, 2)], "error": None}
