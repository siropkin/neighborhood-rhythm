"""collector.py — BLE+BT+WiFi+mDNS scans, classify, upsert to SQLite.
Runs on a systemd timer (separate from the web process)."""
import os
import re
import subprocess
import sys
import time

import db
import oui
from classify import classify
from config import SENSOR_ID, RETENTION_DAYS, BLE_RSSI_FLOOR
from position import _distance_from_rssi
from rules import is_random_mac, HAP_CATEGORY
from enrich import enrich


def _now():
    return time.time()


# Per-class TX power defaults (dBm @ 1m) when the device doesn't advertise tx.
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
    """BLE scan. return_adv=True captures rssi + service UUIDs (plain discover() drops them)."""
    try:
        from bleak import BleakScanner  # type: ignore
    except ImportError:
        print("bleak not installed; skipping BLE", file=sys.stderr)
        return []
    out = []
    try:
        import asyncio

        async def _scan():
            return await BleakScanner.discover(timeout=timeout, return_adv=True)

        # Outer wait_for is a hard ceiling in case BlueZ/dbus stalls.
        devs = asyncio.run(asyncio.wait_for(_scan(), timeout=timeout + 5))
        for addr, (dev, adv) in devs.items():
            # Ignore very weak ads: below BLE_RSSI_FLOOR is a drive-by outside
            # the building, not a device in it. -85 dBm is the seam between
            # real devices (median -80) and drive-bys (median -89). Calibrate
            # per-environment — move the Pi, re-check the histogram.
            if adv.rssi is not None and adv.rssi < BLE_RSSI_FLOOR:
                continue
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
    mac_re = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("BSS "):
            if cur.get("bssid"):
                aps.append(cur)
            # iw emits "BSS Load:" (the BSS Load element) as a sub-line; after
            # strip() it matches "BSS " — reject anything that isn't a real MAC.
            bssid = line.split()[1].split("(")[0]
            cur = {"bssid": bssid} if mac_re.match(bssid) else {}
        elif line.startswith("SSID:"):
            ssid = line.split(":", 1)[1].strip()
            # null-byte / unprintable SSIDs from misbehaving APs -> hidden
            cur["ssid"] = ssid if ssid and "\x00" not in ssid else None
        elif line.startswith("freq:"):
            # freq MHz -> channel. 2.4GHz: 2412=ch1..; 5GHz: 5000+ch*5 (5180=ch36).
            freq = int(float(line.split(":")[1].strip()))
            cur["channel"] = (freq - 2412) // 5 + 1 if freq < 5000 else (freq - 5000) // 5
        elif line.startswith("signal:"):
            m = re.search(r"(-?\d+\.\d+)", line)
            cur["signal"] = float(m.group(1)) if m else None
    if cur.get("bssid"):
        aps.append(cur)
    return aps


# --- LAN clients via the ARP table (WiFi devices on our own network) ---
# scan_wifi sees APs (routers), not clients. The Pi is already on the network,
# so its ARP table lists every device that's talked to it — phones, laptops,
# cameras, IoT — with their MAC + IP. No monitor mode, no extra hardware.
# A quick ping sweep populates the table; devices that block ICMP still show
# if they've talked to the Pi recently (mDNS, the dashboard fetch, etc.).
def scan_lan():
    import ipaddress
    # find our IPv4 subnet on wlan0
    try:
        r = subprocess.run(["ip", "-4", "addr", "show", "wlan0"],
                           capture_output=True, text=True, timeout=5)
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/(\d+)", r.stdout)
        if not m:
            return []
        net = ipaddress.ip_network(f"{m.group(1)}/{m.group(2)}", strict=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    # ping sweep to populate the ARP table (devices that block ICMP won't
    # reply, but many will; the rest are caught if they've talked recently).
    # Parallel via a thread pool — 128 hosts in ~2s, not 128s.
    import concurrent.futures
    hosts = [str(h) for h in net.hosts() if str(h) != m.group(1)][:128]
    def _ping(h):
        subprocess.run(["ping", "-c1", "-W1", h], capture_output=True, timeout=2)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
            list(ex.map(_ping, hosts))
    except Exception:
        pass
    # --- mDNS via zeroconf (resolves TXT records: model, category, WiFi MAC) ---
    # read the ARP table — only reachable/stale entries with a MAC
    try:
        r = subprocess.run(["ip", "neigh", "show", "dev", "wlan0"],
                           capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    out = []
    mac_re = re.compile(r"[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}")
    for line in r.stdout.splitlines():
        parts = line.split()
        # "192.168.1.85 lladdr 00:71:47:4e:82:70 STALE" or "... router ..."
        if len(parts) < 4 or parts[1] != "lladdr":
            continue
        ip = parts[0]
        mac = parts[2]
        if not mac_re.match(mac) or "FAILED" in parts:
            continue
        out.append({"mac": mac, "ip": ip, "name": "", "rssi": None, "services": []})
    return out


# --- mDNS via zeroconf (resolves TXT records: model, category, WiFi MAC) ---
# The service types that carry the richest data. Browse these explicitly rather
# than a meta-browse — faster, and we only care about these.
MDNS_TYPES = [
    "_airplay._tcp.local.", "_googlecast._tcp.local.", "_raop._tcp.local.",
    "_spotify-connect._tcp.local.", "_hap._tcp.local.", "_ipp._tcp.local.",
    "_smb._tcp.local.", "_ssh._tcp.local.", "_esphome._tcp.local.",
    "_yandexio._tcp.local.",
]


def scan_mdns(timeout=8):
    """Browse mDNS service types, resolve TXT records. Returns {name, service, hostname, model, category}."""
    try:
        from zeroconf import Zeroconf, ServiceBrowser
    except ImportError:
        return []

    class Collect:
        def __init__(self):
            self.services = []  # (type_, name) pairs; resolve after browse

        def add_service(self, zc, type_, name):
            self.services.append((type_, name))

        def update_service(self, zc, type_, name):
            pass

        def remove_service(self, zc, type_, name):
            pass

    try:
        zc = Zeroconf()
    except OSError:
        return []
    c = Collect()
    for t in MDNS_TYPES:
        ServiceBrowser(zc, t, c)
    # let it discover for `timeout` seconds, then resolve on the main thread
    # (not inside the browser callback) so zc.close() can't interrupt an
    # in-flight get_service_info and drop a mid-resolve service.
    time.sleep(timeout)
    try:
        seen = []
        for type_, name in c.services:
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                continue
            seen.append({
                "name": name.replace("." + type_, ""),
                "service": type_,
                "hostname": (info.server or "").rstrip("."),
                "txt": info.decoded_properties or {},
            })
    finally:
        zc.close()

    # enrich each with model + category from the TXT records
    out = []
    for d in seen:
        txt = d.get("txt") or {}
        model = txt.get("model") or txt.get("md") or txt.get("ty") or txt.get("usb_MDL")
        category = None
        ci = txt.get("ci")
        if ci and ci.isdigit():
            category = HAP_CATEGORY.get(int(ci))
        d["model"] = model
        d["category"] = category
        d["mac"] = None
        d["rssi"] = None
        d["services"] = [d["service"]]
        out.append(d)
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
        # mDNS: no MAC — key by hostname so one physical device (advertising
        # multiple services: _airplay + _raop + _hap) is one row, not N rows.
        for raw in scan_mdns():
            raw["mac"] = f"mdns:{raw.get('hostname') or raw.get('name')}"
            raw["services"] = [raw.get("service", "")]
            if _store_device(conn, raw, "mdns"):
                n_dev += 1
        # LAN clients: WiFi devices on our own network (ARP table). These are
        # the actual devices (phones/laptops/cameras/IoT), not the APs.
        for raw in scan_lan():
            if _store_device(conn, raw, "wifi"):
                n_dev += 1
        n_ap = 0
        for ap in scan_wifi():
            bssid = ap.get("bssid")
            if bssid:
                db.upsert_wifi_ap(conn, bssid, ap.get("ssid"), ap.get("signal"), ap.get("channel"), _now())
                n_ap += 1
        db.rollup_recent(conn, hours_back=2)
        db.prune_raw(conn, RETENTION_DAYS)
        db.prune_transient_devices(conn)  # drop single-sighting drive-bys
        # recompute device fingerprints (cross-radio + rotation linking).
        # cheap on ~1k devices; idempotent.
        from fingerprint import fingerprint_all
        fingerprint_all(conn)
        # rogue-device detection: flag new stable-MAC devices not in baseline.
        from rogue import detect_rogues
        rogues = detect_rogues(conn)
        if rogues:
            print(f"  {len(rogues)} new rogue device(s)")
    _fix_db_perms()
    print(f"scanned {n_dev} devices, {n_ap} APs, stored (sensor={SENSOR_ID})")


def _fix_db_perms():
    """Hand the DB back to siropkin (collector runs as root). No-op if not root."""
    from config import DB_PATH
    if os.geteuid() != 0:
        return
    import pwd, grp
    uid, gid = pwd.getpwnam("siropkin").pw_uid, grp.getgrnam("siropkin").gr_gid
    for path in [DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"]:
        if os.path.exists(path):
            os.chown(path, uid, gid)
            os.chmod(path, 0o664)


if __name__ == "__main__":
    main()
