"""Device behavior detection — classifies a device's presence/signal pattern
into a human-readable behavior label, derived from its sighting timeline.

This is "understanding what it is" from behavior rather than googling:
  - always-on fixed: seen every scan, tight RSSI, all day → infrastructure
  - active-cyclic:   present 24/7 but sightings-per-hour spike (usage cycle)
  - transient:       short bounded presence → a visitor who came and left
  - mobile:           wide RSSI spread → moving (phone in a pocket, not fixed)
  - intermittent:     on/off gaps → a device with a usage cycle (light, TV)

The pattern is a device-class signal, like the service UUID — but behavioral.
"""
import statistics
import time

# Thresholds calibrated against the live data (see the signal-pattern analysis):
#   mmWave sensor: std 4.7, every scan, all day → always-on fixed
#   Roomba:        std 5.0, every scan, evening spike → active-cyclic
#   Govee light:   std 3.3, day gap → intermittent
#   Apple rogue:   7 sightings in 1h then gone → transient
#   soundbar:      std 2.5 → fixed
MOBILE_RSSI_STD = 8.0     # std > this = moving (mobile); fixed devices are 2-6
MIN_ALWAYS_ON_HOURS = 8    # seen in >= this many distinct hours = "all day"
                            # (8 not 12: a sensor deployed 9h ago can't hit 12 yet)
MIN_SIGHTINGS_FOR_BEHAVIOR = 5  # below this, not enough data to classify
TRANSIENT_MAX_SIGHTINGS = 20   # transient = short bounded presence
CYCLIC_SPIKE_RATIO = 1.5   # rate_max >= 1.5x rate_med AND rate_max >= 18 = cyclic
CYCLIC_MIN_RATE = 18       # the spike must reach this many sightings/hour


def classify_behavior(conn, mac, now=None):
    """Classify one device's behavior from its sighting timeline.
    Returns {behavior, stationarity, dwell_s, active_hours, rssi_std}."""
    now = now or time.time()
    rows = conn.execute(
        "SELECT ts, rssi FROM sightings WHERE mac=? ORDER BY ts", (mac,)
    ).fetchall()
    if len(rows) < MIN_SIGHTINGS_FOR_BEHAVIOR:
        return {"behavior": "unknown", "stationarity": None, "dwell_s": None,
                "active_hours": 0, "rssi_std": None, "sighting_count": len(rows)}

    rssi_vals = [r["rssi"] for r in rows if r["rssi"] is not None]
    rssi_std = statistics.pstdev(rssi_vals) if len(rssi_vals) > 1 else 0

    # distinct hours-of-day seen (last 24h for the "all day" check)
    hour_set = set()
    for r in rows:
        if r["ts"] >= now - 86400:
            hour_set.add(time.localtime(r["ts"]).tm_hour)
    active_hours = len(hour_set)

    # sightings per hour (last 24h) — to detect the active-cyclic spike
    by_hour = {}
    for r in rows:
        if r["ts"] >= now - 86400:
            h = time.localtime(r["ts"]).tm_hour
            by_hour[h] = by_hour.get(h, 0) + 1
    rates = list(by_hour.values()) if by_hour else [0]
    rate_med = statistics.median(rates) if rates else 0
    rate_max = max(rates) if rates else 0

    # stationarity: low RSSI std = fixed; high = mobile
    if rssi_std is not None:
        stationarity = "fixed" if rssi_std < MOBILE_RSSI_STD else "mobile"
    else:
        stationarity = None

    # dwell: for transient devices, the span from first to last sighting
    span_s = rows[-1]["ts"] - rows[0]["ts"]

    # classify
    n = len(rows)
    if n <= TRANSIENT_MAX_SIGHTINGS and active_hours <= 3:
        behavior = "transient"
    elif stationarity == "mobile":
        behavior = "mobile"
    elif active_hours >= MIN_ALWAYS_ON_HOURS:
        # always-on: is it cyclic (usage spikes) or flat?
        if rate_max >= CYCLIC_SPIKE_RATIO * max(rate_med, 1) and rate_max >= CYCLIC_MIN_RATE:
            behavior = "active-cyclic"
        else:
            behavior = "always-on"
    else:
        behavior = "intermittent"

    return {
        "behavior": behavior,
        "stationarity": stationarity,
        "dwell_s": span_s if behavior == "transient" else None,
        "active_hours": active_hours,
        "rssi_std": round(rssi_std, 1) if rssi_std is not None else None,
        "sighting_count": n,
        "rate_max": rate_max,
        "rate_med": rate_med,
    }


BEHAVIOR_LABELS = {
    "always-on": "always-on (fixed)",
    "active-cyclic": "active-cyclic (usage spikes)",
    "intermittent": "intermittent (on/off cycle)",
    "transient": "transient (visitor)",
    "mobile": "mobile (moving)",
    "unknown": "—",
}


def behavior_label(b):
    return BEHAVIOR_LABELS.get(b, b)
