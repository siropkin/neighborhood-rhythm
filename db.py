"""SQLite schema + helpers. Multi-sensor from day one."""
import sqlite3
import time
from contextlib import contextmanager

from config import DB_PATH, RETENTION_DAYS, DEDUP_WINDOW_S


SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    mac TEXT PRIMARY KEY,
    oui_name TEXT,
    first_seen REAL,
    last_seen REAL,
    last_type TEXT,
    last_label TEXT,
    sighting_count INTEGER DEFAULT 0,
    is_mine INTEGER DEFAULT 0,
    my_label TEXT
);
CREATE TABLE IF NOT EXISTS sightings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL,
    sensor_id TEXT NOT NULL,
    ts REAL NOT NULL,
    rssi REAL,
    distance REAL,
    name TEXT,
    services TEXT,
    source TEXT,
    tx_power REAL,
    extra TEXT              -- JSON: decoded Apple Continuity, sensor payloads
);
CREATE INDEX IF NOT EXISTS idx_sightings_mac_ts ON sightings(mac, ts);
CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(ts);
CREATE INDEX IF NOT EXISTS idx_sightings_sensor_ts ON sightings(sensor_id, ts);

-- Hourly rollup: the rhythm (count + time spread) lives here, kept forever;
-- raw sightings pruned after RETENTION_DAYS. One row per (hour, mac, sensor, tech).
CREATE TABLE IF NOT EXISTS sightings_hourly (
    hour        INTEGER NOT NULL,   -- epoch sec truncated to the hour
    mac         TEXT    NOT NULL,
    sensor_id   TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    n           INTEGER NOT NULL,   -- sighting count = the rhythm signal
    rssi_avg    REAL,
    rssi_min    REAL,
    rssi_max    REAL,
    distance_avg REAL,
    first_ts    REAL,
    last_ts     REAL,
    PRIMARY KEY (hour, mac, sensor_id, source)
);
CREATE INDEX IF NOT EXISTS idx_hourly_mac_hour ON sightings_hourly(mac, hour);
CREATE INDEX IF NOT EXISTS idx_hourly_hour ON sightings_hourly(hour);

CREATE TABLE IF NOT EXISTS sensors (
    sensor_id TEXT PRIMARY KEY,
    hostname TEXT,
    first_seen REAL,
    last_seen REAL,
    location_label TEXT,
    x REAL,
    y REAL
);
CREATE TABLE IF NOT EXISTS wifi_aps (
    bssid TEXT PRIMARY KEY,
    ssid TEXT,
    first_seen REAL,
    last_seen REAL,
    last_signal REAL,
    channel INTEGER
);

-- Device fingerprints: a stable identity above the rotating MAC layer.
-- One physical device = one fingerprint_id, even across MAC rotations and
-- across BLE/WiFi/mDNS radios. device_aliases maps many MACs → one fingerprint.
CREATE TABLE IF NOT EXISTS device_fingerprints (
    fingerprint_id  TEXT PRIMARY KEY,   -- uuid4, the stable device identity
    device_class    TEXT,                -- classify() type (phone/speaker/...)
    label           TEXT,                -- best human label
    first_seen      REAL,
    last_seen       REAL,
    sighting_count  INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0       -- max confidence of any link into this fp
);
CREATE TABLE IF NOT EXISTS device_aliases (
    mac             TEXT PRIMARY KEY,   -- a MAC or mdns: pseudo-key
    fingerprint_id  TEXT NOT NULL,      -- which physical device this is
    source          TEXT,               -- ble / bt / mdns / wifi
    first_seen      REAL,
    last_seen       REAL,
    sighting_count  INTEGER DEFAULT 0,
    link_confidence REAL,               -- confidence of the link that put this MAC here
    link_method     TEXT,               -- 'continuity' / 'cross-radio' / 'rotation' / 'direct'
    FOREIGN KEY (fingerprint_id) REFERENCES device_fingerprints(fingerprint_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_fp ON device_aliases(fingerprint_id);

-- Rogue-device detection: a device is "rogue" if it's a stable MAC (not a
-- rotating phone), seen consistently (2+ scans), and not in the known list.
-- known_devices: the baseline the user maintains (their own devices).
-- rogue_events: one row per new stable device that wasn't known.
CREATE TABLE IF NOT EXISTS known_devices (
    mac TEXT PRIMARY KEY,
    label TEXT,
    added_ts REAL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS rogue_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL,
    first_seen REAL NOT NULL,
    ts REAL NOT NULL,           -- when we flagged it
    oui_name TEXT,
    device_class TEXT,
    label TEXT,
    source TEXT,
    resolved INTEGER DEFAULT 0, -- 1 once the user marks it known/dismissed
    note TEXT
);
CREATE INDEX IF NOT EXISTS idx_rogue_mac ON rogue_events(mac);
CREATE INDEX IF NOT EXISTS idx_rogue_unresolved ON rogue_events(resolved);
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # synchronous=NORMAL (not FULL) avoids per-commit fsync — SD-card wear.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(SCHEMA)
        # Migrations: CREATE TABLE IF NOT EXISTS won't add a missing column
        # to an existing table, so ALTER explicitly.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(sightings)")}
        if "tx_power" not in cols:
            conn.execute("ALTER TABLE sightings ADD COLUMN tx_power REAL")
        if "extra" not in cols:
            conn.execute("ALTER TABLE sightings ADD COLUMN extra TEXT")
        dcols = {r[1] for r in conn.execute("PRAGMA table_info(devices)")}
        if "fingerprint_id" not in dcols:
            conn.execute("ALTER TABLE devices ADD COLUMN fingerprint_id TEXT")


def upsert_device(conn, mac, oui_name, ts, dev_type, label):
    conn.execute(
        """INSERT INTO devices(mac, oui_name, first_seen, last_seen, last_type, last_label, sighting_count)
           VALUES(?,?,?,?,?,?,1)
           ON CONFLICT(mac) DO UPDATE SET
             oui_name=COALESCE(excluded.oui_name, devices.oui_name),
             last_seen=excluded.last_seen,
             last_type=COALESCE(excluded.last_type, devices.last_type),
             last_label=COALESCE(excluded.last_label, devices.last_label),
             sighting_count=devices.sighting_count+1""",
        (mac, oui_name, ts, ts, dev_type, label),
    )


def insert_sighting(conn, mac, sensor_id, ts, rssi, distance, name, services, source,
                     tx_power=None, extra=None):
    # Dedup guard: bleak can double-callback the same device within a scan.
    # Same mac + sensor within DEDUP_WINDOW_S is one sighting, not two.
    import json
    extra_json = json.dumps(extra) if extra else None
    conn.execute(
        """INSERT INTO sightings(mac, sensor_id, ts, rssi, distance, name, services, source, tx_power, extra)
           SELECT ?,?,?,?,?,?,?,?,?,?
           WHERE NOT EXISTS (
             SELECT 1 FROM sightings
             WHERE mac=? AND sensor_id=? AND ts BETWEEN ? AND ?
           )""",
        (mac, sensor_id, ts, rssi, distance, name, services, source, tx_power, extra_json,
         mac, sensor_id, ts - DEDUP_WINDOW_S, ts),
    )


def upsert_wifi_ap(conn, bssid, ssid, signal, channel, ts):
    conn.execute(
        """INSERT INTO wifi_aps(bssid, ssid, first_seen, last_seen, last_signal, channel)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(bssid) DO UPDATE SET
             ssid=COALESCE(excluded.ssid, wifi_aps.ssid),
             last_seen=excluded.last_seen,
             last_signal=excluded.last_signal,
             channel=COALESCE(excluded.channel, wifi_aps.channel)""",
        (bssid, ssid, ts, ts, signal, channel),
    )


def register_sensor(conn, sensor_id, hostname, location_label=None, x=None, y=None):
    now = time.time()
    conn.execute(
        """INSERT INTO sensors(sensor_id, hostname, first_seen, last_seen, location_label, x, y)
           VALUES(?,?,?,?,?,?,?)
           ON CONFLICT(sensor_id) DO UPDATE SET
             hostname=COALESCE(excluded.hostname, sensors.hostname),
             last_seen=excluded.last_seen,
             location_label=COALESCE(excluded.location_label, sensors.location_label),
             x=COALESCE(excluded.x, sensors.x),
             y=COALESCE(excluded.y, sensors.y)""",
        (sensor_id, hostname, now, now, location_label, x, y),
    )


def rollup_hour(conn, hour_start):
    """Collapse one hour of raw sightings into sightings_hourly (idempotent via PRIMARY KEY)."""
    conn.execute(
        """INSERT OR REPLACE INTO sightings_hourly
           (hour, mac, sensor_id, source, n, rssi_avg, rssi_min, rssi_max,
            distance_avg, first_ts, last_ts)
           SELECT ?, mac, sensor_id, source, COUNT(*),
                  AVG(rssi), MIN(rssi), MAX(rssi), AVG(distance),
                  MIN(ts), MAX(ts)
           FROM sightings
           WHERE ts >= ? AND ts < ?
           GROUP BY mac, sensor_id, source""",
        (hour_start, hour_start, hour_start + 3600),
    )


def rollup_recent(conn, hours_back=2):
    now = time.time()
    for h in range(hours_back + 1):
        rollup_hour(conn, int((now - h * 3600) // 3600 * 3600))


def prune_raw(conn, retention_days):
    """Delete raw sightings older than retention_days (already rolled up)."""
    conn.execute("DELETE FROM sightings WHERE ts < ?", (time.time() - retention_days * 86400,))


def latest_sighting_per_device(conn, cutoff_ts):
    """Latest sighting per device for /api/now — uses the (mac, ts) composite index."""
    return conn.execute(
        """SELECT d.*, s.rssi, s.distance, s.name, s.source, s.tx_power
           FROM devices d
           JOIN sightings s ON s.id = (
               SELECT id FROM sightings
               WHERE mac = d.mac AND ts >= ? ORDER BY ts DESC LIMIT 1)
           WHERE d.last_seen >= ?""",
        (cutoff_ts, cutoff_ts),
    ).fetchall()


def smoothed_rssi(conn, mac, window=11):
    """Rolling-median RSSI over the last `window` readings — cuts per-sample distance noise."""
    rows = conn.execute(
        "SELECT rssi FROM sightings WHERE mac=? AND rssi IS NOT NULL ORDER BY ts DESC LIMIT ?",
        (mac, window),
    ).fetchall()
    if not rows:
        return None
    vals = sorted(r["rssi"] for r in rows)
    return vals[len(vals) // 2]


if __name__ == "__main__":
    init_db()
    print(f"initialized {DB_PATH}")
