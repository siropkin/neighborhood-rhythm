#!/usr/bin/env python3
import sqlite3, json, collections
db = sqlite3.connect("/home/siropkin/neighborhood-rhythm/rhythm.db")
db.row_factory = sqlite3.Row
type_counter = collections.Counter()
nearby_lens = collections.Counter()
airpods_models = collections.Counter()
airpods_unknown = []
nearby_auth = 0
nearby_total = 0
apple_total = 0
action_codes = collections.Counter()
for r in db.execute('SELECT extra FROM sightings WHERE extra LIKE "%apple%"'):
    try:
        e = json.loads(r["extra"])
    except:
        continue
    a = e.get("apple")
    if not a:
        continue
    apple_total += 1
    types = a.get("types", [])
    for t in types:
        type_counter[t] += 1
    if "nearby_info" in types:
        nearby_list = a.get("nearby", [])
        for nb in nearby_list:
            nearby_total += 1
            if nb.get("auth_tag"):
                nearby_auth += 1
            p = nb.get("payload_hex", "")
            if p:
                nearby_lens[len(p) // 2] += 1
            ac = nb.get("action_code")
            if ac is not None:
                action_codes[ac] += 1
    if "proximity_pairing" in types:
        model = a.get("model_code")
        model_name = a.get("model_name")
        key = str(model) + " " + str(model_name)
        airpods_models[key] += 1
        if model_name and "unknown" in str(model_name).lower():
            airpods_unknown.append(model)

print("Apple sightings:", apple_total)
print("\nApple types:")
for t, n in type_counter.most_common():
    print("  " + str(t) + ": " + str(n))
print("\nNearby total:", nearby_total, "with auth_tag:", nearby_auth)
print("\nNearby payload lengths (bytes):")
for l, n in sorted(nearby_lens.items()):
    print("  " + str(l) + " bytes: " + str(n))
print("\nNearby action codes:")
for ac, n in sorted(action_codes.items()):
    print("  0x" + format(ac, '02x') + ": " + str(n))
print("\nAirPods models:")
for m, n in sorted(airpods_models.items(), key=lambda x: -x[1]):
    print("  " + m + ": " + str(n))
print("\nUnknown AirPods codes:", sorted(set(airpods_unknown)))
