"""Central config — paths, constants, the one shared peer token."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RHYTHM_DB", os.path.join(BASE_DIR, "rhythm.db"))
OUI_PATH = os.path.join(BASE_DIR, "oui.txt")
OUI_URL = "https://standards-oui.ieee.org/oui/oui.txt"
OUI_REFRESH_DAYS = 7

SENSOR_ID = os.environ.get("RHYTHM_SENSOR_ID", os.environ.get("HOSTNAME", "unknown"))
PEER_TOKEN = os.environ.get("RHYTHM_PEER_TOKEN", "")  # set in config_local.py (uncommitted)

# RSSI→distance: d = 10^((ref_rssi - rssi)/(10*n)). Calibrate n per-environment if distances look off.
PATH_LOSS_N = 2.7
REF_RSSI_1M = -59

RETENTION_DAYS = 14   # raw sightings pruned after this; hourly rollup kept forever
DEDUP_WINDOW_S = 2    # same mac+sensor within this window = one sighting (bleak double-callback guard)
ACTIVE_WINDOW_S = 600  # "active now" = seen within this many seconds (10 min)

try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
