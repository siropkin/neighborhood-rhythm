"""Live-data analysis for Neighborhood Rhythm. Read-only — no writes to the DB.
Run on the Pi: python3 scripts/analyze_data.py
Dumps a markdown report to stdout. Save to docs/DATA-ANALYSIS.md.
"""
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

DB = "/home/siropkin/neighborhood-rhythm/rhythm.db"


def q(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def scalar(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def ts_to_dt(ts):
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def hr():
    print("\n---")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    now = scalar(conn, "SELECT MAX(ts) FROM sightings")
    now_dt = ts_to_dt(now) if now else "?"
    span_first = scalar(conn, "SELECT MIN(ts) FROM sightings")
    print(f"# Neighborhood Rhythm — live data analysis")
    print(f"_Generated from {DB}_")
    print(f"_Latest sighting: {now_dt} (span since {ts_to_dt(span_first)})_")
    hr()

    # ---- overview ----
    n_devices = scalar(conn, "SELECT COUNT(*) FROM devices")
    n_sightings = scalar(conn, "SELECT COUNT(*) FROM sightings")
    n_hourly = scalar(conn, "SELECT COUNT(*) FROM sightings_hourly")
    n_fps = scalar(conn, "SELECT COUNT(*) FROM device_fingerprints")
    n_aliases = scalar(conn, "SELECT COUNT(*) FROM device_aliases")
    n_sensors = scalar(conn, "SELECT COUNT(*) FROM sensors")
    n_rogues = scalar(conn, "SELECT COUNT(*) FROM rogue_events")
    n_rogues_unresolved = scalar(conn, "SELECT COUNT(*) FROM rogue_events WHERE resolved=0")
    n_wifi_aps = scalar(conn, "SELECT COUNT(*) FROM wifi_aps")
    n_known = scalar(conn, "SELECT COUNT(*) FROM known_devices")
    print(f"## Overview")
    print(f"- devices: **{n_devices}**")
    print(f"- sightings (raw): **{n_sightings}**")
    print(f"- sightings_hourly: **{n_hourly}**")
    print(f"- fingerprints: **{n_fps}**  aliases: **{n_aliases}**")
    print(f"- sensors: **{n_sensors}**  wifi_aps: **{n_wifi_aps}**")
    print(f"- rogue_events: **{n_rogues}** ({n_rogues_unresolved} unresolved)")
    print(f"- known_devices: **{n_known}**")

    # ---- 1. device-class distribution ----
    hr()
    print(f"## 1. Device-class distribution")
    print("### devices.last_type (one row per MAC)")
    rows = q(conn, "SELECT last_type, COUNT(*) c FROM devices GROUP BY last_type ORDER BY c DESC")
    total = sum(r[1] for r in rows)
    for r in rows:
        pct = 100.0 * r[1] / total if total else 0
        print(f"- `{r['last_type'] or '(null)'}`: {r[1]} ({pct:.1f}%)")
    print("### fingerprint device_class (deduplicated)")
    rows = q(conn, "SELECT device_class, COUNT(*) c FROM device_fingerprints GROUP BY device_class ORDER BY c DESC")
    fp_total = sum(r[1] for r in rows)
    for r in rows:
        pct = 100.0 * r[1] / fp_total if fp_total else 0
        print(f"- `{r['device_class'] or '(null)'}`: {r[1]} ({pct:.1f}%)")
    # unknown bucket — what could reduce it
    n_unknown = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_type='unknown'")
    n_unknown_named = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_type='unknown' AND last_label IS NOT NULL")
    n_unknown_nooui = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_type='unknown' AND (oui_name IS NULL OR oui_name='')")
    n_unknown_random = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_type='unknown' AND mac NOT LIKE 'mdns:%' AND substr(mac,1,2) IN ('6','7','8','9','a','b','c','d','e','f')")
    print(f"### unknown bucket breakdown ({n_unknown} unknown)")
    print(f"- with a name/label (could be reclassified by name rules): {n_unknown_named}")
    print(f"- no OUI (random/anonymous): {n_unknown_nooui}")
    # surprising clusters — top OUIs and top labels
    print("### top OUI vendors (devices)")
    rows = q(conn, "SELECT oui_name, COUNT(*) c FROM devices WHERE oui_name IS NOT NULL AND oui_name!='' GROUP BY oui_name ORDER BY c DESC LIMIT 15")
    for r in rows:
        print(f"- {r['oui_name']}: {r[1]}")
    print("### top labels (devices.last_label)")
    rows = q(conn, "SELECT last_label, COUNT(*) c FROM devices WHERE last_label IS NOT NULL GROUP BY last_label ORDER BY c DESC LIMIT 20")
    for r in rows:
        print(f"- {r['last_label']}: {r[1]}")
    # surprising clusters: Vantiva, Sonos, etc.
    for kw in ["Vantiva", "Sonos", "iRobot", "Roomba", "Govee", "Ruuvi", "Nest", "ecobee", "Chromecast", "Yandex", "Apple", "Samsung", "ESP"]:
        c = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_label LIKE ? OR oui_name LIKE ?", (f"%{kw}%", f"%{kw}%"))
        if c:
            print(f"- cluster `{kw}`: {c} devices")

    # ---- 2. temporal patterns ----
    hr()
    print(f"## 2. Temporal patterns")
    # daily rhythm: sightings per local hour (use UTC hour as proxy; note tz)
    rows = q(conn, """SELECT CAST(ts/3600 AS INTEGER) % 24 AS h, COUNT(*) c
                      FROM sightings GROUP BY h ORDER BY h""")
    print("### sightings by hour-of-day (UTC)")
    for r in rows:
        print(f"- {r['h']:02d}:00 — {r[1]}")
    # distinct devices per hour
    rows = q(conn, """SELECT CAST(ts/3600 AS INTEGER) % 24 AS h, COUNT(DISTINCT mac) c
                      FROM sightings GROUP BY h ORDER BY h""")
    print("### distinct devices by hour-of-day (UTC)")
    for r in rows:
        print(f"- {r['h']:02d}:00 — {r[1]}")
    # night-only devices: first_seen and last_seen both in 00-05 UTC, seen >=2 times
    # "night" is rough — Pi is likely UTC+3 (Russia) so night UTC ~ day local; flag both
    print("### night-only devices (all sightings in 00-05 UTC, seen >=3 times)")
    rows = q(conn, """SELECT mac, COUNT(*) c, MIN(ts) mn, MAX(ts) mx FROM sightings
                      GROUP BY mac HAVING c>=3 AND
                      MIN(CAST(ts/3600 AS INTEGER)%24) <= 5 AND
                      MAX(CAST(ts/3600 AS INTEGER)%24) <= 5
                      ORDER BY c DESC LIMIT 20""")
    for r in rows:
        print(f"- {r['mac']}: {r[1]} sightings, {ts_to_dt(r['mn'])}..{ts_to_dt(r['mx'])}")
    if not rows:
        print("- (none)")
    # devices that disappear and reappear on a schedule: gap analysis
    print("### devices with long gaps then reappearance (>= 1 day gap, seen again after)")
    rows = q(conn, """WITH g AS (
        SELECT mac, ts, LAG(ts) OVER (PARTITION BY mac ORDER BY ts) prev_ts FROM sightings
      ) SELECT mac, COUNT(*) gaps, MAX(ts-prev_ts) max_gap, MIN(ts-prev_ts) min_gap
        FROM g WHERE prev_ts IS NOT NULL AND ts-prev_ts >= 86400
        GROUP BY mac ORDER BY max_gap DESC LIMIT 15""")
    for r in rows:
        print(f"- {r['mac']}: {r['gaps']} gap(s), max gap {r['max_gap']/86400:.1f}d, min {r['min_gap']/86400:.1f}d")
    if not rows:
        print("- (none)")

    # ---- 3. fingerprint quality ----
    hr()
    print(f"## 3. Fingerprint quality")
    # devices with >1 alias (linked)
    rows = q(conn, """SELECT fingerprint_id, COUNT(*) n FROM device_aliases
                      GROUP BY fingerprint_id HAVING n > 1 ORDER BY n DESC""")
    n_linked = len(rows)
    print(f"### fingerprints with >1 alias (linked): **{n_linked}**")
    for r in rows[:15]:
        fp = r[0]
        cls = scalar(conn, "SELECT device_class FROM device_fingerprints WHERE fingerprint_id=?", (fp,))
        lbl = scalar(conn, "SELECT label FROM device_fingerprints WHERE fingerprint_id=?", (fp,))
        macs = q(conn, "SELECT mac, source, link_method FROM device_aliases WHERE fingerprint_id=?", (fp,))
        print(f"- fp `{fp[:8]}` ({cls}, `{lbl}`): {r[1]} aliases")
        for m in macs:
            print(f"    - {m['mac']} [{m['source']}/{m['link_method']}]")
    # link-method breakdown
    print("### link-method breakdown (aliases)")
    rows = q(conn, "SELECT link_method, COUNT(*) c FROM device_aliases GROUP BY link_method ORDER BY c DESC")
    for r in rows:
        print(f"- {r['link_method']}: {r[1]}")
    # missed links: pairs always seen together but not linked (use detect_copresence logic)
    print("### candidate missed links (co-presence >=0.85, not in same fingerprint)")
    # build minute-sets for stable devices
    stable = [r[0] for r in q(conn, "SELECT mac FROM devices WHERE sighting_count >= 10 AND mac NOT LIKE 'mdns:%'")]
    # filter random macs roughly
    def is_random(mac):
        try:
            first = int(mac[0:2], 16)
            return bool(first & 0b10)
        except Exception:
            return False
    stable = [m for m in stable if not is_random(m)]
    minutes = {}
    for mac in stable:
        rs = q(conn, "SELECT DISTINCT CAST(ts/60 AS INTEGER) m FROM sightings WHERE mac=?", (mac,))
        minutes[mac] = {r[0] for r in rs}
    pairs = []
    for i, a in enumerate(stable):
        ma = minutes[a]
        if len(ma) < 10:
            continue
        for b in stable[i+1:]:
            mb = minutes[b]
            if len(mb) < 10:
                continue
            overlap = len(ma & mb)
            union = len(ma | mb)
            if union == 0:
                continue
            ratio = overlap / union
            if ratio >= 0.85:
                pairs.append((a, b, overlap, len(ma), len(mb), round(ratio, 2)))
    pairs.sort(key=lambda p: -p[5])
    # check which are already linked
    n_already = 0
    n_missed = 0
    for a, b, ov, na, nb, r in pairs[:25]:
        fa = scalar(conn, "SELECT fingerprint_id FROM device_aliases WHERE mac=?", (a,))
        fb = scalar(conn, "SELECT fingerprint_id FROM device_aliases WHERE mac=?", (b,))
        same = (fa and fb and fa == fb)
        if same:
            n_already += 1
        else:
            n_missed += 1
            la = scalar(conn, "SELECT last_label FROM devices WHERE mac=?", (a,))
            lb = scalar(conn, "SELECT last_label FROM devices WHERE mac=?", (b,))
            print(f"- {a} ({la}) + {b} ({lb}): co-presence {r}, overlap {ov} — NOT linked")
    print(f"- (checked top {len(pairs[:25])} pairs: {n_already} already linked, {n_missed} missed)")
    if not pairs:
        print("- (none)")

    # ---- 4. rogue detection quality ----
    hr()
    print(f"## 4. Rogue detection quality")
    rows = q(conn, "SELECT resolved, COUNT(*) c FROM rogue_events GROUP BY resolved")
    for r in rows:
        print(f"- resolved={r['resolved']}: {r[1]}")
    # identifiable rogues (have vendor or label)
    n_rog_total = scalar(conn, "SELECT COUNT(*) FROM rogue_events WHERE resolved=0")
    n_rog_vendor = scalar(conn, "SELECT COUNT(*) FROM rogue_events WHERE resolved=0 AND oui_name IS NOT NULL AND oui_name!=''")
    n_rog_label = scalar(conn, "SELECT COUNT(*) FROM rogue_events WHERE resolved=0 AND label IS NOT NULL AND label!=''")
    n_rog_class = scalar(conn, "SELECT COUNT(*) FROM rogue_events WHERE resolved=0 AND device_class IS NOT NULL AND device_class!='unknown'")
    print(f"### unresolved rogues: {n_rog_total}")
    print(f"- with vendor (oui_name): {n_rog_vendor}")
    print(f"- with label: {n_rog_label}")
    print(f"- with a non-unknown device_class: {n_rog_class}")
    # oldest unresolved
    rows = q(conn, """SELECT mac, oui_name, device_class, label, first_seen, ts
                      FROM rogue_events WHERE resolved=0 ORDER BY first_seen ASC LIMIT 15""")
    print("### oldest unresolved rogues")
    for r in rows:
        age = (now - r['first_seen']) / 86400 if now else 0
        print(f"- {r['mac']} [{r['oui_name'] or '?'}] ({r['device_class'] or '?'}, `{r['label'] or '?'}`) — {age:.0f}d old, flagged {ts_to_dt(r['ts'])}")
    # rogues that later got sightings (still active)
    n_rog_active = 0
    for r in q(conn, "SELECT mac FROM rogue_events WHERE resolved=0"):
        ls = scalar(conn, "SELECT MAX(ts) FROM sightings WHERE mac=?", (r['mac'],))
        if ls and now and (now - ls) < 86400:
            n_rog_active += 1
    print(f"### unresolved rogues seen in last 24h: {n_rog_active}")

    # ---- 5. Apple Continuity coverage ----
    hr()
    print(f"## 5. Apple Continuity coverage")
    # sightings with extra JSON containing apple
    n_extra = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra IS NOT NULL AND extra!=''")
    n_apple = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%\"apple\"%'")
    n_nearby = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%nearby%'")
    n_auth_tag = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%auth_tag%'")
    n_airpods = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%proximity_pairing%'")
    n_airtag = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%airtag%'")
    n_find_my = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE extra LIKE '%find_my%'")
    print(f"- sightings with extra JSON: {n_extra}")
    print(f"- sightings with apple continuity: {n_apple}")
    print(f"  - nearby_info (0x10): {n_nearby} (with auth_tag: {n_auth_tag})")
    print(f"  - proximity_pairing (AirPods): {n_airpods}")
    print(f"  - airtag: {n_airtag}")
    print(f"  - find_my: {n_find_my}")
    # AirPods false-positive check: any 'unknown AirPods/Beats' model codes (garbage)?
    # sample extra payloads and decode
    print("### AirPods model codes seen (checking for garbage / false positives)")
    model_codes = Counter()
    n_short_07 = 0
    rows = q(conn, "SELECT extra FROM sightings WHERE extra LIKE '%proximity_pairing%' LIMIT 500")
    for r in rows:
        try:
            e = json.loads(r['extra'])
        except Exception:
            continue
        ap = e.get('apple', {})
        mc = ap.get('model_code')
        if mc:
            model_codes[(mc, ap.get('model'))] += 1
    for (mc, mdl), c in model_codes.most_common():
        print(f"- {mc} `{mdl}`: {c}")
    # distinct auth tags
    n_distinct_tags = 0
    tags = Counter()
    rows = q(conn, "SELECT extra FROM sightings WHERE extra LIKE '%auth_tag%' LIMIT 2000")
    for r in rows:
        try:
            e = json.loads(r['extra'])
        except Exception:
            continue
        for nb in e.get('apple', {}).get('nearby', []) or []:
            t = nb.get('auth_tag')
            if t:
                tags[t] += 1
    n_distinct_tags = len(tags)
    print(f"### distinct Apple Nearby auth tags: {n_distinct_tags}")
    print("top tags (potential linked devices):")
    for t, c in tags.most_common(10):
        print(f"- {t}: {c} sightings")

    # ---- 6. WiFi probe data ----
    hr()
    print(f"## 6. WiFi probe data")
    # sources
    rows = q(conn, "SELECT source, COUNT(*) c FROM sightings GROUP BY source ORDER BY c DESC")
    print("### sightings by source")
    for r in rows:
        print(f"- {r['source'] or '(null)'}: {r[1]}")
    # devices seen via wifi vs ble
    n_wifi_only = scalar(conn, """SELECT COUNT(DISTINCT mac) FROM sightings WHERE source='wifi'
                                   AND mac NOT IN (SELECT DISTINCT mac FROM sightings WHERE source='ble')""")
    n_ble_only = scalar(conn, """SELECT COUNT(DISTINCT mac) FROM sightings WHERE source='ble'
                                  AND mac NOT IN (SELECT DISTINCT mac FROM sightings WHERE source='wifi')""")
    n_both = scalar(conn, """SELECT COUNT(DISTINCT mac) FROM sightings WHERE source='ble'
                              AND mac IN (SELECT DISTINCT mac FROM sightings WHERE source='wifi')""")
    print(f"- devices seen only on wifi: {n_wifi_only}")
    print(f"- devices seen only on ble: {n_ble_only}")
    print(f"- devices seen on both: {n_both}")
    # SSIDs probed — stored where? check name field for wifi source
    print("### sample wifi sightings (name field may hold SSID/probe info)")
    rows = q(conn, "SELECT mac, name, services, rssi FROM sightings WHERE source='wifi' LIMIT 10")
    for r in rows:
        print(f"- {r['mac']} name=`{r['name']}` services=`{r['services']}` rssi={r['rssi']}")
    # wifi_aps table
    rows = q(conn, "SELECT ssid, COUNT(*) c FROM wifi_aps WHERE ssid IS NOT NULL AND ssid!='' GROUP BY ssid ORDER BY c DESC LIMIT 20")
    print("### wifi_aps SSIDs")
    for r in rows:
        print(f"- `{r['ssid']}`: {r[1]}")
    # probe-requests: check if any source like 'probe' or names that look like ssids
    rows = q(conn, "SELECT DISTINCT source FROM sightings")
    print(f"### all distinct sources: {[r[0] for r in rows]}")

    # ---- 7. data-quality issues ----
    hr()
    print(f"## 7. Data-quality issues")
    # orphaned sightings (no device row)
    n_orphan = scalar(conn, "SELECT COUNT(*) FROM sightings s LEFT JOIN devices d ON s.mac=d.mac WHERE d.mac IS NULL")
    print(f"- orphaned sightings (no device row): {n_orphan}")
    # duplicate devices (same fingerprint, different device rows not linked)
    n_dup_fp = scalar(conn, "SELECT COUNT(*) FROM devices WHERE fingerprint_id IS NOT NULL GROUP BY fingerprint_id HAVING COUNT(*) > 1")
    # stale devices (last_seen > 30 days ago)
    n_stale = scalar(conn, "SELECT COUNT(*) FROM devices WHERE last_seen < ?", (now - 30*86400,)) if now else 0
    print(f"- stale devices (not seen in 30d): {n_stale}")
    # devices with sighting_count 1 (transient)
    n_transient = scalar(conn, "SELECT COUNT(*) FROM devices WHERE sighting_count = 1")
    print(f"- transient devices (sighting_count=1): {n_transient}")
    # sightings with null rssi
    n_null_rssi = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE rssi IS NULL")
    print(f"- sightings with null rssi: {n_null_rssi}")
    # sightings with null sensor_id
    n_null_sensor = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE sensor_id IS NULL OR sensor_id=''")
    print(f"- sightings with null sensor_id: {n_null_sensor}")
    # future timestamps
    n_future = scalar(conn, "SELECT COUNT(*) FROM sightings WHERE ts > ?", (now + 3600,)) if now else 0
    print(f"- sightings with future ts (>now+1h): {n_future}")
    # out-of-order: ts < first_seen for the device
    n_before_first = 0
    # duplicate fingerprints: same mac in multiple fingerprints (shouldn't happen — PK)
    n_alias_multi_fp = scalar(conn, "SELECT COUNT(*) FROM (SELECT mac FROM device_aliases GROUP BY mac HAVING COUNT(DISTINCT fingerprint_id) > 1)")
    print(f"- aliases pointing to >1 fingerprint (should be 0): {n_alias_multi_fp}")
    # devices.fingerprint_id pointing to non-existent fp
    n_dangling_fp = scalar(conn, """SELECT COUNT(*) FROM devices d WHERE d.fingerprint_id IS NOT NULL
                                     AND d.fingerprint_id NOT IN (SELECT fingerprint_id FROM device_fingerprints)""")
    print(f"- devices.fingerprint_id dangling (no fp row): {n_dangling_fp}")

    # ---- 8. surprising finding ----
    hr()
    print(f"## 8. Surprising findings")
    # most persistent device (max sighting_count)
    rows = q(conn, "SELECT mac, last_label, oui_name, sighting_count, first_seen, last_seen FROM devices ORDER BY sighting_count DESC LIMIT 5")
    print("### most-sighted devices")
    for r in rows:
        span = (r['last_seen'] - r['first_seen']) / 86400 if r['first_seen'] and r['last_seen'] else 0
        print(f"- {r['mac']} `{r['last_label']}` ({r['oui_name']}): {r['sighting_count']} sightings over {span:.1f}d")
    # longest-lived device (max span)
    rows = q(conn, "SELECT mac, last_label, oui_name, sighting_count, first_seen, last_seen FROM devices WHERE first_seen IS NOT NULL AND last_seen IS NOT NULL ORDER BY (last_seen-first_seen) DESC LIMIT 5")
    print("### longest-tracked devices (span)")
    for r in rows:
        span = (r['last_seen'] - r['first_seen']) / 86400 if r['first_seen'] and r['last_seen'] else 0
        print(f"- {r['mac']} `{r['last_label']}` ({r['oui_name']}): {span:.1f}d, {r['sighting_count']} sightings")
    # sensors
    rows = q(conn, "SELECT sensor_id, hostname, location_label, first_seen, last_seen, x, y FROM sensors")
    print("### sensors")
    for r in rows:
        print(f"- {r['sensor_id']} ({r['hostname']}) loc=`{r['location_label']}` x={r['x']} y={r['y']}")
    # is_mine devices
    rows = q(conn, "SELECT mac, my_label, last_label FROM devices WHERE is_mine=1")
    print(f"### is_mine devices: {len(rows)}")
    for r in rows:
        print(f"- {r['mac']} `{r['my_label']}` (last_label={r['last_label']})")
    # tracked devices
    rows = q(conn, "SELECT mac, last_label, watch_note FROM devices WHERE tracked=1")
    print(f"### tracked devices: {len(rows)}")
    for r in rows:
        print(f"- {r['mac']} `{r['last_label']}` note=`{r['watch_note']}`")

    conn.close()
    print("\n_Done._")


if __name__ == "__main__":
    main()
