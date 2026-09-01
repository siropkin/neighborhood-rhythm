"""Insights feed — plain-language findings, written by the collector pass.

Generators:
  - new_resident: stable device active 3+ DISTINCT days, here a while, not in
    the known baseline, not an open rogue alert (never contradict the rogue
    queue), and not a day-one device (baseline-age guard, same as rogue.py)
  - busyness:     last complete hour's unique-device count > 2.5σ above that
    hour-of-day's trailing median (plus absolute floors — σ alone fires on
    "3 devices vs a typical 1" noise). Fingerprint-deduped, like the chart.
  - gone_missing: a device tagged as mine — or a long-term fixture (seen most
    of the last 7 days) — hasn't been seen in 48h+
  - sensor_lost:  a scan source that reported daily goes dark for 24h+
    (born 2026-08-31: the AR9271 probe adapter died and nobody noticed for
    2 days; this insight would have caught it the next morning)

Runs every collector pass (5 min); the dedup guards make repeats cheap:
one new_resident per MAC ever, one busyness per hour, one gone_missing /
sensor_lost per absence episode (a return + new absence re-fires).

Day/hour bucketing is UTC — consistent grouping is what the comparisons need;
the dashboard labels findings from their ts in the VIEWER's tz.
"""
import statistics
import time

from rules import is_random_mac

NEW_RESIDENT_MIN_SPAN_S = 3 * 86400   # present 3+ days = a resident, not a visitor
NEW_RESIDENT_MIN_SIGHTINGS = 10       # ...and actually seen, not a 2-scan blip
NEW_RESIDENT_MIN_DAYS = 3             # active on 3+ DISTINCT days (span alone lies:
                                      # "5 days" can be 2 active days with a gap)
GONE_MISSING_AFTER_S = 48 * 3600
FIXTURE_MIN_SIGHTINGS = 100           # untagged fixture = a de-facto resident:
FIXTURE_MIN_DAYS_7 = 5                # 100+ sightings, active 5+ of the last 7 days
SOURCE_DARK_AFTER_S = 24 * 3600       # a daily source silent this long = lost
SOURCE_MIN_DAYS_7 = 5                 # must have been active 5+ of the 7 days
                                      # before the gap (bt is sporadic by design)
BUSYNESS_SIGMA = 2.5
BUSYNESS_MIN_LIFT = 5                 # must beat the median by >= 5 devices
BUSYNESS_MIN_COUNT = 8                # ...and reach 8 absolute (kills 3-vs-1 noise)
BUSYNESS_MIN_DAYS = 5                 # need this many trailing days to have a "typical"


def _label(r):
    """Best human handle for a device; never lead with a bare MAC."""
    return r["last_label"] or r["oui_name"] or f"Unknown device ({r['mac']})"


def _active_days(conn, mac, since=None, until=None):
    """Distinct UTC days with a sighting, optionally bounded."""
    q = "SELECT COUNT(DISTINCT CAST(ts/86400 AS INTEGER)) c FROM sightings WHERE mac=?"
    args = [mac]
    if since is not None:
        q += " AND ts >= ?"
        args.append(since)
    if until is not None:
        q += " AND ts <= ?"
        args.append(until)
    return conn.execute(q, args).fetchone()["c"]


def _add(conn, kind, severity, text, mac, now):
    conn.execute(
        "INSERT INTO insights (ts, kind, severity, text, mac) VALUES (?,?,?,?,?)",
        (now, kind, severity, text, mac))


def _new_residents(conn, now):
    rows = conn.execute(
        """SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count
           FROM devices
           WHERE last_seen - first_seen >= ? AND last_seen >= ?
             AND sighting_count >= ? AND is_mine = 0
             AND mac NOT IN (SELECT mac FROM known_devices)
             AND mac NOT IN (SELECT mac FROM rogue_events WHERE resolved=0)
             AND mac NOT IN (SELECT mac FROM insights WHERE kind='new_resident' AND mac IS NOT NULL)""",
        (NEW_RESIDENT_MIN_SPAN_S, now - 86400, NEW_RESIDENT_MIN_SIGHTINGS)).fetchall()
    # baseline-age guard (same as rogue.py): first seen within 24h of the
    # baseline snapshot = part of the neighborhood, not a new resident
    base = conn.execute("SELECT MIN(added_ts) t FROM known_devices").fetchone()["t"]
    baseline_grace = (base + 86400) if base else 0
    n = 0
    for r in rows:
        if is_random_mac(r["mac"]):
            continue  # a rotating MAC can't be a resident — it's phone noise
        if baseline_grace and r["first_seen"] <= baseline_grace:
            continue  # here since the baseline was built
        days = _active_days(conn, r["mac"])
        if days < NEW_RESIDENT_MIN_DAYS:
            continue  # span says weeks, reality is an occasional visitor
        _add(conn, "new_resident", "info",
             f"{_label(r)} has been around for {days} days — looks like a new "
             f"resident, not a visitor. Review it on the unrecognized list.",
             r["mac"], now)
        n += 1
    return n


def _busyness(conn, now):
    # unique PHYSICAL devices per hour (fingerprint-deduped, like the rhythm
    # chart; LEFT JOIN — hourly rows survive transient-device pruning)
    rows = conn.execute(
        "SELECT h.hour, COUNT(DISTINCT COALESCE(d.fingerprint_id, h.mac)) c "
        "FROM sightings_hourly h LEFT JOIN devices d ON d.mac = h.mac "
        "WHERE h.hour >= ? GROUP BY h.hour",
        (int(now - 14 * 86400) // 3600 * 3600,)).fetchall()
    counts = {r["hour"]: r["c"] for r in rows}
    # the last COMPLETE hour — the current one is still accumulating
    cur = int(now // 3600) * 3600 - 3600
    c = counts.get(cur)
    if not c or c < BUSYNESS_MIN_COUNT:
        return 0
    if conn.execute(
            "SELECT 1 FROM insights WHERE kind='busyness' AND ts >= ? LIMIT 1",
            (cur,)).fetchone():
        return 0  # already reported this hour
    hod = int((cur % 86400) // 3600)  # UTC hour-of-day — consistent bucketing
    trailing = [v for h, v in counts.items()
                if h != cur and int((h % 86400) // 3600) == hod]
    if len(trailing) < BUSYNESS_MIN_DAYS:
        return 0
    med = statistics.median(trailing)
    std = statistics.pstdev(trailing)
    if c <= med + BUSYNESS_SIGMA * std or c < med + BUSYNESS_MIN_LIFT:
        return 0
    _add(conn, "busyness", "info",
         f"Unusually busy hour — {c} devices active vs a typical "
         f"~{round(med)} for this hour.",
         None, now)
    return 1


def _gone_missing(conn, now):
    rows = conn.execute(
        """SELECT mac, oui_name, last_label, last_seen, sighting_count, is_mine
           FROM devices WHERE last_seen < ? AND (is_mine = 1 OR sighting_count >= ?)""",
        (now - GONE_MISSING_AFTER_S, FIXTURE_MIN_SIGHTINGS)).fetchall()
    n = 0
    for r in rows:
        if not r["is_mine"]:
            # untagged device: only a de-facto fixture qualifies (active most
            # of the last 7 days) — a neighbor's gadget that left isn't news
            if _active_days(conn, r["mac"], since=now - 7 * 86400) < FIXTURE_MIN_DAYS_7:
                continue
        # same-episode guard: an insight newer than the device's last_seen
        # already covers this absence
        if conn.execute(
                "SELECT 1 FROM insights WHERE kind='gone_missing' AND mac=? AND ts > ? LIMIT 1",
                (r["mac"], r["last_seen"])).fetchone():
            continue
        days = (now - r["last_seen"]) / 86400
        _add(conn, "gone_missing", "warn",
             f"{_label(r)} hasn't been seen in {days:.0f} days — "
             f"powered off, moved, or left?",
             r["mac"], now)
        n += 1
    return n


def _sensor_lost(conn, now):
    n = 0
    for r in conn.execute(
            "SELECT source, MAX(ts) last FROM sightings GROUP BY source").fetchall():
        src, last = r["source"], r["last"]
        if not src or last >= now - SOURCE_DARK_AFTER_S:
            continue  # still reporting
        # was it a DAILY source before going dark? (sporadic ones like bt
        # going quiet isn't a loss)
        days = conn.execute(
            "SELECT COUNT(DISTINCT CAST(ts/86400 AS INTEGER)) c FROM sightings "
            "WHERE source=? AND ts BETWEEN ? AND ?",
            (src, last - 7 * 86400, last)).fetchone()["c"]
        if days < SOURCE_MIN_DAYS_7:
            continue
        # same-episode guard: an insight newer than the source's last sighting
        # already covers this outage
        if conn.execute(
                "SELECT 1 FROM insights WHERE kind='sensor_lost' AND text LIKE ? AND ts > ? LIMIT 1",
                (f"{src} %", last)).fetchone():
            continue
        dark = (now - last) / 86400
        _add(conn, "sensor_lost", "warn",
             f"{src} hasn't reported in {dark:.0f} days — adapter unplugged, "
             f"interface down, or the source is gone?",
             None, now)
        n += 1
    return n


def run_insights(conn, now=None):
    """Run all generators; returns how many insights were written."""
    now = now or time.time()
    return (_new_residents(conn, now) + _busyness(conn, now)
            + _gone_missing(conn, now) + _sensor_lost(conn, now))


if __name__ == "__main__":
    import db
    db.init_db()
    with db.get_db() as conn:
        n = run_insights(conn)
        rows = conn.execute(
            "SELECT * FROM insights ORDER BY ts DESC LIMIT 10").fetchall()
    print(f"{n} new insight(s)")
    for r in rows:
        print(f"  [{r['kind']}] {r['text']}")
