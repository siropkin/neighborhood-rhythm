"""Insights — warn-level findings, written by the collector pass, surfaced in
the dashboard's status banner. Only things that need ACTION earn a row;
everything informational was cut on 2026-08-31 (user feedback: the card was
noise — new_resident duplicated the rogue queue, busyness was trivia the
rhythm chart already shows).

Generators:
  - gone_missing: a device tagged as mine — or a long-term fixture (seen most
    of the last 7 days) — hasn't been seen in 48h+
  - sensor_lost:  a scan source that reported daily goes dark for 24h+
    (born 2026-08-31: the AR9271 probe adapter died and nobody noticed for
    2 days; this insight would have caught it the next morning)
  - ap_event:     a new WiFi network appears nearby — strong (>= -80 dBm) or
    persistent (still here after 24h). The AP-level analog of rogue detection
    (validated 2026-09-01: a neighbor's Xfinity install lit up 4 BSSIDs at
    once; raw churn is ~90 faint APs/14d, so the guards do the work)

Runs every collector pass (5 min); dedup is per absence episode (a return +
new absence re-fires). Day bucketing is UTC — consistent grouping is what the
comparisons need; the dashboard labels findings from their ts in the
VIEWER's tz.
"""
import time

GONE_MISSING_AFTER_S = 48 * 3600
FIXTURE_MIN_SIGHTINGS = 100           # untagged fixture = a de-facto resident:
FIXTURE_MIN_DAYS_7 = 5                # 100+ sightings, active 5+ of the last 7 days
SOURCE_DARK_AFTER_S = 24 * 3600       # a daily source silent this long = lost
SOURCE_MIN_DAYS_7 = 5                 # must have been active 5+ of the 7 days
                                      # before the gap (bt is sporadic by design)


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


def _dark_sources(conn, now):
    """Sources with no sighting in 24h+ — the scanner isn't listening there."""
    return {r["source"] for r in conn.execute(
        "SELECT source, MAX(ts) last FROM sightings GROUP BY source")
        if r["source"] and r["last"] < now - SOURCE_DARK_AFTER_S}


def _gone_missing(conn, now):
    dark = _dark_sources(conn, now)
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
        # a device can't be "missing" from a scanner that isn't listening: if
        # every source it used in its final week is dark, the absence is a
        # source outage, not a departure (the 08-29 probe-adapter death
        # flooded 27 of these in one pass)
        srcs = {s["source"] for s in conn.execute(
            "SELECT DISTINCT source FROM sightings WHERE mac=? AND ts >= ?",
            (r["mac"], r["last_seen"] - 7 * 86400))}
        if srcs and srcs <= dark:
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


AP_MIN_SIGNAL = -80        # dBm — fainter than this is edge-of-range flicker
AP_PERSIST_S = 24 * 3600   # ...unless it stuck around this long
AP_REFIRE_S = 30 * 86400   # one insight per network name per month


def _ap_events(conn, now):
    # candidates: BSSIDs first seen in the last 8 days (wide window — the
    # persistence path fires at the 24h mark, the refire guard dedups).
    # Baseline-fill guard: on a fresh DB every AP gets first_seen=day one;
    # anything from that first 24h is the initial inventory, not an event.
    rows = conn.execute(
        "SELECT bssid, ssid, first_seen, last_seen, last_signal FROM wifi_aps "
        "WHERE first_seen >= ?",
        (now - 8 * 86400,)).fetchall()
    base = conn.execute("SELECT MIN(first_seen) f FROM wifi_aps").fetchone()["f"]
    fill_grace = (base + 86400) if base else 0
    rows = [r for r in rows if not fill_grace or r["first_seen"] > fill_grace]
    # group same-SSID same-day arrivals: one ISP install lights up 4 radios —
    # that's ONE event, not four
    groups = {}
    for r in rows:
        strong = r["last_signal"] is not None and r["last_signal"] >= AP_MIN_SIGNAL
        persisted = (now - r["first_seen"] >= AP_PERSIST_S
                     and r["last_seen"] >= now - 3600)
        if not (strong or persisted):
            continue
        key = r["ssid"] or "(hidden)"
        groups.setdefault(key, []).append(r)
    n = 0
    for ssid, members in groups.items():
        # refire guard: same network name reported in the last 30 days?
        if conn.execute(
                "SELECT 1 FROM insights WHERE kind='ap_event' AND text LIKE ? AND ts >= ? LIMIT 1",
                (f"%{ssid}%", now - AP_REFIRE_S)).fetchone():
            continue
        best = max(members, key=lambda m: m["last_signal"] or -100)
        radios = f"{len(members)} radios, " if len(members) > 1 else ""
        _add(conn, "ap_event", "warn",
             f"New WiFi network nearby: {ssid} ({radios}strongest "
             f"{best['last_signal']:.0f} dBm) — a neighbor's new gear, or "
             f"something claiming a familiar name?",
             None, now)
        n += 1
    return n


def run_insights(conn, now=None):
    """Run all generators; returns how many insights were written."""
    now = now or time.time()
    return (_gone_missing(conn, now) + _sensor_lost(conn, now)
            + _ap_events(conn, now))


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
