"""enrich(raw) -> dict | None. Decodes passive ad payloads (Apple Continuity,
BLE sensors, mDNS model) into a dict stored as JSON in sightings.extra."""
from apple_continuity import decode_apple
from sensors import decode_sensor


def enrich(raw):
    """raw: BLE scan dict or mDNS dict. Returns decoded dict or None."""
    out = {}
    mfr = raw.get("manufacturer_data") or {}
    svc = raw.get("service_data") or {}

    apple = decode_apple(mfr)
    if apple:
        out["apple"] = apple

    sensor = decode_sensor(raw)
    if sensor:
        out["sensor"] = sensor

    # mDNS model + category (already parsed by scan_mdns)
    if raw.get("model") or raw.get("category"):
        mdns = {}
        if raw.get("model"):
            mdns["model"] = raw["model"]
        if raw.get("category"):
            mdns["category"] = raw["category"]
        if raw.get("hostname"):
            mdns["hostname"] = raw["hostname"]
        out["mdns"] = mdns

    return out or None


if __name__ == "__main__":
    # quick self-check with a fake AirPods frame
    sample = {
        "manufacturer_data": {"76": "0707" + "200e" + "01" + "4f" + "00" + "01" + "04" + "00" + "00" * 16},
        "service_data": {},
    }
    print("sample:", enrich(sample))
