"""Classifier rules — a data table so logic stays separate from rules.
Each rule: (match_fn(raw) -> bool, type, label_fn(raw) -> str|None, confidence).
"""
import re

# Service UUID / mDNS service -> type. Substring-matched against raw['services'].
SERVICE_RULES = {
    # mDNS services (come as e.g. '_spotify-connect._tcp')
    "_airplay": ("speaker", "AirPlay speaker", 0.85),
    "_raop": ("speaker", "AirPlay speaker", 0.85),
    "_spotify-connect": ("speaker", "Spotify Connect speaker", 0.85),
    "_googlecast": ("speaker", "Chromecast", 0.85),
    "_yandexio": ("speaker", "Yandex smart speaker", 0.85),
    "_companion-link": ("apple-device", "Apple device", 0.7),
    "workstation": ("computer", "workstation", 0.7),
    "_smb": ("computer", "Windows PC (SMB)", 0.75),
    "_http._tcp": ("computer", "web server", 0.6),
    "_ssh._tcp": ("computer", "SSH host", 0.65),
    # BLE service UUIDs (16-bit, come as 0000xxxx-0000-1000-...)
    "0000fef3": ("sensor", "sensor/beacon", 0.7),
    "0000fff0": ("iot", "serial IoT", 0.7),
    "0000fea0": ("speaker", "smart speaker", 0.6),   # member-assigned, often speakers
    "00001812": ("sensor", "human-interface sensor", 0.6),
    "0000fd82": ("iot", "BLE IoT", 0.55),
    "0000fe2c": ("iot", "BLE IoT", 0.55),
}

# Name patterns -> (type, label, confidence). Order matters: first match wins.
NAME_RULES = [
    (lambda n: "govee" in n, "light", lambda n: f"Govee {n.split('_',1)[-1] if '_' in n else 'light'}", 0.9),
    (lambda n: "macbook" in n, "laptop", lambda n: "Mac laptop", 0.9),
    (lambda n: "narwal" in n, "vacuum", lambda n: "robot vacuum", 0.9),
    (lambda n: "roborock" in n, "vacuum", lambda n: "robot vacuum", 0.9),
    (lambda n: n.startswith("[av]") or "soundbar" in n, "speaker", lambda n: "soundbar", 0.85),
    (lambda n: "crystal uhd" in n or "cu8000" in n, "tv", lambda n: "Samsung TV", 0.9),
    (lambda n: "iphone" in n, "phone", lambda n: "iPhone", 0.9),
    (lambda n: "ipad" in n, "tablet", lambda n: "iPad", 0.9),
    (lambda n: "kitchen speaker" in n, "speaker", lambda n: "smart speaker", 0.8),
    (lambda n: "spotifyconnect" in n, "speaker", lambda n: "Spotify Connect speaker", 0.85),
    (lambda n: "yandexio" in n or "yandex" in n, "speaker", lambda n: "Yandex smart speaker", 0.85),
    (lambda n: n.startswith("sivanpi") or "workstation" in n, "computer", lambda n: "computer", 0.8),
    (lambda n: "venus_" in n, "iot", lambda n: "Venus IoT device", 0.7),
    (lambda n: "elk-ble" in n, "iot", lambda n: "ELK BLE device", 0.7),
    (lambda n: "apple" in n, "apple-device", lambda n: "Apple device", 0.8),
    (lambda n: "samsung" in n, "samsung-device", lambda n: "Samsung device", 0.75),
    (lambda n: "espressif" in n or "esp32" in n, "iot", lambda n: "ESP32 IoT", 0.8),
]

# OUI vendor -> (type, label, confidence)
OUI_RULES = {
    "espressif inc.": ("iot", "ESP32 IoT device", 0.6),
    "apple, inc.": ("apple-device", "Apple device", 0.6),
    "samsung electronics co.,ltd": ("samsung-device", "Samsung device", 0.6),
    "samsung electronics co., ltd": ("samsung-device", "Samsung device", 0.6),
    "google inc.": ("google-device", "Google device", 0.6),
    "nest labs inc.": ("iot", "Nest IoT", 0.7),
    "irobot corporation": ("vacuum", "iRobot vacuum", 0.75),
    "telink semiconductor": ("iot", "IoT device (Telink)", 0.6),
    "texas instruments": ("iot", "IoT device (TI)", 0.55),
    "hon hai precision": ("computer", "device (Foxconn)", 0.45),  # foxconn: could be phone/PC/IoT, low conf
    "ecobee": ("thermostat", "ecobee thermostat", 0.8),
}

def is_random_mac(mac):
    """Locally-administered bit = second bit of first octet (0b10).
    Returns False for non-MAC keys (e.g. mDNS pseudo-macs like 'mdns:...')."""
    if not mac:
        return False
    hexpart = mac.replace(":", "").replace("-", "")
    # real MACs are 12 hex chars; anything else (pseudo-macs) is not random.
    if len(hexpart) != 12:
        return False
    try:
        first = int(hexpart[0:2], 16)
    except ValueError:
        return False
    return bool(first & 0b10)
