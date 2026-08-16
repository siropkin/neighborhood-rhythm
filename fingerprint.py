"""Device fingerprinting — derives a stable identity above the rotating MAC
layer so one physical device is one row, not many.

Three linking passes, ordered by confidence:
  A. Apple Continuity  — same Nearby auth tag = same device (0.95)
  B. Cross-radio       — mDNS hostname serial / OUI+name match across BLE/WiFi/mDNS (0.95)
  C. MAC-rotation      — same class+signature, sequential (old gone, new appears) within a window (0.7)

See docs/FINGERPRINTING.md (design) and docs/FINGERPRINTING-VALIDATION.md
(what the data actually showed — service-UUID set is a CLASS signal not a
UNIT signal, so Pass C needs the time-adjacency guard against over-merging).

A fingerprint_id is a uuid4 — a synthetic stable handle, not PII. Many MACs
map to one fingerprint_id via the device_aliases table.
"""
import json
import uuid
from collections import defaultdict

import db
from rules import is_random_mac

# Link confidence thresholds.
CONF_CONTINUITY = 0.95   # Apple Nearby auth tag — stable per device
CONF_CROSS_RADIO = 0.95   # mDNS hostname serial / OUI+name — stable per device
CONF_ROTATION = 0.7       # MAC rotation — same class+signature, sequential
CONF_AIRPODS = 0.6        # AirPods model+color — same model, maybe same unit

ROTATION_WINDOW_S = 900   # 15 min — ~3 scan intervals; one rotation gap.


def _extract_apple_tag(extra):
    """Pull the stable Apple identifier from a sighting's extra JSON.
    Returns ('auth_tag', value) for Nearby, ('airpods', 'model:color') for
    AirPods, or None."""
    if not extra:
        return None
    try:
        e = json.loads(extra) if isinstance(extra, str) else extra
    except (json.JSONDecodeError, TypeError):
        return None
    apple = e.get("apple") or {}
    # Nearby auth tag — the stable per-device ID (Pass A).
    for nb in apple.get("nearby") or []:
        tag = nb.get("auth_tag")
        if tag:
            return ("auth_tag", tag)
    # AirPods model+color — coarser (same model, maybe same unit).
    if apple.get("model_code") and apple.get("color") is not None:
        return ("airpods", f"{apple['model_code']}:{apple['color']}")
    return None


def _mdns_serial(mac):
    """If this is an mDNS pseudo-mac, extract the hostname serial — the
    stable per-device ID embedded in many mDNS hostnames."""
    if not mac or not mac.startswith("mdns:"):
        return None
    # mdns:[hostname]:service — the hostname often has a serial.
    # e.g. mdns:[yandexmini-2-MG0000...local]:_yandexio._tcp
    body = mac[5:]
    # strip the [hostname] portion
    if body.startswith("["):
        host = body[1:body.index("]")] if "]" in body else body
    else:
        host = body.split(":")[0]
    # drop trailing .local
    host = host.replace(".local", "")
    return host or None


def _oui_prefix(mac):
    """First 3 octets uppercased, or None for random/mDNS keys."""
    if not mac or mac.startswith("mdns:") or is_random_mac(mac):
        return None
    parts = mac.replace("-", ":").upper().split(":")
    return ":".join(parts[:3]) if len(parts) >= 3 else None


def _name_key(name):
    """Normalize a device name for matching — lowercased, whitespace-collapsed.
    None → None."""
    if not name:
        return None
    return " ".join(name.lower().split())


def _device_signature(services, extra):
    """The class-level signature: service-UUID set + Apple continuity type.
    Stable per device-class but NOT per unit (validated: 456/508 random MACs
    share an empty set). Used only as a rotation-cluster *component*, never
    alone."""
    svc = set()
    if services:
        svc = {s.strip().lower() for s in str(services).split(",") if s.strip()}
    return (frozenset(svc), _extract_apple_tag(extra))


def _new_fingerprint_id():
    return str(uuid.uuid4())


def _get_or_create_fp(conn, fingerprint_id, device_class, label, ts, confidence):
    """Create a fingerprint row if new, else bump its sighting_count + last_seen."""
    row = conn.execute(
        "SELECT fingerprint_id FROM device_fingerprints WHERE fingerprint_id=?",
        (fingerprint_id,)).fetchone()
    if row:
        conn.execute("""UPDATE device_fingerprints SET
            last_seen=MAX(last_seen, ?), sighting_count=sighting_count+1,
            confidence=MAX(confidence, ?)""",
            (ts, confidence))
    else:
        conn.execute("""INSERT INTO device_fingerprints
            (fingerprint_id, device_class, label, first_seen, last_seen, sighting_count, confidence)
            VALUES (?,?,?,?,?,1,?)""",
            (fingerprint_id, device_class, label, ts, ts, confidence))


def _link_alias(conn, mac, source, fingerprint_id, ts, confidence, method):
    """Map a MAC → fingerprint_id. Creates or updates the alias row."""
    conn.execute("""INSERT INTO device_aliases
        (mac, fingerprint_id, source, first_seen, last_seen, sighting_count, link_confidence, link_method)
        VALUES (?,?,?,?,?,1,?,?)
        ON CONFLICT(mac) DO UPDATE SET
          last_seen=MAX(device_aliases.last_seen, excluded.last_seen),
          sighting_count=device_aliases.sighting_count+1""",
        (mac, fingerprint_id, source, ts, ts, confidence, method))
    # cache on the devices row too
    conn.execute("UPDATE devices SET fingerprint_id=? WHERE mac=?", (fingerprint_id, mac))


def fingerprint_all(conn, reclassify_fn=None):
    """Recompute all fingerprints from scratch. Idempotent: clears the
    fingerprint tables first, then runs all three passes over every device.

    Pass order: B (cross-radio) + A (continuity) first — they're deterministic
    and high-confidence. C (rotation) last, only for random MACs left unlinked.
    """
    conn.execute("DELETE FROM device_fingerprints")
    conn.execute("DELETE FROM device_aliases")
    conn.execute("UPDATE devices SET fingerprint_id=NULL")

    devs = conn.execute(
        "SELECT mac, oui_name, last_type, last_label, first_seen, last_seen, sighting_count "
        "FROM devices").fetchall()

    # Gather per-device signals from their latest sighting.
    sig = {}
    for d in devs:
        mac = d["mac"]
        s = conn.execute(
            "SELECT name, services, extra, source FROM sightings WHERE mac=? "
            "ORDER BY ts DESC LIMIT 1", (mac,)).fetchone()
        sig[mac] = {
            "mac": mac,
            "oui": d["oui_name"],
            "oui_prefix": _oui_prefix(mac),
            "type": d["last_type"],
            "label": d["last_label"],
            "name": _name_key(s["name"] if s else None),
            "services": s["services"] if s else None,
            "apple": _extract_apple_tag(s["extra"] if s else None),
            "mdns_serial": _mdns_serial(mac),
            "source": s["source"] if s else None,
            "first_seen": d["first_seen"],
            "last_seen": d["last_seen"],
            "count": d["sighting_count"],
        }

    # ---- Pass B: cross-radio linking (mDNS serial + OUI+name) ----
    # mDNS hostnames with serials link to BLE devices with matching names.
    # Same-host multi-service mDNS rows (Anastasiias-MacBook _airplay + _raop) link together.
    clusters = {}  # mac -> set of macs in its cluster
    for mac, s in sig.items():
        clusters[mac] = {mac}

    def _merge(a, b):
        """Union two clusters."""
        ra, rb = clusters[a], clusters[b]
        if ra is rb:
            return
        merged = ra | rb
        for m in merged:
            clusters[m] = merged

    # B1: mDNS rows with the same hostname serial → one device.
    mdns_by_host = defaultdict(list)
    for mac, s in sig.items():
        if s["mdns_serial"]:
            mdns_by_host[s["mdns_serial"]].append(mac)
    for host, macs in mdns_by_host.items():
        for i in range(1, len(macs)):
            _merge(macs[0], macs[i])

    # B2: mDNS serial matches a BLE device name (e.g. yandexmini-2-MG0000...).
    for mac, s in sig.items():
        if not s["mdns_serial"]:
            continue
        host = s["mdns_serial"]
        for mac2, s2 in sig.items():
            if mac2 == mac or s2["mdns_serial"]:
                continue
            if s2["name"] and host in s2["name"]:
                _merge(mac, mac2)
            # also match on the hostname base (before any serial suffix)
            elif s2["name"] and host.split("-")[0] in s2["name"]:
                _merge(mac, mac2)

    # B3: BLE + WiFi with same OUI prefix + similar name.
    for mac, s in sig.items():
        if not s["oui_prefix"] or not s["name"]:
            continue
        for mac2, s2 in sig.items():
            if mac2 == mac or not s2["oui_prefix"]:
                continue
            if s["oui_prefix"] == s2["oui_prefix"] and s["name"] == s2["name"]:
                _merge(mac, mac2)

    # ---- Pass A: Apple Continuity linking ----
    # Same Nearby auth tag → same device. Same AirPods model+color → same-class.
    by_tag = defaultdict(list)
    by_airpods = defaultdict(list)
    for mac, s in sig.items():
        if s["apple"]:
            kind, val = s["apple"]
            if kind == "auth_tag":
                by_tag[val].append(mac)
            elif kind == "airpods":
                by_airpods[val].append(mac)
    for tag, macs in by_tag.items():
        for i in range(1, len(macs)):
            _merge(macs[0], macs[i])
    # AirPods: only merge if also same class + time-adjacent (coarser signal).
    for val, macs in by_airpods.items():
        if len(macs) < 2:
            continue
        macs.sort(key=lambda m: sig[m]["first_seen"])
        for i in range(1, len(macs)):
            if sig[macs[i]]["type"] == sig[macs[i-1]]["type"]:
                _merge(macs[i-1], macs[i])

    # ---- Pass C: MAC-rotation clustering (random MACs only) ----
    # Same class+signature, SEQUENTIAL (old last_seen < new first_seen, within
    # window), and old not seen again after new appears. The time-adjacency
    # guard is what stops the over-merge the data validation warned about.
    #
    # Validated constraint: the 454 random MACs with an EMPTY signature (no
    # service set, no Apple tag) share one signature — that's a class signal,
    # not a unit signal. Linking them by time-adjacency alone over-merges
    # (chained A→B→C→D into one 10-MAC cluster of simultaneous phones). So
    # Pass C only runs on signatures with a real device-identifying component
    # (a non-empty service set or an Apple tag). The empty-set MACs stay
    # un-merged — they're honest footfall noise, not linkable units.
    random_devs = [s for s in sig.values() if is_random_mac(s["mac"])]
    by_sig = defaultdict(list)
    for s in random_devs:
        svc_set, apple = _device_signature(s["services"], None)
        # skip the empty signature — not a unit signal, just "anonymous phone"
        if not svc_set and not apple:
            continue
        by_sig[(s["type"], _device_signature(s["services"], None))].append(s)
    # Temporal-confidence boost: a rotation handoff is A gone → B appears
    # within a short window, AND A not seen again after B (clean handoff, no
    # overlap). This is the "visible 15 min, gone, new appears" pattern — it
    # lets us link pairs where the signature alone is weak, because the
    # temporal handoff is itself a device-identifying signal.
    HANDOFF_MAX_GAP_S = 120   # A gone → B appears within 2 min = a handoff
    HANDOFF_OVERLAP_S = 30    # A seen up to 30s after B = scan jitter, not overlap
    for key, group in by_sig.items():
        if len(group) < 2:
            continue
        # Cardinality guard: if too many MACs share this signature, it's a
        # class signature (e.g. 0000fcf1 = Google Nearby, 20 simultaneous MACs),
        # not a device-unique one. Linking them chains unrelated phones.
        if len(group) > 4:
            continue
        group.sort(key=lambda s: s["first_seen"])
        for i in range(1, len(group)):
            prev, cur = group[i-1], group[i]
            gap = cur["first_seen"] - prev["last_seen"]
            if gap <= 0:
                continue  # B appeared before/while A was still around — overlap, not a handoff
            # Link if A is gone before B (no overlap beyond scan jitter) and
            # the handoff is within the rotation window. A clean handoff
            # (gap <= 2 min) is a strong rotation signal; a longer gap within
            # the window is a weaker but still valid link.
            a_gone_before_b = prev["last_seen"] <= cur["first_seen"] + HANDOFF_OVERLAP_S
            if a_gone_before_b and gap <= ROTATION_WINDOW_S:
                _merge(prev["mac"], cur["mac"])

    # ---- Pass C2: rotation-interval extension ----
    # Once a cluster has 2+ linked MACs (A→B), we've observed one rotation
    # interval (B.first_seen - A.first_seen ≈ the phone's rotation period).
    # A 3rd MAC C appearing at the expected interval (±2 min) with the same
    # signature and a clean handoff from the last MAC links with higher
    # confidence — the periodicity is itself a device-identifying signal.
    # This catches the D in A→B→C→D that a single-pair check might miss.
    for key, group in by_sig.items():
        if len(group) < 3:
            continue
        if len(group) > 4:
            continue  # same cardinality cap
        group.sort(key=lambda s: s["first_seen"])
        # for each linked pair in this group, check if a later MAC matches
        # the learned interval from the pair
        linked = [m for m in group if len(clusters[m]) > 1]
        if len(linked) < 2:
            continue
        # observed interval = first linked pair's first_seen gap
        interval = linked[1]["first_seen"] - linked[0]["first_seen"]
        if interval <= 0:
            continue
        last_linked = linked[-1]
        for cand in group:
            if cand["mac"] in clusters[last_linked["mac"]]:
                continue  # already linked
            since = cand["first_seen"] - last_linked["last_seen"]
            if since <= 0:
                continue
            # candidate appears ~one interval after the last linked MAC,
            # with a clean handoff. The interval match + signature + handoff
            # = high confidence this is the next rotation.
            if (abs((cand["first_seen"] - last_linked["first_seen"]) - interval) <= 120
                    and since <= ROTATION_WINDOW_S
                    and last_linked["last_seen"] <= cand["first_seen"] + HANDOFF_OVERLAP_S):
                _merge(last_linked["mac"], cand["mac"])

    # ---- Write clusters to the tables ----
    seen_clusters = set()
    n_fps = 0
    for mac, s in sig.items():
        cluster = clusters[mac]
        rep = min(cluster)  # stable representative
        if rep in seen_clusters:
            continue
        seen_clusters.add(rep)
        # pick the best label + class in the cluster (prefer named/typed members)
        best = max(cluster, key=lambda m: (sig[m]["label"] is not None,
                                           sig[m]["type"] not in (None, "unknown", "phone-anon"),
                                           sig[m]["count"]))
        fp_id = _new_fingerprint_id()
        cls = sig[best]["type"]
        label = sig[best]["label"]
        first = min(sig[m]["first_seen"] or 0 for m in cluster)
        last = max(sig[m]["last_seen"] or 0 for m in cluster)
        count = sum(sig[m]["count"] or 0 for m in cluster)
        # cluster-level link method + confidence: highest-confidence pass that fired
        has_mdns = any(sig[m]["mdns_serial"] for m in cluster)
        has_tag = any(sig[m]["apple"] and sig[m]["apple"][0] == "auth_tag" for m in cluster)
        if has_mdns:
            method, conf = "cross-radio", CONF_CROSS_RADIO
        elif has_tag:
            method, conf = "continuity", CONF_CONTINUITY
        elif len(cluster) > 1:
            method, conf = "rotation", CONF_ROTATION
        else:
            method, conf = "direct", 0.0
        conn.execute("""INSERT INTO device_fingerprints
            (fingerprint_id, device_class, label, first_seen, last_seen, sighting_count, confidence)
            VALUES (?,?,?,?,?,?,?)""",
            (fp_id, cls, label, first, last, count, conf))
        for m in cluster:
            ms = sig[m]
            _link_alias(conn, m, ms["source"], fp_id, ms["last_seen"] or first, conf, method)
        n_fps += 1
    return n_fps


if __name__ == "__main__":
    # Self-check: run fingerprinting over the live DB, report the dedup.
    with db.get_db() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        n = fingerprint_all(conn)
        after = conn.execute("SELECT COUNT(*) c FROM device_fingerprints").fetchone()["c"]
    print(f"devices: {before} → fingerprints: {after} ({n} created)")
    print(f"dedup: {before - after} MACs merged")
