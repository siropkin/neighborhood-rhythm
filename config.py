"""Central config — paths, constants, the one shared peer token."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RHYTHM_DB", os.path.join(BASE_DIR, "rhythm.db"))
OUI_PATH = os.path.join(BASE_DIR, "oui.txt")
OUI_URL = "https://standards-oui.ieee.org/oui/oui.txt"
OUI_REFRESH_DAYS = 7

# This Pi's identity — hostname by default, override with RHYTHM_SENSOR_ID.
SENSOR_ID = os.environ.get("RHYTHM_SENSOR_ID", os.environ.get("HOSTNAME", "unknown"))

# Shared token for peer /api/sighting POSTs. Set in config_local.py (not committed).
PEER_TOKEN = os.environ.get("RHYTHM_PEER_TOKEN", "")

# RSSI → distance. log-model: d = 10^((ref_rssi - rssi) / (10*n)). ref tuned for BLE.
# ponytail: fixed path-loss exponent; calibrate per-environment when distance looks wrong.
PATH_LOSS_N = 2.7
REF_RSSI_1M = -59

# Data retention: raw sightings kept this many days, then pruned (the hourly
# rollup in sightings_hourly is kept forever). 14 days of raw is plenty for the
# device-details history + sparklines; older rhythm lives in the rollup.
RETENTION_DAYS = 14
# Two sightings of the same mac+sensor within this window are one sighting
# (dedup guard against bleak double-callbacks).
DEDUP_WINDOW_S = 2

try:
    from config_local import *  # noqa: F401,F403 — overrides live here, uncommitted
except ImportError:
    pass
