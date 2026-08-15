# Device Fingerprinting — Design Doc

**Goal:** stop keying devices by MAC address alone. Derive a stable *device
fingerprint* from multiple passive signals so one physical device is one row,
not many. This is a design doc, not code.

**Status:** design. No code changes yet. References the current schema in
`db.py`, capture logic in `collector.py`, decoding in `apple_continuity.py`
and `enrich.py`, and classification in `classify.py` / `rules.py`.

---

## 1. The duplicate problem

The `devices` table uses `mac` as `PRIMARY KEY` (`db.py` line 11), and
`sightings.mac` references it. Every sighting is keyed by MAC. This produces
three distinct kinds of duplicate — one physical device spread across many
rows.

### 1.1 MAC randomization (the big one)

Modern phones rotate their BLE MAC every ~15 minutes for privacy
([iOS](https://developer.apple.com/documentation/wireless-data-protection/),
Android). One physical phone seen over an hour is ~4 different `devices` rows.

**Real data from the Pi (1030 devices, 3433 sightings, 2026-08-15):**

| metric | count |
|---|---|
| total devices | 1030 |
| random-MAC devices (locally-administered bit set) | 499 (48%) |
| `phone-anon` (the random-MAC bucket) | 448 |
| `phone-anon` seen more than once | 314 |
| devices seen **exactly once** | 303 (29%) |

So ~448 of 1030 "devices" are anonymous phones, and they are really on the
order of **5–20 physical phones** (a phone that rotates every 15 min and is
seen for an hour produces ~4 MACs; most are seen a handful of times then
disappear). 314 of them were re-sighted, which is the linkable population.
The other 134 single-sighting phone-anons are unrecoverable noise.

This is the #1 source of duplicates by far. `phone-anon` is the largest
single bucket and it is almost entirely inflated by rotation.

### 1.2 BLE MAC vs WiFi MAC vs mDNS hostname

One physical device exposes different identifiers on each radio. A speaker
has a BLE MAC, a WiFi BSSID, and an mDNS hostname. Currently these are 3
separate `devices` rows.

The code already hacks around this with a string-key: `collector.py` line 232
does `raw["mac"] = f"mdns:{raw.get('hostname') or raw.get('name')}"`. That
makes one mDNS device one row (good — it collapses `_airplay` + `_raop` +
`_hap` from the same host), but it does **not** link the mDNS device to its
BLE or WiFi counterpart. It's a namespace hack, not a link.

**Real data:** 12 mDNS pseudo-macs exist. mDNS hostnames often carry a
device-unique serial, e.g. `yandexmini-2-MG000000000000066428000017e35c12.local`
— that `MG0000…` string is a perfect stable identifier, better than any MAC.
The Yandex speaker is one physical device that currently appears as a BLE row,
an mDNS row, and possibly a WiFi AP row.

### 1.3 Apple Continuity

Apple devices broadcast a rotating Continuity payload (company `0x004C`) that
can be partially fingerprinted — device model, color — but not by MAC. The
decoder (`apple_continuity.py`) already extracts these. The problem: an
AirPods Pro broadcasts model `0x1420` + color `0x00` on a MAC that rotates,
so each rotation is a new `devices` row even though the model+color are
constant.

**Real data:** 5 Apple-continuity sightings in the current DB (Find My,
AirTag, Nearby Info). Small but growing as Apple-device density rises.

---

## 2. Available signals

Every signal the scanner already captures, per radio, and how stable it is.
"Stable" = fixed for the lifetime of the physical device. "Rotates" = changes
under MAC randomization. "Semi-stable" = changes slowly or with state.

### 2.1 BLE (`scan_ble`, source=`ble`)

| field | source in code | stability | useful for fingerprint? |
|---|---|---|---|
| `mac` | `dev.address` | **rotates** for phones; stable for peripherals | no (phones); yes (peripherals) |
| `name` | `dev.name` / `adv.local_name` | semi-stable (some devices blank it, some don't) | yes — strong when present |
| `services` (UUID list) | `adv.service_uuids` | stable per device (the advertised service set is a device signature) | **yes — primary signal** |
| `manufacturer_data` (company id + payload) | `adv.manufacturer_data` | stable per device (company id + payload shape) | **yes — primary signal** |
| `service_data` (UUID + payload) | `adv.service_data` | stable per device | yes |
| `tx_power` | `adv.tx_power` | stable per device class | weak — same for all devices of a model |
| `rssi` | `adv.rssi` | ephemeral (distance/path loss) | no for identity; yes for proximity clustering |

**Apple Continuity** (decoded from `manufacturer_data` by `apple_continuity.py`):

| TLV type | field | stability | useful? |
|---|---|---|---|
| `0x07` Proximity Pairing (AirPods/Beats) | model (2-byte) | **stable** (per product) | **yes** |
| `0x07` | color (1-byte) | **stable** (per unit) | **yes** |
| `0x07` | battery / status / charging | ephemeral | no |
| `0x10` Nearby Info | **authentication tag (3 bytes)** | **stable** (per device) | **yes — the key Apple signal** |
| `0x10` | action code / status flags | ephemeral (state) | no |
| `0x12` Find My | EC public key (28 bytes) | **rotates every 15 min** (by design, unlinkable) | no — cryptographically unlinkable |
| `0x16` AirTag | same as Find My | rotates | no |
| `0x0C` Handoff | encrypted payload | opaque | no |
| `0x02` iBeacon | UUID + major + minor | stable per beacon config | yes (for beacons) |

The **Nearby Info authentication tag** is the stable Apple device identifier
that survives MAC rotation — this is the basis of the "Discontinued Privacy"
line of work (Celosia & Cunche, and the furiousMAC/continuity project, which
documents the wire format). The AirPods model+color are a coarser but still
stable signal. Find My / AirTag public keys are *designed* to be unlinkable
across rotations — do not try to link them.

### 2.2 WiFi (`scan_wifi`, `wifi_aps` table)

| field | stability | useful? |
|---|---|---|
| `bssid` (AP MAC) | stable for APs; **rotates** for client probe-requests | yes (APs); the scanner currently only sees APs, not clients |
| `ssid` | stable | yes (weak — shared by many) |
| `channel` / `freq` | stable | weak |
| `signal` | ephemeral | no for identity |

**Note:** `scan_wifi` only scans APs (`iw dev wlan0 scan`), not client
probe-requests. So WiFi-side device tracking (the probe-request IE
fingerprinting literature) is **not currently available** — it would need
monitor mode + a different capture path. This is a future avenue (see §6),
not a current signal.

### 2.3 mDNS (`scan_mdns`, source=`mdns`)

| field | source in code | stability | useful? |
|---|---|---|---|
| `hostname` | `info.server` | **stable** (device-chosen, often has a serial) | **yes — strongest mDNS signal** |
| `name` (service instance) | parsed | stable | yes |
| `service` (type) | `_airplay._tcp` etc. | stable | yes (class) |
| `txt` records (`model`, `ci` category, `md`, `ty`) | `info.decoded_properties` | **stable** | **yes — model is a strong signal** |
| `category` (HomeKit `ci`) | mapped via `HAP_CATEGORY` | stable | yes (class) |

mDNS hostnames frequently embed a serial (`yandexmini-2-MG0000…`,
`SivanPi.local`, `linux.local`). The serial-bearing ones are the best stable
identifiers in the whole system.

### 2.4 OUI (derived from MAC via `oui.py`)

| field | stability | useful? |
|---|---|---|
| OUI prefix (first 3 octets) | stable for **global** MACs; **meaningless** for random MACs | yes for stable MACs; **no for random MACs** |

**Critical caveat confirmed by the data:** the IEEE OUI list does **not**
cover locally-administered (random) MACs. Of 531 stable-MAC devices, **504
have no OUI** (`oui_name` is null/empty). OUI is only useful for the ~27
stable devices with a registered vendor prefix. Do **not** rely on OUI for
random-MAC linking — it's empty by definition there.

---

## 3. Fingerprint design

The key insight: **no single field is stable, but a combination is.** A
phone rotates its MAC, but its advertised service-UUID set, its Apple
Continuity auth tag, and (when present) its name are stable across that
rotation. So we derive a composite fingerprint and link MACs that share one.

### 3.1 The composite fingerprint

A *device fingerprint* is a tuple of the stable signals from a single sighting:

```
fingerprint = (
    oui_prefix,            # "" for random MACs; vendor prefix for stable
    device_class,           # classify() type: phone/speaker/beacon/apple-device/...
    service_set,            # sorted set of advertised service UUIDs (the device signature)
    apple_continuity_tag,   # Nearby Info auth tag, or AirPods model+color, or None
    name_pattern,           # normalized name (serial stripped to a pattern), or None
    mdns_hostname,          # the mDNS hostname if this is an mDNS sighting, or None
)
```

The fingerprint is **not** a single hash — different subsets apply to
different device classes, so we compute a *match score* between two
fingerprints rather than demanding exact equality.

### 3.2 Linking passes

Three independent linking passes, ordered by confidence. A device is linked
if *any* pass fires, and the passes attach a confidence to the link.

**Pass A — Apple Continuity linking (highest confidence).**
Two sightings with the same Nearby Info auth tag are the same device,
regardless of MAC. Two sightings with the same AirPods model+color are *a*
device of that model (not necessarily *the same unit* — model+color is a
coarser signal; treat as same-class, lower confidence). Find My / AirTag
pubkeys are **never** linked (they rotate by design).

**Pass B — Cross-radio linking (BLE ↔ WiFi ↔ mDNS).**
Link entries that share a stable identifier across radios:
- An mDNS hostname with an embedded serial matches a BLE device advertising
  the same serial in its name (e.g. `yandexmini-2-MG0000…`).
- A BLE device and a WiFi AP with the same OUI prefix *and* similar name
  (string-similarity threshold) are one device.
- mDNS `model` TXT matches a BLE-decoded model.

This is where the `mdns:` string-key hack gets replaced by a real link: the
mDNS row and the BLE row both point at one `fingerprint_id`.

**Pass C — MAC-rotation linking (the phone-anon clusterer).**
This is the big dedup win. When a new random MAC appears with the same
device-class signature (service-UUID set + Apple continuity tag + name
pattern) as a random MAC that just disappeared, within a short time window,
link them as one device.

```
link if:
    new_mac.is_random AND old_mac.is_random
    AND new.device_class == old.device_class
    AND new.service_set == old.service_set           # exact set match
    AND new.apple_tag == old.apple_tag               # if present
    AND |new.first_seen - old.last_seen| < ROTATION_WINDOW_S
```

`ROTATION_WINDOW_S` should be on the order of one scan interval to a few
minutes — the gap between one MAC expiring and the next appearing. The
scanner runs every 5 min (`collector.timer`), so a window of ~10–15 min
covers one rotation gap. Tighter is safer (fewer false links); start at 10
min and tune from the data.

The service-UUID set is the workhorse here: a phone advertises a fairly
stable set of service UUIDs (Fast Pair, Nearby, etc.) that survives MAC
rotation. The Apple continuity tag is the clincher when present.

### 3.3 Confidence scoring

Each link gets a confidence in `[0,1]`:

| signal match | confidence contribution |
|---|---|
| Apple Nearby Info auth tag exact match | 0.95 |
| mDNS hostname serial exact match | 0.95 |
| AirPods model+color match | 0.6 (same model, maybe same unit) |
| service-UUID set exact match + same class | 0.7 |
| name exact match + same class | 0.8 |
| name fuzzy match (similarity > 0.85) + same OUI | 0.6 |
| service-UUID set partial match (>80% overlap) | 0.5 |
| MAC-rotation time-window match alone | 0.3 (weak, needs another signal) |

A link is **accepted** at confidence ≥ 0.7, **tentative** at 0.5–0.7 (held
for re-confirmation on next scan), and **rejected** below 0.5. Tentative
links are promoted to accepted if a second sighting confirms them, and
dropped if a sighting contradicts (a different MAC claims the same stable
signal).

---

## 4. Schema changes

Minimal, additive changes to `db.py`. The existing `devices.mac` PRIMARY KEY
stays (it's still the per-sighting key), but a new layer sits above it.

### 4.1 New table: `device_fingerprints`

```sql
CREATE TABLE IF NOT EXISTS device_fingerprints (
    fingerprint_id  TEXT PRIMARY KEY,   -- uuid4, the stable device identity
    fingerprint     TEXT NOT NULL,      -- canonical JSON of the composite tuple
    device_class    TEXT,               -- classify() type
    label           TEXT,               -- best human label
    first_seen      REAL,
    last_seen       REAL,
    sighting_count  INTEGER DEFAULT 0,
    confidence      REAL DEFAULT 0      -- max confidence of any link into this fp
);
```

### 4.2 New table: `device_aliases` (the many-MACs-to-one-fingerprint map)

```sql
CREATE TABLE IF NOT EXISTS device_aliases (
    mac             TEXT PRIMARY KEY,   -- a MAC or mdns: pseudo-key
    fingerprint_id  TEXT NOT NULL,      -- which physical device this is
    source          TEXT,               -- ble / bt / mdns / wifi
    first_seen      REAL,
    last_seen       REAL,
    sighting_count  INTEGER DEFAULT 0,
    link_confidence REAL,               -- confidence of the link that put this MAC here
    link_method     TEXT,               -- 'continuity' / 'cross-radio' / 'rotation' / 'direct'
    FOREIGN KEY (fingerprint_id) REFERENCES device_fingerprints(fingerprint_id)
);
CREATE INDEX IF NOT EXISTS idx_aliases_fp ON device_fingerprints(fingerprint_id);
```

This is the core of the design: **`device_aliases` maps many MACs → one
`fingerprint_id`**. Every query that today groups by `mac` instead groups
by `fingerprint_id` (via a join to `device_aliases`). One physical phone with
4 rotated MACs is 4 rows in `device_aliases` and 1 row in
`device_fingerprints`.

### 4.3 Column on `devices`

```sql
ALTER TABLE devices ADD COLUMN fingerprint_id TEXT;
```

Optional denormalization for fast single-row lookup. `device_aliases` is the
source of truth; this column is a cache. If you'd rather avoid the ALTER,
skip it and always join through `device_aliases` — the index above makes
that cheap.

### 4.4 Backfill

Existing data is backfilled by replaying the linking passes over all
historical sightings:

1. For every `mac` in `devices`, compute its fingerprint tuple from its
   sightings (most common service set, Apple continuity tag, name).
2. Run Pass A (continuity), then Pass B (cross-radio), then Pass C (rotation)
   to cluster MACs into `fingerprint_id`s.
3. Insert one `device_fingerprints` row per cluster, one `device_aliases`
   row per member MAC.

This is a one-shot migration script (a new `refingerprint.py`, sibling to
the existing `reclassify.py`). It must be idempotent and re-runnable as the
linking heuristics improve. Run it once on deploy, and on every collector run
thereafter the linking is incremental (only new sightings).

### 4.5 Query migration

Every API/dashboard query that does `SELECT ... FROM devices GROUP BY mac`
becomes `... JOIN device_aliases a ON a.mac = d.mac GROUP BY a.fingerprint_id`.
The hourly rollup (`sightings_hourly`) keeps keying by `mac` — it's the raw
rhythm signal — and is aggregated up to `fingerprint_id` at query time.

---

## 5. Trade-offs and limits

**Be honest: MAC randomization is *designed* to defeat this.** What's
achievable, in order of certainty:

- **Cross-radio linking (Pass B): high success, low risk.** A speaker that
  advertises on BLE and mDNS with the same serial is trivially one device.
  This is a pure win — 3 rows → 1, no false positives. ~12 mDNS devices
  today, each likely collapsing with a BLE row.
- **Apple Continuity linking (Pass A): high success for Nearby Info, medium
  for AirPods.** The auth tag is a real stable device ID. AirPods model+color
  identifies a *model*, not a *unit* — two people with the same AirPods model
  are indistinguishable. Accept the coarseness; label it "AirPods Pro 2
  (unit unknown)".
- **MAC-rotation clustering (Pass C): medium success, the main dedup win.**
  Works when a phone advertises a stable service set and is seen across a
  rotation. Fails when the phone leaves and a *different* phone of the same
  class arrives in the window — a false link. The time window and the
  service-set exactness are the two knobs. Expect to collapse the 314
  re-sighted phone-anons into roughly the true phone count (5–20), with some
  over-merging and some un-mergeable singletons (the 134 single-sighting
  phone-anons are lost — no rotation observed).

**What's not achievable:**
- **Find My / AirTag tracking** — the pubkey rotates every 15 min and is
  cryptographically unlinkable. By design. Do not try.
- **Phones that go silent** — a phone seen once then never again is one
  sighting, no rotation to link. 303 devices (29%) are in this bucket.
  They're noise; prune them from the "active devices" count but keep them in
  raw history.
- **WiFi probe-request fingerprinting** — the scanner only captures WiFi
  *APs*, not client probe-requests. The IE-fingerprinting literature (stable
  Information Elements per device) requires monitor mode and a different
  capture path. It's a future avenue (§6), not something the current scanner
  can do.

**Privacy / ethics.** This is passive scanning for footfall analytics (the
B2B mall use case: count people, not identify them). The fingerprint is
designed to count *devices*, not *people* — it deliberately does not recover
a person's identity, only a stable device token. Two practices keep this
honest:
- **Do not persist the Apple auth tag in the clear beyond the linking pass.**
  Hash it (with a per-deployment salt) before storing in `device_fingerprints`.
  The tag is only needed to link; once linked, a salted hash is enough.
- **The fingerprint_id is a random uuid4, not derived from any PII.** It's a
  synthetic stable handle, not an identifier of a person. A phone that leaves
  and returns a week later gets a *new* fingerprint_id (the rotation window
  has long expired) — we do not re-identify individuals across visits.

This matches the stated use case: footfall (how many devices, how long they
stay, the rhythm of the neighborhood), not tracking a specific person.

---

## 6. Phased plan

Ordered by dedup win per unit of effort. Build the highest-leverage, lowest-
risk pass first.

### Phase 1 — Cross-radio linking (Pass B). *Biggest win, lowest risk.*
- Add `device_fingerprints` + `device_aliases` tables (`db.py`).
- Link mDNS rows to BLE rows by hostname-serial / model match.
- Link BLE to WiFi AP by OUI + name similarity (the ~27 stable-OUI devices).
- Replaces the `mdns:` string-key hack at `collector.py:232` with a real
  `fingerprint_id`.
- **Effect:** collapses each multi-radio device from 2–3 rows to 1. Small
  absolute count (a dozen devices) but it's the foundation — the
  `fingerprint_id` abstraction has to exist before the harder passes.
- **Effort:** small. Schema + one linking function + backfill script.

### Phase 2 — MAC-rotation clustering (Pass C). *The big dedup.*
- Cluster the 448 `phone-anon` (and other random-MAC) devices by
  (device_class + service_set + name_pattern) within `ROTATION_WINDOW_S`.
- Collapse 314 re-sighted random MACs into ~5–20 physical devices.
- **Effect:** cuts the device count by ~30% (448 → ~20–40). This is the
  single largest dedup in the system.
- **Effort:** medium. The clustering logic + tuning the window from real
  data. Start conservative (10 min, exact service-set match) and loosen
  only if the data shows under-merging.

### Phase 3 — Apple Continuity linking (Pass A). *Targeted, high-precision.*
- Link by Nearby Info auth tag (0.95 confidence) and AirPods model+color.
- Hash the auth tag before storing (privacy, §5).
- **Effect:** small absolute count (5 sightings today) but high-precision and
  growing with Apple density. Also gives a clean label ("AirPods Pro 2")
  to otherwise-anonymous Apple BLE rows.
- **Effort:** small. Decoder already exists (`apple_continuity.py`); just
  wire the tag into the fingerprint tuple.

### Phase 4 (future, not in scope) — WiFi probe-request fingerprinting.
- Would require monitor-mode capture (not `iw dev scan`) and IE parsing.
- The literature (probe-request IE fingerprinting) shows stable per-device
  signatures in the Information Elements even as MAC rotates. This is the
  next frontier if the BLE-side clustering proves insufficient, but it's a
  different capture pipeline, not a change to the current scanner.

### What to build first
**Phase 1 + Phase 2 together** deliver ~all the achievable dedup. Phase 3 is
a cheap add-on once the fingerprint table exists. Phase 4 is explicitly
deferred.

---

## 7. Open questions

- **`ROTATION_WINDOW_S` value.** Start at 600s (10 min, ~2 scan intervals).
  Needs tuning against real rotation data — log (old_mac.last_seen,
  new_mac.first_seen, matched signature) pairs for a week, then set the
  window at the 95th percentile of observed gaps.
- **Service-set stability.** Do phones really keep a stable service-UUID set
  across rotations? The data shows 64 sightings of `0000fcf1` (Google
  Nearby) and 46 of `0000fcb2` (Apple Continuity) — these look stable per
  device, but verify by checking whether the same *rotated* MAC reappears
  with the same set. A quick analysis script over `sightings` can answer
  this before building Phase 2.
- **Over-merge risk in Phase 2.** Two identical phones (same model, same
  service set) arriving minutes apart would wrongly merge. The Apple auth
  tag disambiguates Apple devices; Android devices without a stable tag are
  at risk. Acceptable for footfall (we're counting, not identifying), but
  flag it in the dashboard confidence field.

---

## References

- Apple Continuity wire format: [furiousMAC/continuity](https://github.com/furiousMAC/continuity)
  — TLV docs, including the Nearby Info auth tag and AirPods model/color.
- "Discontinued Privacy" — Celosia & Cunche — the academic work on tracking
  Apple devices via Continuity despite MAC randomization (the basis for the
  auth-tag-as-stable-ID claim).
- `ble_monitor` ([custom-components/ble_monitor](https://github.com/custom-components/ble_monitor))
  — Home Assistant BLE integration; confirms the industry baseline is "track
  by static MAC or UUID," i.e. it does *not* solve rotation. Our Pass C is
  beyond the state of the common open-source tooling.
- IEEE OUI list (`oui.py`) — does not cover locally-administered MACs; OUI
  is only useful for the ~27 stable-OUI devices in the current data.
