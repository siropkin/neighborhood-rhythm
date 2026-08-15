"""BLE service-data sensor decoder. Passive (no connection, no key).
BTHome v2 (0xFCD2), RuuviTag v5 (0x0499), Govee (0xEC88). Routed by service UUID / company id."""
import struct

# BTHome v2 object ids -> (name, length, signed, factor)
BTHOME_OBJECTS = {
    0x01: ("battery", 1, False, 1),         # %
    0x02: ("temperature", 2, True, 0.01),   # °C
    0x03: ("humidity", 2, False, 0.01),      # %
    0x04: ("pressure", 3, False, 0.01),       # mbar
    0x05: ("illuminance", 3, False, 0.01),    # lx
    0x09: ("co2", 2, False, 1),              # ppm
    0x0C: ("voltage", 2, False, 0.001),      # V
    0x45: ("temperature", 2, True, 0.1),      # °C (alt)
    0x4A: ("voltage", 2, False, 0.1),         # V (alt)
}


def decode_bthome(payload):
    """BTHome v2 (service 0xFCD2). First byte = adv_info (bit 0 = encrypted).
    Then objects: u8 id + value (length from table)."""
    if not payload:
        return None
    adv_info = payload[0]
    if adv_info & 0x01:
        return {"device": "BTHome (encrypted)", "encrypted": True}
    out = {"device": "BTHome sensor"}
    i = 1
    while i < len(payload):
        oid = payload[i]
        if oid not in BTHOME_OBJECTS:
            break  # unknown object; objects must be ascending, bail
        name, ln, signed, factor = BTHOME_OBJECTS[oid]
        if i + 1 + ln > len(payload):
            break
        raw = payload[i + 1:i + 1 + ln]
        if signed:
            val = int.from_bytes(raw, "little", signed=True)
        else:
            val = int.from_bytes(raw, "little", signed=False)
        out[name] = round(val * factor, 2)
        i += 1 + ln
    return out if len(out) > 1 else None


def decode_ruuvitag(payload):
    """RuuviTag v5 (company 0x0499, manufacturer_data). 18 bytes after the
    2-byte company id + 2-byte format. No encryption. Full env sensor."""
    # payload here is the full manufacturer_data value (hex-decoded already).
    # Layout after company id: format(2)=0x05, then 18 bytes of sensor data.
    if len(payload) < 20:
        return None
    fmt = struct.unpack(">H", payload[0:2])[0]
    if fmt != 0x05:
        return None  # v2/v3 not handled here
    d = payload[2:20]
    temp = struct.unpack(">h", d[0:2])[0] * 0.005
    hum = struct.unpack(">H", d[2:4])[0] * 0.0025
    pres = struct.unpack(">H", d[4:6])[0] + 50000  # Pa
    power = struct.unpack(">H", d[10:12])[0]
    voltage = (1600 + (power >> 5)) / 1000
    batt = power & 0x1F
    return {
        "device": "RuuviTag",
        "temperature": round(temp, 2),
        "humidity": round(hum, 2),
        "pressure_pa": pres,
        "battery_v": round(voltage, 3),
    }


def decode_govee(payload, company_id):
    """Govee temp/humidity sensors. 3 packing families by company id + length.
    All passive, no encryption."""
    try:
        if company_id in (0xEC88, 0x0001) and len(payload) >= 8:
            # H5072/H5075/H5101/H5178: 3-byte packet
            pkt = int.from_bytes(payload[5:8], "big")
            sign = 1 if pkt & 0x800000 else -1
            temp = sign * int(pkt / 1000) / 10
            hum = (pkt % 1000) / 10
            batt = payload[8] if len(payload) > 8 else None
            out = {"device": "Govee sensor", "temperature": temp, "humidity": hum}
            if batt is not None:
                out["battery"] = batt
            return out
    except Exception:
        pass
    return None


def decode_sensor(raw):
    """Route by service_data UUID or manufacturer_data company id."""
    svc = raw.get("service_data") or {}
    mfr = raw.get("manufacturer_data") or {}

    # BTHome v2
    for key in ("0xfcd2", "0000fcd2-0000-1000-8000-00805f9b34fb"):
        if key in svc:
            return decode_bthome(bytes.fromhex(svc[key]))

    # RuuviTag (manufacturer data, company 0x0499)
    if "1189" in mfr or 0x0499 in mfr or "0x499" in mfr:
        raw_hex = mfr.get("1189") or mfr.get(0x0499) or mfr.get("0x499")
        if raw_hex:
            return decode_ruuvitag(bytes.fromhex(raw_hex))

    # Govee (company 0xEC88 or 0x0001)
    for cid in ("60424", "0xec88", "0001"):
        if cid in mfr:
            return decode_govee(bytes.fromhex(mfr[cid]), int(cid, 16) if cid.startswith("0x") else int(cid))

    return None


if __name__ == "__main__":
    # self-check: a BTHome temp+battery frame
    # adv_info=0x00 (unencrypted), battery=0x01 0x55 (85%), temp=0x02 0x0a 0x01 (26.6°C)
    bth = bytes([0x00, 0x01, 0x55, 0x02, 0x0A, 0x01])
    print("BTHome:", decode_bthome(bth))
