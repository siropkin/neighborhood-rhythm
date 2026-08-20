#!/usr/bin/env python3
"""Neighborhood Rhythm — R2 deep analysis. Read-only, no DB writes."""
import sqlite3, json, time, statistics, os, collections

DB = os.path.expanduser("~/neighborhood-rhythm/rhythm.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
db = conn
now = time.time()

def is_random_mac(mac):
    if not mac: return False
    h = mac.replace(":","").replace("-","")
    if len(h) != 12: return False
    try: first = int(h[0:2], 16)
    except ValueError: return False
    return bool(first & 0b11)

def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")

# ── overview ──
section("OVERVIEW")
for q, label in [
    ("SELECT COUNT(*) FROM devices", "devices"),
    ("SELECT COUNT(*) FROM sightings", "sightings (raw)"),
    ("SELECT COUNT(*) FROM sightings_hourly", "sightings_hourly"),
    ("SELECT COUNT(*) FROM device_fingerprints", "fingerprints"),
    ("SELECT COUNT(*) FROM device_aliases", "aliases"),
    ("SELECT COUNT(*) FROM rogue_events", "rogue_events"),
    ("SELECT COUNT(*) FROM rogue_events WHERE resolved=0", "rogue_events unresolved"),
    ("SELECT COUNT(*) FROM rogue_events WHERE resolved=1", "rogue_events resolved"),
    ("SELECT COUNT(*) FROM known_devices", "known_devices"),
    ("SELECT COUNT(*) FROM wifi_aps", "wifi_aps"),
    ("SELECT COUNT(*) FROM sensors", "sensors"),
]:
    print(f"  {label}: {db.execute(q).fetchone()[0]}")
min_ts = db.execute("SELECT MIN(ts) FROM sightings").fetchone()[0]
max_ts = db.execute("SELECT MAX(ts) FROM sightings").fetchone()[0]
span_d = (max_ts - min_ts) / 86400
print(f"  data span: {span_d:.1f} days ({time.strftime('%Y-%m-%d %H:%M', time.localtime(min_ts))} → {time.strftime('%Y-%m-%d %H:%M', time.localtime(max_ts))})")
print(f"  now: {time.strftime('%Y-%m-%d %H:%M', time.localtime(now))}")

# ── 1. daily rhythm ──
section("1. DAILY RHYTHM (local time)")
# sightings by local hour
hourly = collections.Counter()
for r in db.execute("SELECT ts FROM sightings"):
    hourly[time.localtime(r["ts"]).tm_hour] += 1
print("  hour | sightings")
for h in range(24):
    bar = '#' * (hourly[h] // 200)
    print(f"  {h:02d}  | {hourly[h]:6d} {bar}")

# distinct devices by hour
dev_by_hour = collections.Counter()
for r in db.execute("SELECT DISTINCT mac, ts FROM sightings"):
    dev_by_hour[time.localtime(r["ts"]).tm_hour] += 1
print("\n  distinct devices by hour:")
for h in range(24):
    print(f"  {h:02d}  | {dev_by_hour[h]:5d} {'#'*(dev_by_hour[h]//50)}")

# peak/dip hours
peak_h = max(hourly, key=hourly.get)
dip_h = min(hourly, key=hourly.get)
print(f"\n  peak hour: {peak_h:02d}:00 ({hourly[peak_h]} sightings)")
print(f"  dip hour: {dip_h:02d}:00 ({hourly[dip_h]} sightings)")
print(f"  peak/dip ratio: {hourly[peak_h]/max(hourly[dip_h],1):.1f}x")

# ── residential check ──
print("\n  --- residential indicator ---")
# night = 22-06 local, day = 09-17 local
night = sum(hourly[h] for h in list(range(22,24))+list(range(0,7)))
day = sum(hourly[h] for h in range(9,17))
eve = sum(hourly[h] for h in range(17,23))
total = sum(hourly.values())
print(f"  night (22-06): {night} ({night/total*100:.1f}%)")
print(f"  day (09-17):   {day} ({day/total*100:.1f}%)")
print(f"  evening (17-23): {eve} ({eve/total*100:.1f}%)")
print(f"  night/day ratio: {night/max(day,1):.2f}")

# ── rhythm-breakers ──
print("\n  --- devices that break the rhythm ---")
# midday-only devices (seen only 09-17, >=3 sightings)
# night-only devices (seen only 22-06, >=3 sightings)
mac_hours = collections.defaultdict(set)
mac_count = collections.Counter()
for r in db.execute("SELECT mac, ts FROM sightings"):
    mac_hours[r["mac"]].add(time.localtime(r["ts"]).tm_hour)
    mac_count[r["mac"]] += 1

midday_only = []
night_only = []
for mac, hrs in mac_hours.items():
    if mac_count[mac] < 3: continue
    all_day = all(9 <= h < 17 for h in hrs)
    all_night = all(h >= 22 or h < 6 for h in hrs)
    if all_day and len(hrs) >= 2:
        midday_only.append((mac, mac_count[mac], sorted(hrs)))
    if all_night and len(hrs) >= 2:
        night_only.append((mac, mac_count[mac], sorted(hrs)))

print(f"  midday-only devices (>=3 sightings, only 09-17): {len(midday_only)}")
for mac, n, hrs in sorted(midday_only, key=lambda x: -x[1])[:15]:
    dev = db.execute("SELECT oui_name, last_type, last_label FROM devices WHERE mac=?", (mac,)).fetchone()
    oui = dev["oui_name"] if dev else ""
    typ = dev["last_type"] if dev else ""
    lbl = dev["last_label"] if dev else ""
    rand = "random" if is_random_mac(mac) else "stable"
    print(f"    {mac} n={n} hrs={hrs} {rand} oui={oui} type={typ} label={lbl}")

print(f"\n  night-only devices (>=3 sightings, only 22-06): {len(night_only)}")
for mac, n, hrs in sorted(night_only, key=lambda x: -x[1])[:15]:
    dev = db.execute("SELECT oui_name, last_type, last_label FROM devices WHERE mac=?", (mac,)).fetchone()
    oui = dev["oui_name"] if dev else ""
    typ = dev["last_type"] if dev else ""
    lbl = dev["last_label"] if dev else ""
    rand = "random" if is_random_mac(mac) else "stable"
    print(f"    {mac} n={n} hrs={hrs} {rand} oui={oui} type={typ} label={lbl}")

# ── 2. rogue churn ──
section("2. ROGUE CHURN")
rogues = db.execute("SELECT * FROM rogue_events ORDER BY ts").fetchall()
print(f"  total rogue events: {len(rogues)}")
resolved = [r for r in rogues if r["resolved"]]
unresolved = [r for r in rogues if not r["resolved"]]
print(f"  resolved: {len(resolved)}")
print(f"  unresolved: {len(unresolved)}")
print(f"  resolution rate: {len(resolved)/max(len(rogues),1)*100:.1f}%")

# new today vs carried over
rogue_24h = [r for r in unresolved if (now - r["ts"]) < 86400]
rogue_old = [r for r in unresolved if (now - r["ts"]) >= 86400]
print(f"  unresolved seen in last 24h: {len(rogue_24h)}")
print(f"  unresolved older than 24h: {len(rogue_old)}")

# age distribution of unresolved rogues
print("\n  unresolved rogue age distribution:")
age_buckets = collections.Counter()
for r in unresolved:
    age_h = (now - r["ts"]) / 3600
    if age_h < 6: age_buckets["<6h"] += 1
    elif age_h < 24: age_buckets["6-24h"] += 1
    elif age_h < 48: age_buckets["1-2d"] += 1
    elif age_h < 72: age_buckets["2-3d"] += 1
    else: age_buckets["3d+"] += 1
for k in ["<6h","6-24h","1-2d","2-3d","3d+"]:
    print(f"    {k}: {age_buckets[k]}")

# re-appearing rogues: same MAC with multiple rogue events
rogue_macs = collections.Counter(r["mac"] for r in rogues)
multi_rogue = {mac: c for mac, c in rogue_macs.items() if c > 1}
print(f"\n  MACs with multiple rogue events: {len(multi_rogue)}")
for mac, c in sorted(multi_rogue.items(), key=lambda x: -x[1])[:10]:
    events = [r for r in rogues if r["mac"] == mac]
    resolved_any = any(e["resolved"] for e in events)
    print(f"    {mac}: {c} events, resolved_any={resolved_any}")

# rogues that were resolved then re-detected
re_detected = 0
for mac in multi_rogue:
    events = sorted([r for r in rogues if r["mac"] == mac], key=lambda x: x["ts"])
    has_resolved = any(e["resolved"] for e in events)
    has_unresolved = any(not e["resolved"] for e in events)
    if has_resolved and has_unresolved:
        re_detected += 1
        if re_detected <= 5:
            print(f"    RE-DETECTED: {mac} — resolved then re-flagged")
print(f"  total re-detected (resolved then re-flagged): {re_detected}")

# rogue by class
print("\n  unresolved rogue by device_class:")
cls = collections.Counter(r["device_class"] for r in unresolved)
for c, n in cls.most_common():
    print(f"    {c}: {n}")

# rogue by OUI
print("\n  top rogue OUIs (unresolved):")
oui_c = collections.Counter(r["oui_name"] for r in unresolved if r["oui_name"])
for o, n in oui_c.most_common(10):
    print(f"    {o}: {n}")

# ── 3. fingerprint quality ──
section("3. FINGERPRINT QUALITY")
fps = db.execute("SELECT * FROM device_fingerprints").fetchall()
aliases = db.execute("SELECT * FROM device_aliases").fetchall()
print(f"  fingerprints: {len(fps)}")
print(f"  aliases: {len(aliases)}")
# aliases per fingerprint
alias_count = collections.Counter(a["fingerprint_id"] for a in aliases)
multi_alias = {fp: c for fp, c in alias_count.items() if c > 1}
print(f"  fingerprints with >1 alias: {len(multi_alias)}")
print(f"  merge rate: {len(aliases) - len(fps)} MACs merged ({(len(aliases)-len(fps))/max(len(aliases),1)*100:.2f}%)")

# link method breakdown
print("\n  link method breakdown:")
methods = collections.Counter(a["link_method"] for a in aliases)
for m, n in methods.most_common():
    print(f"    {m}: {n}")

# top multi-alias fingerprints
print("\n  top multi-alias fingerprints:")
for fp, c in sorted(multi_alias.items(), key=lambda x: -x[1])[:20]:
    fp_row = db.execute("SELECT device_class, label, sighting_count FROM device_fingerprints WHERE fingerprint_id=?", (fp,)).fetchone()
    al = db.execute("SELECT mac, source, link_method FROM device_aliases WHERE fingerprint_id=?", (fp,)).fetchall()
    macs = [a["mac"] for a in al]
    print(f"    {fp} class={fp_row['device_class']} label={fp_row['label']} aliases={c}")
    for a in al:
        print(f"      {a['mac']} src={a['source']} method={a['link_method']}")

# missed links: co-presence analysis (sample — devices always seen together)
print("\n  --- candidate missed links (co-presence) ---")
# find MACs seen in the same hourly buckets very often
# sample top 200 most-sighted stable MACs to keep it fast
top_macs = [r["mac"] for r in db.execute(
    "SELECT mac FROM devices WHERE sighting_count > 50 ORDER BY sighting_count DESC LIMIT 200").fetchall()]
# build hour-set per mac
mac_hour_set = collections.defaultdict(frozenset)
for r in db.execute("SELECT mac, hour FROM sightings_hourly WHERE mac IN (%s)" % ",".join("?"*len(top_macs)), top_macs):
    mac_hour_set[r["mac"]] = mac_hour_set[r["mac"]] | {r["hour"]}

# find pairs with high overlap (Jaccard)
pairs = []
for i, m1 in enumerate(top_macs):
    h1 = mac_hour_set.get(m1)
    if not h1 or len(h1) < 5: continue
    for m2 in top_macs[i+1:]:
        h2 = mac_hour_set.get(m2)
        if not h2 or len(h2) < 5: continue
        inter = len(h1 & h2)
        union = len(h1 | h2)
        if union == 0: continue
        j = inter / union
        if j >= 0.8 and inter >= 10:
            # check if already linked
            fp1 = db.execute("SELECT fingerprint_id FROM device_aliases WHERE mac=?", (m1,)).fetchone()
            fp2 = db.execute("SELECT fingerprint_id FROM device_aliases WHERE mac=?", (m2,)).fetchone()
            linked = fp1 and fp2 and fp1["fingerprint_id"] == fp2["fingerprint_id"]
            if not linked:
                pairs.append((m1, m2, j, inter))

pairs.sort(key=lambda x: -x[2])
print(f"  high co-presence unlinked pairs (Jaccard >= 0.8, overlap >= 10 hours): {len(pairs)}")
for m1, m2, j, inter in pairs[:15]:
    d1 = db.execute("SELECT oui_name, last_type FROM devices WHERE mac=?", (m1,)).fetchone()
    d2 = db.execute("SELECT oui_name, last_type FROM devices WHERE mac=?", (m2,)).fetchone()
    print(f"    {m1} ({d1['oui_name']}/{d1['last_type']}) + {m2} ({d2['oui_name']}/{d2['last_type']}) J={j:.2f} overlap={inter}h")

# ── 4. classification coverage ──
section("4. CLASSIFICATION COVERAGE")
print("  devices.last_type distribution:")
cls_dist = collections.Counter()
for r in db.execute("SELECT last_type, COUNT(*) as n FROM devices GROUP BY last_type ORDER BY n DESC"):
    cls_dist[r["last_type"]] = r["n"]
total_dev = sum(cls_dist.values())
for c, n in cls_dist.most_common():
    print(f"    {c}: {n} ({n/total_dev*100:.1f}%)")

# unknown breakdown
print("\n  --- 'unknown' bucket analysis ---")
unknowns = db.execute("SELECT mac, oui_name, last_label FROM devices WHERE last_type='unknown'").fetchall()
print(f"  total unknown: {len(unknowns)}")
random_unknown = [d for d in unknowns if is_random_mac(d["mac"])]
stable_unknown = [d for d in unknowns if not is_random_mac(d["mac"])]
print(f"  random-MAC unknowns: {len(random_unknown)}")
print(f"  stable-MAC (registered OUI) unknowns: {len(stable_unknown)}")

# random unknowns with name vs without
rand_with_name = [d for d in random_unknown if d["last_label"]]
rand_no_name = [d for d in random_unknown if not d["last_label"]]
print(f"    random unknowns WITH a name/label: {len(rand_with_name)}")
print(f"    random unknowns WITHOUT a name: {len(rand_no_name)}")
print(f"    (random+no-name = should be phone-anon if is_random_mac fix worked)")

# stable unknowns by OUI
print(f"\n  stable-MAC unknowns by OUI (top 15):")
stable_oui = collections.Counter(d["oui_name"] for d in stable_unknown if d["oui_name"])
for o, n in stable_oui.most_common(15):
    print(f"    {o}: {n}")

# phone-anon check: are they all random?
phone_anon = db.execute("SELECT mac FROM devices WHERE last_type='phone-anon'").fetchall()
pa_random = sum(1 for d in phone_anon if is_random_mac(d["mac"]))
print(f"\n  phone-anon: {len(phone_anon)} total, {pa_random} random-MAC ({pa_random/len(phone_anon)*100:.1f}%)")

# ── 5. Apple Continuity ──
section("5. APPLE CONTINUITY")
apple_types = collections.Counter()
apple_total = 0
nearby_lens = collections.Counter()
airpods_models = collections.Counter()
airpods_unknown = []
for r in db.execute("SELECT extra FROM sightings WHERE extra LIKE '%apple%'"):
    try:
        e = json.loads(r["extra"])
    except: continue
    a = e.get("apple")
    if not a: continue
    apple_total += 1
    atype = a.get("type")
    apple_types[atype] += 1
    if atype == "nearby_info":
        payload = a.get("payload_hex", "")
        nearby_lens[len(payload)//2] += 1
    if atype == "proximity_pairing":
        model = a.get("model_code")
        model_name = a.get("model_name")
        if model_name and model_name != "unknown AirPods/Beats":
            airpods_models[f"{model} {model_name}"] += 1
        else:
            airpods_models[f"{model} unknown"] += 1
            if model: airpods_unknown.append(model)

print(f"  sightings with Apple data: {apple_total}")
print(f"\n  Apple type distribution:")
for t, n in apple_types.most_common():
    print(f"    {t}: {n}")

print(f"\n  Nearby Info (0x10) payload length distribution (bytes):")
for l, n in sorted(nearby_lens.items()):
    print(f"    {l} bytes: {n}")
nearby_with_auth = sum(n for l, n in nearby_lens.items() if l >= 19)
print(f"  Nearby payloads >= 19 bytes (auth tag present): {nearby_with_auth}")

print(f"\n  AirPods model codes:")
for m, n in sorted(airpods_models.items(), key=lambda x: -x[1]):
    print(f"    {m}: {n}")
print(f"  unknown AirPods/Beats codes: {sorted(set(airpods_unknown))}")

# ── 6. WiFi probe data ──
section("6. WIFI PROBE DATA")
sources = collections.Counter()
for r in db.execute("SELECT source, COUNT(*) FROM sightings GROUP BY source ORDER BY 2 DESC"):
    sources[r["source"]] = r[1]
print("  sightings by source:")
for s, n in sources.most_common():
    print(f"    {s}: {n}")

# probe-request unique MACs
probe_macs = set()
for r in db.execute("SELECT DISTINCT mac FROM sightings WHERE source='wifi_probe'"):
    probe_macs.add(r["mac"])
print(f"\n  wifi_probe unique MACs: {len(probe_macs)}")

# overlap with BLE
ble_macs = set()
for r in db.execute("SELECT DISTINCT mac FROM sightings WHERE source='ble'"):
    ble_macs.add(r["mac"])
overlap = probe_macs & ble_macs
print(f"  probe MACs also seen on BLE: {len(overlap)}")
print(f"  probe MACs only on wifi_probe: {len(probe_macs - ble_macs)}")

# SSIDs from wifi_aps
print(f"\n  wifi_aps SSID distribution (top 25):")
ssid_c = collections.Counter()
for r in db.execute("SELECT ssid, COUNT(*) as n FROM wifi_aps GROUP BY ssid ORDER BY n DESC LIMIT 25"):
    ssid_c[r["ssid"]] = r["n"]
    print(f"    {r['ssid']}: {r['n']}")

# total unique SSIDs
total_ssids = db.execute("SELECT COUNT(DISTINCT ssid) FROM wifi_aps").fetchone()[0]
print(f"  total unique SSIDs: {total_ssids}")

# probe-request names (devices broadcasting a name in probe)
print(f"\n  probe-request device names (non-empty):")
probe_named = 0
probe_names = collections.Counter()
for r in db.execute("SELECT DISTINCT mac, name FROM sightings WHERE source='wifi_probe' AND name != '' AND name IS NOT NULL"):
    probe_named += 1
    probe_names[r["name"]] += 1
print(f"  probe MACs with a name: {probe_named}")
for name, n in probe_names.most_common(15):
    print(f"    {name}: {n}")

# ── 7. behavior + time-pattern coverage ──
section("7. BEHAVIOR + TIME-PATTERN COVERAGE")
# replicate behavior.classify_behavior + detect_time_pattern for all devices with >=5 sightings
# but that's 15K devices — sample the ones with enough data
behav_counts = collections.Counter()
pattern_counts = collections.Counter()
behav_by_type = collections.defaultdict(collections.Counter)
pattern_by_type = collections.defaultdict(collections.Counter)
devices_with_behavior = 0
devices_with_pattern = 0
devices_sampled = 0

# only classify devices with >= 5 sightings (MIN_SIGHTINGS_FOR_BEHAVIOR)
eligible = db.execute("SELECT mac, last_type FROM devices WHERE sighting_count >= 5").fetchall()
print(f"  devices with >=5 sightings (eligible for behavior): {len(eligible)}")

for dev in eligible:
    mac = dev["mac"]
    typ = dev["last_type"]
    rows = db.execute("SELECT ts, rssi FROM sightings WHERE mac=? ORDER BY ts", (mac,)).fetchall()
    if len(rows) < 5:
        continue
    devices_sampled += 1
    # behavior
    rssi_vals = [r["rssi"] for r in rows if r["rssi"] is not None]
    rssi_std = statistics.pstdev(rssi_vals) if len(rssi_vals) > 1 else 0
    hour_set = set()
    for r in rows:
        if r["ts"] >= now - 86400:
            hour_set.add(time.localtime(r["ts"]).tm_hour)
    active_hours = len(hour_set)
    by_hour = collections.Counter()
    for r in rows:
        if r["ts"] >= now - 86400:
            h = time.localtime(r["ts"]).tm_hour
            by_hour[h] += 1
    rates = list(by_hour.values()) if by_hour else [0]
    rate_med = statistics.median(rates) if rates else 0
    rate_max = max(rates) if rates else 0
    stationarity = "fixed" if rssi_vals and rssi_std < 8.0 else ("mobile" if rssi_vals else None)
    n = len(rows)
    rand = is_random_mac(mac)
    if n <= 20 and active_hours <= 3:
        behavior = "rotation" if rand else "transient"
    elif stationarity == "mobile":
        behavior = "mobile"
    elif active_hours >= 8:
        if rate_max >= 1.5 * max(rate_med, 1) and rate_max >= 18:
            behavior = "active-cyclic"
        else:
            behavior = "always-on"
    else:
        behavior = "intermittent"
    behav_counts[behavior] += 1
    behav_by_type[typ][behavior] += 1
    devices_with_behavior += 1

    # time pattern
    hours = collections.Counter()
    for r in rows:
        h = time.localtime(r["ts"]).tm_hour
        hours[h] += 1
    n_hours = len(hours)
    total = sum(hours.values())
    day_s = sum(v for h, v in hours.items() if 9 <= h < 17)
    eve_s = sum(v for h, v in hours.items() if 17 <= h < 23)
    night_s = sum(v for h, v in hours.items() if h >= 23 or h < 6)
    day_share = day_s / total if total else 0
    eve_share = eve_s / total if total else 0
    night_share = night_s / total if total else 0
    if n_hours <= 3:
        pattern = "transient"
    elif night_share >= 0.6:
        pattern = "night-only"
    elif day_share >= 0.5 and n_hours >= 8:
        pattern = "day-active"
    elif eve_share >= 0.45:
        pattern = "evening"
    elif n_hours >= 16:
        pattern = "always-on"
    else:
        pattern = "irregular"
    pattern_counts[pattern] += 1
    pattern_by_type[typ][pattern] += 1
    devices_with_pattern += 1

print(f"  devices classified for behavior: {devices_with_behavior}/{devices_sampled}")
print(f"\n  behavior distribution:")
for b, n in behav_counts.most_common():
    print(f"    {b}: {n} ({n/devices_with_behavior*100:.1f}%)")

print(f"\n  time-pattern distribution:")
for p, n in pattern_counts.most_common():
    print(f"    {p}: {n} ({n/devices_with_pattern*100:.1f}%)")

print(f"\n  behavior by device type (top types):")
for typ in ["phone-anon", "unknown", "sensor", "apple-device", "phone", "speaker", "iot"]:
    if typ in behav_by_type:
        print(f"    {typ}:")
        for b, n in behav_by_type[typ].most_common():
            print(f"      {b}: {n}")

print(f"\n  time-pattern by device type (top types):")
for typ in ["phone-anon", "unknown", "sensor", "apple-device", "phone", "speaker", "iot"]:
    if typ in pattern_by_type:
        print(f"    {typ}:")
        for p, n in pattern_by_type[typ].most_common():
            print(f"      {p}: {n}")

# ── 8. surprising findings ──
section("8. SURPRISING FINDINGS")

# most-sighted device
top_dev = db.execute("SELECT mac, oui_name, last_type, last_label, sighting_count FROM devices ORDER BY sighting_count DESC LIMIT 10").fetchall()
print("  most-sighted devices:")
for d in top_dev:
    rand = "random" if is_random_mac(d["mac"]) else "stable"
    print(f"    {d['mac']} n={d['sighting_count']} {rand} oui={d['oui_name']} type={d['last_type']} label={d['last_label']}")

# devices seen across all 24 hours
all_day_devs = []
for mac, hrs in mac_hours.items():
    if len(hrs) >= 20 and mac_count[mac] >= 50:
        dev = db.execute("SELECT oui_name, last_type, last_label, sighting_count FROM devices WHERE mac=?", (mac,)).fetchone()
        if dev:
            all_day_devs.append((mac, len(hrs), dev))
all_day_devs.sort(key=lambda x: -x[1])
print(f"\n  devices seen in >=20 distinct hours (always-on infrastructure): {len(all_day_devs)}")
for mac, nh, dev in all_day_devs[:10]:
    print(f"    {mac} hours={nh} n={dev['sighting_count']} oui={dev['oui_name']} type={dev['last_type']} label={dev['last_label']}")

# RSSI distribution
rssi_vals = [r["rssi"] for r in db.execute("SELECT rssi FROM sightings WHERE rssi IS NOT NULL")]
if rssi_vals:
    print(f"\n  RSSI stats (all sightings with RSSI): n={len(rssi_vals)}")
    print(f"    mean={statistics.mean(rssi_vals):.1f} median={statistics.median(rssi_vals):.1f} stdev={statistics.pstdev(rssi_vals):.1f}")
    print(f"    min={min(rssi_vals)} max={max(rssi_vals)}")
    # closest devices
    close = db.execute("SELECT s.mac, s.rssi, s.distance, d.oui_name, d.last_type FROM sightings s LEFT JOIN devices d ON s.mac=d.mac WHERE s.rssi IS NOT NULL AND s.rssi > -40 ORDER BY s.rssi DESC LIMIT 10").fetchall()
    print(f"  closest devices (RSSI > -40):")
    for c in close:
        print(f"    {c['mac']} rssi={c['rssi']} dist={c['distance']} oui={c['oui_name']} type={c['last_type']}")

# orphaned sightings
orphan = db.execute("SELECT COUNT(*) FROM sightings s LEFT JOIN devices d ON s.mac=d.mac WHERE d.mac IS NULL").fetchone()[0]
print(f"\n  orphaned sightings (no device row): {orphan}")

# null rssi
null_rssi = db.execute("SELECT COUNT(*) FROM sightings WHERE rssi IS NULL").fetchone()[0]
total_sight = db.execute("SELECT COUNT(*) FROM sightings").fetchone()[0]
print(f"  null RSSI: {null_rssi}/{total_sight} ({null_rssi/total_sight*100:.1f}%)")

# sensors table
sensors = db.execute("SELECT * FROM sensors").fetchall()
print(f"\n  sensors: {len(sensors)}")
for s in sensors:
    print(f"    {s['sensor_id']} loc={s['location_label']} x={s['x']} y={s['y']}")

# known_devices: how many match rogues
known = db.execute("SELECT mac FROM known_devices").fetchall()
known_macs = set(k["mac"] for k in known)
rogue_macs_set = set(r["mac"] for r in rogues)
print(f"\n  known_devices: {len(known_macs)}")
print(f"  rogue MACs in known_devices: {len(rogue_macs_set & known_macs)}")

# sites
sites = db.execute("SELECT * FROM sites").fetchall()
print(f"  sites: {len(sites)}")
for s in sites:
    print(f"    {s['site_id']} label={s['label']}")

# devices with site_id set
sited = db.execute("SELECT COUNT(*) FROM devices WHERE site_id IS NOT NULL").fetchone()[0]
print(f"  devices with site_id: {sited}")

# tracked devices
tracked = db.execute("SELECT COUNT(*) FROM devices WHERE tracked=1").fetchone()[0]
print(f"  tracked devices: {tracked}")

# is_mine
mine = db.execute("SELECT COUNT(*) FROM devices WHERE is_mine=1").fetchone()[0]
print(f"  is_mine devices: {mine}")

# watch_note
watched = db.execute("SELECT COUNT(*) FROM devices WHERE watch_note IS NOT NULL AND watch_note != ''").fetchone()[0]
print(f"  watched devices: {watched}")

# ── extra: named devices that are unknown ──
print(f"\n  --- named 'unknown' devices (could add name rules) ---")
named_unknown = db.execute("SELECT last_label, COUNT(*) as n FROM devices WHERE last_type='unknown' AND last_label IS NOT NULL AND last_label != '' GROUP BY last_label ORDER BY n DESC LIMIT 20").fetchall()
for r in named_unknown:
    print(f"    {r['last_label']}: {r['n']}")

print("\n\nDONE.")
conn.close()
