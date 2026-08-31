"""Insights feed — plain-language findings, written by the collector pass.

Three generators:
  - new_resident: stable device present 3+ days, not in the known baseline
  - busyness:     last complete hour's unique-device count > 2.5σ above that
                  hour-of-day's trailing median (plus absolute floors — σ
                  alone fires on "3 devices vs a typical 1" noise)
  - gone_missing: a device tagged as mine hasn't been seen in 48h+

Runs every collector pass (5 min); the dedup guards make repeats cheap:
one new_resident per MAC ever, one busyness per hour, one gone_missing per
absence episode (a return + new absence re-fires).

Hour-of-day bucketing is UTC — consistent grouping is what the σ comparison
needs; the dashboard labels the finding from its ts in the VIEWER's tz (the
Pi's tz may not be the browser's).
"""
import statistics
import time

from rules import is_random_mac

NEW_RESIDENT_MIN_SPAN_S = 3 * 86400   # present 3+ days = a resident, not a visitor
NEW_RESIDENT_MIN_SIGHTINGS = 10       # ...and actually seen, not a 2-scan blip
GONE_MISSING_AFTER_S = 48 * 3600
BUSYNESS_SIGMA = 2.5
BUSYNESS_MIN_LIFT = 5                 # must beat the median by >= 5 devices
BUSYNESS_MIN_COUNT = 8                # ...and reach 8 absolute (kills 3-vs-1 noise)
BUSYNESS_MIN_DAYS = 5                 # need this many trailing days to have a "typical"


def _label(r):
    return r["last_label"] or r["oui_name"] or r["mac"]


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
             AND mac NOT IN (SELECT mac FROM insights WHERE kind='new_resident' AND mac IS NOT NULL)""",
        (NEW_RESIDENT_MIN_SPAN_S, now - 86400, NEW_RESIDENT_MIN_SIGHTINGS)).fetchall()
    n = 0
    for r in rows:
        if is_random_mac(r["mac"]):
            continue  # a rotating MAC can't be a resident — it's phone noise
        days = round((r["last_seen"] - r["first_seen"]) / 86400)
        _add(conn, "new_resident", "info",
             f"{_label(r)} has been around for {days} days — looks like a new "
             f"resident, not a visitor. Review it on the unrecognized list.",
             r["mac"], now)
        n += 1
    return n


def _busyness(conn, now):
    # unique devices per hour (sightings_hourly dedups per mac/hour), 14 days
    rows = conn.execute(
        "SELECT hour, COUNT(DISTINCT mac) c FROM sightings_hourly "
        "WHERE hour >= ? GROUP BY hour",
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
        """SELECT mac, oui_name, last_label, last_seen FROM devices
           WHERE is_mine = 1 AND last_seen < ?""",
        (now - GONE_MISSING_AFTER_S,)).fetchall()
    n = 0
    for r in rows:
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


def run_insights(conn, now=None):
    """Run all generators; returns how many insights were written."""
    now = now or time.time()
    return (_new_residents(conn, now) + _busyness(conn, now)
            + _gone_missing(conn, now))


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
