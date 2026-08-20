"""Classifier rules — a data table so logic stays separate from rules.
Each rule: (match_fn(raw) -> bool, type, label_fn(raw) -> str|None, confidence).
"""
import re

# Service UUID / mDNS service -> type. Substring-matched against raw['services'].
# UUIDs verified against the Bluetooth SIG member registry (via bleep-tool mirror)
# and open-source BLE fingerprinting projects (rfparty, ble_monitor, adwatch).
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
    "0000fea0": ("speaker", "Google/Nest smart speaker", 0.85),  # Google Cast setup (SIG: Google LLC)
    "0000fe2c": ("phone", "Android device (Fast Pair)", 0.8),    # Google Fast Pair (SIG: Google LLC)
    "0000fd82": ("tv", "Sony device", 0.8),                       # SIG: Sony Corporation (BRAVIA etc.)
    "0000fcf1": ("sensor", "Find My / Nearby beacon", 0.7),      # Google Nearby Presence
    "0000fcb2": ("apple-device", "Apple device (Continuity)", 0.8),  # Apple Continuity (Handoff/Find My)
    "0000fca4": ("computer", "HP device", 0.7),                   # HP Inc.
    "0000fdf7": ("computer", "HP device", 0.7),                   # HP Inc.
    "0000fef3": ("sensor", "ChromeOS/Android Nearby", 0.65),      # Google Nearby Connections
    "0000fff0": ("light", "LED controller / serial-BLE", 0.6),    # generic vendor UART (Awox/Santoker LED)
    "00001812": ("sensor", "HID (keyboard/mouse/remote)", 0.7),  # HID Service
    "0000af30": ("sensor", "mmWave radar / sensor", 0.55),        # LD2410 radar, cat printers, BMS (not unique)
    # full 128-bit vendor UUIDs
    "c74edd21": ("vacuum", "iRobot robot", 0.9),                  # iRobot Robot Control Command service
    "06aa1910": ("iot", "IoT device", 0.5),                       # unregistered vendor UUID (Venus/etc.)
    "fefe0000": ("iot", "IoT device", 0.5),                       # unregistered vendor UUID (QN-S500 etc.)
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
    (lambda n: "kitchen speaker" in n, "speaker", lambda n: "Google/Nest smart speaker", 0.8),
    (lambda n: "spotifyconnect" in n, "speaker", lambda n: "Spotify Connect speaker", 0.85),
    (lambda n: "yandexio" in n or "yandex" in n, "speaker", lambda n: "Yandex smart speaker", 0.85),
    (lambda n: n.startswith("sivanpi") or "workstation" in n, "computer", lambda n: "computer", 0.8),
    # iRobot operational name: single letter + 5-6 digits (N185020, Q312020, Y014020)
    (lambda n: bool(re.match(r"^[a-z]\d{4,6}$", n)), "vacuum", lambda n: "iRobot robot (Roomba/Braava)", 0.75),
    (lambda n: "roomba" in n or "braava" in n or "altadena" in n, "vacuum", lambda n: "iRobot robot", 0.9),
    # Levoit air purifier: LAP-V201S-* (VeSync ecosystem), despite ESP32 OUI
    (lambda n: n.startswith("lap-"), "sensor", lambda n: "Levoit air purifier", 0.85),
    # ELK LED strip controllers
    (lambda n: "elk-ble" in n, "light", lambda n: "BLE LED strip controller", 0.85),
    (lambda n: "venus_" in n, "iot", lambda n: "Venus IoT device", 0.7),
    (lambda n: "apple" in n, "apple-device", lambda n: "Apple device", 0.8),
    (lambda n: "samsung" in n, "samsung-device", lambda n: "Samsung device", 0.75),
    (lambda n: "espressif" in n or "esp32" in n, "iot", lambda n: "ESP32 IoT", 0.8),
    # WiFi probe-request SSIDs: a device probing for these SSIDs is that device.
    # The probed SSID is a device-identification signal (the device is looking
    # for the network it belongs to). Captured by the AR9271 monitor adapter.
    (lambda n: n.startswith("sonos_"), "speaker", lambda n: "Sonos speaker", 0.85),
    (lambda n: "coway" in n, "iot", lambda n: "Coway IoT device", 0.8),
    (lambda n: n.startswith("whitesky"), "iot", lambda n: "WhiteSky WiFi device", 0.7),
    (lambda n: "mamaroo" in n, "iot", lambda n: "mamaRoo infant rocker", 0.85),
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
    # probe-device OUIs (seen via WiFi probe-requests, not on our network)
    "vantiva - connected home": ("iot", "set-top box / router (Vantiva)", 0.55),
    "vantiva": ("iot", "set-top box / router (Vantiva)", 0.55),
    "hp inc.": ("computer", "HP device", 0.6),
    "mercury corporation": ("iot", "IoT device (Mercury)", 0.5),
    "humax networks": ("iot", "HUMAX set-top box / router", 0.6),
    "amazon technologies inc.": ("iot", "Amazon device (Echo/Fire TV)", 0.6),
    "amazon technologies inc": ("iot", "Amazon device (Echo/Fire TV)", 0.6),
}

# HomeKit category IDs (from _hap TXT 'ci') -> our type taxonomy.
# Maps to existing type keys so TYPE_COLORS/TYPE_LABELS cover them.
HAP_CATEGORY = {
    1: "bridge", 2: "fan", 4: "light", 5: "lock", 6: "outlet", 7: "switch",
    8: "thermostat", 9: "sensor", 10: "sensor", 16: "camera", 17: "sensor",
    18: "sensor", 22: "speaker",
}

def is_random_mac(mac):
    """A locally-administered MAC sets either bit 0 (0b01, non-resolvable
    private) or bit 1 (0b10, resolvable private) of the first octet.
    Returns True if either is set (a random/rotating address). Returns False
    for non-MAC keys (e.g. mDNS pseudo-macs like 'mdns:...')."""
    if not mac:
        return False
    hexpart = mac.replace(":", "").replace("-", "")
    if len(hexpart) != 12:
        return False
    try:
        first = int(hexpart[0:2], 16)
    except ValueError:
        return False
    return bool(first & 0b11)  # either LA bit = random
