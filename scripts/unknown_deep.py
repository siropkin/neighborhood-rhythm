#!/usr/bin/env python3
import sqlite3, json, collections
db = sqlite3.connect("/home/siropkin/neighborhood-rhythm/rhythm.db")
db.row_factory = sqlite3.Row

def is_random_mac(mac):
    if not mac: return False
    h = mac.replace(":","").replace("-","")
    if len(h) != 12: return False
    try: first = int(h[0:2], 16)
    except ValueError: return False
    return bool(first & 0b11)

# unknown deep dive
unknowns = db.execute("SELECT mac, oui_name, last_label FROM devices WHERE last_type='unknown'").fetchall()
print("Total unknown:", len(unknowns))
random_u = [d for d in unknowns if is_random_mac(d["mac"])]
stable_u = [d for d in unknowns if not is_random_mac(d["mac"])]
print("Random-MAC unknowns:", len(random_u))
print("Stable-MAC unknowns:", len(stable_u))

# stable unknowns: with OUI vs without
with_oui = [d for d in stable_u if d["oui_name"]]
no_oui = [d for d in stable_u if not d["oui_name"]]
print("  stable with OUI:", len(with_oui))
print("  stable without OUI (no OUI lookup):", len(no_oui))

# no-OUI stable MACs — check if they are actually locally-administered
# (is_random_mac checks bit 0 or 1; but some MACs might have bit 2 set = different)
print("\n  stable no-OUI MACs (first 20):")
for d in no_oui[:20]:
    h = d["mac"].replace(":","")
    first = int(h[0:2], 16)
    la_bit = "LA" if (first & 0b11) else "registered"
    print(f"    {d['mac']} first_byte=0x{first:02x} {la_bit} label={d['last_label']}")

# stable with OUI — top OUIs
print("\n  stable unknown with OUI (top 20):")
oui_c = collections.Counter(d["oui_name"] for d in with_oui)
for o, n in oui_c.most_common(20):
    print(f"    {o}: {n}")

# how many stable unknowns have a name?
named = [d for d in stable_u if d["last_label"]]
print(f"\n  stable unknowns with a name: {len(named)}")
for d in sorted(named, key=lambda x: x["last_label"]):
    print(f"    {d['mac']} oui={d['oui_name']} label={d['last_label']}")

# check: are there random MACs classified as unknown with a name?
# (the classify.py line 43-44: random MAC + name -> unknown)
print("\n  random-MAC unknowns (should not exist after fix):", len(random_u))
for d in random_u[:5]:
    print(f"    {d['mac']} oui={d['oui_name']} label={d['last_label']}")

# Check the "Private" OUI — these are random MACs that got an OUI of "Private"
print("\n  'Private' OUI unknowns:")
for d in db.execute("SELECT mac, oui_name, last_label FROM devices WHERE last_type='unknown' AND oui_name='Private'"):
    rand = is_random_mac(d["mac"])
    print(f"    {d['mac']} random={rand} label={d['last_label']}")

# Vantiva rogue check — how many Vantiva devices total vs rogues
vantiva_total = db.execute("SELECT COUNT(*) FROM devices WHERE oui_name LIKE '%Vantiva%'").fetchone()[0]
vantiva_rogue = db.execute("SELECT COUNT(*) FROM rogue_events WHERE oui_name LIKE '%Vantiva%'").fetchone()[0]
print(f"\n  Vantiva devices total: {vantiva_total}, Vantiva rogues: {vantiva_rogue}")

# Check if any Vantiva are in known_devices
vantiva_known = 0
for d in db.execute("SELECT mac FROM devices WHERE oui_name LIKE '%Vantiva%'"):
    k = db.execute("SELECT 1 FROM known_devices WHERE mac=?", (d["mac"],)).fetchone()
    if k: vantiva_known += 1
print(f"  Vantiva in known_devices: {vantiva_known}")
