# ANANTHAM — User Manual

ANANTHAM is a software laboratory for the **coarse alignment** stage of Pointing,
Acquisition and Tracking (PAT) for mobile FSOC terminals (SIH26169). It simulates a
rate-limited pan/tilt camera looking at a virtual screen with one or more optical
beacons, disturbs the image the way real optics and atmosphere do, and runs a closed
loop PERCEIVE → VALIDATE → PREDICT → CONTROL → RECOVER. In **Evaluator MP4** mode it
bypasses the PTZ camera and runs the same perception and tracking stack on your video.

---

## 1. Installation

### Windows executable (no Python needed)
1. Unzip `ANANTHAM-windows.zip`.
2. Double-click `ANANTHAM\ANANTHAM.exe` — the GUI opens.
3. The same executable accepts CLI commands from a terminal, e.g.
   `ANANTHAM.exe run --preset fog --seed 3 --out results`.

### From source (Windows / Linux / macOS, Python ≥ 3.11)
```bash
pip install -r requirements.txt
pip install -e .
anantham gui
```
Linux needs the Qt system libraries (`libegl1 libxkbcommon0 libfontconfig1`).
Training the CNN additionally needs `torch` and `onnx` (not needed to run).

## 2. First run (2 minutes)

1. `anantham gui` (or double-click the .exe).
2. Leave **SIMULATION** selected, choose scenario **circular**, seed **0**, press **▶ Start**.
3. Watch the camera view: the state label turns cyan (CANDIDATE) and then green (LOCKED);
   the cyan box is the measured centroid, the orange ellipse the Kalman prediction ±1σ.
4. When the run ends (20 s by default) press **Export Report** → a folder under
   `results/gui/` with CSV logs, JSON summary and the PDF report.

## 3. The console

### Top bar
| control | function |
|---|---|
| SIMULATION / EVALUATOR MP4 | mode toggle |
| ▶ Start / ⏸ Pause / ⏭ Step / ⟲ Reset | run control (Step advances exactly one frame) |
| Scenario | loads any preset (default + every benchmark scenario) into the configuration panel |
| Seed | random seed; the same config + seed reproduces the same frames bit-for-bit |
| Speed | 0.25×–4× of real time (limited by the machine for fast settings) |
| Export Report | writes CSV / JSON / PDF of the current run |
| Blind mode | hides every truth overlay (always ON in MP4 mode) |

### Camera view (left)
Overlays, each togglable: boresight cross, measured centroid (cyan box), Kalman prediction
+1σ ellipse (orange), predicted track (dotted orange), rejected candidates (grey ×), true
position (green dot — simulation only, hidden in blind mode; other beacons grey).

### Scene minimap (below)
The whole 2000×2000 screen: camera FOV rectangle (cyan), global search path (dashed),
true target trail (green, simulation only), estimated trail (orange).
**Click** on the minimap to set a user-defined target start position.

### Telemetry cards (right)
STATE (SEARCH red, CANDIDATE cyan, LOCKED green, COAST/RECOVER amber), the px↔angle
conversion line, centroiding error (px, µrad), tracking error, acquisition time,
re-acquisition count and last time, lock retention %, target loss %, processing FPS and ms,
pan/tilt angle and rate, target SNR and candidate count. Values are green/red against the
PS thresholds.

### Live plots (bottom, scrolling 30 s)
Centroiding error with the 10 px PS line (tracking error overlaid), processing FPS with the
20 FPS line, pan/tilt rates with the ±slew-limit lines, state timeline strip.

### Configuration panel (left dock)
Tabs **Scene & Camera**, **Target**, **Disturbances**, **Tracker**, **Run**. Every field
shows its PS range; a value outside the PS range turns **red** and the reason is listed
under the panel. Starting with out-of-range values asks for confirmation (physically
impossible values are refused).

### Extra tabs
* **Perception Debug** — raw, 3×3 median, top-hat, threshold mask, CNN heatmap of the best
  candidate, and a candidate table (score, size-match, SNR, CNN probability, accepted /
  rejected + reason).
* **Benchmark** — tick scenarios, choose seeds / duration / acquisition mode / start mode,
  **Run benchmark** (background thread; the UI never blocks), results table coloured
  PASS/FAIL, **Open report**.
* **Evaluator MP4** — see section 5.

## 4. Parameter reference (PS defaults and ranges)

| group | parameter | default | PS range / note |
|---|---|---|---|
| camera | screen | 2000×2000 px | ≥ 2000×2000 |
| camera | resolution | 640×480 | 640×480 |
| camera | FOV | 4°×3° | user-defined |
| camera | frame rate | 30 Hz | ≥ 30 Hz |
| camera | colour | off (monochrome FPA) | colour optional |
| camera | max pan / tilt speed | 5 °/s | 5–10 °/s |
| camera | control update | 30 Hz | ≥ 20 Hz |
| camera | initial position | screen centre | — |
| target | number of targets | 1 | 1 mandatory, more optional (distractors) |
| target | shape | square | square / rectangle / circle / gaussian |
| target | size | 10×10 px | 5–20 px |
| target | initial location | random | random / centre / in FOV / user (minimap click) |
| target | motion | circular | stationary, straight, circular, figure-8, random, spiral, sinusoidal, waypoints |
| target | blink code | off | designated beacon dims at a known frequency (identity) |
| noise | salt & pepper | off, 10 % | ~10 % of image |
| noise | Gaussian σ | on, 2 DN | max 20 (user-defined) |
| noise | Poisson | on, gain 0.1 DN/e⁻ | selectable |
| jitter | camera jitter | 0 | up to ±20 px/frame |
| atmosphere | preset | clear | clear, haze, fog, rain, low light (+ contrast/brightness sliders) |
| turbulence | preset | none | weak / moderate / strong / custom (scintillation, AoA, PSF) |
| platform | motion, rate | none | linear, circular, random, spiral, figure-8; up to ±20 px/frame |
| tracker | acquisition | spiral | spiral (single camera) / wide_fov (OPTIONAL separate sensor) |
| tracker | perception | hybrid | classical / hybrid (classical + CNN) / cnn |

**Geometry.** At the defaults 1 px = 0.00625° ≈ 109.1 µrad, and 5 °/s at 30 Hz ≈ 26.7 px/frame.
**Platform rate interpretation.** "±20 px/frame" is implemented as the *peak rate* of the
platform line-of-sight motion (px per frame), with a separate excursion amplitude.
**Screen-edge policy.** The FOV may extend beyond the screen (padded background); the
boresight can reach every on-screen position.

## 5. Evaluator MP4 workflow

1. Select **EVALUATOR MP4**, open the **Evaluator MP4** tab, **Browse…** for the video
   (any resolution / frame rate; colour is converted to grey). A `<video>_truth.csv` next to
   the video is picked up automatically.
2. Optional truth CSV: `frame,time_s,x_px,y_px[,visible]`, pixel centres at `i + 0.5`.
3. Set the FOV of your camera in **Scene & Camera** (used for px↔angle and the virtual
   slew limits). The spot size is estimated automatically from the first 15 frames
   (adaptive scale); nothing assumes 640×480 or 10 px.
4. **Run on video**. Detected resolution, fps and spot scale are shown.
5. **Export per-frame centroid CSV…** → `frame,time_s,x_px,y_px,state,confidence`
   (empty x/y when no confirmed measurement).

CLI equivalent:
```bash
anantham video --input eval.mp4 [--truth truth.csv] --out results/
anantham make-video --preset fog --duration 10 --out test.mp4   # synthetic video + truth CSV
```

## 6. CLI

```bash
anantham gui
anantham run --preset circular --seed 3 --duration 20 --out results/ [--acq wide_fov] [--start in_fov]
anantham run --preset default --set target.size_px=15 --set disturbances.jitter_px=10
anantham video --input eval.mp4 [--truth truth.csv] --out results/
anantham bench --scenarios all --seeds 5 --out results/ [--acq both] [--start both] [--ablation]
anantham make-video --preset fog --out test.mp4
anantham train --samples 60000 --epochs 12          # needs torch
```

## 7. Reading the reports

Each run writes:

| file | content |
|---|---|
| `<name>_report.pdf` | PS PASS/FAIL table, metric table, full config, error histograms, error vs time, state timeline, processing FPS, pan/tilt rates, seed |
| `<name>_summary.json` | every metric (definitions in `docs/METRICS.md`) + PASS/FAIL rows |
| `<name>_frames.csv` | per-frame state, measurement, prediction, truth, errors, pan/tilt |
| `<name>_timing.csv` | per-frame processing and render time |
| `<name>_centroids.csv` | evaluator format |
| `<name>_config.yaml` | exact config + seed (re-run with `--preset <that file>`) |
| `<name>.log` | px↔angle line, kernel sizes, analytic worst-case search time, state transitions |

The benchmark writes `benchmark_runs.csv`, `benchmark_summary.csv/.md` and a combined
`benchmark_report.pdf` (scenario matrix, PASS green / FAIL red, worst case highlighted).
Tracking error is always reported for *all locked frames* and *steady state* (≥ 1 s after
the latest (re)lock); detection coverage is always shown next to accuracy.

## 8. Troubleshooting

| symptom | fix |
|---|---|
| GUI does not start on Linux (`libEGL.so.1`) | install `libegl1 libxkbcommon0 libfontconfig1` |
| "CNN model not found" | the ONNX file must be at `anantham/models/verifier.onnx`; or set Tracker → perception mode = classical |
| Speed 4× runs slower than 4× | the machine is the limit; simulation time stays correct, only wall pacing differs |
| Acquisition > 2 s with random start | expected for a single 4° camera on a 12.5° screen (see technical report); use `acquisition.mode = wide_fov` |
| MP4 not locking | check the FOV setting and the detected spot scale; very large or defocused spots need `perception.expected_size_px` |
| Configuration refused on the CLI | a value is outside the PS range; add `--allow-out-of-spec` if intended |
