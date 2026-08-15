"""OUI lookup — downloads + caches the IEEE OUI list, parses it."""
import os
import time
import urllib.request

from config import OUI_PATH, OUI_URL, OUI_REFRESH_DAYS

_cache = None


def _needs_refresh():
    if not os.path.exists(OUI_PATH):
        return True
    age_days = (time.time() - os.path.getmtime(OUI_PATH)) / 86400
    return age_days > OUI_REFRESH_DAYS


def download_oui():
    req = urllib.request.Request(OUI_URL, headers={"User-Agent": "neighborhood-rhythm/1.0"})
    with urllib.request.urlopen(req) as r, open(OUI_PATH, "wb") as f:
        f.write(r.read())
    return OUI_PATH


def _load():
    global _cache
    if _cache is not None:
        return _cache
    if _needs_refresh():
        try:
            download_oui()
        except Exception:
            # offline + no cached file: degrade to empty map; collector still runs.
            if not os.path.exists(OUI_PATH):
                _cache = {}
                return _cache
    mapping = {}
    try:
        with open(OUI_PATH, encoding="utf-8", errors="replace") as f:
            for line in f:
                # "(hex)        A4CF12    Espressif Inc."
                if "(hex)" in line:
                    parts = line.split("(hex)")
                    if len(parts) == 2:
                        prefix = parts[0].strip().replace("-", ":").upper()
                        vendor = parts[1].strip()
                        if len(prefix) == 8 and vendor:
                            mapping[prefix] = vendor
    except FileNotFoundError:
        pass
    _cache = mapping
    return _cache


def lookup(mac: str):
    """Return manufacturer name or None. mac may use : or - separators."""
    if not mac:
        return None
    m = mac.replace("-", ":").upper()
    parts = m.split(":")
    if len(parts) < 3:
        return None
    return _load().get(":".join(parts[:3]))


if __name__ == "__main__":
    if _needs_refresh():
        print("downloading OUI list...")
        download_oui()
    print(f"{len(_load())} OUI entries loaded")
    print("sample:", lookup("A4:CF:12:00:00:00"))  # Espressif
