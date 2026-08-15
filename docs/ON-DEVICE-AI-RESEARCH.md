# On-device AI/ML research — what could realistically improve data quality on a Pi 3

Date: 2026-08-15
Hardware: Raspberry Pi 3 Model B — ARM Cortex-A53 quad-core 1.2GHz, 1GB LPDDR2,
no GPU, no NPU. OS takes ~250-400MB, leaving ~600-750MB for user workloads.

This is a fact-check of whether on-device ML is worth building for the four data
quality problems: MAC randomization linking, classification accuracy, RSSI
distance, and device linking. The verdict is honest about what ML can and
cannot do given the Pi 3's constraints.

---

## Executive verdict

**Most of the ML ideas here are not worth building on a Pi 3. The one that is
worth it is a small tree model (random forest / XGBoost) for the classification
long tail — and only as a fallback behind the existing rules, not a
replacement.**

| Use case | Worth it on Pi 3? | Why |
|---|---|---|
| **ML classification (long-tail fallback)** | **Yes** | Small tree model, <5MB, <10ms inference. Helps the ~10-20% of devices rules can't classify. But needs self-labeled training data. |
| **ML MAC-rotation linking** | **Not worth it now** | Academic work exists (SimBle ~90% sim, Puig DBSCAN 89.6% on WiFi) but the improvement over your rules is marginal in coverage (36% → maybe 40-50%). The empty-payload majority (~64%) stays un-linkable with passive HCI capture. Fix the Apple decoder instead — it's the proven 90% re-ID method. |
| **ML RSSI distance** | **No** | The log-path-loss formula is already near the physics floor for a single sensor. No calibration-free ML model beats it. The bottleneck is the signal (3-7dB RSSI std dev → ±50% distance), not the formula. |
| **On-device LLM (1-3B)** | **No on Pi 3** | A 1B Q4 model (~700MB weights) does not fit in 1GB RAM without swap; with swap, <1 tok/s. A 0.5B Q4 (~350MB) fits but runs at ~5-8 tok/s — borderline, and weak model quality. LLMs need a Pi 4 (marginal) or Pi 5 (usable). |
| **LLM for label generation** | **Not on Pi 3** | A 0.5B Q4 model on a Pi 5 does ~300-400ms per classification. On a Pi 3 it takes ~2-3s per name (borderline), and 1B+ doesn't fit. Not viable as a per-sighting tool. |

**The honest summary**: the Pi 3 can run small tree models (random forest,
XGBoost) in milliseconds. It cannot run LLMs at usable speed. For the four data
quality problems, rules are already near-optimal for three of them; ML only
helps for classification of the unknown long tail, and only with labeled
training data you'd have to create yourself.

---

## Pi 3 constraints — realistic model sizes and inference times

### Hardware

- **CPU**: ARM Cortex-A53 quad-core @ 1.2GHz. ARMv8.0 — no dotprod, no fp16
  acceleration ISAs (those arrived in ARMv8.2, which the Pi 5's A76 has).
- **RAM**: 1GB LPDDR2. OS + scanner + web server take ~250-400MB. Realistic free
  budget: **~600-750MB** for a model + runtime.
- **Memory bandwidth**: ~4 GB/s (vs Pi 4's ~8 GB/s, Pi 5's ~16 GB/s). This
  matters: LLM decode is memory-bandwidth-bound.
- **No GPU, no NPU** — CPU-only inference.

### What runs well on a Pi 3

| Model type | Size | Inference (1 sample) | Framework |
|---|---|---|---|
| **Random forest / XGBoost** (100-500 trees, tabular) | 1-10 MB | **~0.5-10ms** | scikit-learn / XGBoost (joblib-serialized) |
| **Small Kalman filter** (RSSI smoothing) | KB | sub-millisecond | numpy (already installed) |
| **Tiny MLP** (1-3 inputs, 1 hidden layer) | KB | microseconds | numpy or TFLite |
| **KNN fingerprinting** (RSSI vector distance) | depends on DB | milliseconds | numpy |
| **TFLite MobileNet V2 INT8** (vision, for reference) | ~4MB | **~30ms** | TFLite + XNNPACK |
| **TFLite MobileNet V2 FP32** (vision, for reference) | ~14MB | **~79ms** | TFLite + XNNPACK |

The MobileNet numbers are from the XNNPACK benchmark suite (Pi 3+, A53 @ 1.4GHz,
Feb 2022) — they're vision models, not our data, but they confirm the Pi 3 can
run small neural nets in tens of milliseconds. Tree models and small linear
models are the sweet spot for our tabular data: they run in milliseconds, fit in
a few MB, and need no special framework — just scikit-learn + joblib.

### What does NOT run well on a Pi 3

| Model type | Size | Inference | Why it fails |
|---|---|---|---|
| **1B+ quantized LLM** (Q4) | ~600-700MB weights | **<1 tok/s** (with swap) | Weights alone (~600-700MB) + KV cache (~50-100MB) + runtime (~50-100MB) + OS (~300MB) = ~1.0-1.3GB — does not fit in 1GB without swap. With SD-card swap, throughput drops to <1 tok/s. A53's Q4 throughput is ~5.76 GB/s (llama.cpp PR #8151) vs A72's 9.26 and A76's ~10 — but RAM is the wall, not bandwidth. |
| **0.5B quantized LLM** (Q4) | ~350-430MB weights, ~500-600MB peak | **~5-8 tok/s** (estimated) | Fits in RAM, but a single device-name classification (10-15 tokens out) takes 2-3 seconds. Borderline usable for occasional lookups, not per-sighting. The A53 lacks the ARMv8.2 dotprod/fp16 ISAs that give the Pi 5 a 3-10x boost. |
| **2-3B quantized LLM** (Q4) | 1.3-2GB | **impractical** | Does not fit in 1GB RAM at all, even with swap. Seconds per token. |

### Real LLM benchmarks (for comparison — these are Pi 5 numbers, not Pi 3)

From Raspberry Pi's own Aug 2026 LiteRT benchmarks (Pi 5, 8GB, A76):

| Model | Framework | Prefill (tok/s) | Decode (tok/s) | Peak RAM |
|---|---|---|---|---|
| Gemma 3 270M | LiteRT-LM | 433 | 23 | 680 MB |
| Gemma 4 E2B | LiteRT-LM | 99 | 9 | 1432 MB |
| Gemma 3 270M | llama.cpp Q8 | 462 | 39 | 685 MB |
| Gemma 4 E2B | llama.cpp Q4 | 24 | 4 | 4406 MB |

From community benchmarks (Pi 5, A76):

| Model | Quant | Decode tok/s | Latency per classification* |
|---|---|---|---|
| Qwen2.5-0.5B | Q4 | 30-36 | ~300-400ms |
| TinyLlama 1.1B | Q4 | 12-15 | ~600-750ms |
| Qwen3-0.6B | Q4_K_M | 15 | ~400-500ms |
| Gemma 2B | Q4 | 5 | ~1-1.8s |

From community benchmarks (Pi 4, A72):

| Model | Quant | Decode tok/s | Latency per classification* |
|---|---|---|---|
| TinyLlama 1.1B | Q8 | ~3 | ~2-4s |
| TinyLlama 1.1B | F16 | ~2 | ~3-5s |

*Classification latency assumes a few-shot prompt (~50-100 tokens in) and a
short label output (~5-15 tokens out).

**Pi 3 extrapolation**: the Pi 3's A53 has Q4 throughput of ~5.76 GB/s (llama.cpp
PR #8151, direct measurement) vs the Pi 5's ~10 GB/s. A 0.5B Q4 model (~350-430MB)
fits in RAM and would run at ~5-8 tok/s — borderline usable for occasional
lookups (2-3s per name classification). A 1B Q4 model (~600-700MB weights) does
NOT fit in 1GB without swap; with SD-card swap it drops to <1 tok/s. **A 1B+
LLM is not viable on a Pi 3. A 0.5B LLM is marginal at best.**

### Framework recommendation for a Pi 3

**Use scikit-learn + joblib.** Do not use TensorFlow Lite, ONNX Runtime, or
PyTorch for the tabular models that actually help here. Reasons:
- scikit-learn and XGBoost both run on ARM, are already in the Python ecosystem,
  and serialize to a few MB via joblib.
- TFLite and ONNX Runtime add load time and memory overhead for no accuracy
  gain on tabular data. They're designed for neural nets, not tree models.
- The Pi 3's venv already has numpy. A random forest needs only sklearn.

**For minimal footprint**: emlearn (github.com/emlearn/emlearn) compiles sklearn
tree models to C99 — a random forest from 2KB flash, 50 bytes RAM. Use this if
you want the model trivially small and dependency-free.

**Note on the A53 and quantization**: the Cortex-A53 lacks the SDOT instruction
(present on the Pi 5's A76), so INT8 quantization gives only ~1.3x speedup vs
~5x on newer Pis. Don't rely on quantization to make a big model fit — use a
smaller model instead.

If a neural net ever becomes justified (it isn't for this data), TFLite is the
path — but tree models dominate tabular/categorical data and are far cheaper.

---

## Per-use-case analysis

### 1. MAC randomization linking

**The problem**: phones rotate their BLE MAC every ~15 min. We want to link
rotated MACs that belong to one physical device. Current rules catch ~36% of
random MACs (those with a non-empty service set or Apple Continuity tag); the
rest (empty service set, no Apple data) are un-linkable.

**Current approach** (fingerprint.py): three passes —
- A. Apple Continuity auth tag (same tag = same device, conf 0.95)
- B. Cross-radio (mDNS hostname serial + OUI+name, conf 0.95)
- C. MAC rotation (same class+signature, sequential within 15min, cardinality
  cap of 4, conf 0.7)

**The ML approach in the literature** (more nuanced than "nothing works"):
- **Apple Continuity sequence-number regression** (Martin et al., PETS 2019,
  "Handoff All Your Privacy", arXiv:1904.10600): uses monotonic sequence numbers
  (not reset by MAC rotation) + the Nearby data field (constant for 1-2 frames
  after MAC change) + OS fingerprint. Linear regression on sequence-number
  trajectory + prediction-interval matching. **Median 90% re-identification.**
  Passive. This is your current rules-based Apple approach, academically
  validated. Your Apple Continuity rules are already the proven method — ML won't
  beat them on that subset.
- **Advertising-interval fingerprinting** (SimBle, Mishra et al., 2021,
  arXiv:2101.11728): uses the advertising interval ("characteristic time") as a
  weak identifier + linear assignment + union-find. ~90% linking in simulation
  (100 devices, mobile); ~78% with 3-min randomization. Passive. Quadratic
  complexity — authors admit "not feasible for device-tracking purposes" at
  scale. Pi-3 feasible for tens-to-low-hundreds of devices.
- **Inter-Broadcast Latency (IBL)** (Graßhoff et al., TRUSTBUS 2023,
  arXiv:2307.02931): a single timing fingerprint. Entropy H(X)=4.88 bits (~29
  devices distinguishable) from one feature. Feasibility study, not an
  end-to-end linker. Replicated on Raspberry Pi 4B. Proves timing alone carries
  device-unique signal.
- **WiFi-side DBSCAN on bitwise payload + timing + RSSI** (Puig et al., 2026,
  arXiv:2606.25788): the most transferable template. DBSCAN on bitwise-decomposed
  HT-capabilities + inter-probe arrival time + 3 RSSI samples. **Up to 89.6%
  global accuracy on 22 devices.** Passive, unsupervised, no training. Your BLE
  scanner has the analogous fields (service UUIDs, manufacturer_data,
  service_data = payload bits; RSSI; advertisement timing).
- **Clustering on service-UUID sets** (what your rules do): the validation doc
  proved this over-merges. 456/508 random MACs share an empty set; the 47 with a
  set cluster into 6 groups, and those are simultaneous (different devices, not
  one rotating). The service set is a class signal, not a unit signal. ML
  clustering on the same exact-set features would over-merge identically.

**Feasibility on Pi 3**: a DBSCAN or random forest model is cheap — sub-millisecond
inference, <10MB model. The constraint is not compute; it's signal.

**Expected improvement over rules**:
- **On the linkable subset** (devices with non-empty service set or Apple tag —
  your current ~36%): ML (DBSCAN/RF on bitwise payload + timing + RSSI) could
  plausibly raise linking accuracy from your current rules-based rate toward the
  **85-90% range** seen in the WiFi analogue, by handling partial-match cases
  your exact-set rule rejects (e.g. UUID subset present, minor manufacturer_data
  variation).
- **On the empty-payload majority** (~64%): IBL timing features could extend
  linking to *some* devices with empty payload — Corona-Warn showed IBL
  distinguishes ~29 devices from one feature. But same-model phones collide, and
  this is unproven end-to-end.
- **Realistic total coverage**: maybe **40-50%** of all MACs (up from 36%) if
  timing features add a modest gain on empty-payload devices. Not a dramatic
  jump. The empty-payload floor is real — no passive HCI-level method in the
  literature overcomes it. You'd need SDR/CFO hardware (AirCatch) to fingerprint
  those, which a standard BLE dongle can't capture.

**Effort**: medium-high (adapt Puig's DBSCAN approach, add IBL feature, validate
on real captures). The model is easy; the validation is the work.

**Verdict**: **Not worth it on a Pi 3 right now.** The improvement is marginal in
coverage (36% → maybe 40-50%) and the empty-payload majority stays un-linkable.
The higher-value fixes are: (1) fix the Apple Continuity decoder to extract the
auth tag (offsets 16-18) — this is the proven 90% re-ID method, and it's a
decoder fix, not ML; (2) store raw manufacturer_data so the tag is backfillable.
If you later want to pursue ML linking, adapt Puig's DBSCAN approach
(bitwise-decompose payload + IBL + RSSI) — it's Pi-3 feasible and unsupervised,
but validate on real captures first; no published BLE-specific number exists.

---

### 2. Classification accuracy

**The problem**: rules misclassify some devices. The long tail (unknown name,
ESP32 OUI, phone vs tablet vs laptop) is where rules are weakest.

**Current approach** (classify.py + rules.py): mDNS HomeKit category > name
patterns (substring) > service UUID substring > OUI vendor > random-MAC
fallback. Confidence 0.2-0.9.

**The ML approach**:
- **Model type**: gradient-boosted trees (XGBoost) or random forest. This is
  tabular/categorical data (name tokens, service-UUID flags, OUI vendor,
  manufacturer_data byte-features, tx_power). Neural nets are the wrong default
  — tree models dominate tabular data, are smaller, and give interpretable
  feature importances.
- **Features**: name tokens (character n-grams or word tokens), service-UUID
  presence flags (one-hot per known UUID), OUI vendor (one-hot or embedding),
  manufacturer_data byte-features (Apple 0x004C type bytes, Google 0xFEAA
  FastPair flags, Govee prefixes), tx_power, rssi.
- **Training data**: **no public dataset exists** for BLE advertisement-metadata
  device-type classification. Every relevant paper uses network traffic or RF
  physical-layer features, not advertisement metadata. You must self-label
  from your own captures. This is the single biggest obstacle.

**Feasibility on Pi 3**: **easily.** A 100-500 tree XGBoost model is 1-5MB on
disk and infers in **<10ms** on a Pi 3. scikit-learn + joblib, no special
framework. Cap threads (`n_jobs=2`) to avoid oversubscription.

**Expected improvement over rules**:
- On devices rules already classify (Govee, iRobot, Apple, HomeKit): **~0%**.
  The rules ARE the optimal deterministic classifier for those. A tree model
  learns the same splits.
- On the long tail (unknown name, ESP32 OUI, phone vs tablet): **5-15
  percentage points** *if* you have a few hundred labeled examples per
  ambiguous class. Without labeled tail data, the model reproduces rule
  behavior or hallucinates.
- The strongest ML case: **ESP32 devices sharing OUI but differing in function**
  (light vs sensor vs switch). Their service_data / manufacturer_data payloads
  and advertised service UUIDs differ by firmware/application. A tree model on
  byte-features can learn application-specific patterns no name/UUID rule can.

**Effort**: medium-high. The model is easy; the labeling is the work. Budget a
few thousand hand-labeled advertisements. Feature engineering (tokenizing name,
byte-features from manufacturer_data, UUID flags) is 80% of the effort.

**Verdict**: **Worth building as a fallback classifier for the rule-miss tail
only.** Keep rules as primary. Add XGBoost as a fallback for devices that rules
classify as "unknown" or with confidence <0.4. Target the ESP32-same-OUI case
first — it has the highest signal-to-noise. Do NOT replace rules with ML.

---

### 3. RSSI distance estimation

**The problem**: RSSI→distance is ±50% noisy. Current formula:
`d = 10^((ref_rssi - rssi)/(10*n))` with ref from tx_power (or per-class
default) and n=2.7, smoothed with a rolling median.

**The ML approach in the literature**:
- **Fingerprinting** (dominant): offline RSSI radio map, online KNN/SVM/NN
  matching. Requires site survey. Gives 2D position, not 1D distance.
- **RNN/LSTM on RSSI trajectories**: ~30% better than single-sample, but needs
  multi-beacon sequences with ground-truth positions.
- **Kalman filters**: temporal filtering, not a better instantaneous mapping.
  Cuts RSSI volatility from ~10dB to ~5dB, cutting distance error
  proportionally.

**The critical finding**: **no paper reports a calibration-free ML model
beating the path-loss formula.** Every strong ML result used labeled training
data. The log-path-loss formula IS the calibration-free baseline — it's a
2-parameter model where ref_rssi and n have physical meaning and can be set
from tx_power and a reasonable environment constant.

**Why ±50% is the physics floor, not a model deficiency**:
```
fractional distance error = (ln(10) * sigma_rssi) / (10 * n)
```
With n=2.7:
| sigma_rssi (dB) | 1-sigma distance error |
|---|---|
| 3 | ±25.6% |
| 5 | ±42.6% |
| 7 | ±59.7% |

Indoor RSSI std dev is 3-7dB. **Your ±50% is the 1-sigma floor at
sigma_rssi=3-5dB.** This is the information-theoretic limit — the mapping from
distance to RSSI is many-to-one (multipath creates the same RSSI at very
different distances). No model extracts distance information that isn't in the
signal.

**Feasibility on Pi 3**: any model here (Kalman, small RF, KNN) runs trivially
on a Pi 3 — sub-millisecond. The constraint is not compute; it's training data
and the physics of multipath.

**Expected improvement over rules**:
- **Without calibration data: zero.** A model trained on nothing has nothing to
  learn.
- **With calibration data + multiple anchors**: multi-anchor papers show 50% →
  ~30% error is plausible. But you have one sensor (1D distance, not 2D
  position) and no calibration data.
- **Self-calibration from stable devices** (the one promising direction): detect
  stationary APs/beacons (stable RSSI over hours, stable MAC), treat them as
  fixed beacons at known distances, fit n per region/time from their RSSI, apply
  that n to mobile devices. This is novel, physically sound, and unvalidated in
  the literature. It's the most promising improvement path — and it's a
  statistics problem, not an ML problem.

**Effort**: high (ML path) for near-zero gain; low (self-calibration path) for
modest gain.

**Verdict**: **Do not build an ML model for distance.** Instead:
1. Keep the log-path-loss formula + rolling-median smoothing (already near-optimal).
2. Add device-class-specific path-loss parameters (per-class ref_rssi and n) —
   a 2-parameter model per class, not ML.
3. Build self-calibration from stable devices (fit n per region/time from
   stationary APs/beacons). This is the one novel contribution worth pursuing.
4. Consider a small Kalman filter for better temporal smoothing (cuts sigma_rssi,
   which cuts distance error proportionally).

---

### 4. Device linking (BLE/WiFi/mDNS of one physical device)

**The problem**: linking BLE, WiFi, and mDNS rows that belong to one physical
device.

**Current approach** (fingerprint.py Pass B): mDNS hostname serial match +
OUI+name match across radios. This works well for devices that broadcast mDNS
(speakers, TVs, printers) and is deterministic.

**The ML approach**: could a model learn to link BLE/WiFi/mDNS rows by combining
weak signals (OUI prefix, name similarity, service overlap, time-adjacency)?
Possibly, but the current rules already use the strongest signals (mDNS serial,
OUI+name). A model would add marginal value on the cases where signals are
ambiguous — and those cases are rare because mDNS hostnames with serials are
high-confidence.

**Feasibility on Pi 3**: a linking model (pairwise classification: "are these
two rows the same device?") is a small tree model, <10ms inference. Feasible.

**Expected improvement**: low. The rules already handle the high-confidence
cases. The low-confidence cases (no mDNS, no OUI match) lack the signal to link
regardless of model.

**Verdict**: **Not worth building.** The cross-radio rules are already strong.
Improve them by expanding the mDNS hostname serial extraction and OUI coverage
— both rules work, not ML.

---

### 5. On-device LLM for label generation

**The problem**: generating human-readable labels from messy device names,
mDNS TXT records, and cluster context. E.g. "LAP-V201S-A-EU" → "Levoit air
purifier", or labeling a cluster of linked devices.

**The LLM approach**: a small quantized LLM (0.5B-1B) can do few-shot
classification — show it 5 examples of "name → type" and it generalizes to
novel names. It can also interpret free-form mDNS TXT fields and generate
cluster labels.

**The evidence**:
- On a Pi 5 (A76), Qwen2.5-0.5B Q4 does ~30-36 tok/s decode, ~300-400ms per
  classification. Usable.
- On a Pi 4 (A72), TinyLlama 1.1B Q8 does ~3 tok/s, ~2-4s per classification.
  Marginal — usable for occasional lookups, not per-sighting.
- On a Pi 3 (A53): **not viable.** <1 tok/s estimated, 10-30+ seconds per
  classification. The A53 lacks the ARMv8.2 dotprod/fp16 ISAs that give the Pi 5
  a 3-10x boost, and has 1/4 the memory bandwidth.

**LLM vs dedicated classifier**: the literature is clear — fine-tuned encoder
models (BERT-tiny, ~30MB) achieve competitive or superior accuracy at 1-2 orders
of magnitude lower cost and latency than few-shot LLM prompting. For structured
device names, a dedicated classifier is the right tool. LLMs are "better
positioned as complementary elements within hybrid architectures" (arxiv
2602.06370).

**Feasibility on Pi 3**: **no.** A 0.5B Q4 model (~350-430MB) fits in RAM and
would run at ~5-8 tok/s (estimated from A53 Q4 bandwidth of ~5.76 GB/s). A
single name classification (10-15 tokens out) takes ~2-3 seconds — borderline
for occasional use, but the model quality at 0.5B is weak for this task, and
it competes with the scanner + web server for RAM. A 1B+ model does not fit
without swap. **Not viable as a per-sighting tool; marginal even as an
occasional fallback.**

**Feasibility on Pi 5**: yes. Qwen2.5-0.5B Q4 at ~300-400ms per classification
is practical for occasional use (the unknown long tail, maybe 5-15% of devices,
with caching so you never re-classify the same name).

**Verdict**: **Not on a Pi 3.** A 0.5B Q4 model fits in RAM but is borderline
(~2-3s per classification, weak model quality). A 1B+ model does not fit without
swap. If you upgrade to a Pi 5, a 0.5B Q4 LLM as a fallback for the unknown
long tail (rules → small classifier → LLM) is the right hybrid architecture.
The LLM's real value is few-shot generalization to novel names and generating
human-readable cluster labels — generative tasks where rules and classifiers
can't compete.

---

## Phased recommendation

### Phase 0 — do these first (no ML, pure wins)

1. **Fix the Apple Continuity decoder** to extract the Nearby auth tag (offsets
   16-18 of the 0x10 payload). This is the highest-value fix for MAC linking —
   it's the only path to linking the 116 Apple empty-set random MACs. Not ML.
2. **Store raw manufacturer_data hex** in sightings (already done in enrich.py
   — verify it's working) so the auth tag is backfillable without re-scanning.
3. **Refresh the AirPods model table** from the current furiousMAC list — the
   observed codes don't match the dict.
4. **Add device-class-specific path-loss parameters** (per-class ref_rssi and n)
   instead of a single n=2.7. A 2-parameter model per class, not ML.

### Phase 1 — if you build any ML (Pi 3 viable)

1. **XGBoost fallback classifier** for the rule-miss tail. Train on
   self-labeled captures (name tokens, service-UUID flags, OUI, manufacturer_data
   byte-features). Target the ESP32-same-OUI case first. Ship as a joblib model,
   ~1-5MB, <10ms inference. Keep rules as primary; ML fires only when rules
   return "unknown" or confidence <0.4.
2. **Self-calibration of path-loss exponent** from stable devices. Detect
   stationary APs/beacons, fit n per region/time, apply to mobile devices. This
   is statistics, not ML, but it's the most promising distance improvement.

### Phase 2 — only if you upgrade to a Pi 5

1. **0.5B Q4 LLM fallback** (Qwen2.5-0.5B-Instruct) for the unknown long tail
   that neither rules nor the XGBoost classifier can handle. ~300-400ms per
   classification on a Pi 5. Cache results so you never re-classify the same
   name. Invoke only for novel names, not per-sighting.
2. **LLM cluster labeling** — generate human-readable labels for groups of
   linked devices. This is a generative task where LLMs genuinely outperform
   rules and classifiers. Run once per cluster, not per sighting.

### What not to build

- **ML MAC-rotation linking** (for now) — academic work exists (SimBle, Puig
  DBSCAN) but the improvement is marginal in coverage (36% → maybe 40-50%) and
  the empty-payload majority stays un-linkable. Fix the Apple decoder instead.
  If you pursue it later, adapt Puig's DBSCAN (bitwise payload + IBL + RSSI) —
  it's Pi-3 feasible and unsupervised, but validate on real captures first.
- **ML RSSI distance model** — the formula is near the physics floor. No
  calibration-free model beats it. Self-calibration is the path, not ML.
- **Any LLM on a Pi 3** — not viable. <1 tok/s, 10-30s per classification.

---

## Honest limits — what ML won't fix

1. **MAC randomization for empty-set non-Apple random MACs**: ~340 devices in
   your data have no service UUID, no Apple Continuity, no OUI. They are
   irreducible noise for passive HCI-level capture. No ML model can link them
   because the signal isn't there — the literature confirms this (you'd need
   SDR/CFO hardware to fingerprint them physically). IBL timing might recover a
   few, but same-model phones collide. Count them in footfall; don't pretend to
   link them.

2. **RSSI ±50% distance error**: this is the physics floor for a single sensor.
   Indoor multipath makes the distance→RSSI mapping many-to-one. No model
   extracts distance information that isn't in the signal. The only improvements
   are (a) more sensors (trilateration needs 3+), (b) better temporal smoothing
   (reduces sigma_rssi), or (c) self-calibration of the path-loss exponent.

3. **Classification without labeled data**: no public dataset exists for BLE
   advertisement-metadata device-type classification. You must self-label.
   A model trained on rule-generated labels learns your rules' biases, not ground
   truth. The labeling is 80% of the effort.

4. **LLM speed on a Pi 3**: the A53 lacks the ARMv8.2 ISAs and memory bandwidth
   that make LLMs viable on a Pi 5. A 0.5B Q4 model fits in RAM but runs at only
   ~5-8 tok/s (~2-3s per name) and has weak model quality. A 1B+ model does not
   fit without swap. LLMs need a Pi 4 (marginal) or Pi 5 (usable).

5. **The long tail is long**: rules already handle the head (Govee, iRobot,
   Apple, HomeKit) well. ML only helps the ~10-20% tail, and only with labeled
   data. The marginal value is real but narrow — don't oversell it.

---

## Sources

**Pi 5 LLM benchmarks**: Raspberry Pi + Google, "Mastering edge AI on Raspberry
Pi with LiteRT and Gemma" (Aug 2026) — Gemma 3 270M: 680MB peak, 23 decode tok/s;
Gemma 4 E2B: 1432MB peak, 9 decode tok/s. Pi 5 (8GB, A76) only.

**Pi 4 LLM benchmarks**: llamafile article (Justine Tunney) — TinyLlama 1.1B Q8:
~3 tok/s on Pi 4 (A72). Community benchmarks: Pi 5 is ~3-4x Pi 4 for eval
throughput.

**Pi 3 extrapolation**: Pi 3 A53 is ~1/4 Pi 4 memory bandwidth, lacks ARMv8.2
dotprod/fp16 ISAs. A 1B Q4 model (~700MB-1GB weights) exceeds the 1GB RAM budget
after OS overhead. Even 0.5B Q4 (~430MB) would run at <1 tok/s.

**Pi 3 TFLite benchmarks**: XNNPACK benchmark suite (Feb 2022, Pi 3+, A53 @
1.4GHz) — MobileNet V2 INT8: 30ms; MobileNet V2 FP32: 79ms; MobileNet V1 INT8:
46ms. Source: `github.com/google/XNNPACK` README.

**Pi 3 llama.cpp throughput**: `github.com/ggml-org/llama.cpp` PR #8151 — A53
Q4_K throughput ~5.76 GB/s (vs A72 9.26, A76 ~10). A 0.5B Q4 model (~350MB)
at this bandwidth → ~5-8 tok/s (borderline). A 1B Q4 (~700MB) does not fit in
1GB RAM without swap.

**BLE classification**: No public dataset for advertisement-metadata type
classification. IoT identification literature (Sivanathan arXiv:2001.10632,
IoTSense arXiv:1804.03852, Aksu arXiv:1809.10387) uses traffic/RF features, not
advertisement metadata. Tree models (XGBoost/RF) are the right tool for tabular
categorical data; <10ms inference on Pi 3.

**RSSI distance**: No calibration-free ML model beats the log-path-loss formula.
Multi-anchor ML papers (DeepBLE arXiv:2103.00252, Hoang 2019, AugBoost
arXiv:2211.08752, Cortesi 2024) all use labeled training data. The physics:
fractional distance error = ln(10)*sigma_rssi/(10*n); indoor sigma_rssi=3-7dB
→ ±25-60% is the floor. Survey: Sonny et al. arXiv:2403.04333.

**LLM vs classifier**: arxiv 2602.06370 (2026) — fine-tuned encoders 1-2 orders
of magnitude lower cost/latency than few-shot LLM; LLMs better as hybrid
components. arxiv 2603.21389 — 0.5-3B models superior performance-efficiency
ratio. arxiv 2308.10783 — fine-tuned transformers outperform LLM few-shot.

**MAC randomization**: the validation doc (FINGERPRINTING-VALIDATION.md) is the
primary source — 456/508 random MACs share an empty service set; the service set
is a class signal, not a unit signal. Clustering over-merges. The Apple Nearby
auth tag (furiousMAC) is the only stable per-device ID, and it requires a
decoder fix, not ML.

**BLE MAC randomization tracking (academic)**:
- Martin et al., "Handoff All Your Privacy" (PETS 2019, arXiv:1904.10600) —
  Apple Continuity sequence-number regression + payload, ~90% re-ID, passive.
  Validates the current Apple rules approach.
- Mishra et al., "SimBle" (2021, arXiv:2101.11728) — advertising-interval
  fingerprinting, ~90% sim / ~78% with 3-min randomization. Passive, quadratic.
- Graßhoff et al. (TRUSTBUS 2023, arXiv:2307.02931) — Inter-Broadcast Latency
  as a timing fingerprint, H(X)=4.88 bits (~29 devices), replicated on Pi 4B.
- Puig et al. (2026, arXiv:2606.25788) — DBSCAN on bitwise WiFi payload +
  timing + RSSI, 89.6% on 22 devices. The most transferable template to BLE.
- furiousMAC/continuity (GitHub) — Apple Continuity protocol reverse engineering;
  the Nearby Info auth tag (3-4 bytes) is the stable per-device ID across MAC
  rotation. PETS 2019 paper proves trackability despite randomized BD_ADDR.
