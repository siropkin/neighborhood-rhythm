"""enrich(raw) -> dict | None. Decodes passive advertisement payloads into
structured data: Apple Continuity (AirPods/AirTag/iPhone-vs-Mac), BLE sensor
service-data (RuuviTag/BTHome/Qingping/Govee/etc.), iBeacon/Eddystone.

Returns a dict of decoded fields (stored as JSON in sightings.extra), or None
if nothing decodable. Filled in incrementally by decoder modules.
"""
from apple_continuity import decode_apple
from sensors import decode_sensor


def enrich(raw):
    """raw: the BLE scan dict (mac, name, rssi, tx_power, services,
    manufacturer_data, service_data). Returns decoded dict or None."""
    out = {}
    mfr = raw.get("manufacturer_data") or {}
    svc = raw.get("service_data") or {}

    # Apple Continuity (manufacturer data, company 0x004c)
    apple = decode_apple(mfr)
    if apple:
        out["apple"] = apple

    # BLE sensor service-data (RuuviTag, BTHome, Qingping, Govee, etc.)
    sensor = decode_sensor(raw)
    if sensor:
        out["sensor"] = sensor

    return out or None


if __name__ == "__main__":
    # quick self-check with a fake AirPods frame
    sample = {
        "manufacturer_data": {"76": "0707" + "200e" + "01" + "4f" + "00" + "01" + "04" + "00" + "00" * 16},
        "service_data": {},
    }
    print("sample:", enrich(sample))
