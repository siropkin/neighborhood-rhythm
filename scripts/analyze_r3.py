#!/usr/bin/env python3
"""R3 deep analysis of the live rhythm.db — read-only, no DB writes.
Covers: rogue churn, fingerprint quality, classification coverage,
Apple Continuity, WiFi probes, behavior/time-patterns, daily rhythm,
and one genuinely surprising finding."""
import sqlite3, json, time, statistics, os, sys
from collections import defaultdict, Counter
from datetime import datetime

DB = os.path.expanduser("~/neighborhood-rhythm/rhythm.db")

def ts_str(ts):
    if ts is None: return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")

def date_str(ts):
    if ts is None: return "—"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

def is_random_mac(mac):
    if not mac: return False
    h = mac.replace(":", "").replace("-", "")
    if len(h) != 12: return False
    try: return bool(int(h[0:2], 16) & 0b11)
    except ValueError: return False

def main():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    c = db.cursor()
    now = time.time()

    # ---- overview ----
    n_devices = c.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
    n_sightings = c.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
    n_fps = c.execute("SELECT COUNT(*) FROM device_fingerprints").fetchone()[0]
    n_aliases = c.execute("SELECT COUNT(*) FROM device_aliases").fetchone()[0]
    n_rogues_total = c.execute("SELECT COUNT(*) FROM rogue_events").fetchone()[0]
    n_rogues_unresolved = c.execute("SELECT COUNT(*) FROM rogue_events WHERE resolved=0").fetchone()[0]
    n_rogues_resolved = c.execute("SELECT COUNT(*) FROM rogue_events WHERE resolved=1").fetchone()[0]
    n_known = c.execute("SELECT COUNT(*) FROM known_devices").fetchone()[0]
    n_wifi_aps = c.execute("SELECT COUNT(*) FROM wifi_aps").fetchone()[0]
    n_sensors = c.execute("SELECT COUNT(*) FROM sensors").fetchone()[0]
    n_sites = c.execute("SELECT COUNT(*) FROM sites").fetchone()[0]

    min_ts = c.execute("SELECT MIN(ts) FROM sightings").fetchone()[0]
    max_ts = c.execute("SELECT MAX(ts) FROM sightings").fetchone()[0]
    span_days = (max_ts - min_ts) / 86400 if min_ts and max_ts else 0

    print("=" * 70)
    print("NEIGHBORHOOD RHYTHM — R3 DEEP ANALYSIS")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Data span: {ts_str(min_ts)} → {ts_str(max_ts)} ({span_days:.1f} days)")
    print(f"Devices: {n_devices:,} | Sightings: {n_sightings:,} | Fingerprints: {n_fps:,}")
    print(f"Rogues: {n_rogues_total} total, {n_rogues_unresolved} unresolved, {n_rogues_resolved} resolved")
    print(f"Known devices: {n_known} | WiFi APs: {n_wifi_aps} | Sensors: {n_sensors} | Sites: {n_sites}")
    print("=" * 70)

    # ======================================================================
    # 1. ROGUE CHURN
    # ======================================================================
    print("\n" + "=" * 70)
    print("1. ROGUE CHURN")
    print("=" * 70)

    rogues = c.execute("SELECT * FROM rogue_events ORDER BY first_seen").fetchall()
    unresolved = [r for r in rogues if r["resolved"] == 0]
    resolved = [r for r in rogues if r["resolved"] == 1]

    # age distribution
    print(f"\nTotal rogue events: {len(rogues)}")
    print(f"Resolved: {len(resolved)} ({len(resolved)/max(len(rogues),1)*100:.1f}%)")
    print(f"Unresolved: {len(unresolved)}")

    # age buckets
    age_buckets = {"<6h": 0, "6-24h": 0, "1-2d": 0, "2-3d": 0, "3+d": 0}
    for r in unresolved:
        age = now - r["first_seen"]
        if age < 21600: age_buckets["<6h"] += 1
        elif age < 86400: age_buckets["6-24h"] += 1
        elif age < 172800: age_buckets["1-2d"] += 1
        elif age < 259200: age_buckets["2-3d"] += 1
        else: age_buckets["3+d"] += 1
    print(f"\nUnresolved age distribution:")
    for k, v in age_buckets.items():
        print(f"  {k}: {v}")

    # rogues by day (first_seen)
    print(f"\nRogue events by first-seen date:")
    by_day = Counter()
    for r in rogues:
        by_day[date_str(r["first_seen"])] += 1
    for d in sorted(by_day.keys()):
        print(f"  {d}: {by_day[d]} new rogues")

    # re-appearing rogues (same MAC multiple events)
    mac_counts = Counter(r["mac"] for r in rogues)
    multi = {mac: cnt for mac, cnt in mac_counts.items() if cnt > 1}
    print(f"\nMACs with multiple rogue events: {len(multi)}")
    for mac, cnt in sorted(multi.items(), key=lambda x: -x[1])[:10]:
        events = [r for r in rogues if r["mac"] == mac]
        resolved_status = [e["resolved"] for e in events]
        print(f"  {mac}: {cnt} events, resolved={resolved_status}")

    # rogues seen recently (last 24h) — check if the device is still active
    print(f"\nUnresolved rogues — last sighting activity:")
    active_24h = 0
    active_3d = 0
    stale = 0
    for r in unresolved:
        mac = r["mac"]
        dev = c.execute("SELECT last_seen FROM devices WHERE mac=?", (mac,)).fetchone()
        last = dev["last_seen"] if dev else None
        if last and (now - last) < 86400:
            active_24h += 1
        elif last and (now - last) < 259200:
            active_3d += 1
        else:
            stale += 1
    print(f"  Seen in last 24h: {active_24h}")
    print(f"  Seen in last 3 days (but not 24h): {active_3d}")
    print(f"  Stale (not seen in 3+ days): {stale}")

    # rogue by class
    print(f"\nUnresolved rogues by class:")
    class_counts = Counter(r["device_class"] for r in unresolved)
    for k, v in class_counts.most_common():
        print(f"  {k}: {v}")

    # rogue by OUI
    print(f"\nUnresolved rogues by OUI (top 15):")
    oui_counts = Counter(r["oui_name"] for r in unresolved)
    for k, v in oui_counts.most_common(15):
        print(f"  {k}: {v}")

    # known_devices overlap with rogue MACs
    known_macs = {r["mac"] for r in c.execute("SELECT mac FROM known_devices").fetchall()}
    rogue_macs = {r["mac"] for r in rogues}
    overlap = known_macs & rogue_macs
    print(f"\nKnown devices: {len(known_macs)}")
    print(f"Rogue MACs in known_devices: {len(overlap)}")

    # ======================================================================
    # 2. FINGERPRINT QUALITY
    # ======================================================================
    print("\n" + "=" * 70)
    print("2. FINGERPRINT QUALITY")
    print("=" * 70)

    # aliases per fingerprint
    fp_alias_counts = c.execute("""
        SELECT fingerprint_id, COUNT(*) as n_aliases, SUM(sighting_count) as total_sightings
        FROM device_aliases GROUP BY fingerprint_id
    """).fetchall()
    multi_alias = [r for r in fp_alias_counts if r["n_aliases"] > 1]
    print(f"\nFingerprints: {len(fp_alias_counts)}")
    print(f"Aliases: {n_aliases}")
    print(f"MACs merged: {sum(r['n_aliases'] - 1 for r in multi_alias)} ({len(multi_alias)} clusters)")
    print(f"Merge rate: {sum(r['n_aliases']-1 for r in multi_alias)/max(n_devices,1)*100:.2f}%")

    # link method breakdown
    print(f"\nLink method breakdown:")
    methods = c.execute("SELECT link_method, COUNT(*) as n FROM device_aliases GROUP BY link_method").fetchall()
    for r in methods:
        print(f"  {r['link_method']}: {r['n']}")

    # biggest clusters
    print(f"\nBiggest clusters (>2 aliases):")
    big_clusters = sorted(multi_alias, key=lambda r: -r["n_aliases"])[:20]
    for r in big_clusters:
        fp_id = r["fingerprint_id"]
        fp = c.execute("SELECT device_class, label FROM device_fingerprints WHERE fingerprint_id=?", (fp_id,)).fetchone()
        aliases = c.execute("SELECT mac, source, link_method, sighting_count FROM device_aliases WHERE fingerprint_id=?", (fp_id,)).fetchall()
        print(f"\n  FP {fp_id[:8]} | {fp['device_class']} | {fp['label']} | {r['n_aliases']} aliases, {r['total_sightings']} sightings")
        for a in aliases[:8]:
            print(f"    {a['mac']} | {a['source']} | {a['link_method']} | {a['sighting_count']} sightings")

    # missed links — co-presence analysis (sample)
    print(f"\nCo-presence candidate pairs (Jaccard >= 0.8, >=10 co-scans):")
    stable_devs = c.execute("""
        SELECT mac FROM devices WHERE sighting_count >= 10 AND mac NOT LIKE 'mdns:%'
    """).fetchall()
    stable = [d["mac"] for d in stable_devs if not is_random_mac(d["mac"])]
    # build minute-sets for top 200 most-sighted
    stable.sort(key=lambda m: -c.execute("SELECT sighting_count FROM devices WHERE mac=?", (m,)).fetchone()[0])
    sample = stable[:200]
    minutes = {}
    for mac in sample:
        rows = c.execute("SELECT DISTINCT CAST(ts/60 AS INTEGER) m FROM sightings WHERE mac=?", (mac,)).fetchall()
        minutes[mac] = {r["m"] for r in rows}
    pairs = []
    for i, a in enumerate(sample):
        ma = minutes[a]
        for b in sample[i+1:]:
            mb = minutes[b]
            union = len(ma | mb)
            if union == 0: continue
            ratio = len(ma & mb) / union
            if ratio >= 0.8:
                pairs.append((a, b, ratio, len(ma & mb)))
    pairs.sort(key=lambda p: -p[2])
    print(f"  Found {len(pairs)} high co-presence pairs (sample of {len(sample)} stable devices)")
    for a, b, ratio, overlap in pairs[:10]:
        oa = c.execute("SELECT oui_name, last_type FROM devices WHERE mac=?", (a,)).fetchone()
        ob = c.execute("SELECT oui_name, last_type FROM devices WHERE mac=?", (b,)).fetchone()
        print(f"  {a} ({oa['oui_name']}, {oa['last_type']}) + {b} ({ob['oui_name']}, {ob['last_type']}) — J={ratio:.2f}, overlap={overlap}")

    # ======================================================================
    # 3. CLASSIFICATION COVERAGE
    # ======================================================================
    print("\n" + "=" * 70)
    print("3. CLASSIFICATION COVERAGE")
    print("=" * 70)

    print(f"\ndevices.last_type distribution:")
    type_dist = c.execute("SELECT last_type, COUNT(*) as n FROM devices GROUP BY last_type ORDER BY n DESC").fetchall()
    for r in type_dist:
        print(f"  {r['last_type']}: {r['n']} ({r['n']/n_devices*100:.1f}%)")

    # is_random_mac working?
    print(f"\nRandom-MAC check — unknown bucket:")
    unknowns = c.execute("SELECT mac FROM devices WHERE last_type='unknown'").fetchall()
    random_unknown = sum(1 for r in unknowns if is_random_mac(r["mac"]))
    stable_unknown = len(unknowns) - random_unknown
    print(f"  Total unknown: {len(unknowns)}")
    print(f"  Random MAC in unknown: {random_unknown}")
    print(f"  Stable MAC in unknown: {stable_unknown}")

    # phone-anon with Apple data
    print(f"\nphone-anon with Apple Continuity data:")
    pa_devs = c.execute("SELECT mac FROM devices WHERE last_type='phone-anon'").fetchall()
    pa_with_apple = 0
    pa_sample = 0
    for r in pa_devs:
        mac = r["mac"]
        s = c.execute("SELECT extra FROM sightings WHERE mac=? AND extra IS NOT NULL ORDER BY ts DESC LIMIT 1", (mac,)).fetchone()
        if s:
            pa_sample += 1
            try:
                e = json.loads(s["extra"])
                if e.get("apple"):
                    pa_with_apple += 1
            except: pass
    print(f"  Sampled {pa_sample} phone-anon devices with extra data")
    print(f"  With Apple data: {pa_with_apple}")

    # phone-anon on wifi (LAN misclassification)
    print(f"\nphone-anon on source=wifi (LAN misclassification):")
    pa_wifi = c.execute("""
        SELECT d.mac, d.sighting_count, d.last_type
        FROM devices d
        WHERE d.last_type='phone-anon'
        AND EXISTS (SELECT 1 FROM sightings s WHERE s.mac=d.mac AND s.source='wifi')
    """).fetchall()
    print(f"  phone-anon with any wifi source: {len(pa_wifi)}")
    high_pa = sorted(pa_wifi, key=lambda r: -r["sighting_count"])[:10]
    for r in high_pa:
        print(f"  {r['mac']} — {r['sighting_count']} sightings")

    # what's still unknown — OUI breakdown
    print(f"\nUnknown devices — OUI breakdown:")
    unknown_oui = c.execute("SELECT oui_name, COUNT(*) as n FROM devices WHERE last_type='unknown' GROUP BY oui_name ORDER BY n DESC LIMIT 20").fetchall()
    for r in unknown_oui:
        print(f"  '{r['oui_name']}': {r['n']}")

    # name distribution among unknowns
    print(f"\nUnknown devices — name distribution (top 20):")
    unknown_names = c.execute("""
        SELECT d.mac, s.name
        FROM devices d
        JOIN sightings s ON s.mac = d.mac
        WHERE d.last_type='unknown' AND s.name IS NOT NULL AND s.name != ''
        GROUP BY d.mac
    """).fetchall()
    name_counts = Counter(r["name"] for r in unknown_names)
    for name, cnt in name_counts.most_common(20):
        print(f"  '{name}': {cnt}")

    # ======================================================================
    # 4. APPLE CONTINUITY
    # ======================================================================
    print("\n" + "=" * 70)
    print("4. APPLE CONTINUITY")
    print("=" * 70)

    # count sightings with apple data
    apple_sightings = 0
    apple_types = Counter()
    nearby_actions = Counter()
    airpods_models = Counter()
    airtag_macs = set()
    nearby_with_auth = 0
    nearby_total = 0

    # scan all sightings with extra
    rows = c.execute("SELECT mac, extra FROM sightings WHERE extra IS NOT NULL").fetchall()
    for r in rows:
        try:
            e = json.loads(r["extra"])
        except:
            continue
        apple = e.get("apple")
        if not apple:
            continue
        apple_sightings += 1
        for t in apple.get("types", []):
            apple_types[t] += 1
        # nearby
        for nb in apple.get("nearby") or []:
            nearby_total += 1
            nearby_actions[nb.get("action_code", "?")] += 1
            if nb.get("auth_tag"):
                nearby_with_auth += 1
        # airpods
        if apple.get("model_code"):
            airpods_models[apple["model_code"]] += 1
        # airtag
        if "airtag" in apple.get("types", []):
            airtag_macs.add(r["mac"])

    print(f"\nSightings with Apple data: {apple_sightings} ({apple_sightings/n_sightings*100:.1f}% of all)")
    print(f"\nApple type breakdown:")
    for t, cnt in apple_types.most_common():
        print(f"  {t}: {cnt}")
    print(f"\nNearby info total: {nearby_total}")
    print(f"Nearby with auth_tag: {nearby_with_auth}")
    print(f"\nNearby action code distribution (top 20):")
    for code, cnt in nearby_actions.most_common(20):
        print(f"  {code}: {cnt}")

    print(f"\nAirPods/Beats model codes:")
    for code, cnt in airpods_models.most_common():
        print(f"  {code}: {cnt}")

    print(f"\nAirTag distinct MACs: {len(airtag_macs)}")
    # estimate physical airtags
    airtag_sightings = apple_types.get("airtag", 0)
    if airtag_sightings > 0 and span_days > 0:
        # AirTag rotates every ~15 min, scan every 5 min → ~1 sighting per 15 min per tag
        est_tags = len(airtag_macs) / (span_days * 96)  # 96 rotations/day
        print(f"  AirTag sightings: {airtag_sightings}")
        print(f"  Estimated physical AirTags: {est_tags:.1f}")

    # ======================================================================
    # 5. WIFI PROBE DATA
    # ======================================================================
    print("\n" + "=" * 70)
    print("5. WIFI PROBE DATA")
    print("=" * 70)

    # probes in last 24h
    cutoff_24h = max_ts - 86400
    probes_24h = c.execute("SELECT COUNT(*) FROM sightings WHERE source='wifi_probe' AND ts >= ?", (cutoff_24h,)).fetchone()[0]
    probes_total = c.execute("SELECT COUNT(*) FROM sightings WHERE source='wifi_probe'").fetchone()[0]
    probe_macs = c.execute("SELECT COUNT(DISTINCT mac) FROM sightings WHERE source='wifi_probe'").fetchone()[0]

    print(f"\nTotal wifi_probe sightings: {probes_total}")
    print(f"Probe sightings in last 24h: {probes_24h}")
    print(f"Distinct probe MACs: {probe_macs}")

    # SSIDs probed
    print(f"\nSSIDs being probed (from device names):")
    probe_names = c.execute("""
        SELECT name, COUNT(*) as n FROM sightings
        WHERE source='wifi_probe' AND name IS NOT NULL AND name != ''
        GROUP BY name ORDER BY n DESC LIMIT 30
    """).fetchall()
    for r in probe_names:
        print(f"  '{r['name']}': {r['n']}")

    # probe MACs also seen on BLE?
    probe_mac_list = [r["mac"] for r in c.execute("SELECT DISTINCT mac FROM sightings WHERE source='wifi_probe'").fetchall()]
    ble_macs = {r["mac"] for r in c.execute("SELECT DISTINCT mac FROM sightings WHERE source='ble'").fetchall()}
    overlap = sum(1 for m in probe_mac_list if m in ble_macs)
    print(f"\nProbe MACs also seen on BLE: {overlap}")

    # ======================================================================
    # 6. BEHAVIOR + TIME-PATTERN
    # ======================================================================
    print("\n" + "=" * 70)
    print("6. BEHAVIOR + TIME-PATTERN")
    print("=" * 70)

    # import behavior module
    sys.path.insert(0, os.path.expanduser("~/neighborhood-rhythm"))
    try:
        from behavior import classify_behavior, detect_time_pattern
        behavior_available = True
    except:
        behavior_available = False
    print(f"\nBehavior module available: {behavior_available}")

    if behavior_available:
        eligible = c.execute("SELECT mac FROM devices WHERE sighting_count >= 5").fetchall()
        print(f"Devices eligible (>=5 sightings): {len(eligible)}")

        behaviors = Counter()
        patterns = Counter()
        night_only = []
        day_active = []
        evening = []

        for r in eligible:
            mac = r["mac"]
            b = classify_behavior(db, mac, now=now)
            behaviors[b["behavior"]] += 1
            tp = detect_time_pattern(db, mac)
            patterns[tp["pattern"]] += 1
            if tp["pattern"] == "night-only":
                night_only.append((mac, b, tp))
            elif tp["pattern"] == "day-active":
                day_active.append((mac, b, tp))
            elif tp["pattern"] == "evening":
                evening.append((mac, b, tp))

        print(f"\nBehavior distribution:")
        for k, v in behaviors.most_common():
            print(f"  {k}: {v} ({v/len(eligible)*100:.1f}%)")

        print(f"\nTime-pattern distribution:")
        for k, v in patterns.most_common():
            print(f"  {k}: {v} ({v/len(eligible)*100:.1f}%)")

        print(f"\nNight-only devices ({len(night_only)}):")
        for mac, b, tp in night_only[:15]:
            dev = c.execute("SELECT oui_name, last_type, last_label, sighting_count FROM devices WHERE mac=?", (mac,)).fetchone()
            print(f"  {mac} | {dev['last_type']} | {dev['oui_name']} | {dev['sighting_count']} sightings | {dev['last_label']}")

        print(f"\nDay-active devices ({len(day_active)}):")
        for mac, b, tp in day_active[:15]:
            dev = c.execute("SELECT oui_name, last_type, last_label, sighting_count FROM devices WHERE mac=?", (mac,)).fetchone()
            print(f"  {mac} | {dev['last_type']} | {dev['oui_name']} | {dev['sighting_count']} sightings | {dev['last_label']}")

    # ======================================================================
    # 7. THE DAILY RHYTHM
    # ======================================================================
    print("\n" + "=" * 70)
    print("7. THE DAILY RHYTHM")
    print("=" * 70)

    # hourly sightings (local time)
    print(f"\nHourly sightings (local time, all data):")
    hourly = c.execute("SELECT ts FROM sightings").fetchall()
    hour_counts = Counter()
    for r in hourly:
        h = time.localtime(r["ts"]).tm_hour
        hour_counts[h] += 1
    max_h = max(hour_counts.values()) if hour_counts else 1
    for h in range(24):
        cnt = hour_counts.get(h, 0)
        bar = "#" * int(cnt / max_h * 40)
        print(f"  {h:02d} | {cnt:6d} {bar}")

    # daily totals
    print(f"\nDaily sighting totals:")
    daily = Counter()
    for r in hourly:
        d = date_str(r["ts"])
        daily[d] += 1
    for d in sorted(daily.keys()):
        cnt = daily[d]
        bar = "#" * int(cnt / max(daily.values()) * 50)
        print(f"  {d}: {cnt:6d} {bar}")

    # day-by-day hourly (to check stability)
    print(f"\nDay-by-day hourly pattern (stability check):")
    day_hour = defaultdict(lambda: Counter())
    for r in hourly:
        d = date_str(r["ts"])
        h = time.localtime(r["ts"]).tm_hour
        day_hour[d][h] += 1
    for d in sorted(day_hour.keys()):
        hours = day_hour[d]
        peak_h = max(hours, key=hours.get) if hours else 0
        peak_v = hours[peak_h] if hours else 0
        min_h = min(hours, key=hours.get) if hours else 0
        min_v = hours[min_h] if hours else 0
        total = sum(hours.values())
        print(f"  {d}: total={total:6d}, peak={peak_h:02d}h ({peak_v}), trough={min_h:02d}h ({min_v}), ratio={peak_v/max(min_v,1):.1f}x")

    # ======================================================================
    # 8. SURPRISING FINDINGS
    # ======================================================================
    print("\n" + "=" * 70)
    print("8. SURPRISING FINDINGS")
    print("=" * 70)

    # most-sighted devices
    print(f"\nTop 20 most-sighted devices:")
    top_devs = c.execute("SELECT mac, oui_name, last_type, last_label, sighting_count FROM devices ORDER BY sighting_count DESC LIMIT 20").fetchall()
    for r in top_devs:
        print(f"  {r['mac']} | {r['sighting_count']:5d} | {r['last_type']} | {r['oui_name']} | {r['last_label']}")

    # RSSI stats
    print(f"\nRSSI statistics:")
    rssi_rows = c.execute("SELECT rssi FROM sightings WHERE rssi IS NOT NULL").fetchall()
    rssi_vals = [r["rssi"] for r in rssi_rows]
    if rssi_vals:
        print(f"  Count: {len(rssi_vals)}")
        print(f"  Mean: {statistics.mean(rssi_vals):.1f} dBm")
        print(f"  Median: {statistics.median(rssi_vals):.1f} dBm")
        print(f"  Stdev: {statistics.pstdev(rssi_vals):.1f}")
        print(f"  Min: {min(rssi_vals):.1f}, Max: {max(rssi_vals):.1f}")

    # mamaRoo count
    mama = c.execute("SELECT COUNT(DISTINCT mac) FROM sightings WHERE name LIKE '%mamaRoo%'").fetchone()[0]
    print(f"\nmamaRoo devices: {mama}")

    # SSID census
    print(f"\nWiFi AP SSID census (top 30):")
    ssids = c.execute("SELECT ssid, COUNT(*) as n FROM wifi_aps GROUP BY ssid ORDER BY n DESC LIMIT 30").fetchall()
    for r in ssids:
        print(f"  '{r['ssid']}': {r['n']} APs")

    # orphaned sightings
    orphan = c.execute("""
        SELECT COUNT(*) FROM sightings s
        LEFT JOIN devices d ON d.mac = s.mac
        WHERE d.mac IS NULL
    """).fetchone()[0]
    print(f"\nOrphaned sightings (no device row): {orphan}")

    # data quality
    null_rssi = c.execute("SELECT COUNT(*) FROM sightings WHERE rssi IS NULL").fetchone()[0]
    print(f"Null RSSI: {null_rssi} ({null_rssi/n_sightings*100:.1f}%)")

    # devices seen in last 24h
    active_devs = c.execute("SELECT COUNT(*) FROM devices WHERE last_seen >= ?", (cutoff_24h,)).fetchone()[0]
    print(f"\nDevices seen in last 24h: {active_devs}")

    # tracked / watched / is_mine
    tracked = c.execute("SELECT COUNT(*) FROM devices WHERE tracked=1").fetchone()[0]
    is_mine = c.execute("SELECT COUNT(*) FROM devices WHERE is_mine=1").fetchone()[0]
    watched = c.execute("SELECT COUNT(*) FROM devices WHERE watch_note IS NOT NULL").fetchone()[0]
    print(f"Tracked: {tracked}, Is mine: {is_mine}, Watched: {watched}")

    # sensor locations
    sensor_locs = c.execute("SELECT sensor_id, hostname, location_label, x, y FROM sensors").fetchall()
    print(f"\nSensors ({len(sensor_locs)}):")
    for s in sensor_locs:
        print(f"  {s['sensor_id']} | {s['hostname']} | loc={s['location_label']} | x={s['x']} y={s['y']}")

    # sites
    all_sites = c.execute("SELECT * FROM sites").fetchall()
    print(f"\nSites ({len(all_sites)}):")
    for s in all_sites:
        print(f"  {s['site_id']} | {s['label']}")

    # devices with site_id
    dev_with_site = c.execute("SELECT COUNT(*) FROM devices WHERE site_id IS NOT NULL AND site_id != ''").fetchone()[0]
    print(f"Devices with site_id: {dev_with_site}")

    # source breakdown
    print(f"\nSightings by source:")
    sources = c.execute("SELECT source, COUNT(*) as n FROM sightings GROUP BY source ORDER BY n DESC").fetchall()
    for r in sources:
        print(f"  {r['source']}: {r['n']} ({r['n']/n_sightings*100:.1f}%)")

    # unique SSIDs from wifi_aps
    unique_ssids = c.execute("SELECT COUNT(DISTINCT ssid) FROM wifi_aps WHERE ssid IS NOT NULL").fetchone()[0]
    print(f"\nUnique SSIDs: {unique_ssids}")

    # apartment-named SSIDs
    apt_ssids = c.execute("SELECT ssid FROM wifi_aps WHERE ssid LIKE '%APT%' OR ssid LIKE '%KYNE%' OR ssid LIKE '%PADDOCK%' OR ssid LIKE '%PONY%' GROUP BY ssid").fetchall()
    print(f"\nApartment-named SSIDs ({len(apt_ssids)}):")
    for r in apt_ssids:
        print(f"  {r['ssid']}")

    # Find surprising: devices that appear and disappear in patterns
    # Devices seen exactly once per day at the same hour
    print(f"\n--- Surprising: devices with consistent daily-hour patterns ---")
    # Find devices seen on multiple days, always at the same hour
    dev_hours = defaultdict(lambda: defaultdict(set))  # mac -> hour -> set of dates
    for r in c.execute("SELECT mac, ts FROM sightings WHERE ts >= ? AND ts < ?", (min_ts, max_ts)).fetchall():
        d = date_str(r["ts"])
        h = time.localtime(r["ts"]).tm_hour
        dev_hours[r["mac"]][h].add(d)

    # devices seen on 3+ days, always in the same hour
    consistent = []
    for mac, hour_dates in dev_hours.items():
        if len(hour_dates) == 1:
            h, dates = list(hour_dates.items())[0]
            if len(dates) >= 3:
                dev = c.execute("SELECT oui_name, last_type, last_label, sighting_count FROM devices WHERE mac=?", (mac,)).fetchone()
                if dev:
                    consistent.append((mac, h, len(dates), dev))
    consistent.sort(key=lambda x: -x[2])
    print(f"Devices seen on 3+ days, always at the same single hour ({len(consistent)}):")
    for mac, h, days, dev in consistent[:15]:
        print(f"  {mac} | hour={h:02d} | {days} days | {dev['last_type']} | {dev['oui_name']} | {dev['last_label']}")

    # Find: devices that were seen for a while then stopped (possible departure)
    print(f"\n--- Devices that stopped being seen (last seen > 2 days ago, was seen 10+ times) ---")
    departed = c.execute("""
        SELECT mac, oui_name, last_type, last_label, sighting_count, first_seen, last_seen
        FROM devices
        WHERE sighting_count >= 10 AND last_seen < ?
        ORDER BY sighting_count DESC LIMIT 15
    """, (now - 172800)).fetchall()
    for r in departed:
        print(f"  {r['mac']} | {r['sighting_count']} sightings | {ts_str(r['first_seen'])} → {ts_str(r['last_seen'])} | {r['last_type']} | {r['oui_name']}")

    # Find: new devices in last 24h
    new_devs = c.execute("""
        SELECT mac, oui_name, last_type, last_label, sighting_count, first_seen
        FROM devices WHERE first_seen >= ?
        ORDER BY sighting_count DESC LIMIT 15
    """, (cutoff_24h,)).fetchall()
    print(f"\nNew devices in last 24h ({len(new_devs)} shown, top by sightings):")
    for r in new_devs:
        print(f"  {r['mac']} | {r['sighting_count']} sightings | {r['last_type']} | {r['oui_name']} | {r['last_label']}")

    # Find: devices with very high sighting counts but classified as phone-anon (possible misclassification)
    print(f"\n--- phone-anon with >200 sightings (likely misclassified) ---")
    high_pa = c.execute("""
        SELECT mac, sighting_count, last_label FROM devices
        WHERE last_type='phone-anon' AND sighting_count > 200
        ORDER BY sighting_count DESC LIMIT 15
    """).fetchall()
    for r in high_pa:
        sources = c.execute("SELECT source, COUNT(*) as n FROM sightings WHERE mac=? GROUP BY source", (r["mac"],)).fetchall()
        src_str = ", ".join(f"{s['source']}:{s['n']}" for s in sources)
        print(f"  {r['mac']} | {r['sighting_count']} | {src_str} | {r['last_label']}")

    # Find: the "Field_House_Private" SSID with 65 APs — what is it?
    print(f"\n--- Field_House_Private SSID investigation ---")
    fh = c.execute("SELECT bssid, ssid, channel, last_signal FROM wifi_aps WHERE ssid='Field_House_Private'").fetchall()
    print(f"  {len(fh)} APs")
    if fh:
        bssids = [r["bssid"] for r in fh]
        oui_prefixes = Counter()
        for b in bssids:
            oui_prefixes[b[:8].upper()] += 1
        print(f"  OUI prefixes: {dict(oui_prefixes)}")
        channels = Counter(r["channel"] for r in fh)
        print(f"  Channels: {dict(channels)}")

    db.close()
    print("\n" + "=" * 70)
    print("ANALYSIS COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
