# ANANTHAM — Technical Report

**AI-Based Virtual Camera Tracking System for Coarse Alignment of Mobile FSOC Terminals**
Smart India Hackathon 2026 · Problem statement SIH26169 (ISRO / Space Applications Centre)

> Every performance number in this report is inserted automatically from benchmark output
> by `tools/insert_results.py` (blocks between `RESULTS` markers). Analytic numbers (geometry,
> bounds) are labelled *analytic*. Anything not measured is written "not yet measured".

---

## 1. Problem understanding

A mobile free-space optical (FSOC) link needs its two terminals to point at each other to
within the fine-steering mirror's capture range before the fine loop can close. The
**coarse** stage must find the partner's beacon in a wide uncertainty region, keep it
centred with a rate-limited pan/tilt unit despite platform motion, camera jitter,
atmospheric effects and sensor noise, and recover after a dropout. SIH26169 asks for an
AI-based *virtual* camera tracking system that exercises exactly this stage in software,
with measurable requirements: acquisition ≤ 2 s, tracking error ≤ 10 px, target loss < 5 %,
re-acquisition ≤ 1 s, processing ≥ 20 FPS, a 640×480 camera at ≥ 30 Hz with a 4°×3° FOV,
5–10 °/s pan/tilt, a ≥ 2000×2000 px screen, 5–20 px beacons, seven motion families, three
noise types, jitter and platform motion up to ±20 px/frame, and atmospheric conditions.
Evaluators will also feed their own MP4 videos, bypassing the PTZ camera.

Our reading of the PS terms:

* **designated target** — the beacon we must track; other beacons are distractors. Its
  nominal size and (optionally) blink code are *designation* data known to the operator.
* **centroiding error** — accuracy of the measured spot centre in the image.
* **tracking error** — pointing error of the boresight w.r.t. the beacon.
* **lock retention / target loss** — fraction of post-acquisition time we are locked on
  the right target with a good centroid.
* **coarse alignment** — bringing the beacon onto the boresight within the tolerances above.

## 2. PAT background

Pointing, Acquisition and Tracking in FSOC is usually split into (i) *open-loop pointing*
from GPS/INS, (ii) *acquisition* — scanning the uncertainty cone until the beacon is seen,
(iii) *coarse tracking* with a gimbal and a wide(ish)-FOV camera (tens to hundreds of
µrad), and (iv) *fine tracking* with a fast-steering mirror and a quadrant detector
(µrad). ANANTHAM covers (ii) and (iii); the hand-off to (iv) is future work. The coarse
loop is limited by the gimbal's slew rate, the camera latency and the image noise; the
atmosphere adds scintillation (intensity fading), angle-of-arrival jitter and beam spread.

## 3. Architecture

See `docs/ARCHITECTURE.md` for diagrams. The loop is PERCEIVE → VALIDATE → PREDICT →
CONTROL → RECOVER:

| stage | module | what it does |
|---|---|---|
| PERCEIVE | `perception/classical.py` | median → top-hat → robust threshold → components → signature → sub-pixel centroid |
| VALIDATE | `perception/cnn.py` | CNN verifier on 64×64 ROIs (ONNX Runtime, CPU); optional heatmap refinement |
| PREDICT | `tracking/*` | tentative tracks, temporal identity gate, blink code, CV Kalman in the pointing frame |
| CONTROL | `control/controller.py` | PID + velocity feed-forward + latency compensation, anti-windup, slew clamp |
| RECOVER | `control/search.py`, `state_machine.py` | COAST → local spiral → global spiral; optional wide-FOV hand-off |

**Sensor boundary (R1).** Ground truth exists only in `sim/` and `metrics/`. The PAT stack
receives a `Frame` (image + commanded pan/tilt). `tests/test_boundary.py` fails if any
perception/tracking/control/PAT module imports the simulator or the metrics, statically or
transitively. The main loop marks the boundary with a banner (`pipeline/session.py`).

**Reproducibility (R4).** Every stochastic process draws from a `numpy.random.SeedSequence`
child of the run seed; OpenCV's noise generator is re-seeded from it on every call. The
config and seed are saved next to every run; `tests/test_determinism.py` checks that the
same seed gives bit-identical frames and a byte-identical per-frame CSV.

## 4. Camera and disturbance models

**Geometry (analytic).** Pinhole: `x − cx = f tan θ`, `f = (W/2)/tan(FOV_h/2)` = 9163.7 px
at the defaults; the nominal IFOV is 4°/640 = 0.00625° = 109.1 µrad/px; 5 °/s at 30 Hz is
26.7 px/frame. The screen is an angular grid with the camera IFOV (2000 px ≙ 12.5°). The
pointing frame ("screen px") is `u = W_s/2 + pan/IFOV`. Pixel centres at `i + 0.5`.

**Screen-edge policy (lesson 12e).** The FOV may extend beyond the screen (padded
background); the pan/tilt range lets the boresight reach every on-screen point, so a target
near the edge is always reachable. Trajectories keep a margin of half a FOV + 20 px.

**Beacon rendering.** A box of size *s* convolved with a Gaussian PSF, integrated exactly
over each pixel using the antiderivative of the normal CDF,
`∫Φ(z)dz = zΦ(z) + φ(z)`, so the spot position is truly sub-pixel. Shapes: square,
rectangle, circle (5× supersampled disc ⊗ PSF), Gaussian. Unit test: the moment centroid of
a noise-free spot recovers the true centre within 0.05 px for 5/10/20 px spots.
**Background**: gradient + low-frequency ripple + a faint star field (clutter, 0.5 stars
per 100×100 px, 8–90 DN, σ 0.55–0.9 px).

**Disturbance order** (section 4.2 of the brief):
1. *Line of sight*: platform offset + camera jitter shift the whole scene.
   Platform types linear (triangle wave), circular, random (bounded, rate-limited), spiral,
   figure-8, with a peak **rate** (≤ 20 px/frame, PS) and an excursion amplitude. Jitter is
   white, uniform in ±J (or Gaussian σ = J/3 clipped).
2. *Beacon*: turbulence per beacon — angle-of-arrival offset (AR(1), τ = 0.1 s),
   log-normal scintillation with scintillation index σ_I², PSF broadening. Presets
   (σ_I², AoA σ px, PSF px): weak (0.05, 0.5, 0.3), moderate (0.2, 1.5, 0.8), strong
   (0.5, 3.0, 1.5).
3. *Image*: atmosphere (transmission/contrast `t`, airlight, blur, rain streaks,
   brightness): haze (0.7, 70 DN, blur 0.7), fog (0.4, 120 DN, blur 1.5), rain (0.8, 40 DN,
   90 streaks), low light (brightness 0.25); then Poisson (gain DN/e⁻; exact below λ = 20 e⁻,
   Gaussian limit above — mean and variance exact), Gaussian (σ ≤ 20 DN), salt & pepper.
4. 8-bit quantisation.

**Test videos (lesson 12h).** `make-video` renders with a *different* optical model
(8× supersampled Moffat β = 3, 1.3× wider, 15 % elliptical) plus random sub-pixel phase,
quantisation and MP4 compression, so the renderer and the centroid do not share a model.

## 5. Perception and AI

**Classical detector.** 3×3 median (kills salt & pepper) → morphological top-hat with a
square kernel ≈ 2.5·s + 4 (29 px for s = 10) → a 4-px border is zeroed (lesson 12b) →
threshold = median + 6·1.4826·MAD on a subsampled top-hat → 8-connected components →
features: area, peak, flux, fill, SNR, edge flag, half-max size `sqrt(A½)` → signature
score = size-match × compactness × brightness, with size-match
`exp(−½(ln(ŝ/s)/0.33)²)`, compactness from fill and aspect ratio, brightness
`1 − exp(−SNR/8)` → intensity-weighted centroid of `(top-hat − threshold)⁺` over the
component window (pixel centres at i + 0.5).

**CNN verifier (section 4.4).** A 6-layer fully convolutional net (28 948 parameters) on a
64×64 ROI with three heads: a *score* (beacon centred within ±6 px or not), a stride-4
centre *heatmap* and sub-cell *offsets* (CenterNet-style) for centroid refinement.
Trained on simulator ROIs with domain randomisation: spot size 3–22 px, 4 shapes, PSF
σ 0.5–2.3 px, log-normal intensity, clutter stars, other beacons, rain streaks, contrast
loss/airlight, blur, low light, Poisson/Gaussian/S&P noise, edge clipping (reflect padding
as at image borders) and 28 % negatives (noise, stars, off-centre beacons, streaks,
elongated blobs). Exported to ONNX, run with ONNX Runtime on one CPU thread. Switchable:
`perception.mode = classical | hybrid | cnn`.

Measured on the held-out 10 % (from `anantham/models/verifier_card.json`):

<!-- RESULTS:cnn -->
| item | value |
|---|---|
| training samples (simulated ROIs) | 60000 (10 % held out) |
| epochs / seed | 12 / 0 |
| parameters | 28948 |
| validation accuracy | 96.53 % |
| precision / recall | 97.87 % / 97.23 % |
| false-positive rate | 5.18 % |
| heatmap localisation error median / P95 | 0.348 / 26.368 px |
| training time (CPU) | 32.1 min |
<!-- /RESULTS:cnn -->

In *hybrid* mode (default) every candidate with size-match ≥ 0.3 is verified; candidates
with p < 0.5 are rejected before tracking. The heatmap centroid is used only for
edge-clipped candidates when `cnn_refine_centroid` is on (the moment centroid is more
accurate for full spots). *CNN-only* mode tiles the frame into overlapping ROIs and uses
the heatmap peaks as detections (ablation only).

**Adaptive spot scale (video).** The first 15 frames are processed with a large kernel
and no size gating; the median half-max size of the strongest compact blob sets *s*, from
which kernels, gates and ROI sizes are derived. Nothing assumes 640×480 or 10 px
(unit-tested on a 960×720 video with 16 px spots).

## 6. Identity gate and Kalman filter

**Tentative tracks.** A track may start only from a non-edge candidate with size-match
≥ 0.7 and score ≥ 0.35; association requires size-match ≥ 0.5. Up to six tentative tracks
run in parallel; CANDIDATE → LOCKED needs **N = 3 consecutive** associations (temporal
identity gate). During confirmation the gate is widened to a *kinematic bound*
(gate base + 1.5 × slew limit per frame), because the measurement noise is not known yet.

**Blink code.** When enabled, the designated beacon dims to 45 % for half of every
period (4 Hz). Over a whole number of periods within ≤ 0.5 s (15 frames at 30 Hz) the
fraction of intensity variance at the code frequency must be ≥ 0.45 with a modulation depth
≥ 0.08; tracks that fail twice are marked *rejected* and kept (so they cannot respawn).

**Kalman filter.** Constant-velocity `[u, v, u̇, v̇]`, dt = 1 frame, in the pointing frame:
the measurement is *commanded pointing + pinhole image offset*, so our own slew cancels
exactly. **Adaptive R**: `σ² = r₀²(1 + (8/SNR)²)` (+ s²/4 for edge-clipped spots), floored
by the *measured* measurement noise — the median of squared second differences of recent
measurements (`E[d²] = 6σ²` for white noise), which is how camera jitter enters R without
the tracker seeing truth. **Adaptive Q**: Q is scaled by the recent mean NIS / 2 (1–25×),
which absorbs smooth manoeuvres. **Manoeuvres**: a strong, signature-matched blob just
outside the gate (up to gate + 2|v| + base, which covers a velocity reversal) is accepted;
the velocity covariance is inflated only if the large innovation *persists* in a consistent
direction or exceeds 8σ of the measured noise — a single jitter spike opens only the
position covariance. **Gate** = max(6 px, s/2) + 3·σ_S, growing during COAST. An IMM stub
fixes the interface for a later CV/CA/CT upgrade.

## 7. Control

Plant: `p[k+1] = p[k] + u[k]` (px/frame). Law per axis:
`aim = x̂ + v̂·L`, `e = aim − p`, `u = g(Kp e + Kd Δe) + Ki ∫e + ff·v̂`, with
`g = 1/(1 + σ_KF/σ₀)` (uncertainty-scaled gains). With ff = 1 the steady-state error to a
constant-velocity target is zero and the error decays as `(1 − g Kp)^k`; a small integrator
(Ki = 0.005, frozen while saturated — anti-windup) removes feed-forward mismatch. A 0.25 px
deadband avoids chatter; the command is clamped per axis to the slew limit (unit-tested:
the camera model can never exceed it). Defaults: Kp 0.55, Kd 0.05, σ₀ 12 px, L = 0 (the
one-frame actuation delay is handled by the feed-forward; L compensates extra latency).

## 8. Acquisition and recovery

**Single-camera spiral (default).** A square spiral from the screen centre in steps of
85 % of the FOV (544×408 px), clipped to the screen, rings chosen so the swept FOV covers
the whole screen (unit-tested). *Analytic* worst-case traversal at 5 °/s: **14.1 s**
(logged per run as `worst_case_spiral_search_s`). A 4°×3° camera cannot guarantee the
2 s acquisition requirement over a 12.5° uncertainty region at 5–10 °/s; we report this
rather than tune around it (lesson 12a) and measure "start inside FOV" separately.

**Optional wide-FOV acquisition sensor** (clearly labelled OPTIONAL in UI and reports): a
fixed sensor on the same platform sees the whole screen at ¼ resolution with the same
disturbances; after 2 consistent detections it hands the position (+ velocity lead) to the
narrow camera, which slews there at the slew limit and must still confirm with N = 3
frames. Rejected hand-offs are placed on a 3 s tabu list.

**Recovery.** COAST follows the Kalman prediction for 0.33 s (velocity damped 15 %/frame
and capped at the slew limit, so a reversal during a dropout cannot run the camera away),
then RECOVER runs a local square spiral (step 0.45 FOV, 2 rings) around the prediction
with a growing gate; re-detections must be re-confirmed (N frames); after 2 s the global
SEARCH resumes.

## 9. Test methodology

* 55 unit/integration tests (renderer, geometry, slew limit, noise statistics, Kalman,
  identity gate and blink code, controller, spiral coverage, config validation, sensor
  boundary, determinism, MP4 round trip and adaptive scale, CNN, GUI smoke test, three
  end-to-end scenarios with reports).
* 34 benchmark scenarios (30 PS-derived + target absent, temporary occlusion, edge
  exit/re-entry, user waypoints), 5 seeds each, 20 s each, both acquisition modes and both
  start modes ("random" anywhere on the screen, "in_fov" within ±30 % of the initial FOV).
* Ablation over 7 cumulative variants on the same scenarios (3 seeds, in-FOV start).
* Processing time = perception + tracking + control wall time on one core (4 benchmark
  processes run in parallel on a 4-core machine; rendering excluded).

## 10. Results

<!-- RESULTS:meta -->
Source: `results/final` — 680 runs, 5 seeds × 20 s, acquisition modes spiral, wide_fov, start modes random, in_fov, perception: config default; ablation 714 runs.
<!-- /RESULTS:meta -->

### 10.1 PS requirements — runs passing each row

<!-- RESULTS:bench_headline -->
| PS requirement | spiral / in_fov | spiral / random | wide_fov / in_fov | wide_fov / random |
|---|---|---|---|---|
| Acquisition ≤ 2 s | 160/165 | 41/165 | 165/165 | 162/165 |
| Centroiding RMSE ≤ 10 px | 165/165 | 165/165 | 165/165 | 165/165 |
| Tracking RMSE (all locked) ≤ 10 px | 131/165 | 35/165 | 128/165 | 36/165 |
| Tracking RMSE (steady) ≤ 10 px | 150/165 | 149/164 | 150/165 | 150/165 |
| Target loss < 5 % | 160/165 | 160/165 | 160/165 | 160/165 |
| Re-acquisition ≤ 1 s | 10/15 | 6/11 | 10/15 | 7/12 |
| Processing ≥ 20 FPS | 170/170 | 170/170 | 170/170 | 170/170 |
| No false lock (target absent) | 5/5 | 5/5 | 5/5 | 5/5 |
| All rows pass | 131/170 | 29/170 | 131/170 | 37/170 |
<!-- /RESULTS:bench_headline -->

### 10.2 Single camera, spiral search, target starts inside the FOV

<!-- RESULTS:bench_spiral_in_fov -->
| scenario | acquired | acq. time s mean / worst | centroid RMSE px (worst) | track RMSE all px mean / worst | track RMSE steady px mean / worst | target loss mean / worst | re-acq max s | re-acq after visible max s | unrec. | false-lock fr. | proc FPS min | all-PS pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stationary | 5/5 | 0.07 / 0.07 | 0.020 | 4.48 / 6.97 | 0.37 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 93 | 100 % |
| straight_slow | 5/5 | 0.07 / 0.07 | 0.020 | 4.52 / 6.72 | 0.44 / 0.46 | 0.00 % / 0.00 % | — | — | 0 | 0 | 90 | 100 % |
| straight_fast | 5/5 | 0.07 / 0.07 | 0.020 | 8.21 / 13.56 | 5.81 / 6.71 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 80 % |
| circular | 5/5 | 0.07 / 0.07 | 0.021 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 100 % |
| figure8 | 5/5 | 0.07 / 0.07 | 0.020 | 5.43 / 8.45 | 0.80 / 0.82 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 100 % |
| random | 5/5 | 0.07 / 0.07 | 0.020 | 4.82 / 7.93 | 1.49 / 1.78 | 0.00 % / 0.00 % | — | — | 0 | 0 | 98 | 100 % |
| spiral | 5/5 | 0.07 / 0.07 | 0.020 | 4.83 / 7.60 | 0.42 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 100 % |
| sinusoidal | 5/5 | 0.07 / 0.07 | 0.020 | 6.96 / 13.91 | 2.03 / 2.15 | 0.00 % / 0.00 % | — | — | 0 | 0 | 106 | 80 % |
| gauss20 | 5/5 | 0.07 / 0.07 | 0.101 | 4.48 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 100 % |
| poisson | 5/5 | 0.07 / 0.07 | 0.048 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 100 % |
| salt_pepper | 5/5 | 0.07 / 0.07 | 0.096 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 91 | 100 % |
| mixed_noise | 5/5 | 0.07 / 0.07 | 0.088 | 4.47 / 7.48 | 0.35 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 100 % |
| haze | 5/5 | 0.07 / 0.07 | 0.028 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 100 % |
| fog | 5/5 | 0.07 / 0.07 | 0.060 | 4.47 / 7.48 | 0.36 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 98 | 100 % |
| rain | 5/5 | 0.07 / 0.07 | 0.049 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 93 | 100 % |
| low_light | 5/5 | 0.07 / 0.07 | 0.056 | 4.47 / 7.48 | 0.35 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 108 | 100 % |
| turb_weak | 5/5 | 0.07 / 0.07 | 0.021 | 4.63 / 7.52 | 0.94 / 1.00 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 100 % |
| turb_moderate | 5/5 | 0.07 / 0.07 | 0.025 | 5.38 / 7.89 | 2.58 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 95 | 100 % |
| turb_strong | 5/5 | 0.07 / 0.07 | 0.038 | 6.97 / 8.99 | 4.99 / 5.31 | 0.00 % / 0.00 % | — | — | 0 | 0 | 102 | 100 % |
| jitter10 | 5/5 | 0.07 / 0.07 | 0.019 | 11.12 / 12.42 | 9.69 / 9.99 | 0.03 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 91 | 20 % |
| jitter20 | 5/5 | 0.08 / 0.13 | 0.020 | 19.80 / 20.75 | 18.57 / 19.16 | 0.10 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 92 | 0 % |
| platform_linear20 | 5/5 | 0.07 / 0.07 | 0.020 | 29.03 / 30.58 | 27.77 / 27.82 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 0 % |
| platform_circular10 | 5/5 | 0.07 / 0.07 | 0.019 | 9.25 / 13.89 | 2.72 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 99 | 40 % |
| distractor | 5/5 | 0.07 / 0.07 | 0.021 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 108 | 100 % |
| target5 | 5/5 | 0.07 / 0.07 | 0.028 | 4.47 / 7.48 | 0.36 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 95 | 100 % |
| target20 | 5/5 | 0.07 / 0.07 | 0.018 | 4.47 / 7.48 | 0.37 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 102 | 100 % |
| blink | 5/5 | 0.47 / 0.47 | 0.028 | 0.40 / 0.44 | 0.35 / 0.38 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 100 % |
| fast_noise | 5/5 | 0.07 / 0.07 | 0.102 | 8.22 / 13.56 | 5.81 / 6.71 | 0.00 % / 0.00 % | — | — | 0 | 0 | 104 | 80 % |
| lowlight_jitter | 5/5 | 0.07 / 0.07 | 0.054 | 11.12 / 12.41 | 9.69 / 9.99 | 0.03 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 104 | 20 % |
| combined | 5/5 | 0.07 / 0.07 | 0.183 | 23.42 / 25.09 | 21.46 / 21.89 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 0 % |
| target_absent | 0/5 | — / — | — | — / — | — / — | — / — | — | — | 0 | 0 | 150 | 100 % |
| occlusion | 5/5 | 0.07 / 0.07 | 0.020 | 4.72 / 7.91 | 0.44 / 0.47 | 2.84 % / 2.84 % | 0.57 | 0.07 | 0 | 0 | 95 | 100 % |
| edge_exit | 5/5 | 0.07 / 0.07 | 0.020 | 6.86 / 6.86 | 1.02 / 1.02 | 13.38 % / 13.38 % | 2.67 | 0.07 | 0 | 0 | 99 | 0 % |
| waypoints | 5/5 | 4.43 / 4.43 | 0.021 | 25.05 / 25.05 | 1.20 / 1.20 | 0.00 % / 0.00 % | — | — | 0 | 0 | 116 | 0 % |
<!-- /RESULTS:bench_spiral_in_fov -->

### 10.3 Single camera, spiral search, random start anywhere on the screen

<!-- RESULTS:bench_spiral_random -->
| scenario | acquired | acq. time s mean / worst | centroid RMSE px (worst) | track RMSE all px mean / worst | track RMSE steady px mean / worst | target loss mean / worst | re-acq max s | re-acq after visible max s | unrec. | false-lock fr. | proc FPS min | all-PS pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stationary | 5/5 | 3.71 / 4.73 | 0.021 | 19.08 / 22.69 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 99 | 20 % |
| straight_slow | 5/5 | 6.35 / 18.17 | 0.020 | 21.07 / 31.03 | 0.50 / 0.61 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 20 % |
| straight_fast | 5/5 | 5.37 / 17.60 | 0.020 | 19.92 / 53.41 | 6.38 / 9.69 | 0.00 % / 0.00 % | — | — | 0 | 0 | 99 | 0 % |
| circular | 5/5 | 5.26 / 14.43 | 0.020 | 18.95 / 30.57 | 0.41 / 0.49 | 0.00 % / 0.00 % | — | — | 0 | 0 | 95 | 20 % |
| figure8 | 5/5 | 2.73 / 4.43 | 0.020 | 14.05 / 18.59 | 0.82 / 0.82 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 20 % |
| random | 5/5 | 8.75 / 19.20 | 0.021 | 34.46 / 86.37 | 1.54 / 1.88 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 20 % |
| spiral | 5/5 | 2.75 / 4.60 | 0.020 | 18.59 / 24.38 | 0.43 / 0.46 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 20 % |
| sinusoidal | 5/5 | 1.81 / 4.50 | 0.020 | 14.33 / 21.21 | 1.83 / 2.07 | 0.00 % / 0.00 % | — | — | 0 | 0 | 99 | 20 % |
| gauss20 | 5/5 | 5.26 / 14.43 | 0.100 | 18.95 / 30.57 | 0.42 / 0.54 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 20 % |
| poisson | 5/5 | 5.26 / 14.43 | 0.049 | 18.95 / 30.57 | 0.40 / 0.51 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 20 % |
| salt_pepper | 5/5 | 5.26 / 14.43 | 0.098 | 18.95 / 30.57 | 0.42 / 0.55 | 0.00 % / 0.00 % | — | — | 0 | 0 | 92 | 20 % |
| mixed_noise | 5/5 | 5.26 / 14.43 | 0.088 | 18.95 / 30.57 | 0.40 / 0.53 | 0.00 % / 0.00 % | — | — | 0 | 0 | 110 | 20 % |
| haze | 5/5 | 5.26 / 14.43 | 0.027 | 18.95 / 30.57 | 0.40 / 0.49 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 20 % |
| fog | 5/5 | 5.26 / 14.43 | 0.059 | 18.95 / 30.57 | 0.40 / 0.51 | 0.00 % / 0.00 % | — | — | 0 | 0 | 117 | 20 % |
| rain | 5/5 | 5.26 / 14.43 | 0.052 | 18.95 / 30.57 | 0.41 / 0.50 | 0.00 % / 0.00 % | — | — | 0 | 0 | 90 | 20 % |
| low_light | 5/5 | 5.26 / 14.43 | 0.055 | 18.95 / 30.57 | 0.39 / 0.49 | 0.00 % / 0.00 % | — | — | 0 | 0 | 111 | 20 % |
| turb_weak | 5/5 | 5.26 / 14.43 | 0.021 | 18.97 / 30.58 | 0.95 / 1.01 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 20 % |
| turb_moderate | 5/5 | 5.26 / 14.43 | 0.025 | 19.15 / 30.66 | 2.57 / 2.74 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 20 % |
| turb_strong | 5/5 | 5.26 / 14.43 | 0.037 | 19.70 / 30.91 | 4.97 / 5.32 | 0.00 % / 0.00 % | — | — | 0 | 0 | 104 | 20 % |
| jitter10 | 5/5 | 5.26 / 14.43 | 0.020 | 21.87 / 32.75 | 9.67 / 9.83 | 0.00 % / 0.00 % | — | — | 0 | 0 | 105 | 0 % |
| jitter20 | 5/5 | 5.27 / 14.43 | 0.020 | 26.32 / 38.04 | 18.48 / 18.75 | 0.08 % / 0.21 % | 0.03 | 0.03 | 0 | 0 | 88 | 0 % |
| platform_linear20 | 5/5 | 5.00 / 13.33 | 0.019 | 35.58 / 43.23 | 27.63 / 27.71 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 0 % |
| platform_circular10 | 5/5 | 5.03 / 13.33 | 0.020 | 20.42 / 48.13 | 2.73 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 113 | 20 % |
| distractor | 5/5 | 5.26 / 14.43 | 0.020 | 18.95 / 30.57 | 0.41 / 0.49 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 20 % |
| target5 | 5/5 | 5.26 / 14.43 | 0.029 | 18.95 / 30.57 | 0.39 / 0.48 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 20 % |
| target20 | 5/5 | 5.26 / 14.43 | 0.018 | 18.95 / 30.57 | 0.40 / 0.49 | 0.00 % / 0.00 % | — | — | 0 | 0 | 102 | 20 % |
| blink | 5/5 | 6.39 / 16.60 | 0.029 | 0.44 / 0.66 | 0.40 / 0.55 | 0.00 % / 0.00 % | — | — | 0 | 0 | 88 | 20 % |
| fast_noise | 5/5 | 5.37 / 17.60 | 0.102 | 19.92 / 53.41 | 6.37 / 9.70 | 0.00 % / 0.00 % | — | — | 0 | 0 | 105 | 0 % |
| lowlight_jitter | 5/5 | 5.26 / 14.43 | 0.054 | 21.87 / 32.75 | 9.67 / 9.83 | 0.00 % / 0.00 % | — | — | 0 | 0 | 118 | 0 % |
| combined | 5/5 | 2.66 / 4.37 | 0.179 | 26.65 / 29.42 | 21.44 / 21.87 | 0.00 % / 0.00 % | — | — | 0 | 0 | 98 | 0 % |
| target_absent | 0/5 | — / — | — | — / — | — / — | — / — | — | — | 0 | 0 | 133 | 100 % |
| occlusion | 5/5 | 5.26 / 14.43 | 0.020 | 19.19 / 30.57 | 0.45 / 0.49 | 2.68 % / 3.56 % | 0.57 | 0.07 | 0 | 0 | 110 | 20 % |
| edge_exit | 5/5 | 0.07 / 0.07 | 0.020 | 6.86 / 6.86 | 1.02 / 1.02 | 13.38 % / 13.38 % | 2.67 | 0.07 | 0 | 0 | 114 | 0 % |
| waypoints | 5/5 | 4.43 / 4.43 | 0.021 | 25.05 / 25.05 | 1.20 / 1.20 | 0.00 % / 0.00 % | — | — | 0 | 0 | 119 | 0 % |
<!-- /RESULTS:bench_spiral_random -->

### 10.4 OPTIONAL wide-FOV acquisition sensor, random start

<!-- RESULTS:bench_wide_random -->
| scenario | acquired | acq. time s mean / worst | centroid RMSE px (worst) | track RMSE all px mean / worst | track RMSE steady px mean / worst | target loss mean / worst | re-acq max s | re-acq after visible max s | unrec. | false-lock fr. | proc FPS min | all-PS pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stationary | 5/5 | 0.36 / 0.50 | 0.021 | 14.35 / 19.73 | 0.35 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 83 | 20 % |
| straight_slow | 5/5 | 0.37 / 0.47 | 0.021 | 14.53 / 20.59 | 0.47 / 0.62 | 0.00 % / 0.00 % | — | — | 0 | 0 | 95 | 20 % |
| straight_fast | 5/5 | 0.42 / 0.77 | 0.020 | 13.74 / 24.32 | 5.60 / 6.93 | 0.00 % / 0.00 % | — | — | 0 | 0 | 92 | 20 % |
| circular | 5/5 | 0.35 / 0.47 | 0.021 | 14.88 / 20.54 | 0.39 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 20 % |
| figure8 | 5/5 | 0.25 / 0.40 | 0.020 | 11.57 / 18.16 | 0.83 / 0.84 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 40 % |
| random | 5/5 | 0.35 / 0.50 | 0.020 | 14.30 / 19.92 | 1.50 / 1.88 | 0.00 % / 0.00 % | — | — | 0 | 0 | 92 | 40 % |
| spiral | 5/5 | 0.23 / 0.37 | 0.021 | 13.59 / 20.23 | 0.45 / 0.50 | 0.00 % / 0.00 % | — | — | 0 | 0 | 113 | 40 % |
| sinusoidal | 5/5 | 0.37 / 0.60 | 0.020 | 14.24 / 25.87 | 1.75 / 2.02 | 0.00 % / 0.00 % | — | — | 0 | 0 | 120 | 40 % |
| gauss20 | 5/5 | 0.35 / 0.47 | 0.099 | 14.88 / 20.54 | 0.39 / 0.45 | 0.00 % / 0.00 % | — | — | 0 | 0 | 118 | 20 % |
| poisson | 5/5 | 0.35 / 0.47 | 0.049 | 14.88 / 20.54 | 0.38 / 0.43 | 0.00 % / 0.00 % | — | — | 0 | 0 | 110 | 20 % |
| salt_pepper | 5/5 | 0.35 / 0.47 | 0.096 | 14.88 / 20.54 | 0.38 / 0.43 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 20 % |
| mixed_noise | 5/5 | 0.35 / 0.47 | 0.088 | 14.87 / 20.54 | 0.37 / 0.43 | 0.00 % / 0.00 % | — | — | 0 | 0 | 105 | 20 % |
| haze | 5/5 | 0.35 / 0.47 | 0.028 | 14.88 / 20.54 | 0.38 / 0.43 | 0.00 % / 0.00 % | — | — | 0 | 0 | 104 | 20 % |
| fog | 5/5 | 0.35 / 0.47 | 0.061 | 14.88 / 20.54 | 0.38 / 0.43 | 0.00 % / 0.00 % | — | — | 0 | 0 | 110 | 20 % |
| rain | 5/5 | 0.36 / 0.50 | 0.049 | 14.49 / 18.59 | 0.39 / 0.42 | 0.00 % / 0.00 % | — | — | 0 | 0 | 91 | 20 % |
| low_light | 5/5 | 0.35 / 0.47 | 0.056 | 14.87 / 20.54 | 0.37 / 0.42 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 20 % |
| turb_weak | 5/5 | 0.35 / 0.47 | 0.021 | 14.90 / 20.55 | 0.94 / 0.99 | 0.00 % / 0.00 % | — | — | 0 | 0 | 116 | 20 % |
| turb_moderate | 5/5 | 0.35 / 0.47 | 0.025 | 15.12 / 20.70 | 2.58 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 106 | 20 % |
| turb_strong | 5/5 | 0.35 / 0.47 | 0.038 | 15.77 / 21.15 | 4.99 / 5.31 | 0.00 % / 0.00 % | — | — | 0 | 0 | 112 | 20 % |
| jitter10 | 5/5 | 0.35 / 0.47 | 0.019 | 18.64 / 23.55 | 9.69 / 9.99 | 0.00 % / 0.00 % | — | — | 0 | 0 | 107 | 0 % |
| jitter20 | 5/5 | 0.36 / 0.47 | 0.020 | 24.49 / 28.48 | 18.54 / 19.14 | 0.07 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 94 | 0 % |
| platform_linear20 | 5/5 | 0.41 / 0.67 | 0.019 | 30.02 / 32.52 | 27.67 / 27.74 | 0.00 % / 0.00 % | — | — | 0 | 0 | 115 | 0 % |
| platform_circular10 | 5/5 | 0.34 / 0.47 | 0.020 | 12.29 / 16.06 | 2.71 / 2.72 | 0.00 % / 0.00 % | — | — | 0 | 0 | 115 | 20 % |
| distractor | 5/5 | 0.36 / 0.47 | 0.021 | 14.56 / 20.54 | 0.39 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 108 | 20 % |
| target5 | 5/5 | 2.54 / 5.63 | 0.028 | 14.92 / 22.48 | 0.40 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 89 | 20 % |
| target20 | 5/5 | 0.35 / 0.47 | 0.018 | 14.88 / 20.54 | 0.39 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 95 | 20 % |
| blink | 5/5 | 1.10 / 2.17 | 0.028 | 1.24 / 4.59 | 0.36 / 0.38 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 80 % |
| fast_noise | 5/5 | 0.41 / 0.73 | 0.101 | 14.23 / 24.33 | 5.58 / 6.84 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 0 % |
| lowlight_jitter | 5/5 | 0.35 / 0.47 | 0.053 | 18.64 / 23.56 | 9.69 / 9.99 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 0 % |
| combined | 5/5 | 0.23 / 0.37 | 0.182 | 24.64 / 28.63 | 21.50 / 22.00 | 0.00 % / 0.00 % | — | — | 0 | 0 | 98 | 0 % |
| target_absent | 0/5 | — / — | — | — / — | — / — | — / — | — | — | 0 | 0 | 82 | 100 % |
| occlusion | 5/5 | 0.35 / 0.47 | 0.020 | 15.15 / 21.03 | 0.44 / 0.48 | 2.88 % / 2.90 % | 0.57 | 0.07 | 0 | 0 | 98 | 20 % |
| edge_exit | 5/5 | 0.07 / 0.07 | 0.020 | 10.79 / 16.73 | 1.04 / 1.06 | 14.28 % / 15.38 % | 3.07 | 0.47 | 0 | 0 | 98 | 0 % |
| waypoints | 5/5 | 0.43 / 0.43 | 0.020 | 13.48 / 13.48 | 1.30 / 1.30 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 0 % |
<!-- /RESULTS:bench_wide_random -->

### 10.5 OPTIONAL wide-FOV acquisition sensor, start inside the FOV

<!-- RESULTS:bench_wide_in_fov -->
| scenario | acquired | acq. time s mean / worst | centroid RMSE px (worst) | track RMSE all px mean / worst | track RMSE steady px mean / worst | target loss mean / worst | re-acq max s | re-acq after visible max s | unrec. | false-lock fr. | proc FPS min | all-PS pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| stationary | 5/5 | 0.07 / 0.07 | 0.020 | 4.48 / 6.97 | 0.37 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 89 | 100 % |
| straight_slow | 5/5 | 0.07 / 0.07 | 0.020 | 4.52 / 6.72 | 0.44 / 0.46 | 0.00 % / 0.00 % | — | — | 0 | 0 | 96 | 100 % |
| straight_fast | 5/5 | 0.07 / 0.07 | 0.020 | 8.21 / 13.56 | 5.81 / 6.71 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 80 % |
| circular | 5/5 | 0.07 / 0.07 | 0.021 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 100 % |
| figure8 | 5/5 | 0.07 / 0.07 | 0.020 | 5.43 / 8.45 | 0.80 / 0.82 | 0.00 % / 0.00 % | — | — | 0 | 0 | 93 | 100 % |
| random | 5/5 | 0.07 / 0.07 | 0.020 | 4.82 / 7.93 | 1.49 / 1.78 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 100 % |
| spiral | 5/5 | 0.07 / 0.07 | 0.020 | 4.83 / 7.60 | 0.42 / 0.44 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 100 % |
| sinusoidal | 5/5 | 0.07 / 0.07 | 0.020 | 6.96 / 13.91 | 2.03 / 2.15 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 80 % |
| gauss20 | 5/5 | 0.07 / 0.07 | 0.101 | 4.48 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 100 % |
| poisson | 5/5 | 0.07 / 0.07 | 0.048 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 112 | 100 % |
| salt_pepper | 5/5 | 0.07 / 0.07 | 0.096 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 97 | 100 % |
| mixed_noise | 5/5 | 0.07 / 0.07 | 0.088 | 4.47 / 7.48 | 0.35 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 100 | 100 % |
| haze | 5/5 | 0.07 / 0.07 | 0.028 | 4.47 / 7.48 | 0.37 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 104 | 100 % |
| fog | 5/5 | 0.07 / 0.07 | 0.060 | 4.47 / 7.48 | 0.36 / 0.40 | 0.00 % / 0.00 % | — | — | 0 | 0 | 111 | 100 % |
| rain | 5/5 | 0.07 / 0.07 | 0.051 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 90 | 100 % |
| low_light | 5/5 | 0.07 / 0.07 | 0.056 | 4.47 / 7.48 | 0.35 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 100 % |
| turb_weak | 5/5 | 0.07 / 0.07 | 0.021 | 4.63 / 7.52 | 0.94 / 1.00 | 0.00 % / 0.00 % | — | — | 0 | 0 | 119 | 100 % |
| turb_moderate | 5/5 | 0.07 / 0.07 | 0.025 | 5.38 / 7.89 | 2.58 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 106 | 100 % |
| turb_strong | 5/5 | 0.07 / 0.07 | 0.038 | 6.97 / 8.99 | 4.99 / 5.31 | 0.00 % / 0.00 % | — | — | 0 | 0 | 118 | 100 % |
| jitter10 | 5/5 | 0.07 / 0.07 | 0.019 | 11.12 / 12.42 | 9.69 / 9.99 | 0.03 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 101 | 20 % |
| jitter20 | 5/5 | 0.08 / 0.13 | 0.020 | 19.80 / 20.75 | 18.57 / 19.16 | 0.10 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 101 | 0 % |
| platform_linear20 | 5/5 | 0.07 / 0.07 | 0.020 | 29.03 / 30.58 | 27.77 / 27.82 | 0.00 % / 0.00 % | — | — | 0 | 0 | 101 | 0 % |
| platform_circular10 | 5/5 | 0.07 / 0.07 | 0.019 | 9.25 / 13.89 | 2.72 / 2.73 | 0.00 % / 0.00 % | — | — | 0 | 0 | 102 | 40 % |
| distractor | 5/5 | 0.07 / 0.07 | 0.021 | 4.47 / 7.48 | 0.38 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 106 | 100 % |
| target5 | 5/5 | 0.07 / 0.07 | 0.028 | 4.47 / 7.48 | 0.36 / 0.39 | 0.00 % / 0.00 % | — | — | 0 | 0 | 98 | 100 % |
| target20 | 5/5 | 0.07 / 0.07 | 0.018 | 4.47 / 7.48 | 0.37 / 0.41 | 0.00 % / 0.00 % | — | — | 0 | 0 | 115 | 100 % |
| blink | 5/5 | 0.47 / 0.47 | 0.028 | 0.40 / 0.44 | 0.35 / 0.38 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 100 % |
| fast_noise | 5/5 | 0.07 / 0.07 | 0.102 | 8.22 / 13.56 | 5.81 / 6.71 | 0.00 % / 0.00 % | — | — | 0 | 0 | 103 | 80 % |
| lowlight_jitter | 5/5 | 0.07 / 0.07 | 0.054 | 11.12 / 12.41 | 9.69 / 9.99 | 0.03 % / 0.17 % | 0.03 | 0.03 | 0 | 0 | 99 | 20 % |
| combined | 5/5 | 0.07 / 0.07 | 0.183 | 23.42 / 25.09 | 21.46 / 21.89 | 0.00 % / 0.00 % | — | — | 0 | 0 | 94 | 0 % |
| target_absent | 0/5 | — / — | — | — / — | — / — | — / — | — | — | 0 | 0 | 82 | 100 % |
| occlusion | 5/5 | 0.07 / 0.07 | 0.020 | 4.72 / 7.91 | 0.44 / 0.47 | 2.84 % / 2.84 % | 0.57 | 0.07 | 0 | 0 | 95 | 100 % |
| edge_exit | 5/5 | 0.07 / 0.07 | 0.020 | 10.79 / 16.73 | 1.04 / 1.06 | 14.28 % / 15.38 % | 3.07 | 0.47 | 0 | 0 | 100 | 0 % |
| waypoints | 5/5 | 0.43 / 0.43 | 0.020 | 13.48 / 13.48 | 1.30 / 1.30 | 0.00 % / 0.00 % | — | — | 0 | 0 | 99 | 0 % |
<!-- /RESULTS:bench_wide_in_fov -->

## 11. Ablation

<!-- RESULTS:ablation -->
| variant | runs | acquired | centroid RMSE px | steady track RMSE px (mean/worst) | target loss (mean/worst) | re-acq events/run | re-acq max s | unrecovered runs | wrong-target frames/run | false-lock frames (target absent) | proc FPS | all-PS pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| classical_only | 102 | 100% | 140.282 | 28.86 / 958.75 | 25.05% / 100.00% | 15.6 | 7.37 | 18 | 40.4 | 275.0 | 134 | 2% |
| classical_kalman | 102 | 100% | 182.322 | 53.72 / 964.20 | 27.00% / 100.00% | 25.5 | 1.37 | 17 | 49.4 | 409.0 | 152 | 2% |
| cnn_only | 102 | 100% | 195.886 | 10.57 / 27.97 | 28.86% / 99.83% | 17.9 | 2.97 | 33 | 15.4 | 65.7 | 10 | 0% |
| hybrid | 102 | 100% | 33.927 | 10.54 / 28.12 | 21.70% / 100.00% | 14.5 | 6.87 | 24 | 1.1 | 16.0 | 112 | 2% |
| hybrid_gate | 102 | 100% | 0.040 | 10.53 / 28.10 | 18.11% / 97.32% | 11.7 | 6.93 | 20 | 0.0 | 0.0 | 136 | 29% |
| hybrid_gate_ff | 102 | 100% | 0.040 | 4.87 / 38.51 | 1.51% / 31.44% | 1.0 | 2.67 | 2 | 0.0 | 0.0 | 136 | 76% |
| full | 102 | 100% | 0.040 | 3.74 / 27.82 | 0.49% / 13.38% | 0.1 | 2.67 | 0 | 0.0 | 0.0 | 129 | 76% |
<!-- /RESULTS:ablation -->

Note on provenance: the *hybrid* row was re-run (same scenarios and seeds) after the
first ablation pass showed it identical to *classical_kalman*. Cause: the CNN verifier only
checked candidates passing a loose size prefilter (size-match ≥ 0.3), which is part of the
identity gate; with the gate off, clutter stars bypassed the verifier. The verifier now
checks every candidate whenever the identity gate is off. Variants with the gate on
(including *full* and the main benchmark) are unaffected by this change.

Reading the table: the CNN verifier removes most clutter locks (wrong-target and
target-absent false-lock frames); the temporal identity gate removes the rest; prediction /
feed-forward and manoeuvre handling cut steady error and loss; adaptive R/Q,
uncertainty-scaled gains and the local recovery spiral remove the remaining unrecovered
runs. CNN-only perception is ~10 FPS on one CPU core — below the 20 FPS requirement.

Variants (cumulative): *classical_only* (no Kalman, no identity gate, no feed-forward, no
local recovery) · *classical_kalman* · *cnn_only* (CNN detections + Kalman) · *hybrid*
(classical + CNN verifier + Kalman) · *hybrid_gate* (+ temporal identity gate, signature
checks, blink code) · *hybrid_gate_ff* (+ feed-forward, manoeuvre handling) · *full*
(+ adaptive R/Q, uncertainty-scaled gains, local recovery spiral).

## 12. Failure analysis

Worst scenario groups (lowest all-PS pass rate first):

<!-- RESULTS:worst -->
| scenario | acq / start | pass rate | worst steady RMSE px | worst loss | worst acq. s |
|---|---|---|---|---|---|
| edge_exit | wide_fov / in_fov | 0 % | 1.06 | 15.38 % | 0.07 |
| edge_exit | wide_fov / random | 0 % | 1.06 | 15.38 % | 0.07 |
| edge_exit | spiral / in_fov | 0 % | 1.02 | 13.38 % | 0.07 |
| edge_exit | spiral / random | 0 % | 1.02 | 13.38 % | 0.07 |
| jitter20 | spiral / random | 0 % | 18.75 | 0.21 % | 14.43 |
| jitter20 | wide_fov / random | 0 % | 19.14 | 0.17 % | 0.47 |
| jitter20 | spiral / in_fov | 0 % | 19.16 | 0.17 % | 0.13 |
| jitter20 | wide_fov / in_fov | 0 % | 19.16 | 0.17 % | 0.13 |
<!-- /RESULTS:worst -->

What limits each failing case (bounds are *analytic*; measured values are in the tables):

* **Random-start acquisition with one camera.** The spiral needs up to 14.1 s (analytic)
  to sweep 12.5°×12.5° at 5 °/s; moving targets can additionally evade a pass. The 2 s
  requirement is only achievable with prior pointing knowledge (target inside the FOV) or
  a wider-FOV acquisition sensor — both measured above.
* **Tracking error over *all* locked frames.** Includes the pull-in after lock: the target
  may lock up to ~⅓ FOV off-centre, and at 26.7 px/frame the gimbal needs several frames to
  centre it. The steady-state figure (≥ 1 s after lock) isolates the tracking quality.
* **Camera jitter ±10 / ±20 px/frame.** White jitter is a real line-of-sight error that no
  controller with a one-frame delay can cancel. For uniform ±J jitter the per-frame radial
  pointing error has RMS ≥ J·√(2/3) = 8.2 px (J = 10) and 16.3 px (J = 20) — the
  steady-state errors measured sit just above these floors. The jitter-free error
  (reported separately, never used for PASS/FAIL) shows what the loop controls.
* **Linear platform ±20 px/frame.** The platform LOS reverses at 20 px/frame every
  ~12 frames while the gimbal can slew 26.7 px/frame: after each reversal the error grows at
  up to 40 px/frame for the detection delay and closes at only ~6.7 px/frame (analytic),
  so the mean error is dominated by slew physics, not by estimation. Lock is kept.
* **Everything combined.** Jitter (R grows) and a rotating platform (velocity changes
  every frame) pull the CV filter in opposite directions; the residual is estimation lag.
  An IMM (CV + CT) is the planned fix.
* **Edge exit / occlusion.** Frames with the target off-screen or hidden count as lost by
  definition; the re-acquisition *after the target is visible again* is reported
  separately.
* **CNN-only perception** (ablation) is too slow for 20 FPS on one CPU core with frame
  tiling, and without the identity gate it false-locks on clutter.

## 13. Limitations (simulation vs hardware)

* Rendered images: no rolling shutter, no motion blur during slews, no detector
  non-uniformity, hot pixels or blooming; turbulence is a phenomenological model (log-normal
  scintillation, AR(1) angle of arrival), not a phase-screen simulation.
* Gimbal: ideal rate source with slew limit and optional delay — no acceleration limit,
  backlash, resonance or encoder quantisation.
* Pan/tilt are treated as independent small-angle axes; the wide-FOV sensor uses an
  f-θ (angular) projection.
* The CNN is trained on simulated data only; its benefit on real imagery must be
  re-measured.
* Processing-time numbers come from a 4-core cloud VM with four benchmark processes in
  parallel; on the GUI the displayed processing time also includes CPU contention with
  drawing.
* The Windows executable is built by CI on tags; a clean-machine test must be performed on a
  real Windows PC (this could not be done in the development container).

## 14. Future work

Real camera and gimbal drivers behind the same `FrameSource`; hand-off to a fine-pointing
loop (FSM + quadrant detector); IMM (CV/CA/CT) filtering; image registration on background
clutter to separate LOS jitter from target motion; acceleration-limited gimbal model;
phase-screen turbulence; CNN fine-tuning on recorded field data; GPU inference for the
CNN-only detector.
