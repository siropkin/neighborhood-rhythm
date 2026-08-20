#!/usr/bin/env python3
import sqlite3, json, collections, time
db = sqlite3.connect("/home/siropkin/neighborhood-rhythm/rhythm.db")
db.row_factory = sqlite3.Row

# mamaRoo5 — how many distinct units? Are they always-on or intermittent?
print("=== mamaRoo5 cluster ===")
mama = db.execute("SELECT mac, sighting_count, first_seen, last_seen FROM devices WHERE last_label='mamaRoo5' ORDER BY sighting_count DESC").fetchall()
print(f"Count: {len(mama)}")
sightings_total = sum(d["sighting_count"] for d in mama)
print(f"Total sightings: {sightings_total}")
# how many seen in last 24h?
now = time.time()
recent = sum(1 for d in mama if (now - d["last_seen"]) < 86400)
print(f"Seen in last 24h: {recent}")
# sighting count distribution
sc = collections.Counter(d["sighting_count"] for d in mama)
print("Sighting count distribution:")
for n, c in sorted(sc.items()):
    print(f"  {n} sightings: {c} devices")
# are they all different MACs? (yes, by definition)
# check if any are linked by fingerprint
for d in mama[:5]:
    fp = db.execute("SELECT fingerprint_id FROM device_aliases WHERE mac=?", (d["mac"],)).fetchone()
    print(f"  {d['mac']} n={d['sighting_count']} fp={fp['fingerprint_id'] if fp else 'none'}")

# 3429 no-OUI stable unknowns — what are they?
# Check if they have any sightings with services or name
print("\n=== no-OUI stable unknowns (3429) ===")
no_oui = db.execute("SELECT mac, last_label, sighting_count FROM devices WHERE last_type='unknown' AND (oui_name IS NULL OR oui_name='')").fetchall()
print(f"Count: {len(no_oui)}")
# sighting count distribution
sc2 = collections.Counter()
for d in no_oui:
    if d["sighting_count"] == 1: sc2["1"] += 1
    elif d["sighting_count"] <= 5: sc2["2-5"] += 1
    elif d["sighting_count"] <= 20: sc2["6-20"] += 1
    elif d["sighting_count"] <= 100: sc2["21-100"] += 1
    else: sc2["100+"] += 1
print("Sighting count distribution:")
for k in ["1","2-5","6-20","21-100","100+"]:
    print(f"  {k}: {sc2[k]}")
# check a sample — do they have any name/services in sightings?
print("\nSample no-OUI unknowns (top 10 by sightings):")
for d in sorted(no_oui, key=lambda x: -x["sighting_count"])[:10]:
    s = db.execute("SELECT name, services, source FROM sightings WHERE mac=? ORDER BY ts DESC LIMIT 1", (d["mac"],)).fetchone()
    print(f"  {d['mac']} n={d['sighting_count']} name={s['name'] if s else 'none'} svc={s['services'] if s else 'none'} src={s['source'] if s else 'none'}")

# Are these registered MACs that just have no OUI in the database?
# Check first 3 bytes (OUI prefix)
print("\nOUI prefix distribution (top 20) for no-OUI unknowns:")
prefixes = collections.Counter()
for d in no_oui:
    prefixes[d["mac"][:8].upper()] += 1
for p, n in prefixes.most_common(20):
    print(f"  {p}: {n}")

# Reid Casa San Mateo — what is it?
print("\n=== Reid Casa San Mateo ===")
reid = db.execute("SELECT mac, oui_name, last_type, last_label, sighting_count FROM devices WHERE last_label LIKE '%Reid%' OR last_label LIKE '%Casa%'").fetchall()
for d in reid:
    print(f"  {d['mac']} oui={d['oui_name']} type={d['last_type']} label={d['last_label']} n={d['sighting_count']}")

# SSID census — identifiable networks
print("\n=== SSID census (identifiable) ===")
ssids = db.execute("SELECT ssid, COUNT(*) as n FROM wifi_aps WHERE ssid IS NOT NULL GROUP BY ssid ORDER BY n DESC").fetchall()
# categorize: personal, business, xfinity, hidden
personal = []
business = []
xfinity = []
hidden = []
for s in ssids:
    name = s["ssid"]
    n = s["n"]
    if "xfinity" in name.lower() or "xfset" in name.lower():
        xfinity.append((name, n))
    elif name.startswith("__NA"):
        hidden.append((name, n))
    elif any(x in name.lower() for x in ["siropkin", "3cats", "aspen", "hello", "corona", "bugfree", "wideshoes", "xtrinitya", "xixi", "xfpine", "home", "aha", "twyn"]):
        personal.append((name, n))
    else:
        business.append((name, n))
print(f"Personal/residential SSIDs ({len(personal)}):")
for name, n in sorted(personal, key=lambda x: -x[1]):
    print(f"  {name}: {n}")
print(f"\nBusiness/venue SSIDs ({len(business)}):")
for name, n in sorted(business, key=lambda x: -x[1]):
    print(f"  {name}: {n}")
print(f"\nXfinity/Comcast ({len(xfinity)}):")
for name, n in sorted(xfinity, key=lambda x: -x[1]):
    print(f"  {name}: {n}")
print(f"\nHidden/NA ({len(hidden)}):")
for name, n in sorted(hidden, key=lambda x: -x[1]):
    print(f"  {name}: {n}")

# Probe-request device names — these reveal who's probing
print("\n=== Probe-request device names (passive census) ===")
probe_names = db.execute("SELECT DISTINCT name, mac FROM sightings WHERE source='wifi_probe' AND name IS NOT NULL AND name != ''").fetchall()
print(f"Named probe devices: {len(probe_names)}")
# These names are often the device's configured SSID or device name
for p in probe_names[:20]:
    print(f"  {p['mac']} -> {p['name']}")

# The "always-on" phone-anon devices — phones that don't rotate?
print("\n=== phone-anon seen in 24 hours (non-rotating?) ===")
always_on_pa = db.execute("SELECT mac, sighting_count FROM devices WHERE last_type='phone-anon' AND sighting_count > 500 ORDER BY sighting_count DESC LIMIT 20").fetchall()
for d in always_on_pa:
    # check RSSI std
    rssi = [r["rssi"] for r in db.execute("SELECT rssi FROM sightings WHERE mac=? AND rssi IS NOT NULL", (d["mac"],)).fetchall()]
    std = (sum((x - sum(rssi)/len(rssi))**2 for x in rssi) / len(rssi))**0.5 if rssi else 0
    print(f"  {d['mac']} n={d['sighting_count']} rssi_std={std:.1f}")

# Check the 8-MAC rotation cluster (biggest fingerprint)
print("\n=== 8-MAC rotation cluster (0bac4427) ===")
fp_macs = db.execute("SELECT mac FROM device_aliases WHERE fingerprint_id='0bac4427-afee-40d4-89be-8942c1d70a13'").fetchall()
for m in fp_macs:
    s = db.execute("SELECT MIN(ts), MAX(ts), COUNT(*) FROM sightings WHERE mac=?", (m["mac"],)).fetchone()
    span_min = (s[1] - s[0]) / 60
    print(f"  {m['mac']} n={s[2]} span={span_min:.0f}min first={time.strftime('%m-%d %H:%M', time.localtime(s[0]))} last={time.strftime('%m-%d %H:%M', time.localtime(s[1]))}")

# How many AirTags?
print("\n=== AirTag analysis ===")
airtag_macs = set()
for r in db.execute('SELECT mac, extra FROM sightings WHERE extra LIKE "%airtag%"'):
    try:
        e = json.loads(r["extra"])
        if "airtag" in e.get("apple", {}).get("types", []):
            airtag_macs.add(r["mac"])
    except: pass
print(f"Distinct AirTag MACs: {len(airtag_macs)}")
for m in list(airtag_macs)[:10]:
    d = db.execute("SELECT mac, oui_name, last_type, sighting_count FROM devices WHERE mac=?", (m,)).fetchone()
    if d:
        print(f"  {m} oui={d['oui_name']} type={d['last_type']} n={d['sighting_count']}")
    else:
        print(f"  {m} (no device row)")
