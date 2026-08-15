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
    source TEXT
);
-- Composite (mac, ts) serves: device history (ORDER BY ts), compute_position
-- (mac + time range, no sort), and the per-device latest-sighting lookup.
-- Drops the old single-column idx_sightings_mac + idx_sightings_sensor
-- (sensor_id alone isn't a query pattern; the sensor filter always pairs
-- with mac via this composite or with ts via idx_sightings_ts).
CREATE INDEX IF NOT EXISTS idx_sightings_mac_ts ON sightings(mac, ts);
CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(ts);
CREATE INDEX IF NOT EXISTS idx_sightings_sensor_ts ON sightings(sensor_id, ts);

-- Hourly rollup of raw sightings. The "rhythm" lives here (count + time
-- spread), not in raw rows. Kept indefinitely; raw sightings are pruned
-- after RETENTION_DAYS (see config). One row per (hour, mac, sensor, tech).
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
"""


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # WAL + synchronous=NORMAL: the critical Pi setting. FULL (default) fsyncs
    # every commit and wears the SD card; NORMAL loses at most the last txn on
    # power loss, acceptable for sightings. busy_timeout lets the writer wait
    # instead of erroring on contention.
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


def insert_sighting(conn, mac, sensor_id, ts, rssi, distance, name, services, source):
    # Dedup guard: bleak can double-callback the same device within a scan.
    # Same mac + sensor within DEDUP_WINDOW_S is one sighting, not two.
    conn.execute(
        """INSERT INTO sightings(mac, sensor_id, ts, rssi, distance, name, services, source)
           SELECT ?,?,?,?,?,?,?,?
           WHERE NOT EXISTS (
             SELECT 1 FROM sightings
             WHERE mac=? AND sensor_id=? AND ts BETWEEN ? AND ?
           )""",
        (mac, sensor_id, ts, rssi, distance, name, services, source,
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
    """Collapse one hour of raw sightings into sightings_hourly. Idempotent:
    re-running for the same hour replaces the rollup row (PRIMARY KEY)."""
    hour_end = hour_start + 3600
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
        (hour_start, hour_start, hour_end),
    )


def rollup_recent(conn, hours_back=2):
    """Roll up the last few hours (catch-up). Called by the collector each run."""
    now = time.time()
    for h in range(hours_back + 1):
        rollup_hour(conn, int((now - h * 3600) // 3600 * 3600))


def prune_raw(conn, retention_days):
    """Delete raw sightings older than retention_days (already rolled up).
    Keeps the hourly rollup forever; only raw rows are pruned."""
    cutoff = time.time() - retention_days * 86400
    conn.execute("DELETE FROM sightings WHERE ts < ?", (cutoff,))


def latest_sighting_per_device(conn, cutoff_ts):
    """Fast latest-sighting-per-device lookup for /api/now. Uses the (mac, ts)
    composite index — one ordered scan per device, no per-row sort."""
    return conn.execute(
        """SELECT d.*, s.rssi, s.distance, s.name, s.source
           FROM devices d
           JOIN sightings s ON s.id = (
               SELECT id FROM sightings
               WHERE mac = d.mac AND ts >= ? ORDER BY ts DESC LIMIT 1)
           WHERE d.last_seen >= ?""",
        (cutoff_ts, cutoff_ts),
    ).fetchall()


if __name__ == "__main__":
    init_db()
    print(f"initialized {DB_PATH}")
