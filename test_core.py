"""Core-logic self-checks — no framework, run: python3 test_core.py
Covers the tricky invariants: random-MAC detection, distance clamp,
behavior transient bounds, rogue auto-resolve. Uses a temp DB.
Needs the OUI cache (oui.py) — present on any machine that runs the collector."""
import os
import tempfile
import time

os.environ["RHYTHM_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

import db
from rules import is_random_mac
from classify import classify
from position import _distance_from_rssi
from behavior import classify_behavior
from rogue import autoresolve_stale, detect_rogues, MIN_SIGHTINGS


def test_random_mac():
    assert is_random_mac("6A:BB:CC:DD:EE:FF") is True      # LA bit set
    assert is_random_mac("A4:CF:12:00:00:01") is False     # real OUI range
    assert is_random_mac("mdns:printer.local") is False    # pseudo-key
    assert is_random_mac("") is False
    # BLE static-random (top two bits): random only when OUI lookup misses
    assert is_random_mac("FC:11:22:33:44:55") is True      # no such OUI
    assert is_random_mac("FC:B0:DE:11:22:33") is False     # Cloud Network Tech (real OUI)


def test_distance_clamp():
    assert _distance_from_rssi(None) is None
    assert _distance_from_rssi(-85, 17) == 100.0           # lying tx_power capped
    assert _distance_from_rssi(-85, 12) == 100.0
    d = _distance_from_rssi(-85, -59)
    assert 5 < d < 15                                      # sane path untouched


def test_classify_wifi_private_mac():
    # phone with per-network private WiFi MAC, no name/OUI → phone-anon
    r = classify({"mac": "2E:D2:EE:CF:CC:61", "name": "", "oui_name": "",
                  "services": [], "source": "wifi", "is_random": True})
    assert r["type"] == "phone-anon", r
    # same MAC shape but with a vendor → stays for other rules (not phone-anon)
    r = classify({"mac": "2E:D2:EE:CF:CC:61", "name": "", "oui_name": "SomeVendor",
                  "services": [], "source": "wifi", "is_random": True})
    assert r["type"] != "phone-anon", r


def _mk_conn():
    import sqlite3
    db.init_db()
    conn = sqlite3.connect(os.environ["RHYTHM_DB"])
    conn.row_factory = sqlite3.Row
    return conn


def test_behavior_transient_span():
    conn = _mk_conn()
    now = time.time()
    mac = "3C:BB:CC:DD:EE:01"  # stable MAC (no LA bits, not 0xC0)
    # 5 sightings spread over 8 days → intermittent, NOT a multi-day "visitor"
    with conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO sightings (mac, sensor_id, ts, rssi, source) VALUES (?,?,?,?,?)",
                (mac, "t", now - 8 * 86400 + i * 2 * 86400, -80, "ble"))
    b = classify_behavior(conn, mac, now=now)
    assert b["behavior"] == "intermittent", b
    assert b["dwell_s"] is None
    # 5 sightings within one hour → transient visitor with bounded dwell
    mac2 = "3C:BB:CC:DD:EE:02"
    with conn:
        for i in range(5):
            conn.execute(
                "INSERT INTO sightings (mac, sensor_id, ts, rssi, source) VALUES (?,?,?,?,?)",
                (mac2, "t", now - 3000 + i * 300, -80, "ble"))
    b = classify_behavior(conn, mac2, now=now)
    assert b["behavior"] == "transient", b
    assert 0 < b["dwell_s"] <= 3600
    conn.close()


def test_rogue_autoresolve():
    conn = _mk_conn()
    now = time.time()
    gone_mac = "3C:BB:CC:DD:EE:03"    # last seen 3 days ago (stable MAC)
    live_mac = "3C:BB:CC:DD:EE:04"    # seen just now (stable MAC)
    with conn:
        for mac, last in ((gone_mac, now - 3 * 86400), (live_mac, now)):
            conn.execute(
                "INSERT INTO devices (mac, first_seen, last_seen, sighting_count) VALUES (?,?,?,?)",
                (mac, last - 100000, last, 10))
            conn.execute(
                "INSERT INTO rogue_events (mac, first_seen, ts) VALUES (?,?,?)",
                (mac, last - 100000, last - 50000))
    n = autoresolve_stale(conn, now=now)
    assert n == 1, n
    rows = {r["mac"]: r["resolved"] for r in conn.execute("SELECT mac, resolved FROM rogue_events")}
    assert rows[gone_mac] == 1 and rows[live_mac] == 0, rows
    conn.close()


def test_rogue_min_sightings():
    assert MIN_SIGHTINGS >= 5  # drive-by tail guard


def test_mac_normalization():
    assert db._norm_mac("28:56:5a:a1:5b:89") == "28:56:5A:A1:5B:89"
    assert db._norm_mac("4C:B9:EA:FA:F7:5B") == "4C:B9:EA:FA:F7:5B"
    assert db._norm_mac("mdns:printer.local") == "mdns:printer.local"  # pseudo-key untouched
    # migration uppercases historical rows
    conn = _mk_conn()
    with conn:
        conn.execute("INSERT INTO devices (mac, first_seen, last_seen) VALUES ('28:56:5a:a1:5b:89', 1, 2)")
    db.init_db()  # runs the migration
    assert conn.execute("SELECT COUNT(*) c FROM devices WHERE mac != UPPER(mac)").fetchone()["c"] == 0
    conn.close()


def test_smoothed_rssi_tukey():
    conn = _mk_conn()
    now = time.time()
    mac = "3C:BB:CC:DD:EE:05"
    # steady ~-70 with two spikes (-95, -40): fence drops them, mean ≈ -70
    vals = [-70, -71, -69, -70, -72, -68, -70, -71, -95, -40]
    with conn:
        for i, v in enumerate(vals):
            conn.execute(
                "INSERT INTO sightings (mac, sensor_id, ts, rssi, source) VALUES (?,?,?,?,?)",
                (mac, "t", now - (len(vals) - i) * 60, v, "ble"))
    s = db.smoothed_rssi(conn, mac)
    assert -71.5 <= s <= -69.0, s
    assert db.smoothed_rssi(conn, "00:00:00:00:00:00") is None
    conn.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok {fn.__name__}")
    print(f"{len(fns)} checks passed")
