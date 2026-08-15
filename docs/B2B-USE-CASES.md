# Neighborhood Rhythm — B2B Use Cases

**A passive BLE / WiFi / mDNS environment scanner on a Raspberry Pi, positioned for B2B.**

This document analyzes every plausible B2B vertical where passive environment
scanning + footfall/rhythm analytics adds value. It names real competitors, real
pricing where findable, real privacy regulations, and the gaps a $35 Pi + passive
BLE could fill.

Research date: August 2026.

---

## Executive summary

The product is a passive BLE/WiFi/mDNS scanner on a Raspberry Pi. It listens to
the radio neighborhood (BLE advertisements, WiFi APs, mDNS broadcasts), classifies
every device it hears (phone / speaker / TV / light / sensor / etc.), estimates
distance from RSSI, and stores a 14-day rolling history with hourly rollups kept
forever. It is multi-Pi-ready: one Pi gives honest distance rings, two or more
give trilateration. Hardware cost is ~$35 (Pi) + ~$10 (case/power) = ~$45 BOM.

**Top 3 verticals with the clearest product-market fit:**

1. **Retail / mall footfall analytics.** The incumbents (RetailNext, ShopperTrak)
   use overhead cameras at $150–600/store/month plus $1k–3k hardware. The BLE
   beacon players (Estimote, Kontakt.io, Gimbal) have all pivoted away from retail
   footfall — to UWB asset tracking, healthcare RTLS, and ad-tech respectively.
   Passive BLE footfall via payload classification is genuinely under-served. A $45
   Pi that counts devices (not faces) is the privacy-friendly wedge. The gap: MAC
   randomization means you count *device-class traffic density*, not unique people
   — but that is exactly what footfall analytics needs.

2. **Smart building / workplace occupancy.** Privacy is the #1 adoption barrier (70%
   of organizations cite it, per JLL 2026). Density built their entire brand on
   "can't be evil" (no camera, no PII) and charges $229/sensor + $2.50–15/sensor/
   month. A $45 Pi that counts devices (not people) with no camera is a 5x hardware
   cost undercut with a comparable privacy story. The wedge: "camera-free privacy
   at WiFi-scale deployment, at a fraction of proprietary sensor cost." The honest
   limitation: it counts *devices*, not *people* — a person with phone + laptop +
   watch is 3 devices; a visitor with no phone is 0. This is a fundamental trade-off
   vs camera/thermal/radar sensors that detect human presence directly.

3. **IoT device inventory / rogue device detection.** Enterprise IoT security
   platforms (Armis, Claroty, Forescout, Nozomi) are agentless, passive, and
   sales-led at enterprise pricing (no public per-device figures; quote-based,
   $25k+ minimums). A $45 Pi that passively inventories every BLE/WiFi/mDNS device
   in a building and classifies it (phone/speaker/TV/light/sensor) is a cheap
   rogue-device-detection and asset-inventory sensor for commercial/building
   environments — not industrial OT. The closest enterprise analog is Nozomi
   Guardian Air (wireless sensor), but at enterprise pricing, not $45.

**The cross-cutting moat:** passive BLE payload classification. The competitors
who tried pure-MAC WiFi footfall are dead (Euclid, privacy-killed). The ones who
pivoted to BLE went to healthcare/asset-tracking. The technical moat is not in
capturing the MAC (worthless now — phones rotate every 15 min) but in **classifying
the advertisement payloads** (Apple Continuity, Fast Pair, BTHome, mDNS models) to
distinguish device classes and estimate traffic density without a stable ID.

---

## Per-vertical analysis

### 1. Retail / mall footfall analytics

**The problem.** Retailers and malls need to know: how many people enter, when,
how long they stay (dwell), where they go (zone/traffic), and whether they return.
This drives staffing, lease pricing (malls charge tenants by footfall), marketing
attribution, and layout optimization.

**How the product fits.** A Pi at each entrance or zone passively counts every BLE
device in range, classifies it (phone vs speaker vs wearable), and tracks the
"rhythm" of devices coming and going. With 2+ Pis, trilateration gives zone-level
positioning. The 14-day rolling history + hourly rollups (kept forever) give the
dwell and return-visit signal. No camera, no faces, no app install required.

**Competitors.**

| Vendor | How they count | Pricing | Notes |
|---|---|---|---|
| **RetailNext** (Aurora) | Stereo-video overhead sensor (dual-camera 3D depth) + WiFi probe | ~$200–600/store/mo (industry-reported) + $1k–3k hardware/sensor | Quote-based. JS-rendered site, hard to verify live. |
| **ShopperTrak** (Sensormatic/JCI) | Overhead video/thermal counters + WiFi/MAC tracking | ~$150–500/store/mo (industry-reported) + hardware | "165 billion shopper visits counted." Quote-based. |
| **Density** | Radar (Waffle sensor, no camera) | **$229/sensor + $2.50–15/sensor/mo (published)** | Pivoted from retail to workplace. The only published pricing. |
| **Placer.ai** | Phone location data (SDK partnerships, no in-store sensors) | ~$2k–10k+/yr per location (industry-reported) | No hardware. Dependent on third-party SDK data supply. |
| **Euclid Analytics** | WiFi probe-request capture | Defunct (privacy-killed, ~2016) | Philz Coffee dropped Euclid in 2014 over privacy. Acquired by Webtrends, retired. |
| **Gimbal/Infillion** | iBeacon + SDK (active, not passive) | Quote-based | Requires an app on the shopper's phone. Pivoted to ad-tech. |
| **Estimote** | BLE beacons → UWB asset tracking | $199 dev kit (3 tags) | Pivoted away from retail footfall to UWB. |
| **Kontakt.io** | BLE → healthcare RTLS | Quote-based | Pivoted entirely to healthcare. |

**The gap.** The major BLE beacon players (Estimote, Kontakt.io, Gimbal) have all
pivoted away from retail footfall. WiFi-probe footfall is dead (privacy-killed,
MAC-randomization-broken). Camera-based counting is accurate but expensive and
privacy-invasive (BIPA, GDPR Art. 9 biometric data). Passive BLE footfall via
payload classification is genuinely under-served.

**Privacy.** Passive BLE scanning listens to advertisements the phone is already
broadcasting (Find My, Continuity, Fast Pair) — it does not cause the phone to do
anything. No imagery, no biometric data, no faces. Under GDPR, the legal axis is
*identifier retention and linkability*, not sensor modality. A camera doing
on-device anonymous counting (no image retention) processes no personal data; a BLE
scanner retaining stable MACs processes personal data. The defensible pitch: "we
capture only randomized, rotating BLE MACs, retain no stable identifiers, and output
only aggregated counts." (See Privacy section.)

**Gaps to close.** MAC randomization means you cannot reliably dedupe or count
unique devices without fingerprinting beyond the MAC. The product's
fingerprinting work (cross-radio linking, Apple Continuity linking, MAC-rotation
clustering) is the technical moat. The honest caveat: ~456 of 508 random-MAC
devices advertise no service UUIDs at all — they are irreducible noise for
deduplication, but still count in footfall.

---

### 2. Smart building / workplace occupancy

**The problem.** Post-pandemic office utilization is ~40–56% (CBRE 2023: under
40%; Density 2025: 47% peak; JLL 2026: 56%). Companies need to know which floors,
rooms, and desks are actually used to right-size leases (a 20% real-estate cut
yields material savings; RE is a top-3 operating cost), optimize HVAC (BrainBox AI
saves 11–25% HVAC electricity), eliminate ghost meetings (25%+ of booked meetings
are no-shows), and plan cleaning staffing.

**How the product fits.** A Pi per zone passively counts BLE devices present, with
distance rings (1 Pi) or trilaterated position (2+ Pis). The "rhythm" dashboard
shows when devices come and go — a proxy for when people are present. No camera,
no PII, no ceiling installation. Deploy in hours, not months.

**Competitors.**

| Vendor | Technology | Pricing | Notes |
|---|---|---|---|
| **Density** (Waffle) | Radar (no camera) | **$229/sensor + $8/unit/mo (rooms), $2.50/unit/mo (desks), $15/unit/mo (all)** | Only published pricing. "Can't be evil." Customers: Uber (1,207 units), ExxonMobil, Stripe. |
| **VergeSense** | Computer vision (edge AI, on-device, images discarded) | Quote-based | "People-counting, not people-tracking." 200M+ sq ft. |
| **Butlr** | Thermal (camera-free, heat only) | Quote-based | "Privacy is a property of the hardware itself." 30k+ sensors, 100M+ sq ft. SOC2 Type II. |
| **PointGrab** | Presence/motion (edge AI, "not cameras") | Quote-based | 95% accuracy, 7-yr operation. Customers: Morgan Stanley, KPMG. |
| **Basking.io** | WiFi (existing Cisco/Aruba APs, no new hardware) | ~$9k–16k/yr for ~100-lease portfolio | "No cameras. No tracking. No invasion." SOC 2 Type II. |
| **Occuspace** | WiFi (existing Aruba APs, BLE radios) | Quote-based | "MAC addresses are hashed instantly, right at the sensor." |
| **Robin** | Software + sensor integrations | **$3–12/employee/mo** + sensors $100–300, displays $300–600 | Per-employee, not per-sensor. Check-in based, not sensor based. |
| **Enlighted** (Siemens) | IoT lighting controls + occupancy | N/A — **shutting down April 2025** | Siemens retaining the workplace app (Building X), exiting sensor hardware. |

**ROI evidence.**
- BrainBox AI (HVAC): Dollar Tree saved $1.03M/yr across 616 stores (no Capex);
  Sleep Country: HVAC electricity −24%, gas −22%; typical savings 11–25%.
- VergeSense (space consolidation): Fresenius $60M lease avoided; Rapid7 $1.5M
  buildout saved; consulting firm $50k/month + 4,100 ghosted-meeting hours eliminated.
- CBRE: space planning efficiencies enable portfolio reduction of up to 30%.

**Privacy.** Privacy is the #1 adoption barrier (JLL 2026: 70% of organizations).
60% of employees reject cameras (YouGov/Density). In Germany/France, camera-based
monitoring almost always requires works council negotiation (months of delay).
Edge AI sensors producing only anonymous aggregate data typically avoid triggering
DPIA requirements. The "anonymous-at-source" standard (PIR, thermal, radar —
physically cannot capture personal data) is the "privacy gold standard." BLE/WiFi
sits in a middle tier: better than cameras (no images) but less airtight than
thermal/radar (MAC addresses are technically PII even when hashed, per EDPB).

**Gaps to close.** The product counts *devices*, not *people*. A person with phone
+ laptop + watch = 3 devices; a visitor with no phone = 0. Calibration ratios are
needed. Room-level granularity only (not desk-level). The honest pitch: "camera-free
privacy at WiFi-scale deployment, at a fraction of proprietary sensor cost" — not
"absolute anonymity."

---

### 3. IoT device inventory / rogue device detection

**The problem.** Buildings have hundreds of unmanaged IoT devices (smart speakers,
smart TVs, smart lights, sensors, wearables) that IT doesn't know about. Rogue
devices (unauthorized APs, shadow IoT, evil twins) are a security risk. Forescout's
headline: average time to find unknown assets dropped from 41 hours to under 6
minutes. The IoT security market is $11.66B in 2026, growing to $47.33B by 2031
(32.35% CAGR, Mordor Intelligence).

**How the product fits.** A Pi passively inventories every BLE/WiFi/mDNS device in
range and classifies it (phone/speaker/TV/light/sensor). The 14-day history shows
what's new (rogue device alert), what's gone (asset left), and the device mix
(inventory). Multi-Pi gives position (where is the rogue device). No agents, no
network integration, no SPAN ports — just listen.

**Competitors.**

| Vendor | How they discover | Pricing | Notes |
|---|---|---|---|
| **Armis** | Agentless; network traffic ingestion (SPAN/mirror) | Quote-based (~$4B valuation) | IoT security leader (8.8/10 PeerSpot). armis.com 403s WebFetch. |
| **Claroty** | Passive monitoring + safe queries + project file analysis + ecosystem enrichment | Quote-based (more expensive than Nozomi) | 22k+ sites, 1.3k+ customers. Gartner MQ Leader 2026. |
| **Forescout** | Agentless; 350+ protocols, 30+ discovery methods | Quote-based | "41hr → 6min." IT/OT/IoT/IoMT. |
| **Nozomi Networks** | Passive observation (SPAN/tap, no active query); Guardian Air wireless sensor | Quote-based ("moderate to high," cheaper than Claroty, +30% recently) | 102M+ devices monitored. "Ideal for high-risk industrial environments." |
| **Estimote** | UWB + BLE tags (asset tracking) | **$199 dev kit (3 tags)** | Inch-level. Customers: Apple, Amazon, Nike, NASA. |
| **Quuppa** | BLE RTLS (Locators + Tags) | Quote-based | Sub-meter. ROI: PostNord +25% sorting, Kloeckner +$20k/day. |
| **AiRISTA Flow** | BLE tags + AoA gateways | Quote-based | Sub-meter. sofia RTLS software. |

**The gap.** Enterprise platforms are sales-led, enterprise-priced ($25k+
minimums), and focused on OT/ICS protocols (Modbus, DNP3, OPC UA) — not
consumer/IT BLE devices. A $45 Pi is 1–2 orders of magnitude cheaper hardware
than Nozomi/Forescout sensors. It competes on cost and simplicity, not on OT
protocol coverage or platform integration (SIEM, NAC, CMDB). The wedge: cheap
rogue-device detection and asset inventory for commercial/building environments
where the threat is shadow IoT (smart speakers, rogue APs, personal hotspots)
not industrial PLCs.

**Privacy.** This is a security use case, not analytics — the privacy calculus is
different. You are inventorying devices on your own network, which is generally
permitted. The product's classification (phone/speaker/TV/light/sensor) gives
actionable inventory without identifying people.

**Gaps to close.** No OT protocol coverage (Modbus, DNP3, OPC UA). No SIEM/NAC/CMDB
integration. No vulnerability database. It's a sensor, not a platform. But for
"find every BLE device in my building and tell me what it is," it's 90% of the
value at 1% of the cost.

---

### 4. Hospitality (hotels)

**The problem.** Hotels need to know: is a room occupied (for housekeeping
optimization), when guests are present (for HVAC/energy savings), and staffing
levels. The no-show/ghost-room problem parallels ghost meetings.

**How the product fits.** A Pi per floor (or per room) passively detects guest
device presence. The "rhythm" of devices coming and going is a proxy for guest
activity. Housekeeping gets a live "occupied" signal without cameras in rooms.
HVAC scales back when no devices are present.

**Competitors.**
- **Density** has Marriott as a customer (hospitality confirmed). Radar-based, $229/sensor.
- **Butlr** serves hospitality (camera-free thermal, smart cleaning/restroom usage).
- **Kontakt.io** BLE beacons for healthcare RTLS (adjacent).
- Hotel room occupancy is typically detected via: PIR motion sensors, door sensors,
  smart thermostats (Honeywell, Siemens), or WiFi presence (guest device on the
  hotel WiFi).

**Pricing.** No published hospitality-specific pricing. Density's $229/sensor +
$8/room/mo is the benchmark. A $45 Pi is a 5x hardware undercut.

**Privacy.** Cameras in hotel rooms are a non-starter. BLE device detection is the
least invasive option. The pitch: "we detect that a device is present, not who the
guest is or what they're doing."

**Gaps to close.** Per-room deployment cost (1 Pi/room is expensive at scale —
better as 1 Pi/floor with distance rings). Device-to-person calibration (a room
with a guest phone = occupied; a room with a smart speaker = ambiguous).

---

### 5. Healthcare / senior living

**The problem.** Senior living facilities need passive, non-intrusive activity
monitoring. A person's device "rhythm" (phone/watch present, moving around) is a
proxy for activity and wellbeing. Disruption of the rhythm (device stops moving,
no devices detected) signals a potential problem.

**How the product fits.** A Pi passively monitors the BLE device rhythm in a
resident's apartment. No camera, no wearable required (uses the resident's own
phone/watch). Anomaly detection: "no devices detected for 12 hours" → alert. This
is the fall-detection adjacency — not fall detection itself, but "activity
anomaly detection" via device presence.

**Competitors.**
- **CarePredict** (wearable + AI activity tracking) — wrist-worn, tracks ADLs.
- **SafelyYou** (camera-based fall detection) — on-device AI, no cloud video.
- **Butlr** (thermal, camera-free) — senior care monitoring, "camera-free."
- **Alarm.com Wellness** — PIR motion sensors, bed sensors, door sensors.
- **Kontakt.io** — BLE RTLS for healthcare (asset tracking, patient flow), HIPAA.

**Pricing.** CarePredict ~$50–150/resident/month (industry-reported). SafelyYou
quote-based. Butlr quote-based. A $45 Pi is a fraction of the hardware cost, but
the product is not a medical device and does not detect falls — it detects device
presence anomalies.

**Privacy.** HIPAA applies if any PHI is collected. The product detects devices,
not health data — but if it's used to infer "resident is inactive," that inference
could be PHI. The pitch: "we detect device presence, not health status — the
alert goes to staff who assess the resident."

**Gaps to close.** Not a medical device. No fall detection. Device presence is a
weak proxy for activity (resident could leave phone in another room). Best as an
adjunct to (not replacement for) PIR/wearable/bed sensors. The strongest use case:
"the resident's phone hasn't moved in 12 hours — check on them."

---

### 6. Event / venue analytics

**The problem.** Event organizers need crowd density, dwell time, device mix, and
flow patterns at concerts, conferences, and sports venues. This drives staffing,
security, vendor placement, and ROI measurement.

**How the product fits.** Multiple Pis deployed across a venue passively count BLE
devices and trilaterate position. The "rhythm" dashboard shows crowd density over
time, dwell time per zone, and device mix (how many phones vs speakers vs
wearables). No app install, no RFID wristbands, no turnstile counters.

**Competitors.**
- **Crowd Connected** (UK) — event analytics, BLE/beacon-based attendee tracking.
- **WaitTime** — crowd density, AI-based people counting (cameras).
- **Xyng** — event analytics.
- WiFi analytics at conferences (Cisco Meraki, Aruba) — counts associated devices.
- RFID wristbands (e.g., events using NFC) — active, requires a wristband.

**Pricing.** Event analytics is typically per-event or per-venue. No published
standard pricing. A $45 Pi deployed temporarily (rentable, returnable) is a
low-cost pop-up analytics kit.

**Privacy.** Events are public spaces; BLE scanning is less invasive than cameras.
The pitch: "count devices, not faces — no facial recognition, no identity
tracking." GDPR still applies (device identifiers are personal data if linkable),
but aggregation and short retention mitigate.

**Gaps to close.** Temporary deployment (Pis need to be placed, powered, and
collected). Multi-Pi sync and calibration for trilateration in a new venue. The
"rentable analytics kit" business model (ship 10 Pis, deploy for the event,
collect, process) is a natural fit.

---

### 7. Real estate / coworking

**The problem.** Flex offices and commercial real estate need space utilization
metrics: which desks/rooms/floors are used, when, and by how much. This drives
lease decisions (right-size), pricing (dynamic desk pricing), and operations
(cleaning, HVAC). Post-pandemic utilization is 40–56% (CBRE, Density, JLL).

**How the product fits.** A Pi per floor or zone passively counts devices present.
The "rhythm" shows peak usage times, day-of-week patterns, and underutilized
zones. No camera, no desk sensors, no ceiling installation.

**Competitors.**

| Vendor | Technology | Pricing |
|---|---|---|
| **Density** | Radar (Waffle) | $229/sensor + $2.50–15/sensor/mo |
| **VergeSense** | Computer vision | Quote-based |
| **Basking.io** | WiFi (existing APs) | ~$9k–16k/yr for ~100-lease portfolio |
| **Butlr** | Thermal | Quote-based |
| **PointGrab** | Presence/motion | Quote-based |
| **Cisco Spaces** | WiFi (existing Cisco APs) | Bundled in Cisco licensing |
| **InnerSpace** | WiFi (sensor-free) | Quote-based |
| **Freespace** | Occupancy sensors | Quote-based |

**ROI.** CBRE: space planning efficiencies enable portfolio reduction of up to 30%.
VergeSense: Fresenius $60M lease avoided; Rapid7 $1.5M buildout saved. The
"3-30-300 Rule" (R-Zero): $3/sqft utilities, $30/sqft rent, $300/sqft payroll —
real estate is a top-3 operating cost; a 20% cut yields material savings.

**Privacy.** Same as workplace (see above). 70% of orgs cite privacy as the #1
barrier (JLL 2026). The no-camera pitch is strong here.

**Gaps to close.** Device-to-person calibration. Room-level granularity only (not
desk-level). The product is best for "floor trends" not "desk utilization" —
compete on cost and deployment simplicity, not on desk-level precision.

---

### 8. Smart home / home automation B2B (integrators)

**The problem.** Custom integrators (AV companies, smart home installers) install
systems in high-end homes and small commercial spaces. They need to inventory the
client's devices, troubleshoot (what's on the network, what's offline), and monitor
the environment.

**How the product fits.** A Pi is a $45 "network stethoscope" the integrator leaves
on-site. It inventories every BLE/WiFi/mDNS device, classifies it, and shows the
rhythm. The integrator gets a dashboard of the client's environment without
logging into each device. Rogue device detection (a neighbor's speaker on the
client's network) is a bonus.

**Competitors.** No direct competitor at this price point. Home Assistant (free,
open-source) does device discovery but requires the integrator to set it up per
site. The product's value: a purpose-built, auto-updating, dashboard-first device
that the integrator can drop in and monitor remotely.

**Pricing.** Integrator model: hardware margin (buy Pi + case at $45, sell at
$150–200 installed) + monitoring SaaS ($10–25/site/month for the dashboard).

**Gaps to close.** Remote access (the integrator needs to see the dashboard from
off-site — currently it's local-only at port 8000). Multi-site management (a
fleet dashboard for all the integrator's clients).

---

## Privacy as a moat

### Passive BLE vs camera-based analytics

**The legal axis is identifier retention, not sensor modality.** Under GDPR, a
camera doing on-device anonymous counting (no image retention) processes no
personal data and falls outside GDPR. A BLE scanner retaining stable MAC addresses
processes personal data (Recital 30: device identifiers are "online identifiers").
The distinction that matters is **whether identifiers are retained**, not whether
the sensor is a camera or a radio.

**The defensible pitch:** "We capture only randomized, rotating BLE MACs, retain
no stable identifiers, hash everything at the sensor, and output only aggregated
counts — so we process no personal data." This is a genuine legal advantage over
camera systems that retain images and over WiFi systems that retain stable MACs.

**The marketing pitch:** "No camera. No faces. No identities. We count devices,
not people." This is intuitive and aligns with consumer expectations — but a
sophisticated buyer will ask: "Do you retain stable MACs? Do you hash? Do you
aggregate?" The legal strength comes from data minimization, not from the BLE
choice alone.

### GDPR / CCPA implications

**GDPR.**
- **Art. 4(1) + Recital 30:** Device identifiers (MAC addresses) are "online
  identifiers" and personal data when linkable to a person.
- **CJEU Breyer (C-582/14, 2016):** A dynamic IP is personal data where the
  controller has the legal means to identify the subject. Applies to MAC addresses
  by the same logic.
- **Randomized MACs:** A randomized, rotating BLE MAC is much harder to argue as
  personal data — the Breyer "disproportionate effort" exception likely applies.
  iOS rotates BLE MACs aggressively (Apple Continuity frames use rotating MACs).
  This is the strongest argument that passive BLE capture of randomized MACs is
  *not* personal data.
- **ePrivacy Directive:** Passive capture of broadcast advertising/probe packets is
  arguably interception of communications in some Member States. The pending
  ePrivacy Regulation would clarify. Secondary risk on top of GDPR.
- **EDPB:** MAC addresses constitute PII "even when hashed" — WiFi tracking is not
  automatically GDPR-safe.

**CCPA/CPRA.**
- "Personal information" includes anything "reasonably capable of being associated
  with" a consumer or household — a functional, linkability-based test paralleling
  GDPR. A stable MAC address that can be linked to a device/household qualifies.
  Randomized MACs that cannot reasonably be linked likely do not.

**Enforcement history.**
- **Google Street View (2010–2013):** Germany fined Google €145,000 for recording
  unencrypted WiFi data. Japan ruled it violated secrecy of communications.
- **Euclid Analytics (FTC, Dec 2013):** FTC staff report on "Mobile Device Tracking"
  following the Euclid matter. Set expectations: notice, opt-out, data
  minimization, hashing/anonymization of MACs. Euclid was privacy-killed (Philz
  Coffee dropped them in 2014).

**Industry self-regulation.**
- **Future of Privacy Forum (FPF):** Mobile Location Analytics code of conduct —
  notice, opt-out, hash/anonymize MACs, aggregate, short retention. The de facto
  US industry standard.

**Bottom line.** Passive BLE is more privacy-preserving than cameras *if paired
with data minimization* (hash MACs, aggregate, short retention, rely on
randomization). The "no faces" framing has marketing value but is not the operative
legal distinction. The moat is the data architecture, not the radio choice.

---

## Business model options

### Hardware + SaaS (the Density model)

- **Hardware:** Pi 4 (2GB) ~$35 + case + power + SD ~$10 = **$45 BOM**. Sell at
  **$149–199** (3–4x margin on hardware, competitive with Density's $229).
- **SaaS:** **$8–15/sensor/month** (matching Density's published pricing for
  rooms/desks). Includes dashboard, historical data, API, alerts.
- **Margin:** Hardware ~70% gross margin ($45 → $149). SaaS ~80%+ gross margin
  (software, no marginal cost per sensor).
- **3-year contract** (Density's model): $149 hardware + $8/mo × 36 = $437 total
  per sensor over 3 years. Cost to serve: ~$45 hardware + ~$2/mo hosting = ~$117.
  Gross margin ~73%.

### Per-sensor / per-site subscription

- **Per sensor:** $149 hardware + $10/sensor/month.
- **Per site:** $199/site/month (up to 5 sensors), $399/site/month (up to 20
  sensors). Simpler for multi-site retail/mall deployments.

### Hardware-only (integrator channel)

- Sell the Pi + case + software license at **$199–299** (one-time). The integrator
  owns the deployment. **$10–25/site/month** for the cloud dashboard (optional).
- Margin: ~80% on hardware, ~90% on the cloud dashboard.

### Freemium / open-core

- The software is MIT-licensed (already open source). The **cloud dashboard** is
  the SaaS: multi-site aggregation, historical export, alerts, API. Free for 1 Pi
  (local dashboard); paid for multi-Pi + cloud.
- This matches the existing architecture: local Pi dashboard is free; the
  multi-Pi sync + cloud is the paid tier.

### Rental / pop-up (events)

- **Rent 10 Pis for $500/event** (ship, deploy, collect, process). The Pis are
  reusable. Margin is high (hardware is amortized across many events).

### Recommended model

**Hardware ($149–199) + SaaS ($8–15/sensor/month), 3-year contract.** This matches
the market benchmark (Density's published pricing) with a 5x hardware cost
advantage. The SaaS is where the recurring revenue and margin live. Lead with the
privacy story ("no camera, no faces, no PII") and the price ("5x cheaper than
Density, 10x cheaper than RetailNext"). The open-source core (MIT) is a trust
signal for privacy-conscious buyers — they can audit the code.

---

## What to build next for B2B

To be sellable in these verticals, the product needs:

### Must-have (to be sellable at all)

1. **Multi-Pi dashboard.** A single dashboard aggregating multiple Pis across a
   site (or multiple sites). Currently each Pi has its own local dashboard. B2B
   buyers need one view of all sensors. (The peer-sync mechanism exists; the
   aggregated dashboard does not.)

2. **Cloud / remote access.** The dashboard is currently local-only (port 8000).
   B2B buyers (and integrators) need to see the dashboard from off-site. Options:
   a cloud relay (the Pi phones home, no inbound port needed), or a VPN/Tailscale.
   The cloud relay is the SaaS product.

3. **Alerts.** "New device detected" (rogue device), "device count dropped to zero"
   (occupancy anomaly), "device X hasn't been seen in N hours" (asset/senior
   alert). The product has the data; it needs alert rules + notification (email,
   webhook, Slack).

4. **API.** The product has a JSON API already. B2B buyers need it documented,
   stable, and with an API key. This is how the data feeds into existing systems
   (BI tools, building management, SIEM).

5. **Historical export.** CSV/JSON export of the hourly rollups (kept forever) for
   custom analysis. B2B buyers will want to pull the data into their own tools.

### Should-have (to be competitive)

6. **Privacy controls.** Hash MACs at the sensor (never store raw MACs in the
   cloud). Aggregate counts below a threshold (k-anonymity). Short retention option
   (configurable, not just 14 days). These are the features that make the privacy
   pitch defensible under GDPR/CCPA.

7. **Device-to-people calibration.** A configurable ratio (e.g., 1 person = 1.3
   devices on average) to convert device counts to people estimates. Honest about
   the limitation. This is what WiFi-based analytics vendors (Basking, Occuspace)
   do.

8. **Zone/floor labeling.** Let the user name zones (entrance, food court, north
   wing) and see per-zone analytics. Multi-Pi trilateration maps devices to zones.

9. **Dwell time.** Time between first and last sighting of a device fingerprint
   (not a MAC — MACs rotate). This is the fingerprinting work (FINGERPRINTING.md)
   — it's the technical moat for accurate dwell/return-visitor metrics.

10. **Return-visitor detection.** A device fingerprint seen on day 1 and day 5 =
    a return visitor. Requires the fingerprinting work (cross-radio linking +
    Apple Continuity linking). This is the metric malls care about most.

### Nice-to-have (to win enterprise)

11. **SIEM / NAC integration.** Webhook alerts to Splunk, ServiceNow, Slack. For
    the IoT security use case, this is how the Pi feeds into existing security
    operations.

12. **Fleet management.** A cloud console for managing 100s of Pis (deploy,
    update, monitor health, push config). The auto-update mechanism exists
    (GitHub releases); the fleet console does not.

13. **White-label dashboard.** Let integrators and resellers brand the dashboard
    with their own logo/colors. Smart home integrators and mall operators want
    their brand on it.

14. **Compliance pack.** A one-page "privacy and compliance" doc explaining the
    data architecture (no raw MACs, hashed, aggregated, short retention) for
    GDPR/CCPA-conscious buyers. This is the sales enablement for the privacy moat.

### The fingerprinting work is the moat

The `docs/FINGERPRINTING.md` and `docs/FINGERPRINTING-VALIDATION.md` work is the
technical differentiator. Without it, the product counts raw MACs (inflated 30%+
by phone rotation). With it, the product collapses 448 phone-anon MACs into ~20
physical devices and links Apple Continuity (593 sightings, not 5 as originally
thought). This is what makes footfall, dwell, and return-visitor metrics accurate
enough to sell. **Build Phase 1 (cross-radio) + Phase 2 (rotation clustering) +
Phase 3 (Apple Continuity, fix the decoder first) before selling B2B.**

---

## Sources

**Retail footfall:**
- retailnext.com, sensormatic.com (ShopperTrak), density.io (pricing), placer.ai
  (data methodology), estimote.com ($199 dev kit), kontakt.io, infillion.com
  (Gimbal), techcrunch.com (Euclid/Philz 2014)

**Smart buildings:**
- density.io (Waffle $229 + $2.50–15/mo, Open Area $0.99/sqft/yr), vergesense.com,
  butlr.com, brainboxai.com (ROI case studies), jll.com (2026 occupancy benchmark,
  70% privacy barrier), robinpowered.com ($3–12/employee/mo), vendr.com (Robin
  pricing), inside.lighting (Enlighted shutdown April 2025), pointgrab.com

**IoT security:**
- claroty.com, forescout.com, nozominetworks.com (Guardian Air), peerspot.com
  (Armis 8.8/10, Nozomi pricing), mordorintelligence.com ($11.66B→$47.33B),
  quuppa.com, estimote.com, wirepas.com, airistaflow.com, en.wikipedia.org
  (rogue access point)

**Privacy:**
- gdpr-info.eu (Art. 4, Recital 30), eur-lex.europa.eu (Breyer C-582/14,
  ePrivacy Directive), oag.ca.gov (CCPA), en.wikipedia.org (Google Street View,
  MAC randomization), ftc.gov (Euclid, mobile device tracking)

**Real estate / coworking:**
- density.io (insights.density.io benchmark), basking.io ($9k–16k/yr), cbre.com
  (portfolio reduction 30%), xysense.com (utilization index), wework.com
  (S-1, 72–75% occupancy, 34,000 sensors)

**Hospitality / healthcare / events:**
- kontakt.io (healthcare RTLS, HIPAA), carepredict.com, safelyyou.com, butlr.com
  (senior care), crowdconnected.com (event analytics)
