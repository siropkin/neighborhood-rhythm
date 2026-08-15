"""collector.py — runs BLE+BT+WiFi+mDNS scans, classifies, upserts to SQLite.
Runs on a systemd timer (separate from the web process). Idempotent + resumable.
"""
import os
import re
import subprocess
import sys
import time

import db
import oui
from classify import classify
from config import SENSOR_ID, RETENTION_DAYS
from position import _distance_from_rssi
from rules import is_random_mac
from enrich import enrich


def _now():
    return time.time()


# Per-class TX power defaults (dBm @ 1m) when the device doesn't advertise tx.
# ponytail: rough defaults from research; refine after a week of data.
_TX_DEFAULTS = {
    "phone": -65, "phone-anon": -65, "wearable": -75, "beacon": -59,
    "light": -59, "iot": -59, "iot-esp32": -59, "sensor": -59,
    "tv": -55, "speaker": -55, "laptop": -65, "computer": -65,
    "apple-device": -65, "samsung-device": -65, "vacuum": -59,
}


def _tx_default(dev_type):
    return _TX_DEFAULTS.get(dev_type, -59)


# --- BLE via bleak ---
def scan_ble(timeout=10):
    """Returns list of {mac, name, rssi, services}. Uses advertisement-data API
    so rssi + service UUIDs are captured (the plain discover() form drops them)."""
    try:
        from bleak import BleakScanner  # type: ignore
    except ImportError:
        print("bleak not installed; skipping BLE", file=sys.stderr)
        return []
    out = []
    try:
        import asyncio

        async def _scan():
            # return_adv=True gives (BLEDevice, AdvertisementData) per device.
            return await BleakScanner.discover(timeout=timeout, return_adv=True)

        # Hard ceiling: bleak's internal timeout=10 is the polite exit; this
        # outer wait_for kills the scan at 15s even if bleak hangs (BlueZ
        # dbus can stall). Catch TimeoutError, degrade to [].
        devs = asyncio.run(asyncio.wait_for(_scan(), timeout=timeout + 5))
        for addr, (dev, adv) in devs.items():
            name = dev.name or getattr(adv, "local_name", "") or ""
            services = [str(u) for u in (adv.service_uuids or [])]
            out.append({
                "mac": dev.address,
                "name": name,
                "rssi": adv.rssi,
                "tx_power": adv.tx_power,
                "services": services,
                "manufacturer_data": {str(k): v.hex() for k, v in (adv.manufacturer_data or {}).items()},
                "service_data": {str(k): v.hex() for k, v in (adv.service_data or {}).items()},
            })
    except asyncio.TimeoutError:
        print("BLE scan timed out; returning partial results", file=sys.stderr)
    except Exception as e:
        print(f"BLE scan failed: {e}", file=sys.stderr)
    return out


# --- Classic BT via hcitool (slow/flaky, degrades gracefully) ---
def scan_bt(timeout=8):
    # ponytail: hcitool is deprecated + flaky; short timeout, ignore failures.
    try:
        r = subprocess.run(
            ["hcitool", "scan", "--flush", "--timeout", str(timeout)],
            capture_output=True, text=True, timeout=timeout + 2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    out = []
    for line in r.stdout.splitlines():
        m = re.match(r"\s*([0-9A-Fa-f:]{17})\s+(.+)", line)
        if m:
            out.append({"mac": m.group(1), "name": m.group(2), "rssi": None, "services": []})
    return out


# --- WiFi APs via iw ---
def scan_wifi():
    try:
        r = subprocess.run(["iw", "dev", "wlan0", "scan"], capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    aps = []
    cur = {}
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("BSS "):
            if cur.get("bssid"):
                aps.append(cur)
            cur = {"bssid": line.split()[1].split("(")[0]}
        elif line.startswith("SSID:"):
            cur["ssid"] = line.split(":", 1)[1].strip()
        elif line.startswith("freq:"):
            # freq MHz -> channel (2.4GHz: 2412=1..; 5GHz: 5000+channel). Approximate.
            freq = int(float(line.split(":")[1].strip()))
            cur["channel"] = (freq - 2412) // 5 + 1 if freq < 5000 else freq - 5000
        elif line.startswith("signal:"):
            m = re.search(r"(-?\d+\.\d+)", line)
            cur["signal"] = float(m.group(1)) if m else None
    if cur.get("bssid"):
        aps.append(cur)
    return aps


# --- mDNS via avahi-browse ---
def scan_mdns(timeout=5):
    try:
        r = subprocess.run(
            ["avahi-browse", "-a", "-r", "-t"],
            capture_output=True, text=True, timeout=timeout + 5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    out = []
    cur = {}
    for line in r.stdout.splitlines():
        if line.startswith("="):
            # = wlan0 IPv4 MacBook Pro _airplay._tcp local
            parts = line.split()
            if len(parts) >= 5:
                cur = {"name": " ".join(parts[3:-2]), "service": parts[-2], "mac": None, "rssi": None}
        elif line.startswith("   hostname ="):
            cur["hostname"] = line.split("=", 1)[1].strip().rstrip(".")
        elif line.startswith("   address =") and "mac" not in cur:
            # avahi gives IP, not MAC; we key mDNS by hostname+service
            pass
        elif line == "" and cur:
            out.append(cur)
            cur = {}
    if cur:
        out.append(cur)
    return out


def _store_device(conn, raw, source):
    mac = raw.get("mac")
    if not mac:
        return None
    ts = _now()
    oui_name = oui.lookup(mac)
    raw["oui_name"] = oui_name
    raw["is_random"] = is_random_mac(mac)
    result = classify(raw)
    rssi = raw.get("rssi")
    tx_power = raw.get("tx_power")
    # Distance: use tx_power as the reference when present (per-class default
    # otherwise), then smooth at query time via a rolling median.
    ref = tx_power if tx_power is not None else _tx_default(result["type"])
    distance = _distance_from_rssi(rssi, ref) if rssi is not None else None
    services = ",".join(raw.get("services", []))
    extra = enrich(raw)  # decoded Apple Continuity / sensor payloads (may be None)
    db.insert_sighting(conn, mac, SENSOR_ID, ts, rssi, distance, raw.get("name"),
                       services, source, tx_power, extra)
    db.upsert_device(conn, mac, oui_name, ts, result["type"], result["label"])
    return mac


def main():
    db.init_db()
    with db.get_db() as conn:
        db.register_sensor(conn, SENSOR_ID, os.environ.get("HOSTNAME", SENSOR_ID))
        n_dev = 0
        for raw in scan_ble():
            if _store_device(conn, raw, "ble"):
                n_dev += 1
        for raw in scan_bt():
            if _store_device(conn, raw, "bt"):
                n_dev += 1
        # mDNS: no MAC, key by hostname+service as a pseudo-device
        for raw in scan_mdns():
            pseudo_mac = f"mdns:{raw.get('hostname') or raw.get('name')}:{raw.get('service')}"
            raw["mac"] = pseudo_mac
            raw["services"] = [raw.get("service", "")]
            if _store_device(conn, raw, "mdns"):
                n_dev += 1
        # WiFi APs
        n_ap = 0
        for ap in scan_wifi():
            bssid = ap.get("bssid")
            if bssid:
                db.upsert_wifi_ap(conn, bssid, ap.get("ssid"), ap.get("signal"), ap.get("channel"), _now())
                n_ap += 1
        # Roll up the last couple hours + prune raw sightings older than retention.
        # Keeps storage bounded; the hourly rollup preserves the rhythm forever.
        db.rollup_recent(conn, hours_back=2)
        db.prune_raw(conn, RETENTION_DAYS)
    _fix_db_perms()
    print(f"scanned {n_dev} devices, {n_ap} APs, stored (sensor={SENSOR_ID})")


def _fix_db_perms():
    """Collector runs as root; hand the DB back to the siropkin group so the
    web service (running as siropkin) can read/write it. No-op if not root."""
    import glob
    from config import DB_PATH
    if os.geteuid() != 0:
        return
    import pwd, grp
    uid = pwd.getpwnam("siropkin").pw_uid
    gid = grp.getgrnam("siropkin").gr_gid
    for path in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"]:
        if os.path.exists(path):
            os.chown(path, uid, gid)
            os.chmod(path, 0o664)


if __name__ == "__main__":
    main()
