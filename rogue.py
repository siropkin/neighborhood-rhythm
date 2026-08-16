"""Rogue-device detection — flags new stable-MAC devices that aren't in the
known baseline.

Why "stable MAC" not "any new MAC": phones rotate their BLE MAC every ~15 min,
so a naive "new MAC" rule would fire constantly. We filter to stable MACs
(registered OUI, not locally-administered) seen consistently (2+ scans), which
excludes the rotating-phone noise and catches the real signal — a new camera,
IoT device, or planted hardware that keeps its MAC.

A device is rogue if:
  - it's a stable MAC (not random — is_random_mac returns False)
  - it's been seen 2+ times (sighting_count >= 2 — filters drive-bys)
  - it's not in the known_devices baseline
  - it hasn't been flagged before (or was resolved then re-appeared)

This is inventory + a diff, not a threat classifier. It tells you "something
new is here"; a human decides if it belongs.
"""
import time

import db
from rules import is_random_mac

# A device is "consistent" (not a drive-by) if seen this many times AND its
# sightings span this many seconds. A device seen 3× in one 10-min scan burst
# then never again is NOT consistent — it's a drive-by that happened to be
# caught multiple times in one scan. The span requirement filters that out.
MIN_SIGHTINGS = 3
MIN_SIGHTING_SPAN_S = 600  # sightings must span >= 10 min (not one burst)


def detect_rogues(conn, now=None):
    """Run after a scan. Find stable-MAC devices seen consistently that aren't
    known and haven't been flagged. Insert rogue_events for new ones.
    Returns the list of newly-flagged devices."""
    now = now or time.time()
    # known MACs (the baseline) + already-flagged MACs (don't re-alert)
    known = {r["mac"] for r in conn.execute("SELECT mac FROM known_devices")}
    flagged = {r["mac"] for r in conn.execute(
        "SELECT mac FROM rogue_events WHERE resolved=0")}
    # stable-MAC devices seen MIN_SIGHTINGS+ times, sightings spanning
    # MIN_SIGHTING_SPAN_S+ (not a single-scan burst), not mDNS pseudo-keys.
    rows = conn.execute(
        """SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count
           FROM devices
           WHERE sighting_count >= ? AND (last_seen - first_seen) >= ? AND mac NOT LIKE 'mdns:%'""",
        (MIN_SIGHTINGS, MIN_SIGHTING_SPAN_S)).fetchall()
    new = []
    for r in rows:
        mac = r["mac"]
        if mac in known or mac in flagged:
            continue
        if is_random_mac(mac):
            continue  # rotating phone — noise, not a rogue device
        # a stable MAC with an OUI (registered vendor) is a real device.
        # A stable MAC with no OUI is still worth flagging (could be a
        # device with an unregistered OUI) — don't over-filter.
        conn.execute(
            """INSERT INTO rogue_events
               (mac, first_seen, ts, oui_name, device_class, label, source)
               VALUES (?,?,?,?,?,?,?)""",
            (mac, r["first_seen"], now, r["oui_name"], r["last_type"],
             r["last_label"], "ble"))
        new.append(dict(r))
    return new


def mark_known(conn, mac, label=None, note=None):
    """Add a MAC to the known baseline (and resolve any open rogue event)."""
    now = time.time()
    conn.execute(
        "INSERT INTO known_devices(mac, label, added_ts, note) VALUES(?,?,?,?) "
        "ON CONFLICT(mac) DO UPDATE SET label=COALESCE(excluded.label, known_devices.label)",
        (mac, label, now, note))
    conn.execute("UPDATE rogue_events SET resolved=1, note=? WHERE mac=? AND resolved=0",
                 (note, mac))


def resolve_rogue(conn, mac, note=None):
    """Dismiss a rogue alert without adding to known (e.g. a one-off visitor)."""
    conn.execute("UPDATE rogue_events SET resolved=1, note=? WHERE mac=? AND resolved=0",
                 (note, mac))


if __name__ == "__main__":
    # self-check: run detection, report what's flagged
    with db.get_db() as conn:
        known = conn.execute("SELECT COUNT(*) c FROM known_devices").fetchone()["c"]
        new = detect_rogues(conn)
        total = conn.execute("SELECT COUNT(*) c FROM rogue_events WHERE resolved=0").fetchone()["c"]
    print(f"known devices: {known}")
    print(f"newly flagged this run: {len(new)}")
    for d in new[:10]:
        print(f"  {d['mac']}  {d['oui_name']}  {d['last_type']}  {d['last_label']}")
    print(f"total unresolved rogue events: {total}")
