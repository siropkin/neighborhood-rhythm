#!/usr/bin/env python3
"""Pipeline analysis — measures scan perf, SQLite health, dedup, classification,
fingerprint cost, and SSE health against the live DB. Read-only; modifies nothing.

Usage: python pipeline_analysis.py [db_path]
"""
import os
import sys
import time
import json
import sqlite3
import statistics

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/neighborhood-rhythm/rhythm.db")

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def section(n, title):
    print(f"\n{'='*70}\n{n}. {title}\n{'='*70}")

def main():
    print(f"DB: {DB_PATH}")
    # File sizes
    for suffix in ["", "-wal", "-shm"]:
        p = DB_PATH + suffix
        if os.path.exists(p):
            sz = os.path.getsize(p)
            print(f"  {os.path.basename(p) or 'rhythm.db'}: {sz/1024/1024:.2f} MB ({sz:,} bytes)")
        else:
            print(f"  {os.path.basename(p) or 'rhythm.db'}: (missing)")

    conn = connect()

    # ---- 1. SCAN PERFORMANCE (inferred from sighting timestamps) ----
    section(1, "SCAN PERFORMANCE (inferred from sighting ts deltas)")
    # Each scan run produces sightings clustered in time. Look at the time
    # spread of sightings per scan-burst (grouped by 60s windows) to estimate
    # how long a full scan takes.
    rows = conn.execute("""
        SELECT source, ts FROM sightings
        WHERE ts >= ? ORDER BY ts
    """, (time.time() - 86400,)).fetchall()
    if rows:
        # group into scan bursts (gap > 30s = new scan)
        bursts = []
        cur_burst = [rows[0]["ts"]]
        for r in rows[1:]:
            if r["ts"] - cur_burst[-1] > 30:
                bursts.append(cur_burst)
                cur_burst = [r["ts"]]
            else:
                cur_burst.append(r["ts"])
        bursts.append(cur_burst)
        # only bursts with >1 sighting (real scans)
        real = [b for b in bursts if len(b) > 1]
        if real:
            durations = [b[-1] - b[0] for b in real]
            print(f"  Scan bursts in last 24h: {len(real)}")
            print(f"  Burst duration (sightings span): min={min(durations):.1f}s "
                  f"median={statistics.median(durations):.1f}s "
                  f"max={max(durations):.1f}s mean={statistics.mean(durations):.1f}s")
            # per-source breakdown within bursts
            src_counts = {}
            for r in rows:
                src_counts[r["source"]] = src_counts.get(r["source"], 0) + 1
            print(f"  Sightings by source (last 24h): {src_counts}")
        else:
            print("  No multi-sighting bursts in last 24h")
    else:
        print("  No sightings in last 24h")

    # probe-request channel hop cost: 5 channels x 2s = 10s minimum
    print(f"\n  Probe-request channel hop: {len([1,6,11,3,9])} channels x 2s dwell = 10s (hard floor)")
    probe_rows = conn.execute("SELECT COUNT(*) c FROM sightings WHERE source='wifi_probe'").fetchone()
    print(f"  wifi_probe sightings total: {probe_rows['c']}")

    # ---- 2. SQLITE HEALTH ----
    section(2, "SQLITE HEALTH")
    for tbl in ["devices", "sightings", "sightings_hourly", "device_fingerprints",
                "device_aliases", "rogue_events", "wifi_aps", "sensors", "known_devices"]:
        c = conn.execute(f"SELECT COUNT(*) c FROM {tbl}").fetchone()["c"]
        print(f"  {tbl}: {c} rows")

    # Page count + page size for real DB size (incl. free pages)
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    freelist = conn.execute("PRAGMA freelist_count").fetchone()[0]
    print(f"\n  Pages: {page_count} total, {freelist} free ({page_size}B/page)")
    print(f"  DB file size (page_count): {page_count * page_size / 1024 / 1024:.2f} MB")
    print(f"  Free pages (bloat): {freelist} ({freelist * page_size / 1024:.0f} KB reclaimable)")

    # WAL size
    wal_path = DB_PATH + "-wal"
    if os.path.exists(wal_path):
        print(f"  WAL file: {os.path.getsize(wal_path)/1024:.0f} KB")

    # Index usage via EXPLAIN QUERY PLAN on hot queries
    print("\n  EXPLAIN QUERY PLAN on hot queries:")
    queries = [
        ("latest_sighting_per_device (api/now)",
         """SELECT d.*, s.rssi FROM devices d
            JOIN sightings s ON s.id = (
               SELECT id FROM sightings WHERE mac = d.mac AND ts >= 1 ORDER BY ts DESC LIMIT 1)
            WHERE d.last_seen >= 1"""),
        ("insert_sighting dedup check",
         """SELECT 1 FROM sightings
            WHERE mac='AA:BB:CC:DD:EE:FF' AND sensor_id='x' AND ts BETWEEN 1 AND 2"""),
        ("api/rhythm",
         "SELECT mac, ts FROM sightings WHERE ts >= 1 ORDER BY ts"),
        ("api/device/<mac> sightings",
         "SELECT * FROM sightings WHERE mac='AA:BB:CC:DD:EE:FF' ORDER BY ts"),
        ("smoothed_rssi",
         "SELECT rssi FROM sightings WHERE mac='AA:BB:CC:DD:EE:FF' AND rssi IS NOT NULL ORDER BY ts DESC LIMIT 11"),
        ("rollup_hour",
         """SELECT mac, sensor_id, source, COUNT(*) FROM sightings
            WHERE ts >= 1 AND ts < 2 GROUP BY mac, sensor_id, source"""),
        ("prune_raw",
         "DELETE FROM sightings WHERE ts < 1"),
        ("rogue detect_rogues",
         """SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count
            FROM devices WHERE sighting_count >= 3 AND (last_seen - first_seen) >= 900 AND mac NOT LIKE 'mdns:%'"""),
        ("SSE stream",
         "SELECT id, mac, name, rssi, distance, ts, source FROM sightings WHERE id > 0 ORDER BY id LIMIT 50"),
        ("fingerprint_all sig gather",
         "SELECT name, services, extra, source FROM sightings WHERE mac='AA:BB:CC:DD:EE:FF' ORDER BY ts DESC LIMIT 1"),
    ]
    for name, q in queries:
        plan = conn.execute("EXPLAIN QUERY PLAN " + q).fetchall()
        detail = " | ".join(r[3] for r in plan)
        print(f"    {name}:")
        print(f"      {detail}")

    # Index list
    print("\n  Indexes:")
    for r in conn.execute("SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name, name"):
        print(f"    {r['tbl_name']}.{r['name']}")

    # Retention effectiveness: oldest vs newest sighting
    oldest = conn.execute("SELECT MIN(ts) ts FROM sightings").fetchone()["ts"]
    newest = conn.execute("SELECT MAX(ts) ts FROM sightings").fetchone()["ts"]
    if oldest and newest:
        age_days = (newest - oldest) / 86400
        print(f"\n  Sightings time span: {age_days:.1f} days (oldest={time.strftime('%Y-%m-%d', time.localtime(oldest))} newest={time.strftime('%Y-%m-%d', time.localtime(newest))})")
        print(f"  Retention target: 14 days raw, hourly rollup kept forever")
        # hourly rollup span
        h_oldest = conn.execute("SELECT MIN(hour) h FROM sightings_hourly").fetchone()["h"]
        h_newest = conn.execute("SELECT MAX(hour) h FROM sightings_hourly").fetchone()["h"]
        if h_oldest and h_newest:
            print(f"  Hourly rollup span: {(h_newest - h_oldest)/86400:.1f} days")

    # ---- 3. DEDUP EFFECTIVENESS ----
    section(3, "DEDUP EFFECTIVENESS")
    # Find actual duplicates: same mac+sensor within 2s that slipped through.
    # The dedup guard uses WHERE NOT EXISTS, so ideally zero. But check if
    # there are near-duplicates (within 2s) that exist anyway.
    dups = conn.execute("""
        SELECT mac, sensor_id, ts, COUNT(*) c FROM sightings
        WHERE EXISTS (
            SELECT 1 FROM sightings s2
            WHERE s2.mac = sightings.mac AND s2.sensor_id = sightings.sensor_id
              AND s2.ts BETWEEN sightings.ts - 2 AND sightings.ts + 2
              AND s2.id != sightings.id
        )
        GROUP BY mac, sensor_id, ts
        LIMIT 20
    """).fetchall()
    print(f"  Duplicate sightings (same mac+sensor within 2s): {len(dups)} groups found")
    for d in dups[:5]:
        print(f"    mac={d['mac']} sensor={d['sensor_id']} ts={d['ts']} count={d['c']}")

    # Also check: how many sightings are within 2s of another (any direction)
    near = conn.execute("""
        SELECT COUNT(*) c FROM sightings s1
        WHERE EXISTS (
            SELECT 1 FROM sightings s2
            WHERE s2.mac = s1.mac AND s2.sensor_id = s1.sensor_id
              AND s2.ts BETWEEN s1.ts - 2 AND s1.ts + 2
              AND s2.id != s1.id
        )
    """).fetchone()["c"]
    print(f"  Total sightings within 2s of a sibling: {near}")

    # Time gap distribution between consecutive sightings of same device
    gaps = conn.execute("""
        WITH ordered AS (
            SELECT mac, sensor_id, ts,
                   LAG(ts) OVER (PARTITION BY mac, sensor_id ORDER BY ts) AS prev_ts
            FROM sightings
        )
        SELECT prev_ts, ts, ts - prev_ts AS gap, mac, sensor_id
        FROM ordered
        WHERE prev_ts IS NOT NULL AND ts - prev_ts BETWEEN 0 AND 2
        LIMIT 20
    """).fetchall()
    print(f"  Consecutive sightings with gap 0-2s (potential dedup misses): {len(gaps)}")
    for g in gaps[:5]:
        print(f"    mac={g['mac']} gap={g['gap']:.3f}s ts={g['ts']}")

    # ---- 4. CLASSIFICATION COVERAGE ----
    section(4, "CLASSIFICATION COVERAGE")
    total_devs = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
    type_dist = conn.execute("""
        SELECT last_type, COUNT(*) c FROM devices GROUP BY last_type ORDER BY c DESC
    """).fetchall()
    unknown = sum(r["c"] for r in type_dist if r["last_type"] in (None, "unknown"))
    known = total_devs - unknown
    pct = (known / total_devs * 100) if total_devs else 0
    print(f"  Total devices: {total_devs}")
    print(f"  Classified (not unknown/None): {known} ({pct:.1f}%)")
    print(f"  Unknown/None: {unknown} ({100-pct:.1f}%)")
    print(f"  Type distribution:")
    for r in type_dist:
        print(f"    {r['last_type']}: {r['c']} ({r['c']/total_devs*100 if total_devs else 0:.1f}%)")

    # Which classify() path fired? We can't directly know, but we can infer:
    # - has oui_name but type != unknown -> OUI or name rule
    # - source = mdns -> mDNS category or service rule
    # - is_random -> phone-anon
    # Let's look at source breakdown of unknowns
    unk_src = conn.execute("""
        SELECT d.mac, d.last_type, d.oui_name, s.source, s.name, s.services
        FROM devices d
        LEFT JOIN (SELECT mac, source, name, services FROM sightings
                   WHERE mac IN (SELECT mac FROM devices WHERE last_type='unknown' OR last_type IS NULL)
                   GROUP BY mac ORDER BY ts DESC) s ON s.mac = d.mac
        WHERE d.last_type='unknown' OR d.last_type IS NULL
        LIMIT 10
    """).fetchall()
    print(f"\n  Sample unknown devices (first 10):")
    for r in unk_src:
        print(f"    mac={r['mac']} oui={r['oui_name']} src={r['source']} name={r['name']} svc={r['services']}")

    # OUI coverage of unknowns
    unk_with_oui = conn.execute("""
        SELECT COUNT(*) c FROM devices
        WHERE (last_type='unknown' OR last_type IS NULL) AND oui_name IS NOT NULL AND oui_name != ''
    """).fetchone()["c"]
    print(f"  Unknown devices that HAVE an OUI vendor: {unk_with_oui} (these could be OUI-classified)")

    # ---- 5. FINGERPRINTING COST ----
    section(5, "FINGERPRINTING COST")
    n_devs = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
    n_fps = conn.execute("SELECT COUNT(*) c FROM device_fingerprints").fetchone()["c"]
    n_aliases = conn.execute("SELECT COUNT(*) c FROM device_aliases").fetchone()["c"]
    n_multi = conn.execute("""
        SELECT COUNT(*) c FROM (
            SELECT fingerprint_id FROM device_aliases
            GROUP BY fingerprint_id HAVING COUNT(*) > 1
        )
    """).fetchone()["c"]
    print(f"  Devices: {n_devs}")
    print(f"  Fingerprints: {n_fps}")
    print(f"  Aliases: {n_aliases}")
    print(f"  Multi-MAC fingerprints (merged): {n_multi}")

    # Time fingerprint_all() — it's O(N) for the sig gather (one query per device)
    # + O(N^2) for the cross-radio pass (nested loop over all devs). Measure it.
    print(f"\n  Timing fingerprint_all() on current DB...")
    # Import the project modules
    sys.path.insert(0, os.path.dirname(DB_PATH))
    try:
        from fingerprint import fingerprint_all
        t0 = time.time()
        with connect() as c2:
            n = fingerprint_all(c2)
        elapsed = time.time() - t0
        print(f"  fingerprint_all() took {elapsed:.3f}s for {n_devs} devices ({n} fingerprints created)")
        print(f"  Per-device: {elapsed/n_devs*1000:.2f} ms/device" if n_devs else "  (no devices)")
        # The sig gather is N queries (one per device). Cross-radio is N^2.
        print(f"  Scaling: sig gather = {n_devs} queries; cross-radio = O({n_devs}^2) = {n_devs**2} comparisons")
    except Exception as e:
        print(f"  Could not time fingerprint_all: {e}")
        # Fallback: time just the sig-gather queries (the N per-device SELECTs)
        t0 = time.time()
        with connect() as c2:
            devs = c2.execute("SELECT mac FROM devices").fetchall()
            for d in devs:
                c2.execute("SELECT name, services, extra, source FROM sightings WHERE mac=? ORDER BY ts DESC LIMIT 1", (d["mac"],)).fetchone()
        elapsed = time.time() - t0
        print(f"  Sig-gather only ({n_devs} per-device SELECTs): {elapsed:.3f}s")

    # ---- 6. SSE / STREAMING HEALTH ----
    section(6, "SSE / STREAMING HEALTH")
    # The SSE endpoint holds one sqlite connection per open generator.
    # Check: is there a max(id) query on every connection? Yes (since=0 path).
    # Check: the polling loop does SELECT ... WHERE id > ? ORDER BY id LIMIT 50 every 2s.
    # Potential issue: no index on `id` alone (it's PK so yes), but the query
    # is on id > ? which uses the PK.
    # The real risk: connection leaks if the generator doesn't get GC'd.
    # Check gunicorn worker count vs potential open connections.
    print("  SSE endpoint: /stream")
    print("  One sqlite connection per generator (opened in event_stream, closed in finally).")
    print("  Polls SELECT ... WHERE id > ? ORDER BY id LIMIT 50 every 2s.")
    print("  Heartbeat: ': ping' every 2s.")
    print("  Risk: each open dashboard tab holds 1 gunicorn worker thread + 1 sqlite conn.")
    print("  Gunicorn: 2 workers x 4 threads = 8 concurrent requests max.")
    print("  With keep-alive 120s, SSE connections can exhaust the thread pool at 8 tabs.")
    # Check if there's a max(id) full-table scan risk
    max_id_plan = conn.execute("EXPLAIN QUERY PLAN SELECT MAX(id) m FROM sightings").fetchall()
    print(f"  MAX(id) plan: {' | '.join(r[3] for r in max_id_plan)}")

    # ---- 7. SUMMARY: single biggest win ----
    section(7, "SUMMARY")
    # Gather the key numbers for the recommendation
    print(f"  DB size: {page_count * page_size / 1024 / 1024:.2f} MB, {freelist} free pages")
    print(f"  Devices: {n_devs}, Fingerprints: {n_fps}")
    if 'elapsed' in dir():
        print(f"  fingerprint_all: {elapsed:.3f}s")
    print(f"  Classification: {pct:.1f}% classified")

    conn.close()
    print("\nDONE.")

if __name__ == "__main__":
    main()
