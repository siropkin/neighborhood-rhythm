# Neighborhood Rhythm vs. the Verkada Ecosystem

**Where a passive BLE/WiFi/mDNS Raspberry Pi scanner fits, competes, or integrates
inside Verkada's cloud-managed building security platform.**

Research date: August 2026 (verified against live verkada.com / apidocs.verkada.com
pages in this session). Sources: verkada.com product pages, the SV20 Series
Applications Guide PDF (docs.verkada.com), apidocs.verkada.com (full API index via
llms.txt), and the Verkada integrations/partners pages. All claims below are tied
to a specific source.

---

## TL;DR

Verkada does **not** do BLE, WiFi, or RF device detection. Their environmental
sensor (the SV20 series) measures air quality, temperature, humidity, motion
(PIR), noise, vape, PM2.5, TVOC, CO2, CO, and formaldehyde — **up to 21
environmental readings on the SV25, zero radio-device readings on any model**.
Their occupancy and people-counting signal comes entirely from **cameras**
(computer-vision "Operational Analytics" — Occupancy Trends, Queue Trends,
People Heatmaps — with people/vehicle counts), not from RF.

Neighborhood Rhythm does the one thing Verkada's entire product line does not:
**passively detect and classify the radio devices (phones, speakers, TVs, lights,
beacons, sensors) in a space, without a camera.** It is a complement, not a
competitor. The honest caveat: it counts *devices*, not *people* — a person with
phone + laptop + watch is 3 devices; a visitor with no phone is 0. Verkada's
cameras count people directly. The two signals are different and, in a
privacy-sensitive deployment, the device signal is the one you can use where
cameras are politically or legally impossible.

---

## 1. Verkada product lineup

Verkada sells cloud-managed building security and IT hardware across seven
product lines (six device lines plus a connectivity/gateway line). Every device
is PoE-powered, cloud-managed from their "Command" platform, and sold on a
hardware-plus-license model. Source: verkada.com/products,
verkada.com/security-cameras/, and per-series product pages.

### Cameras (Video Security)

Seven camera form factors. All do edge-based AI processing (people/vehicle
analytics, face search, line crossing, motion, tamper detection). Onboard
retention 30–365 days. Source: verkada.com/security-cameras/ and per-series pages.

| Series | Models | Resolution | Notes |
|---|---|---|---|
| Dome | CD22, CD22-E, CD32, CD32-E, CD43, CD43-E, CD53, CD53-E, CD63, CD63-E | 3MP–4K | Indoor/outdoor; `-E` = outdoor. 10-yr warranty (gen3), 5-yr (gen2). |
| Bullet | CB53-E, CB63-E, CB53-TE, CB63-TE | 5MP–4K | LPR-capable (plates at up to 80 mph / 128 kph, 3 lanes). `-TE` = telephoto. |
| Mini | CM22, CM41-E, CM42, CM42-S | 3MP–5MP | Discreet; CM42-S is a "split" form. |
| Fisheye | CF83-E | 12.5MP | 180° monitoring. |
| Multisensor | CH52-E, CH53-E, CH63-E (4-sensor); CY53-E, CY63-E (2-sensor) | 5MP–4K per sensor | Independently positionable sensors. |
| PTZ | CP52-E, CP63-E | 5MP–4K | 28x–32x optical zoom, 360° pan / 220° tilt. |
| Remote | CR63-E | 4K | Built-in LTE + battery; solar or hardwired. |

**Camera analytics (the occupancy signal):** "Operational Analytics" — four
edge-based computer-vision features (source: Operational Analytics Overview,
docs.verkada.com):
1. **Occupancy Trends** — counts people/vehicles entering/exiting a region;
   pairs with PoS data for sales conversion rates.
2. **Queue Trends** — measures people/vehicles in a defined queue area + wait times.
3. **People Heatmaps** — visualizes movement history on floor plans with
   color-coded contours.
4. **Helix** — pairs third-party events (PoS, ERP) with video footage.

Also: AI-powered people/vehicle search, face search, reverse image search,
"persons of interest," and a "unified timeline" that reconstructs the journey of
people/vehicles across a property. Processing is **edge-based** ("onboard
processing supports near real-time analytics at the edge"). There is **no
dedicated occupancy hardware product** — occupancy is a camera software feature
included with the camera cloud license. Source: verkada.com/security-cameras/
and docs.verkada.com/docs/operational-analytics-overview.pdf.

### Access Control

| Category | Models | Notes |
|---|---|---|
| Controllers | AC12 (1 door), AC43 (4 door), AC62 (16 door), AX11 (IO + elevator) | PoE; 10-yr warranty. AC62 is 16-door. |
| Door readers | AD34, AD64, AF64 (Access Station Pro) | AD34/AD64 use OSDP v2 + Bluetooth Intent Unlock. AF64 adds a camera + 3D time-of-flight sensor for Face Unlock. |
| Credentials | Apple Wallet NFC, DESFire EV3 NFC cards, Bluetooth, PIN, face, LPR | "Customizable Bluetooth" and mobile NFC in Apple Wallet. |
| Wireless locks | AL54-CY (cylindrical, $1,399), AL54-MS (mortise, $1,799, coming soon) | VLink wireless to hub, up to 16 locks within ~150 ft. |
| Third-party lock integrations | ASSA ABLOY, Schlage, Simons Voss | Via Verkada Command. |
| Access Station Pro | AF64 | Built-in camera + ToF sensor + Face Unlock. |

Verkada claims "#1 in cloud access control" (2024 Omdia market share for
cloud-native access control). Source: verkada.com/access-control/ and
/access-control/access-controllers/, /door-readers/.

**Note on Bluetooth here:** Verkada's access readers *use* Bluetooth (BLE) and
NFC as **credential transport** — a phone presents a credential over BLE to
unlock a door. This is not device *detection or scanning*. The reader does not
inventory BLE devices in the space; it only listens for a credential
presentation from an enrolled phone. This is a critical distinction for the
Neighborhood Rhythm comparison (see §3).

### Alarms

Intrusion system natively integrated with cameras and access. AI-powered camera
triggers (people, loitering, line-crossing) turn existing cameras into alarm
sensors. Badge-to-arm/disarm replaces key codes. Video-verified sensors pair an
alarm sensor with a context camera. Source: verkada.com/alarms/ and pricing page.

| Component | Models | Price (MSRP) |
|---|---|---|
| Panels | BP2 (wireless, $799), BP52 (wired, $899) | — |
| Keypad | BK22 | $399 |
| Expander | BE32 | $349 |
| Horn speaker | BZ11 (115 dB, talk-down, PoE+) | $799 |
| Siren strobe | BZ32 (105 dB, wired/wireless, VLink sub-GHz) | $299 |
| Wired sensors | BR11 (motion), BR12 (contacts), BR13 (recessed contacts) | $99 each |
| Wireless sensors | QC11-W (door/window), QM11-W (wall motion), QT11-W (universal), BR33 (panic), BR35 (water leak) | $99–$159 |
| Wireless infra | WH52 (hub, $599), WH32 (repeater, $299) | — |

### Intercom

| Model | Type | Price (MSRP) | Notes |
|---|---|---|---|
| TD33 | Video intercom | $1,699 | Camera + access controller + door reader in one. |
| TD53 | Video intercom | $1,999 | — |
| TD63 | Video intercom + keypad | $2,199 | Adds keypad / MFA. |
| TS12-N | Audio-only | $1,199 | For noisy environments. |

AI capabilities: live translation, voice directory / call routing. Source:
verkada.com/intercom/ and pricing page.

### Connectivity (Gateways)

Deploy Verkada devices where there is no wired network. Source:
verkada.com/connectivity/ and pricing page.

| Model | Type | Price |
|---|---|---|
| GC31 | Indoor cellular gateway | $999 |
| GC31-E | Outdoor cellular gateway | $1,599 |
| GW31-E | Outdoor Wi-Fi 6 gateway | $999 |
| MT81 | Cloud-managed security trailer | $58,000–$65,000 |

Note: the GW31-E is a Wi-Fi 6 access point/client for device uplink — it does
**not** detect or scan WiFi devices. Its only Bluetooth use is a local
management interface via the Command iOS app.

### Air Quality Sensors (SV20 series) — the product most often confused with a "sensor that detects devices"

Three models, all PoE, all cloud-managed, same form factor (6.96 × 6.67 × 1.8
in, ~500–568 g, 4 W, 5-second sampling, 10-year warranty). This is the critical
product for the Neighborhood Rhythm comparison, so it gets the full treatment.

**Per-model reading counts:** SV21 = 8 readings, SV23 = 16, SV25 = 21. All
environmental. Source: SV21/SV23/SV25 datasheets (docs.verkada.com), the SV20
Series Applications Guide PDF, and the /air-quality/sensors/ product page.

| Reading | SV21 | SV23 | SV25 |
|---|---|---|---|
| Temperature | yes | yes | yes |
| Humidity | yes | yes | yes |
| Heat Index | yes | yes | yes |
| Humidex | yes | yes | yes |
| Dew Point | yes | yes | yes |
| Mold Risk Index | yes | yes | yes |
| Tamper | yes | yes | yes |
| Carbon Dioxide (CO2) | yes | yes | yes |
| Noise | — | yes | yes |
| Motion (PIR) | — | yes | yes |
| Vape Index | — | yes | yes |
| PM 2.5 / 4.0 / 10.0 | — | yes | yes |
| TVOC | — | yes | yes |
| Air Quality Index | — | yes | yes |
| RESET Viral Index | — | yes | yes |
| Ambient Light | — | — | yes |
| Barometric Pressure | — | — | yes |
| Audio Recording | — | — | yes |
| Formaldehyde | — | — | yes |
| Carbon Monoxide (CO) | — | — | yes |

The SV21 is marketed as a "CO2 Monitor" ($699 hardware). The SV23 adds
air-quality + motion + noise + vape ($999). The SV25 is the full kit — adds
light, pressure, audio recording, formaldehyde, CO ($1,299; SV25-128 variant
$1,449). Source: verkada.com/air-quality/sensors/, the SV20 Series Applications
Guide PDF, and the per-model datasheets.

**What the SV20 series does NOT detect (the key finding):**
- **No BLE / Bluetooth device scanning or detection.**
- **No WiFi device detection or WiFi sensing.**
- **No mDNS / network device discovery.**
- **No RF-based presence detection.**
- **No device classification (phone / speaker / TV / light / sensor).**
- **No people counting.** The "motion" reading is a PIR occupancy *hint*
  (motion = someone is probably there), not a count. The PDF's only
  "occupancy" reference is a "User Guide for Occupancy Trends" pointer —
  which is the **camera** feature, not the sensor's.

Confirmed from the primary source: the SV20 Applications Guide PDF describes the
device as one that "simultaneously measures air quality, temperature, humidity,
motion, noise and more" — 14 readings, all environmental. The word "Bluetooth"
does not appear in the sensor spec. The only BLE on Verkada's entire site is in
*access control readers* (credential transport), not sensing.

### Workplace (Guest, Mailroom, Incident Response)

- **Guest** — visitor management: check-in flows, security screens, temporary
  credentials. Source: verkada.com/workplace/.
- **Mailroom** — package/delivery tracking.
- **Incident Response** — crisis/reunification protocols using Guest personnel
  data.

### Pricing model

Hardware-plus-license (source: verkada.com/pricing/ and per-model datasheets at
docs.verkada.com). Hardware is a one-time MSRP purchase; a recurring cloud
license is required for most devices (cameras, sensors, intercoms, controllers).
The license includes OTA firmware/security updates, 24/7 support, unlimited
users, and new features during the term.

**Per-device license tiers (same for new capacity and renewals):**

| License | 1-year | 3-year | 5-year | 10-year |
|---|---|---|---|---|
| Camera (LIC-CAM) | $249 | $659 | $1,099 | $2,199 |
| Air Quality Sensor (LIC-SV) | $249 | $599 | $999 | $1,999 |

**Site/other licenses:** Basic Alarms $600/year per site; Video Alarms
$1,500/year (stackable in packs of 15 cameras); Workplace Standard $3,600/year
(K-12 $1,500/year, government $5,400/year); Data license $599/year per cellular
device.

**Hardware price ranges (MSRP):** Cameras $699 (CM22) to $5,299 (CP63-E PTZ);
Sensors $699 (SV21) / $999 (SV23) / $1,299 (SV25); Controllers $899 (AC12) to
$5,999 (AC62); Door readers $349 (AD34) / $599 (AD64) / $1,999 (AF64);
Intercoms $1,199 (TS12) to $2,199 (TD63); Gateways $999 (GC31) to $65,000 (MT81
trailer).

**License-free hardware:** Door readers (AD34, AD64), wireless locks, alarm
panels/sensors, and credentials are hardware-only — no license required.

The recurring license is effectively mandatory for cameras, controllers, and
sensors to function in Command. Third-party reference: SoftwareAdvice lists a
$199/year starting price; reviews note Verkada "can be expensive compared to
traditional security systems, especially when scaling."

### Target market

Commercial buildings, schools (K-12 and higher ed), retail, healthcare
(Yakima Valley Memorial Hospital is a named sensor customer), manufacturing
(Carolina Ingredients), cold storage / logistics (Canada Goose, Dairy Farmers of
America), and government (separate "government-grade" product lines exist for
cameras, access control, and readers). Source: customer quotes across
verkada.com product pages.

---

## 2. Does Verkada do BLE / WiFi / device detection? (the key question)

**No. Definitively, no.**

This was checked against three primary sources:

1. **verkada.com/air-quality/sensors/** — the SV21/SV23/SV25 spec page lists
   every reading the sensor takes. BLE, Bluetooth, WiFi, wireless device
   detection, beacons, and device classification are **not listed on any model**.
2. **SV20 Series Applications Guide PDF + per-model datasheets (docs.verkada.com)**
   — the full user guide describes "14 sensor readings" (the marketing line; the
   datasheets show 8/16/21 per model), all environmental (air quality, temp,
   humidity, motion, noise, vape, PM, TVOC, CO2, CO, formaldehyde, pressure,
   light, audio). The words "Bluetooth" and "WiFi device detection" do not
   appear. The only "wireless" context is the device's own network connection.
3. **apidocs.verkada.com** — the Sensors API exposes "sensor alerts (with
   thresholds) and sensor readings over time ranges." The readings are the
   environmental values. There is no endpoint for BLE/WiFi device data because
   the hardware does not produce it.

**The only BLE in Verkada's ecosystem is credential transport.** The AD34/AD64
door readers support "Bluetooth Intent Unlock" — an enrolled phone presents a
credential over BLE to unlock a door. This is a *reader listening for one
enrolled credential*, not a *scanner inventorying all BLE devices in range*. It
cannot tell you that a TV, a speaker, or an unknown phone is present. It does
not classify devices. It does not estimate distance. It does not track
comings and goings.

**Where Verkada's occupancy signal comes from:** cameras. The "Operational
Analytics" feature uses computer vision on-camera (edge) to produce occupancy
trends, people/vehicle counts, wait times, and movement patterns. The API
exposes "occupancy trend cameras" and "people/vehicle counts" under
Alerts & Analytics. There is no non-camera occupancy product. The SV20's PIR
"motion" reading is a binary presence hint, not a count, and not positioned as an
occupancy product.

**The gap:** Verkada has no passive, camera-free, RF-based device-presence
signal. If you cannot put a camera in a space (privacy, policy, union, GDPR,
school classroom, bathroom-adjacent, healthcare HIPAA zone), Verkada's only
presence signal is the PIR motion bit on an SV23/SV25 — which says "something
moved," not "what is here," not "how many devices," not "what type."

---

## 3. Where Neighborhood Rhythm fits: complement vs. compete vs. integrate

### It complements, it does not compete.

| Dimension | Verkada | Neighborhood Rhythm |
|---|---|---|
| Presence signal | Camera vision (counts people, sees faces) | RF device detection (counts devices, no faces) |
| Privacy | Camera — captures faces, requires blurring controls, politically sensitive | No camera, no faces, counts devices not people |
| What it detects | People, vehicles, license plates, faces (cameras); air quality + PIR motion (sensors) | Phones, speakers, TVs, lights, beacons, BLE sensors (by RF + mDNS) |
| Device classification | None (cameras classify people/vehicles, not devices) | Rules-based: mDNS model > name > service UUID > OUI > random-MAC |
| Distance / location | Camera FOV (where in frame); no RF distance | RSSI → distance rings (1 Pi); trilateration (3+ Pis) |
| Cost per unit | Camera $699–$5,299 hardware + $249/yr license; sensor $699–$1,299 + $249/yr license | ~$45 BOM (Pi + case + power), no license |
| Deployment friction | PoE cabling, professional install, cloud license provisioning | Boot a Pi, join WiFi, done |
| Where it can't go | Bathrooms, locker rooms, healthcare zones, union floors, private offices, schools under parent pushback | Anywhere a Pi can boot (still needs power + WiFi) |
| What it can't do | RF device inventory, rogue-device detection, device-type classification, camera-free occupancy | See faces, read license plates, verify identity, access control, air quality |

**The non-overlap is the point.** Verkada's cameras and Neighborhood Rhythm's
scanner answer *different questions*:

- Verkada camera: "How many people are in frame, and who are they?"
- Neighborhood Rhythm: "How many devices are in RF range, what type are they,
  and what is the rhythm of them arriving and leaving?"

A person with a phone, a laptop, and a smartwatch is **1 person** to Verkada's
camera and **3 devices** to Neighborhood Rhythm. A visitor with no phone is
**1 person** to the camera and **0 devices** to the scanner. Neither is wrong;
they are different signals. The device signal is a proxy for *activity density*
and *device inventory*; the camera signal is a proxy for *headcount and identity*.

### Where it would compete (be honest)

There is a narrow overlap: **occupancy / footfall counting.** If a customer's
only goal is "how many people are in this space," Verkada's camera-based
occupancy trends and Neighborhood Rhythm's device counts both produce a number.
In that narrow case, Neighborhood Rhythm is a cheaper, privacy-friendlier, less
accurate substitute. But it is a *substitute for the occupancy feature only*, not
for the camera — the camera also does face search, LPR, investigations, evidence,
and identity, none of which a Pi scanner can touch. So even in the overlap, it
substitutes for one feature, not the product.

The B2B-USE-CASES.md doc already makes this point for the broader market: the
smart-building occupancy players (Density, $229/sensor + $2.50–15/sensor/month)
built their brand on "no camera, no PII." Neighborhood Rhythm undercuts on
hardware cost with a comparable privacy story, with the honest trade-off that it
counts devices, not people. Verkada is not in that "camera-free privacy
occupancy" niche — their occupancy is camera-based — so Neighborhood Rhythm is
not taking a Verkada sale, it is taking a *non-Verkada* sale (the customer who
refused cameras).

### Where it is strictly additive

Two things Neighborhood Rhythm does that **no Verkada product does at all**:

1. **IoT / rogue device inventory.** A Pi passively inventories every BLE/WiFi/
   mDNS device in a building and classifies it (phone / speaker / TV / light /
   sensor). Verkada has no product that does this. Their access control knows
   about *enrolled* credentials; it does not discover *unknown* devices. The
   enterprise IoT-security players (Armis, Claroty, Nozomi Guardian Air) do this
   at enterprise pricing ($25k+ minimums). A $45 Pi is a cheap
   rogue-device-detection and asset-inventory sensor for the commercial-building
   tier that Verkada sells into. This is the cleanest complement: a Verkada
   customer adds Pis to get a device inventory Verkada cannot give them.

2. **Camera-free presence in spaces where cameras are blocked.** Bathrooms,
   locker rooms, healthcare zones, union floors, private offices, K-12
   classrooms under parent opt-out. Verkada's only presence signal there is the
   SV23/SV25 PIR motion bit. Neighborhood Rhythm gives device-class density and
   rhythm in those same spaces. Again, additive — it goes where the cameras
   cannot.

---

## 4. The honest positioning

**What Neighborhood Rhythm does that Verkada does not:**
- Passive BLE/WiFi/mDNS device detection and classification. (Verkada: nothing.)
- RF-based distance estimation and multi-sensor trilateration. (Verkada: camera
  FOV only, no RF distance.)
- Device inventory / rogue-device detection. (Verkada: only enrolled access
  credentials, not unenrolled devices.)
- Camera-free occupancy/activity signal. (Verkada: PIR motion bit only.)
- ~$45 BOM, no cloud license, self-hosted. (Verkada: hardware + annual license,
  cloud-only.)
- Decodes Apple Continuity (AirPods, AirTag, Find My, iBeacon), BTHome,
  RuuviTag, Govee, mDNS models — passively, no connections. (Verkada: does not
  decode any BLE payloads; its readers only read enrolled credentials.)

**What Verkada does that Neighborhood Rhythm cannot:**
- Visual verification, face search, identity, LPR, evidence-grade video. (A Pi
  scanner has no camera and no vision.)
- Access control (unlock doors, manage credentials, tailgating alerts). (A Pi
  scanner cannot actuate anything.)
- Air-quality / environmental monitoring (CO2, VOC, vape, PM2.5, temp,
  humidity, CO, formaldehyde). (A Pi scanner has no environmental sensors —
  unless you add them, which the BTHome/RuuviTag/Govee decoding partially
  enables for *separate* BLE sensors, not the Pi itself.)
- Professional monitoring, alarms, intercom, visitor management, mailroom.
- A single integrated cloud platform across all of the above. (Neighborhood
  Rhythm is a standalone dashboard; integration is DIY — see §5.)
- 10-year hardware warranty, 24/7 support, enterprise SLA. (A Pi has neither.)

**The fundamental trade-off, stated plainly:** Neighborhood Rhythm counts
*devices*, not *people*. A person with phone + laptop + watch is 3 devices; a
visitor with no phone is 0 devices. MAC randomization means a phone's BLE MAC
rotates every ~15 min, so you cannot reliably track a specific person across
rotations passively (by design — this is a privacy feature, not a bug). ~80% of
devices (speakers, TVs, lights, beacons, fixed sensors) have stable MACs and
track fine. For *traffic density and rhythm* (the footfall/occupancy use case),
this is sufficient — you do not need to identify individuals, you need to
count the flow. For *headcount*, it is a proxy with a known error band, not a
ground truth. Verkada's cameras give ground-truth headcount (with faces). The
scanner gives device-density (without faces). Choose the signal that matches
the use case and the privacy constraint.

---

## 5. Integration path: piping Neighborhood Rhythm data into a Verkada-style platform

Verkada's platform is more open than its "closed cloud" reputation suggests.
Three integration paths exist (source: verkada.com/integrations/ and
apidocs.verkada.com):

### Path A — Helix (the intended third-party-event ingest)

Verkada Helix is explicitly built to "ingest data from third-party systems and
pair it with Verkada camera footage." You create custom event types, push events
with timestamps, and they appear on the Verkada timeline alongside camera
footage, with real-time alerts and trend dashboards.

**How Neighborhood Rhythm would use it:** the Pi's collector already writes
sightings to SQLite with timestamps and device classifications. A small
exporter would read new sightings and push them to Helix as custom events:
`device_seen` (mac, device_type, rssi, distance, sensor_id, ts). On the Verkada
side, each event lands on the unified timeline next to camera footage from the
nearest camera. A "phone cluster appeared in the back office at 2am" event
sits next to the camera clip from 2am — context the scanner cannot provide
alone and the camera cannot provide without the scanner's trigger.

This is the cleanest path. Helix is the product Verkada built for exactly this:
third-party event data correlated with video. The API supports full CRUD for
Helix Events and Event Types, plus batch event creation (apidocs.verkada.com,
Helix section).

### Path B — Verkada public API (webhooks + unified events)

The public REST API (apidocs.verkada.com, JSON responses, 30-minute auth tokens)
exposes:
- **Webhooks** for LPR, Access Events, New Alarms, Access Credential, and
  Event-Based triggers — Verkada *pushes* these out.
- **Unified Events (v2)** endpoint — consolidated events from cameras, access
  control, and sensors, filterable by product type / device / event type / time
  / site. This is the read side.
- **Alerts & Analytics** — people/vehicle counts, occupancy trends, dashboard
  widget trends, and **MQTT config for object position events**.
- **Sensors** — sensor alerts (with thresholds) and sensor readings over time
  ranges.

**How Neighborhood Rhythm would use it:** the read side (Unified Events, Alerts,
Sensors) lets a Pi-side dashboard pull Verkada context *into* the Neighborhood
Rhythm radar — e.g., overlay Verkada camera occupancy counts next to the
scanner's device counts on the same timeline. The write side is narrower:
Verkada's API does not expose a generic "ingest arbitrary sensor reading"
endpoint for non-Verkada hardware. The Sensors API reads Verkada SV20 readings;
it does not accept third-party sensor data. So for *pushing* Neighborhood Rhythm
data in, Path A (Helix) is the right API, not the Sensors API.

The MQTT "object position events" channel is interesting — it suggests Verkada
can consume position events (x/y from cameras). A trilaterated Neighborhood
Rhythm position (from 3+ Pis) is structurally similar, but there is no public
indication Verkada accepts third-party MQTT position feeds. Treat this as
speculative until confirmed against the API docs.

### Path C — Pre-built integration / partner program

Verkada runs a partner program ("Interested in partnering with us to build an
integration? Apply now" at verkada.com/integrations/sign-up/) and a partner
directory at /integrations/partners/. Existing partners include Okta (SSO/SCIM),
Slack/Teams (alerting), Axon Evidence, Fusus, Singlewire, Schlage, ASSA ABLOY.

A Neighborhood Rhythm → Verkada integration would most plausibly ship as a Helix
connector (Path A) packaged for the partner directory: "BLE/WiFi device presence
events on your Verkada timeline." The partner program is the route to getting
it listed and supported rather than a customer-built script.

### SIEM / GSOC note (no native Splunk connector)

Verkada does **not** publish a native SIEM connector (no Splunk, IBM QRadar,
Datadog, Sumo Logic, or syslog endpoint in the partner directory or the public
API). The closest partners are GSOC/RTCC aggregators — **HiveWatch**, **SureView**,
**Fusus**, **Canopy** — which pull Verkada camera/access events into a unified
security console. The realistic SIEM path for a Pi sensor is therefore
**indirect**: the Pi emits events (webhook or Helix), and a SIEM or GSOC tool
that already ingests Verkada webhooks picks up the Pi's events on the same
feed. There is no "send to Splunk" button on either side; integration is via
the webhook/Unified Events surface, consumed downstream by whatever the
customer already runs.

### What an integration would NOT do

A Neighborhood Rhythm → Verkada integration does **not** make the Pi a Verkada
sensor. Verkada's Sensors API reads SV20 hardware; it does not accept
third-party environmental or RF readings. The Pi cannot appear in Verkada
Command as a first-class device. It can only appear as a **source of Helix
events** on the timeline and in alerts. The dashboard stays the Pi's own; the
Verkada side gets the events. This is a "feed into" integration, not a "become
a Verkada device" integration. That is a real limitation: a customer wanting
one pane of glass gets Verkada's glass with Neighborhood Rhythm events
overlaying, not the Pi's radar inside Command.

---

## 6. Extra sensors to add to the Pi (building-security add-ons)

The Pi is a BLE/WiFi/mDNS scanner today. If the goal is a broader
"building-security sensor," the same Pi can host cheap I2C/UART add-ons that
mirror parts of Verkada's SV20 environmental line. The table below maps each
realistic ~$5–20 sensor to what it detects and whether it overlaps Verkada.
The point is **optionality**, not parity: a $45 Pi + $30 of sensors still
undercuts a $699–$1,299 SV21/SV23/SV25 by an order of magnitude, with the
device-inventory signal Verkada lacks as the primary value.

| Sensor | Interface | Cost | Detects | Overlaps Verkada SV20? | Notes |
|---|---|---|---|---|---|
| PMS5003 (Plantower) | UART | ~$8–12 | PM1.0/2.5/10 particulate mass | Yes — SV23/SV25 PM2.5/4.0/10 | The cheap PM2.5 standard. Needs a fan; ~70 mA active. |
| SCD41 (Sensirion) | I2C | ~$15–40 | CO2 (photoacoustic), temp, humidity | Yes — all SV models CO2 | Photoacoustic, no NDIR bulb warmup. Lower accuracy than NDIR but fine for trend. |
| SGP40 (Sensirion) | I2C | ~$6–9 | TVOC (VOC index) | Yes — SV23/SV25 TVOC | Outputs a 0–500 VOC index, not raw ppm. |
| SGP41 | I2C | ~$10–14 | TVOC + NOx index | Partial — SV25 has no NOx | Adds NOx (combustion / traffic ingress). |
| SHT40 (Sensirion) | I2C | ~$2–5 | Temperature, humidity | Yes — all SV models | Cheapest accurate T/RH; use this if not using SCD41 (which also does T/RH). |
| BMP390 (Bosch) | I2C/SPI | ~$5–10 | Barometric pressure | Yes — SV25 only | Pressure trend → HVAC / door-open inference. |
| PIR (HC-SR501 / AM612) | GPIO | ~$2–4 | Motion (passive IR) | Yes — SV23/SV25 motion | Binary presence, not a count. The SV20 "motion" reading is the same signal. |
| Mic (INMP441 / SPH0645, I2S) | I2S | ~$4–8 | Noise level (dBA), optionally vape hiss | Yes — SV23/SV25 noise; SV25 audio | I2S MEMS mic; Pi has no built-in ADC. Vape detection by spectral signature is weaker than Verkada's dedicated vape index. |
| MQ-135 (cheap) / SCD41 (better) | ADC/I2C | ~$3–15 | CO2 / broad air quality | Partial — SV25 CO + formaldehyde | MQ sensors are cross-sensitive and not lab-grade; only useful for trend. |
| ZMOD4528 (Renesas, NO2/O3) | I2C | ~$15–20 | Outdoor air quality (NO2/O3) | No — not in SV20 | For perimeter / HVAC intake monitoring; not a Verkada overlap. |
| Light (TSL2591 / VEML7700) | I2C | ~$3–6 | Ambient light (lux) | Yes — SV25 only | Cheap and accurate. |
| Vape-specific: no good single IC | — | — | Vape aerosol | Yes — SV23/SV25 vape index | There is no $5 "vape sensor"; Verkada's vape index is a multi-sensor ML model (PM + VOC + humidity). A Pi approximates it poorly from PMS5003 + SGP40 + SHT40. |

**What this gets you:** a Pi that does (a) BLE/WiFi/mDNS device inventory — the
thing Verkada does not do — plus (b) a budget air-quality + presence sensor
that roughly mirrors an SV23 for ~$40–70 total BOM vs. $999 hardware + $249/yr
license. The air-quality side is strictly worse than Verkada's lab-calibrated
SV20 (no vape ML model, no formaldehyde, no CO, no RESET certification), so it
is not a drop-in SV20 replacement for a compliance-driven buyer. It is a
"good-enough environmental trend + the device signal Verkada lacks" for the
price-sensitive tier.

**What it does NOT get you:** Verkada's 10-year warranty, 24/7 support,
RESET/AIR certified readings, formaldehyde, CO, audio recording, tamper
detection as a managed feature, or the cloud dashboard. If a buyer needs
RESET-certified air quality for building codes, they buy the SV20 — the Pi is
not a substitute. The Pi's edge is the RF inventory, with environmental as a
bonus, not the reverse.

---

## 7. Bottom line

- **Verkada does not detect BLE, WiFi, or RF devices.** Their sensor is
  environmental (8–21 air-quality + climate + motion + noise readings across the
  SV21/SV23/SV25). Their occupancy signal is camera-based computer vision. Their
  only BLE use is credential transport in door readers, not scanning.
- **Neighborhood Rhythm fills a gap Verkada has no product for:** passive,
  camera-free RF device detection, classification, and inventory. It is a
  complement — an add-on sensor for a Verkada customer who needs a
  device-presence signal where cameras cannot go, or a device inventory Verkada
  cannot provide.
- **It competes only in the narrow occupancy-counting niche**, and only against
  the camera-based occupancy feature, not the camera product. Even there it is a
  cheaper, privacy-friendlier, less-accurate substitute for one feature, with a
  known trade-off (devices, not people).
- **The integration path is Helix** — push `device_seen` events from the Pi
  onto the Verkada timeline next to camera footage. The public API and partner
  program support this. The Pi cannot become a first-class Verkada device; it
  can only be a Helix event source.
- **The honest positioning:** "the device-presence sensor Verkada doesn't make"
  — a $45 Pi that counts devices (not faces), classifies them, and feeds the
  rhythm of a space into a Verkada-style platform via Helix, for the spaces and
  signals cameras cannot reach.

---

## Sources

- verkada.com/products — product line index
- verkada.com/security-cameras/ and per-series pages (dome, bullet, mini,
  fisheye, multisensor, PTZ, remote) — camera models, specs, Operational
  Analytics / occupancy trends
- verkada.com/access-control/, /access-control/access-controllers/,
  /access-control/door-readers/ — AC12/AC43/AC62/AX11, AD34/AD64/AF64,
  Bluetooth Intent Unlock, OSDP v2
- verkada.com/alarms/ — alarm components, AI camera triggers, badge-to-arm
- verkada.com/intercom/ — TD33/TD53/TD63, TS12
- verkada.com/air-quality/ and verkada.com/air-quality/sensors/ — SV21/SV23/SV25
  reading matrix; confirmed no BLE/WiFi detection
- SV20 Series Applications Guide PDF (docs.verkada.com/docs/sv20-series-applications-guide.pdf)
  — primary source: "14 sensor readings," all environmental; no Bluetooth/WiFi
  device detection; SV21 = "CO2 Monitor"
- verkada.com/workplace/ — Guest, Mailroom, Incident Response
- verkada.com pricing page — hardware-plus-license model, "Additional license
  required," no published per-device license cost
- verkada.com/integrations/ and /integrations/partners/, /integrations/sign-up/
  — Helix, public API, partner program. Partner directory confirms NO native
  SIEM connector (no Splunk/QRadar/Datadog/syslog); closest are GSOC/RTCC
  aggregators HiveWatch, SureView, Fusus, Canopy.
- apidocs.verkada.com (API docs index via llms.txt) — REST/JSON, webhooks (LPR,
  Access, Alarms, Credential, Event-Based), Helix CRUD + batch, Alerts &
  Analytics (people/vehicle counts, occupancy trends, MQTT object position),
  Sensors (alerts + readings), Unified Events v2, 30-min auth tokens. No SIEM
  endpoint in the public API.
