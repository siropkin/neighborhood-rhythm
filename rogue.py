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
MIN_SIGHTING_SPAN_S = 900  # sightings must span >= 15 min (genuinely staying)


def detect_rogues(conn, now=None):
    """Run after a scan. Find stable-MAC devices seen consistently that aren't
    known and haven't been flagged. Insert rogue_events for new ones.
    Returns the list of newly-flagged devices.

    A rogue must be IDENTIFIABLE — has an OUI vendor or a known device class
    (not 'unknown'). An unidentifiable stable MAC is radio noise, not an
    actionable alert (781/820 prior rogues were unidentifiable 'unknown').
    The point is "a new device you can act on", not "a new MAC you can't name".
    """
    now = now or time.time()
    # known MACs (the baseline) + already-flagged MACs (don't re-alert)
    known = {r["mac"] for r in conn.execute("SELECT mac FROM known_devices")}
    flagged = {r["mac"] for r in conn.execute(
        "SELECT mac FROM rogue_events WHERE resolved=0")}
    # also dedupe by fingerprint: if any alias of a fingerprint is already
    # known or flagged, don't re-flag the others (e.g. two Sonos MACs linked
    # as one device shouldn't each generate a rogue event).
    fp_known = set()
    for mac in known | flagged:
        row = conn.execute(
            "SELECT fingerprint_id FROM devices WHERE mac=?", (mac,)).fetchone()
        if row and row["fingerprint_id"]:
            fp_known.add(row["fingerprint_id"])
    # stable-MAC devices seen MIN_SIGHTINGS+ times, sightings spanning
    # MIN_SIGHTING_SPAN_S+ (not a single-scan burst), not mDNS pseudo-keys.
    rows = conn.execute(
        """SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count, fingerprint_id
           FROM devices
           WHERE sighting_count >= ? AND (last_seen - first_seen) >= ? AND mac NOT LIKE 'mdns:%'""",
        (MIN_SIGHTINGS, MIN_SIGHTING_SPAN_S)).fetchall()
    new = []
    for r in rows:
        mac = r["mac"]
        if mac in known or mac in flagged:
            continue
        # dedupe by fingerprint: if a linked alias is already known/flagged
        if r["fingerprint_id"] and r["fingerprint_id"] in fp_known:
            continue
        if is_random_mac(mac):
            continue  # rotating phone — noise, not a rogue device
        # Identifiability gate: must have an OUI vendor OR a known device
        # class (not 'unknown'). A stable MAC we can't name isn't actionable.
        if not r["oui_name"] and r["last_type"] in (None, "unknown"):
            continue
        conn.execute(
            """INSERT INTO rogue_events
               (mac, first_seen, ts, oui_name, device_class, label, source)
               VALUES (?,?,?,?,?,?,?)""",
            (mac, r["first_seen"], now, r["oui_name"], r["last_type"],
             r["last_label"], "ble"))
        new.append(dict(r))
        _fire_alert(mac, r, now)
    return new


def _fire_alert(mac, dev, ts):
    """POST a rogue alert to the configured webhook (Slack/Teams/SIEM).
    No-op if ALERT_WEBHOOK is unset. Fire-and-forget; a failed POST is logged
    but doesn't block the scan. The payload is SIEM-friendly (mac, vendor,
    type, label, ts) so a SIEM can ingest it directly."""
    from config import ALERT_WEBHOOK
    if not ALERT_WEBHOOK:
        return
    import json as _json
    import urllib.request
    payload = _json.dumps({
        "event": "rogue_device",
        "mac": mac,
        "vendor": dev.get("oui_name"),
        "device_class": dev.get("last_type"),
        "label": dev.get("last_label"),
        "first_seen": dev.get("first_seen"),
        "ts": ts,
    }).encode()
    try:
        req = urllib.request.Request(ALERT_WEBHOOK, data=payload,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        import sys
        print(f"alert webhook failed: {e}", file=sys.stderr)


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
