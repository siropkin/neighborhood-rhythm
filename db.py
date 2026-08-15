"""SQLite schema + helpers. Multi-sensor from day one."""
import sqlite3
import time
from contextlib import contextmanager

from config import DB_PATH


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
CREATE INDEX IF NOT EXISTS idx_sightings_mac ON sightings(mac);
CREATE INDEX IF NOT EXISTS idx_sightings_sensor ON sightings(sensor_id);
CREATE INDEX IF NOT EXISTS idx_sightings_ts ON sightings(ts);
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
    conn.execute("PRAGMA journal_mode=WAL")
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
    conn.execute(
        """INSERT INTO sightings(mac, sensor_id, ts, rssi, distance, name, services, source)
           VALUES(?,?,?,?,?,?,?,?)""",
        (mac, sensor_id, ts, rssi, distance, name, services, source),
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


if __name__ == "__main__":
    init_db()
    print(f"initialized {DB_PATH}")
