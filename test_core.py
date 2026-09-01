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
from rogue import autoresolve_stale, detect_rogues, collapse_cohorts, MIN_SIGHTINGS
from insights import run_insights


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
    # fresh DB per test — the suite shares no state. db.py binds DB_PATH at
    # import, so reassign the module global (get_db/init_db read it per call).
    db.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init_db()
    conn = sqlite3.connect(db.DB_PATH)
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


def test_rogue_no_flag_resolve_loop():
    """A device gone >24h must not be (re)flagged — otherwise autoresolve at
    48h and detection loop forever (produced 7.4k junk events on 8/30-31)."""
    conn = _mk_conn()
    now = time.time()
    with conn:
        # stable, identifiable, enough sightings — but last seen 3 days ago
        conn.execute(
            "INSERT INTO devices (mac, oui_name, last_type, first_seen, last_seen, sighting_count) "
            "VALUES ('3C:BB:CC:DD:EE:09', 'Sonos', 'speaker', ?, ?, 50)",
            (now - 4 * 86400, now - 3 * 86400))
    new = detect_rogues(conn, now=now)
    assert new == [], new
    # seen an hour ago → flags fine
    with conn:
        conn.execute("UPDATE devices SET last_seen=? WHERE mac='3C:BB:CC:DD:EE:09'", (now - 3600,))
    new = detect_rogues(conn, now=now)
    assert len(new) == 1
    conn.close()


def test_rogue_cohort_collapse():
    conn = _mk_conn()
    now = time.time()
    with conn:
        # 5 same-vendor devices first seen the same day → cohort
        for i in range(5):
            mac = f"3C:BB:CC:DD:EE:{10+i:02X}"
            conn.execute(
                "INSERT INTO devices (mac, oui_name, first_seen, last_seen, sighting_count) VALUES (?,?,?,?,?)",
                (mac, "Vantiva", now - 86400, now, 10))
            conn.execute("INSERT INTO rogue_events (mac, first_seen, ts, oui_name) VALUES (?,?,?,?)",
                         (mac, now - 86400, now - 80000 + i, "Vantiva"))
        # 2 other-vendor devices same day → NOT a cohort
        for i in range(2):
            mac = f"3C:BB:CC:DD:EF:{10+i:02X}"
            conn.execute(
                "INSERT INTO devices (mac, oui_name, first_seen, last_seen, sighting_count) VALUES (?,?,?,?,?)",
                (mac, "Sonos", now - 86400, now, 10))
            conn.execute("INSERT INTO rogue_events (mac, first_seen, ts, oui_name) VALUES (?,?,?,?)",
                         (mac, now - 86400, now - 80000, "Sonos"))
    n = collapse_cohorts(conn)
    assert n == 4, n  # 4 of 5 Vantiva resolved, representative kept open
    open_rows = conn.execute(
        "SELECT r.mac, r.oui_name, r.note FROM rogue_events r WHERE r.resolved=0").fetchall()
    assert len(open_rows) == 3, open_rows  # 1 Vantiva rep + 2 Sonos
    rep = [r for r in open_rows if r["oui_name"] == "Vantiva"][0]
    assert "cohort" in rep["note"] and "1 of 5" in rep["note"]
    # cohort members joined the baseline (won't re-flag)
    assert conn.execute("SELECT COUNT(*) c FROM known_devices WHERE note LIKE 'cohort:%'").fetchone()["c"] == 4
    conn.close()


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


def _add_device(conn, mac, first, last, n=20, is_mine=0, label=None, oui="Sonos"):
    conn.execute(
        "INSERT INTO devices (mac, oui_name, first_seen, last_seen, sighting_count, is_mine, last_label) "
        "VALUES (?,?,?,?,?,?,?)",
        (mac, oui, first, last, n, is_mine, label))


def test_insights_new_resident():
    conn = _mk_conn()
    now = time.time()

    def seen_days(mac, days):
        for d in days:  # exactly 86400s apart → distinct UTC day buckets
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         (mac, "t", now - d * 86400 - 7200, "ble"))

    with conn:
        # baseline built 10 days ago → grace covers first_seen <= now-9d
        conn.execute("INSERT INTO known_devices (mac, added_ts) VALUES ('3C:BB:CC:DD:EE:21', ?)",
                     (now - 10 * 86400,))
        # stable MAC, 4-day span, active 4 distinct days, still here → resident
        _add_device(conn, "3C:BB:CC:DD:EE:20", now - 4 * 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:20", range(4))
        # known device → no insight
        _add_device(conn, "3C:BB:CC:DD:EE:21", now - 4 * 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:21", range(4))
        # open rogue alert → insights must not contradict the rogue queue
        _add_device(conn, "3C:BB:CC:DD:EE:24", now - 4 * 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:24", range(4))
        conn.execute("INSERT INTO rogue_events (mac, first_seen, ts) VALUES ('3C:BB:CC:DD:EE:24', ?, ?)",
                     (now - 4 * 86400, now - 3600))
        # day-one device (first_seen within 24h of the baseline) → not new
        _add_device(conn, "3C:BB:CC:DD:EE:25", now - 9.5 * 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:25", range(10))
        # 5-day span but only 2 active days → occasional visitor, not resident
        _add_device(conn, "3C:BB:CC:DD:EE:26", now - 5 * 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:26", (0, 4))
        # random MAC present 4 days → phone noise, no insight
        _add_device(conn, "6A:BB:CC:DD:EE:22", now - 4 * 86400, now - 3600)
        seen_days("6A:BB:CC:DD:EE:22", range(4))
        # only 1 day here → still a visitor
        _add_device(conn, "3C:BB:CC:DD:EE:23", now - 86400, now - 3600)
        seen_days("3C:BB:CC:DD:EE:23", (0,))
    n = run_insights(conn, now=now)
    assert n == 1, n
    rows = conn.execute("SELECT * FROM insights WHERE kind='new_resident'").fetchall()
    assert len(rows) == 1 and rows[0]["mac"] == "3C:BB:CC:DD:EE:20", [dict(r) for r in rows]
    assert "4 days" in rows[0]["text"]
    # dedup: a second pass writes nothing
    assert run_insights(conn, now=now + 300) == 0
    conn.close()


def test_insights_busyness():
    conn = _mk_conn()
    now = time.time()
    cur = int(now // 3600) * 3600 - 3600  # last complete hour
    with conn:
        # 8 trailing days of the same hour-of-day at ~10 devices
        for d in range(1, 9):
            h = cur - d * 86400
            for i in range(10):
                conn.execute(
                    "INSERT INTO sightings_hourly (hour, mac, sensor_id, source, n) VALUES (?,?,?,?,1)",
                    (h, f"3C:BB:CC:DD:{d:02X}:{i:02X}", "t", "ble"))
        # the spike hour: 30 devices (med 10, pstdev 0 → needs the +5 floor too)
        for i in range(30):
            conn.execute(
                "INSERT INTO sightings_hourly (hour, mac, sensor_id, source, n) VALUES (?,?,?,?,1)",
                (cur, f"3C:BB:CC:DD:FF:{i:02X}", "t", "ble"))
    n = run_insights(conn, now=now)
    assert n == 1, n
    r = conn.execute("SELECT * FROM insights WHERE kind='busyness'").fetchone()
    assert r and "30 devices" in r["text"] and "~10" in r["text"], dict(r)
    # dedup: same hour doesn't re-fire
    assert run_insights(conn, now=now + 300) == 0
    conn.close()


def test_insights_gone_missing_episode():
    conn = _mk_conn()
    now = time.time()
    mac = "3C:BB:CC:DD:EE:30"
    with conn:
        _add_device(conn, mac, now - 30 * 86400, now - 3 * 86400, is_mine=1, label="Kitchen speaker")
    n = run_insights(conn, now=now)
    assert n == 1, n
    r = conn.execute("SELECT * FROM insights WHERE kind='gone_missing'").fetchone()
    assert r and r["severity"] == "warn" and "3 days" in r["text"], dict(r)
    # same episode: still absent → no re-fire
    assert run_insights(conn, now=now + 86400) == 0
    # device returns, then goes missing again → NEW episode, re-fires
    with conn:
        conn.execute("UPDATE devices SET last_seen=? WHERE mac=?", (now + 2 * 86400, mac))
    assert run_insights(conn, now=now + 2 * 86400 + 3600) == 0  # back, seen recently
    n = run_insights(conn, now=now + 2 * 86400 + 49 * 3600)     # absent 49h again
    assert n == 1, n
    assert conn.execute("SELECT COUNT(*) c FROM insights WHERE kind='gone_missing'").fetchone()["c"] == 2
    conn.close()


def test_insights_gone_missing_fixture():
    """Untagged devices qualify as gone-missing only if they were de-facto
    fixtures (100+ sightings, active 5+ of the last 7 days)."""
    conn = _mk_conn()
    now = time.time()
    with conn:
        # fixture: 120 sightings, 5 active days in the last 7, gone 50h → fires
        _add_device(conn, "3C:BB:CC:DD:EE:32", now - 30 * 86400, now - 50 * 3600,
                    n=120, label="Hallway light")
        for d in (2, 3, 4, 5, 6):  # 86400s apart → 5 distinct UTC days, all in-window
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         ("3C:BB:CC:DD:EE:32", "t", now - d * 86400 - 3600, "ble"))
        # high-count but only 3 active days in-window → a visitor, no fire
        _add_device(conn, "3C:BB:CC:DD:EE:33", now - 30 * 86400, now - 50 * 3600, n=120)
        for d in (2, 3, 4):
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         ("3C:BB:CC:DD:EE:33", "t", now - d * 86400 - 3600, "ble"))
        # keep ble "alive" so the sensor_lost generator doesn't join in
        conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                     ("3C:BB:CC:DD:EE:32", "t", now - 60, "ble"))
    n = run_insights(conn, now=now)
    assert n == 1, n
    r = conn.execute("SELECT * FROM insights WHERE kind='gone_missing'").fetchone()
    assert r["mac"] == "3C:BB:CC:DD:EE:32" and "Hallway light" in r["text"], dict(r)
    conn.close()


def test_insights_sensor_lost():
    conn = _mk_conn()
    now = time.time()
    with conn:
        # wifi_probe: daily for 6 days, dark 2 days → lost
        for d in range(2, 8):
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         (f"3C:BB:CC:DD:AA:{d:02X}", "t", now - d * 86400, "wifi_probe"))
        # bt: sporadic (2 active days), dark 3 days → NOT a loss
        for d in (3, 10):
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         (f"3C:BB:CC:DD:BB:{d:02X}", "t", now - d * 86400, "bt"))
        # ble: active right now → fine
        conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                     ("3C:BB:CC:DD:CC:01", "t", now - 60, "ble"))
    n = run_insights(conn, now=now)
    assert n == 1, n
    r = conn.execute("SELECT * FROM insights WHERE kind='sensor_lost'").fetchone()
    assert r and r["text"].startswith("wifi_probe") and r["severity"] == "warn", dict(r)
    # same episode: the source stays dark → no re-fire
    assert run_insights(conn, now=now + 3600) == 0
    conn.close()


def test_footfall_bounds():
    conn = _mk_conn()
    now = time.time()
    with conn:
        # device A in 3 windows, B in 1, C+D sharing a fingerprint in 1 window
        _add_device(conn, "3C:BB:CC:DD:EE:40", now - 3600, now)
        _add_device(conn, "3C:BB:CC:DD:EE:41", now - 3600, now)
        _add_device(conn, "3C:BB:CC:DD:EE:42", now - 3600, now)
        _add_device(conn, "3C:BB:CC:DD:EE:43", now - 3600, now)
        conn.execute("UPDATE devices SET fingerprint_id='fp1' WHERE mac IN ('3C:BB:CC:DD:EE:42','3C:BB:CC:DD:EE:43')")
        for i in range(3):  # A present in windows 0,1,2 (15-min each)
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         ("3C:BB:CC:DD:EE:40", "t", now - i * 900 - 10, "ble"))
        conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                     ("3C:BB:CC:DD:EE:41", "t", now - 10, "ble"))
        for mac in ("3C:BB:CC:DD:EE:42", "3C:BB:CC:DD:EE:43"):  # same physical device
            conn.execute("INSERT INTO sightings (mac, sensor_id, ts, source) VALUES (?,?,?,?)",
                         (mac, "t", now - 10, "ble"))
    ff = db.footfall_bounds(conn, now=now)
    # window 0: A + B + fp1 = 3 physical devices; windows 1,2: A alone
    assert ff["max_concurrent"] == 3, ff
    assert ff["window_unique_sum"] == 5, ff  # 3 + 1 + 1
    conn.close()


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok {fn.__name__}")
    print(f"{len(fns)} checks passed")
