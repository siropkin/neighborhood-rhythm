# Fingerprinting — data validation (2026-08-15)

Fact-check of `docs/FINGERPRINTING.md` against the live Pi DB (1049 devices,
3531 sightings). What held, what didn't, and what it changes.

## Confirmed

| doc claim | validated | actual |
|---|---|---|
| 48% random-MAC devices | ✓ | 508/1049 (48%) |
| phone-anon is the biggest bucket | ✓ | 457 devices |
| phone-anon re-sighted (linkable) | ✓ | 327 (doc said 314; data grew) |
| single-sighting devices ~29% | ✓ | 303 (28%) |
| 12 mDNS pseudo-mac devices | ✓ exact | 12 |
| ~27 stable-MAC devices with OUI | ✓ exact | 27 |
| OUI meaningless for random MACs | ✓ | 0 random-MAC devices have OUI |
| service-UUID set stable per MAC | ✓ | 503/508 (99%) same set across sightings |

## Wrong — changes the plan

### 1. Apple Continuity is 100× bigger than the doc claimed
Doc: "5 Apple-continuity sightings." **Actual: 593 sightings** with Apple data
(345 device+status, 222 nearby, 26 AirPods). 116 of the 461 empty-set random
MACs are Apple devices broadcasting Continuity — they're not undifferentiated
noise, they're Apple devices we can decode. **Apple linking (Phase 3) is a
primary signal, not a small add-on.**

### 2. The Nearby Info auth tag is NOT being decoded
Doc Phase 3 premise: link by the stable 3-byte auth tag. **Actual:**
`decode_nearby_info` only reads `action_code` (offset 1 in our payload). The
auth tag (furiousMAC docs: offsets 16–18 of the 0x10 payload) is not extracted.
And the raw manufacturer_data hex is not stored in sightings — only decoded
extra — so the tag **cannot be backfilled**. Fixing the decoder is a
prerequisite, and it only helps future scans.

### 3. The service-UUID set is a CLASS signal, not a DEVICE signal
Doc Phase 2 premise: cluster random MACs by service set. **Actual:** 456/508
random MACs advertise **no service UUIDs at all** (empty set). The 47 that do
cluster into just 6 sets — but a shared set (e.g. 20 MACs with `0000fcf1`)
are **different devices seen simultaneously** (same timestamps), not one
rotating phone. **Clustering by service set alone would massively over-merge.**
The service set is a device-CLASS fingerprint, not a device-UNIT fingerprint.

### 4. AirPods model+color is mostly but not perfectly stable
8/11 AirPods MACs show a stable model+color; 2 show different model codes
across sightings. And the model codes in the data (`0x899D`, `0xBF23`...)
don't match the `AIRPODS_MODELS` dict — they decode as "unknown AirPods/Beats".
The model table is stale / missing newer models.

## What this changes

- **Phase 1 (cross-radio linking): unchanged.** Still a pure win, low risk.
  mDNS hostnames with serials + same-host multi-service rows (Anastasiias-MacBook
  appears as _raop AND _airplay = 2 rows → 1).
- **Phase 2 (rotation clustering): needs the time-adjacency guard.** Service
  set alone over-merges. Must require: same set AND **sequential** (old MAC's
  last_seen < new MAC's first_seen, within window) AND old MAC not seen again
  after new appears. Simultaneous sightings = different devices. Even so, the
  456 empty-set MACs have no service set to cluster on — they need the Apple
  tag (Phase 3) or stay un-mergeable.
- **Phase 3 (Apple linking): move up, but fix the decoder first.** Extract the
  auth tag (offsets 16–18) and store the raw manufacturer_data hex so it's
  backfillable. This is the only path to linking the 116 Apple empty-set MACs.
- **AirPods model table:** refresh `AIRPODS_MODELS` from the current
  furiousMAC list; the observed codes aren't in it.

## What stays un-mergeable (honest)
- 303 single-sighting devices (no rotation observed).
- 456 empty-set random MACs that aren't Apple (no service set, no Continuity).
  They're irreducible noise — count them in footfall, don't pretend to link them.
