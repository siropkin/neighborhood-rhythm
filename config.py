"""Central config — paths, constants, the one shared peer token."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("RHYTHM_DB", os.path.join(BASE_DIR, "rhythm.db"))
OUI_PATH = os.path.join(BASE_DIR, "oui.txt")
OUI_URL = "https://standards-oui.ieee.org/oui/oui.txt"
OUI_REFRESH_DAYS = 7

SENSOR_ID = os.environ.get("RHYTHM_SENSOR_ID", os.environ.get("HOSTNAME", "unknown"))
PEER_TOKEN = os.environ.get("RHYTHM_PEER_TOKEN", "")  # set in config_local.py (uncommitted)
API_TOKEN = os.environ.get("RHYTHM_API_TOKEN", "")  # if set, /api/* requires Authorization: Bearer <token>
ALERT_WEBHOOK = os.environ.get("RHYTHM_ALERT_WEBHOOK", "")  # if set, POST rogue alerts here (Slack/Teams/SIEM)
SITE_ID = os.environ.get("RHYTHM_SITE_ID", "")  # multi-tenant: which site this Pi belongs to

# RSSI→distance: d = 10^((ref_rssi - rssi)/(10*n)). Calibrate n per-environment if distances look off.
PATH_LOSS_N = 2.7
REF_RSSI_1M = -59

RETENTION_DAYS = 14   # raw sightings pruned after this; hourly rollup kept forever
DEDUP_WINDOW_S = 2    # same mac+sensor within this window = one sighting (bleak double-callback guard)
ACTIVE_WINDOW_S = 600  # "active now" = seen within this many seconds (10 min)
BLE_RSSI_FLOOR = -85  # ignore BLE ads weaker than this (drive-by, outside the building)

try:
    from config_local import *  # noqa: F401,F403
except ImportError:
    pass
