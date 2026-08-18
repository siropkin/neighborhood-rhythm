#!/usr/bin/env python3
"""Deeper profiling: fingerprint_all breakdown, scan timing from journal,
WAL checkpoint behavior, and the unknown-device OUI analysis."""
import os
import sys
import time
import json
import sqlite3
import subprocess

DB_PATH = os.path.expanduser("~/neighborhood-rhythm/rhythm.db")
APP_DIR = os.path.expanduser("~/neighborhood-rhythm")
sys.path.insert(0, APP_DIR)

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    print("=== FINGERPRINT_ALL BREAKDOWN ===")
    from fingerprint import fingerprint_all, _oui_prefix, _name_key, _mdns_serial, _extract_apple_tag

    conn = connect()
    n_devs = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]

    # Time the sig gather (N per-device queries)
    t0 = time.time()
    devs = conn.execute(
        "SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count FROM devices"
    ).fetchall()
    sig = {}
    for d in devs:
        mac = d["mac"]
        s = conn.execute(
            "SELECT name, services, extra, source FROM sightings WHERE mac=? ORDER BY ts DESC LIMIT 1",
            (mac,)).fetchone()
        sig[mac] = {
            "mac": mac, "oui": d["oui_name"], "oui_prefix": _oui_prefix(mac),
            "type": d["last_type"], "label": d["last_label"],
            "name": _name_key(s["name"] if s else None),
            "services": s["services"] if s else None,
            "apple": _extract_apple_tag(s["extra"] if s else None),
            "mdns_serial": _mdns_serial(mac), "source": s["source"] if s else None,
            "first_seen": d["first_seen"], "last_seen": d["last_seen"], "count": d["sighting_count"],
        }
    t_sig = time.time() - t0
    print(f"  Sig gather: {t_sig:.3f}s ({n_devs} per-device queries = {t_sig/n_devs*1000:.2f} ms/query)")

    # Time the cross-radio B2/B3 nested loops (the O(N^2) part)
    t0 = time.time()
    # B2: mDNS serial matches BLE device name
    for mac, s in sig.items():
        if not s["mdns_serial"]:
            continue
        host = s["mdns_serial"]
        for mac2, s2 in sig.items():
            if mac2 == mac or s2["mdns_serial"]:
                continue
            if s2["name"] and host in s2["name"]:
                pass
            elif s2["name"] and host.split("-")[0] in s2["name"]:
                pass
    t_b2 = time.time() - t0
    print(f"  B2 (mDNS serial -> BLE name, O(N^2)): {t_b2:.3f}s")

    # B3: same OUI prefix + same name
    t0 = time.time()
    for mac, s in sig.items():
        if not s["oui_prefix"] or not s["name"]:
            continue
        for mac2, s2 in sig.items():
            if mac2 == mac or not s2["oui_prefix"]:
                continue
            if s["oui_prefix"] == s2["oui_prefix"] and s["name"] == s2["name"]:
                pass
    t_b3 = time.time() - t0
    print(f"  B3 (OUI+name, O(N^2)): {t_b3:.3f}s")

    # Count how many devices actually have mdns_serial or oui_prefix+name
    n_mdns = sum(1 for s in sig.values() if s["mdns_serial"])
    n_oui_name = sum(1 for s in sig.values() if s["oui_prefix"] and s["name"])
    print(f"  Devices with mDNS serial: {n_mdns}")
    print(f"  Devices with OUI prefix + name: {n_oui_name}")
    print(f"  => B2 only iterates {n_mdns} x {n_devs} = {n_mdns*n_devs} (not full N^2)")
    print(f"  => B3 only iterates {n_oui_name} x {n_devs} = {n_oui_name*n_devs}")

    # Full fingerprint_all time (already measured: 8.183s). The dominant cost
    # is the sig gather (N queries), not the O(N^2) loops, because N_mdns and
    # N_oui_name are small.
    print(f"\n  Total fingerprint_all was 8.183s; sig gather = {t_sig:.3f}s, B2+B3 = {t_b2+t_b3:.3f}s")
    print(f"  Remaining: {8.183 - t_sig - t_b2 - t_b3:.3f}s (Pass A/C + write phase)")

    conn.close()

    print("\n=== SCAN TIMING (systemd journal) ===")
    # Get the last few collector run durations from the journal
    try:
        r = subprocess.run(
            ["journalctl", "-u", "neighborhood-rhythm-collector.service",
             "--since", "1 hour ago", "--no-pager", "-o", "short-iso"],
            capture_output=True, text=True, timeout=10)
        lines = r.stdout.splitlines()
        # Find "scanned N devices" lines to get completion time
        for line in lines[-20:]:
            if "scanned" in line or "rogue" in line:
                print(f"  {line.split(' ', 2)[-1] if len(line.split(' ', 2)) > 2 else line}")
    except Exception as e:
        print(f"  journalctl failed: {e}")

    # Get the actual service timing: time between start and finish
    try:
        r = subprocess.run(
            ["systemctl", "status", "neighborhood-rhythm-collector.service",
             "--no-pager"],
            capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines()[:15]:
            print(f"  {line}")
    except Exception as e:
        print(f"  systemctl failed: {e}")

    print("\n=== UNKNOWN DEVICE OUI ANALYSIS ===")
    conn = connect()
    # The 4980 unknowns: how many have an OUI we could classify?
    unknowns = conn.execute("""
        SELECT d.mac, d.oui_name, s.source, s.name, s.services
        FROM devices d
        LEFT JOIN (SELECT mac, source, name, services FROM sightings
                   GROUP BY mac ORDER BY ts DESC) s ON s.mac = d.mac
        WHERE d.last_type='unknown' OR d.last_type IS NULL
    """).fetchall()
    print(f"  Total unknowns: {len(unknowns)}")
    # Source breakdown
    src = {}
    for u in unknowns:
        src[u["source"] or "none"] = src.get(u["source"] or "none", 0) + 1
    print(f"  Unknowns by source: {src}")
    # How many are random MACs (phone-anon that fell through)?
    from rules import is_random_mac
    n_random = sum(1 for u in unknowns if is_random_mac(u["mac"]))
    n_stable = len(unknowns) - n_random
    print(f"  Unknowns with random MAC: {n_random}")
    print(f"  Unknowns with stable MAC: {n_stable}")
    # Stable unknowns with OUI — these are the ones we could classify
    n_stable_oui = sum(1 for u in unknowns if not is_random_mac(u["mac"]) and u["oui_name"])
    print(f"  Stable unknowns WITH OUI vendor: {n_stable_oui} (actionable for new OUI rules)")
    # What OUIs do the stable unknowns have?
    ouis = {}
    for u in unknowns:
        if not is_random_mac(u["mac"]) and u["oui_name"]:
            ouis[u["oui_name"]] = ouis.get(u["oui_name"], 0) + 1
    print(f"  Top OUI vendors among stable unknowns:")
    for oui, cnt in sorted(ouis.items(), key=lambda x: -x[1])[:10]:
        print(f"    {oui}: {cnt}")

    conn.close()

    print("\n=== WAL CHECKPOINT ===")
    conn = connect()
    # Check WAL checkpoint status
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    print(f"  journal_mode: {mode}")
    # Force a checkpoint to see how much WAL can be merged
    ckpt = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    print(f"  wal_checkpoint(TRUNCATE): busy={ckpt[0]} log={ckpt[1]} checkpointed={ckpt[2]}")
    # Re-check WAL size after checkpoint
    wal_path = DB_PATH + "-wal"
    if os.path.exists(wal_path):
        print(f"  WAL size after checkpoint: {os.path.getsize(wal_path)/1024:.0f} KB")
    conn.close()

    print("\n=== SCAN INTERVAL VS DURATION ===")
    # The timer fires every 5 min (300s). The scan takes ~11-20s. But
    # fingerprint_all adds 8s. So total collector runtime is ~19-28s.
    # That's fine within 300s, but the 8s fingerprint cost is 40% of scan time.
    print(f"  Timer interval: 300s (5 min)")
    print(f"  Scan (BLE+BT+mDNS+LAN+probe+WiFi): ~11-20s (median burst 11.7s)")
    print(f"  fingerprint_all: 8.2s")
    print(f"  rogue detect: <0.1s")
    print(f"  Total collector runtime: ~20-28s per cycle")

if __name__ == "__main__":
    main()
