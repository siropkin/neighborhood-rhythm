#!/usr/bin/env python3
import sqlite3, json, collections, time
db = sqlite3.connect("/home/siropkin/neighborhood-rhythm/rhythm.db")
db.row_factory = sqlite3.Row

# phone-anon with 0 RSSI std
print("=== phone-anon with 0 RSSI std (non-rotating random MACs) ===")
for d in db.execute("SELECT mac, sighting_count FROM devices WHERE last_type='phone-anon' AND sighting_count > 500 ORDER BY sighting_count DESC LIMIT 5"):
    rssi = [r["rssi"] for r in db.execute("SELECT rssi FROM sightings WHERE mac=? AND rssi IS NOT NULL", (d["mac"],)).fetchall()]
    dr = set(rssi)
    sources = collections.Counter(r["source"] for r in db.execute("SELECT source FROM sightings WHERE mac=?", (d["mac"],)).fetchall())
    print("  " + d["mac"] + " n=" + str(d["sighting_count"]) + " distinct_rssi=" + str(len(dr)) + " vals=" + str(sorted(dr)[:5]) + " sources=" + str(dict(sources)))

print("\n  Deep dive: 2e:d2:ee:cf:cc:61 (1843 sightings)")
for r in db.execute("SELECT source, rssi, name, services, ts FROM sightings WHERE mac='2e:d2:ee:cf:cc:61' ORDER BY ts DESC LIMIT 5"):
    print("    src=" + str(r["source"]) + " rssi=" + str(r["rssi"]) + " name=" + str(r["name"]) + " ts=" + time.strftime('%m-%d %H:%M', time.localtime(r["ts"])))
for r in db.execute("SELECT extra FROM sightings WHERE mac='2e:d2:ee:cf:cc:61' AND extra IS NOT NULL LIMIT 1"):
    print("    extra: " + str(r["extra"])[:200])

high_pa = db.execute("SELECT COUNT(*) FROM devices WHERE last_type='phone-anon' AND sighting_count > 100").fetchone()[0]
print("\n  phone-anon with >100 sightings: " + str(high_pa))
high_pa_500 = db.execute("SELECT COUNT(*) FROM devices WHERE last_type='phone-anon' AND sighting_count > 500").fetchone()[0]
print("  phone-anon with >500 sightings: " + str(high_pa_500))

print("\n  High-sighting phone-anon with Apple data:")
for d in db.execute("SELECT mac, sighting_count FROM devices WHERE last_type='phone-anon' AND sighting_count > 500 ORDER BY sighting_count DESC LIMIT 5"):
    has_apple = db.execute("SELECT COUNT(*) FROM sightings WHERE mac=? AND extra LIKE '%apple%'", (d["mac"],)).fetchone()[0]
    print("    " + d["mac"] + " n=" + str(d["sighting_count"]) + " apple_sightings=" + str(has_apple))

print("\n=== Vantiva deep dive ===")
vantiva = db.execute("SELECT mac, last_type, last_label, sighting_count FROM devices WHERE oui_name LIKE '%Vantiva%' ORDER BY sighting_count DESC").fetchall()
print("Total Vantiva devices: " + str(len(vantiva)))
for d in vantiva[:5]:
    print("  " + d["mac"] + " type=" + str(d["last_type"]) + " label=" + str(d["last_label"]) + " n=" + str(d["sighting_count"]))
prefixes = collections.Counter(d["mac"][:8].upper() for d in vantiva)
print("OUI prefixes:")
for p, n in prefixes.most_common():
    print("  " + p + ": " + str(n))

print("\n=== KYNE apartment SSIDs ===")
kyne = db.execute("SELECT ssid FROM wifi_aps WHERE ssid LIKE '%KYNE%' OR ssid LIKE '%PADDOCK%' OR ssid LIKE '%PONY%'").fetchall()
for k in kyne:
    print("  " + k["ssid"])

# How many phone-anon are actually Apple Continuity devices?
print("\n=== phone-anon with Apple Continuity ===")
pa_apple = 0
pa_total = 0
for d in db.execute("SELECT mac FROM devices WHERE last_type='phone-anon'"):
    pa_total += 1
    has_apple = db.execute("SELECT COUNT(*) FROM sightings WHERE mac=? AND extra LIKE '%apple%'", (d["mac"],)).fetchone()[0]
    if has_apple > 0:
        pa_apple += 1
print("  phone-anon total: " + str(pa_total))
print("  phone-anon with Apple data: " + str(pa_apple))
