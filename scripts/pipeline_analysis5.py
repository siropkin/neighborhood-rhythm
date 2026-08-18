#!/usr/bin/env python3
"""Time each scan function individually to get the real wall-clock breakdown."""
import os
import sys
import time

APP_DIR = os.path.expanduser("~/neighborhood-rhythm")
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

def time_fn(name, fn, *args, **kwargs):
    t0 = time.time()
    try:
        result = fn(*args, **kwargs)
        elapsed = time.time() - t0
        n = len(result) if hasattr(result, '__len__') else (len(result[0]) if isinstance(result, tuple) else 0)
        print(f"  {name}: {elapsed:.2f}s ({n} items)")
        return result, elapsed
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  {name}: {elapsed:.2f}s (ERROR: {e})")
        return [], elapsed

def main():
    print("=== SCAN FUNCTION WALL-CLOCK TIMING ===\n")
    import collector

    # Time each scan function
    print("BLE scan (timeout=10):")
    ble, t_ble = time_fn("scan_ble", collector.scan_ble, timeout=10)

    print("\nClassic BT scan (timeout=8):")
    bt, t_bt = time_fn("scan_bt", collector.scan_bt, timeout=8)

    print("\nmDNS scan (timeout=8):")
    mdns, t_mdns = time_fn("scan_mdns", collector.scan_mdns, timeout=8)

    print("\nLAN scan (ARP):")
    lan, t_lan = time_fn("scan_lan", collector.scan_lan)

    print("\nWiFi probes (channel hop):")
    probes, t_probes = time_fn("scan_wifi_probes", collector.scan_wifi_probes)

    print("\nWiFi APs (iw scan):")
    wifi, t_wifi = time_fn("scan_wifi", collector.scan_wifi)

    total = t_ble + t_bt + t_mdns + t_lan + t_probes + t_wifi
    print(f"\n  TOTAL scan wall time: {total:.1f}s")
    print(f"  Breakdown:")
    print(f"    BLE:     {t_ble:5.1f}s ({t_ble/total*100:.0f}%)")
    print(f"    BT:      {t_bt:5.1f}s ({t_bt/total*100:.0f}%)")
    print(f"    mDNS:    {t_mdns:5.1f}s ({t_mdns/total*100:.0f}%)")
    print(f"    LAN:     {t_lan:5.1f}s ({t_lan/total*100:.0f}%)")
    print(f"    Probes:  {t_probes:5.1f}s ({t_probes/total*100:.0f}%)")
    print(f"    WiFi AP: {t_wifi:5.1f}s ({t_wifi/total*100:.0f}%)")

    # Now time fingerprint_all
    print("\n=== FINGERPRINT_ALL TIMING ===")
    import db
    from fingerprint import fingerprint_all
    with db.get_db() as conn:
        n_devs = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        t0 = time.time()
        n = fingerprint_all(conn)
        t_fp = time.time() - t0
    print(f"  fingerprint_all: {t_fp:.2f}s for {n_devs} devices ({n} fingerprints)")
    print(f"  This is {t_fp/(t_fp+total)*100:.0f}% of the total collector runtime")

    grand_total = total + t_fp
    print(f"\n  Grand total (scan + fingerprint): {grand_total:.1f}s")
    print(f"  Timer interval: 300s (5 min)")
    print(f"  Headroom: {300 - grand_total:.0f}s ({(300-grand_total)/300*100:.0f}%)")

if __name__ == "__main__":
    main()
