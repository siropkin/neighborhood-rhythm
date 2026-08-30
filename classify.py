"""classify(raw_device) -> {type, label, confidence}. Pure functions, rules-based v1."""
from rules import NAME_RULES, OUI_RULES, SERVICE_RULES, is_random_mac


def classify(raw):
    """raw: {mac, name, oui_name, services, is_random, model, category}"""
    name = (raw.get("name") or "").lower()
    oui = (raw.get("oui_name") or "").lower()
    services = [s.lower() for s in (raw.get("services") or [])]

    # 0. mDNS self-identification — highest confidence (the device's own model/category).
    # HomeKit category is authoritative for type. A bare model is a good label but
    # not a type — fall through to service/name/OUI rules so a Chromecast with
    # model='Chromecast' still classifies as 'speaker' via _googlecast, not 'unknown'.
    model = raw.get("model")
    category = raw.get("category")
    if category:
        return {"type": category, "label": model or category, "confidence": 0.9}

    # 1. Name rules.
    for match, dev_type, label_fn, conf in NAME_RULES:
        if match(name):
            return {"type": dev_type, "label": label_fn(name), "confidence": conf}

    # 2. Service UUID / mDNS rules (substring match).
    for svc in services:
        for key, (dev_type, label, conf) in SERVICE_RULES.items():
            if key in svc:
                # Prefer the mDNS model as the label when we have one.
                return {"type": dev_type, "label": model or label, "confidence": conf}

    # 3. OUI rules.
    for vendor_key, (dev_type, label, conf) in OUI_RULES.items():
        if vendor_key in oui:
            return {"type": dev_type, "label": label, "confidence": conf}

    # 4. Random MAC -> anonymous phone/tablet/laptop.
    # A LAN device (source=wifi, ARP scan) with a stable MAC is a real network
    # device even if its MAC is locally-administered (some printers/IoT use
    # LA MACs). But a no-name, no-OUI private MAC on the LAN is a phone using
    # per-network private WiFi addressing — those DO get the phone-anon label.
    mac = raw.get("mac") or ""
    source = raw.get("source") or ""
    is_priv = raw.get("is_random") or (is_random_mac(mac) and not name)
    if is_priv and (source != "wifi" or (not name and not oui)):
        return {"type": "phone-anon", "label": "anonymous mobile (privacy mode)", "confidence": 0.3}

    # 5. Fallback — use the mDNS model as the label if we have one.
    if name:
        return {"type": "unknown", "label": raw.get("name"), "confidence": 0.4}
    if model:
        return {"type": "unknown", "label": model, "confidence": 0.4}
    return {"type": "unknown", "label": None, "confidence": 0.2}


if __name__ == "__main__":
    samples = [
        {"mac": "A4:CF:12:00:00:01", "name": "Govee_H6052", "oui_name": "Espressif Inc.", "services": []},
        {"mac": "AA:BB:CC:DD:EE:FF", "name": "", "oui_name": "Apple, Inc.", "services": ["_airplay"]},
        {"mac": "6A:BB:CC:DD:EE:FF", "name": "", "oui_name": "", "services": []},  # random
        {"mac": "00:11:22:33:44:55", "name": "[AV] Samsung Soundbar", "oui_name": "Samsung Electronics", "services": []},
    ]
    for s in samples:
        print(s["mac"], "->", classify(s))
