"""Apple Continuity decoder. Parses the 0x004C manufacturer-data TLV chain
that Apple devices broadcast, passively (no connection).

Adapted from dkrugman/btviz/apple_continuity.py + furiousMAC/continuity specs.
Layout: a sequence of [type:1][length:1][payload:length] TLVs after the
2-byte company id (which bleak already strips — manufacturer_data[0x004c]
starts at the first type byte).
"""
import struct

# Apple Continuity type bytes
TYPE_IBEACON = 0x02
TYPE_AIRDROP = 0x05
TYPE_HOMEKIT = 0x06
TYPE_PROXIMITY_PAIRING = 0x07   # AirPods/Beats — model+battery+color, unencrypted
TYPE_AIRPLAY_TARGET = 0x09
TYPE_HANDOFF = 0x0C
TYPE_NEARBY_INFO = 0x10         # iPhone/iPad/Mac/Watch status
TYPE_FIND_MY = 0x12             # offline finding (non-AirTag)
TYPE_AIRTAG = 0x16              # AirTag lost mode

# AirPods/Beats model codes (2-byte big-endian, from 0x07 payload).
# Community-maintained; may lag new releases.
AIRPODS_MODELS = {
    0x0220: "AirPods (1st gen)", 0x0F20: "AirPods (2nd gen)",
    0x1320: "AirPods (3rd gen)", 0x1920: "AirPods (4th gen)",
    0x1B20: "AirPods (4th gen, ANC)", 0x0E20: "AirPods Pro",
    0x1420: "AirPods Pro (2nd gen)", 0x2420: "AirPods Pro (2nd gen, USB-C)",
    0x0A20: "AirPods Max", 0x1F20: "AirPods Max (USB-C)",
    0x0520: "BeatsX", 0x0620: "Beats Solo3", 0x0920: "BeatsStudio3",
    0x0B20: "Powerbeats3", 0x0C20: "Beats Solo Pro",
    0x1020: "Powerbeats Pro", 0x1120: "Beats Flex",
    0x1720: "Beats Studio Buds", 0x1820: "Beats Fit Pro",
    0x1D20: "Beats Studio Pro", 0x2520: "Beats Solo 4",
    0x2620: "Beats Studio Buds+",
}

# Nearby Info (0x10) action codes -> device class hint
NEARBY_ACTIONS = {
    0x03: "phone (locked)", 0x07: "phone (ringing)", 0x0D: "watch (lock screen)",
    0x0F: "mac (wake)", 0x14: "apple-tv", 0x27: "homepod",
}


def _parse_tlvs(data):
    """Yield (type, payload) for each TLV in the Apple manufacturer data.
    data starts at the first type byte (company id already stripped by bleak)."""
    i = 0
    while i + 2 <= len(data):
        t = data[i]
        ln = data[i + 1]
        payload = data[i + 2:i + 2 + ln]
        yield t, payload
        i += 2 + ln


def decode_proximity_pairing(payload):
    """0x07 — AirPods/Beats. Unencrypted: model, battery, color.
    Layout: prefix(1) | model(2 BE) | status(1) | battery(1) | charge(1) |
            lidcount(1) | color(1) | suffix(1) | encdata(16)."""
    if len(payload) < 9:
        return None
    model = struct.unpack(">H", payload[1:3])[0]
    # battery byte: bits encode per-pod/case charge levels
    return {
        "device": "AirPods/Beats",
        "model_code": f"0x{model:04X}",
        "model": AIRPODS_MODELS.get(model, "unknown AirPods/Beats"),
        "status": payload[3],
        "battery": payload[4],
        "charging": payload[5],
        "color": payload[6],
    }


def decode_nearby_info(payload):
    """0x10 — iPhone/iPad/Mac/Watch presence + action code."""
    if len(payload) < 2:
        return None
    action = payload[1]
    return {
        "device": "Apple device (Nearby)",
        "action_code": action,
        "hint": NEARBY_ACTIONS.get(action, f"action {action:#x}"),
    }


def decode_find_my(payload, is_airtag=False):
    """0x12 (Find My) / 0x16 (AirTag). 28-byte EC public key rotates every
    15 min; cryptographically unlinkable. We only detect presence + battery."""
    return {
        "device": "AirTag" if is_airtag else "Apple Find My device",
        "status": payload[0] if payload else None,
        # pubkey truncated — not useful for tracking, by design
    }


def decode_apple(manufacturer_data):
    """manufacturer_data: {company_id_int: hex_string}. Returns decoded dict."""
    raw = manufacturer_data.get("76") or manufacturer_data.get(0x004C)
    if not raw:
        return None
    try:
        data = bytes.fromhex(raw)
    except ValueError:
        return None

    out = {"types": []}
    for t, payload in _parse_tlvs(data):
        if t == TYPE_PROXIMITY_PAIRING:
            d = decode_proximity_pairing(payload)
            if d:
                out["types"].append("proximity_pairing")
                out.update(d)
        elif t == TYPE_NEARBY_INFO:
            d = decode_nearby_info(payload)
            if d:
                out["types"].append("nearby_info")
                out.setdefault("nearby", []).append(d)
        elif t == TYPE_AIRTAG:
            d = decode_find_my(payload, is_airtag=True)
            if d:
                out["types"].append("airtag")
                out.update(d)
        elif t == TYPE_FIND_MY:
            d = decode_find_my(payload, is_airtag=False)
            if d:
                out["types"].append("find_my")
                out.update(d)
        elif t == TYPE_IBEACON:
            out["types"].append("ibeacon")
        elif t == TYPE_HANDOFF:
            out["types"].append("handoff")
        elif t == TYPE_AIRPLAY_TARGET:
            out["types"].append("airplay_target")
    return out if out["types"] else None


if __name__ == "__main__":
    # self-check: a known AirPods Pro 2 frame (model 0x1420)
    # type=0x07, len=0x07, prefix=0x01, model=0x1420, status=0x01, batt=0x4f...
    frame = bytes([0x07, 0x07, 0x01, 0x14, 0x20, 0x01, 0x4F, 0x00, 0x04])
    print("AirPods frame:", decode_apple({"76": frame.hex()}))
