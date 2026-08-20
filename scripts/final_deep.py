#!/usr/bin/env python3
import sqlite3, json, collections, time
db = sqlite3.connect("/home/siropkin/neighborhood-rhythm/rhythm.db")
db.row_factory = sqlite3.Row

# AirTag MAC rotation — how many physical AirTags?
# AirTags rotate MAC every ~15 min. If we see 2144 MACs over 4 days...
# Check how many sightings per AirTag MAC
print("=== AirTag MAC rotation analysis ===")
airtag_data = []
for r in db.execute('SELECT mac, extra FROM sightings WHERE extra LIKE "%airtag%"'):
    try:
        e = json.loads(r["extra"])
        if "airtag" in e.get("apple", {}).get("types", []):
            airtag_data.append(r["mac"])
    except: pass
mac_counts = collections.Counter(airtag_data)
print(f"Distinct AirTag MACs: {len(mac_counts)}")
print(f"Total AirTag sightings: {sum(mac_counts.values())}")
print(f"Average sightings per MAC: {sum(mac_counts.values())/len(mac_counts):.2f}")
sc = collections.Counter(mac_counts.values())
print("Sightings per MAC distribution:")
for n, c in sorted(sc.items())[:10]:
    print(f"  {n} sighting(s): {c} MACs")

# If AirTags rotate every 15 min, and we scan every 5 min, each MAC should get 1-3 sightings
# 2144 MACs * ~1.3 sightings = ~2787 sightings. With 4 days = 5760 min / 15 min rotation = 384 rotations per AirTag
# So 2144 / 384 = ~5.6 physical AirTags? But many MACs have no device row (pruned)
# Better: count distinct status bytes (AirTag status byte varies by MAC rotation)
print("\nAirTag status byte distribution:")
statuses = collections.Counter()
for r in db.execute('SELECT extra FROM sightings WHERE extra LIKE "%airtag%"'):
    try:
        e = json.loads(r["extra"])
        a = e.get("apple", {})
        if "airtag" in a.get("types", []):
            statuses[a.get("status", "none")] += 1
    except: pass
for s, n in statuses.most_common():
    print(f"  status={s}: {n}")

# phone-anon with 0 RSSI std — what are they?
print("\n=== phone-anon with 0 RSSI std (non-rotating random MACs) ===")
for d in db.execute("SELECT mac, sighting_count FROM devices WHERE last_type='phone-anon' AND sighting_count > 500 ORDER BY sighting_count DESC LIMIT 5"):
    rssi = [r["rssi"] for r in db.execute("SELECT rssi FROM sightings WHERE mac=? AND rssi IS NOT NULL", (d["mac"],)).fetchall()]
    distinct_rssi = set(rssi)
    sources = collections.Counter(r["source"] for r in db.execute("SELECT source FROM sightings WHERE mac=?", (d["mac"],)).fetchall())
    print(f"  {d['mac']} n={d['sighting_count']} distinct_rssi={len(distinct_rssi)} vals={sorted(dist_rssi)[:5] if len(distinct_rssi)<=5 else sorted(distinct_rssi)[:5]}... sources={dict(sources)}")

# 2e:d2:ee:cf:cc:61 — 1843 sightings, RSSI std 0.0 — what source?
print("\n  Deep dive: 2e:d2:ee:cf:cc:61 (1843 sightings)")
for r in db.execute("SELECT source, rssi, name, services, ts FROM sightings WHERE mac='2e:d2:ee:cf:cc:61' ORDER BY ts DESC LIMIT 5"):
    print(f"    src={r['source']} rssi={r['rssi']} name={r['name']} svc={r['services']} ts={time.strftime('%m-%d %H:%M', time.localtime(r['ts']))}")
# check extra
for r in db.execute("SELECT extra FROM sightings WHERE mac='2e:d2:ee:cf:cc:61' AND extra IS NOT NULL LIMIT 1"):
    print(f"    extra: {r['extra'][:200]}")

# How many phone-anon have >100 sightings (potential non-phones)?
high_pa = db.execute("SELECT COUNT(*) FROM devices WHERE last_type='phone-anon' AND sighting_count > 100").fetchone()[0]
print(f"\n  phone-anon with >100 sightings: {high_pa}")
high_pa_500 = db.execute("SELECT COUNT(*) FROM devices WHERE last_type='phone-anon' AND sighting_count > 500").fetchone()[0]
print(f"  phone-anon with >500 sightings: {high_pa_500}")

# Check: are these high-sighting phone-anon devices actually Apple Continuity?
# (Apple devices rotate MACs but broadcast Continuity — they'd be classified as phone-anon if no OUI)
print("\n  High-sighting phone-anon with Apple data:")
for d in db.execute("SELECT mac, sighting_count FROM devices WHERE last_type='phone-anon' AND sighting_count > 500 ORDER BY sighting_count DESC LIMIT 5"):
    has_apple = db.execute("SELECT COUNT(*) FROM sightings WHERE mac=? AND extra LIKE '%apple%'", (d["mac"],)).fetchone()[0]
    print(f"    {d['mac']} n={d['sighting_count']} apple_sightings={has_apple}")

# Vantiva — all 39 are rogues, none known. What types of Vantiva?
print("\n=== Vantiva deep dive ===")
vantiva = db.execute("SELECT mac, last_type, last_label, sighting_count FROM devices WHERE oui_name LIKE '%Vantiva%' ORDER BY sighting_count DESC").fetchall()
print(f"Total Vantiva devices: {len(vantiva)}")
for d in vantiva[:5]:
    print(f"  {d['mac']} type={d['last_type']} label={d['last_label']} n={d['sighting_count']}")
# How many distinct Vantiva OUI prefixes?
prefixes = collections.Counter(d["mac"][:8].upper() for d in vantiva)
print("OUI prefixes:")
for p, n in prefixes.most_common():
    print(f"  {p}: {n}")

# Check the "KYNE_APT" SSIDs — how many apartments?
print("\n=== KYNE apartment SSIDs ===")
kyne = db.execute("SELECT ssid FROM wifi_aps WHERE ssid LIKE '%KYNE%' OR ssid LIKE '%PADDOCK%' OR ssid LIKE '%PONY%'").fetchall()
for k in kyne:
    print(f"  {k['ssid']}")
