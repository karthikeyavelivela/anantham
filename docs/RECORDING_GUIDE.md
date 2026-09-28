# ANANTHAM — Screen-recording walkthrough (for a YouTube demo)

A click-by-click script for an 8–10 minute recording that shows every part of the system.
Timings are approximate; pause the recording between scenes if you need to.

---

## 0 · Before you record (10 minutes, once)

### 0.1 Get the application

**Option A — Windows executable (recommended for the video, no Python needed)**

1. Sign in to GitHub and download
   [`ANANTHAM-windows.zip`](https://github.com/karthikeyavelivela/anantham/actions/runs/36458602000/artifacts/10986039020).
2. Unzip it to a short path, e.g. `C:\ANANTHAM\`. You get `C:\ANANTHAM\ANANTHAM\ANANTHAM.exe`.
3. Double-click `ANANTHAM.exe` once to check it opens (Windows SmartScreen may ask:
   *More info → Run anyway*, because the exe is not code-signed). Close it again.

**Option B — from source**

```bash
git clone https://github.com/karthikeyavelivela/anantham.git
cd anantham
pip install -r requirements.txt
pip install -e .
anantham gui
```

In the steps below, `ANANTHAM.exe <command>` and `anantham <command>` are interchangeable.

### 0.2 Prepare the demo files

Open **Command Prompt** in the folder that contains `ANANTHAM.exe`
(in Explorer: click the address bar, type `cmd`, press Enter) and run:

```bat
ANANTHAM.exe make-video --preset fog --duration 20 --seed 1 --out demo\fog_eval.mp4
ANANTHAM.exe run --preset combined --seed 1 --start in_fov --out demo --name combined_demo
```

This creates:

| file | used in |
|---|---|
| `demo\fog_eval.mp4` + `demo\fog_eval_truth.csv` | Scene 7 (Evaluator MP4 mode) |
| `demo\combined_demo_report.pdf` (+ CSV / JSON / log) | Scene 9 (reports) |

Also keep open in a browser tab: the repository README and
[`docs/results/benchmark_report.pdf`](results/benchmark_report.pdf) (Scene 9).

### 0.3 Recording set-up

* Screen **1920×1080**, Windows display scaling **100 %** (Settings → Display) so the
  console is sharp. At 1366×768 everything still fits, only smaller.
* Close notifications and other windows. Maximise ANANTHAM (double-click its title bar).
* Recorder: **OBS Studio** (free) → *Display Capture*, 1920×1080, 30 fps, MKV or MP4,
  microphone on. Windows alternative: **Xbox Game Bar** (`Win + Alt + R` starts/stops).
* Keep the playback **Speed = 1×** so the video shows real time.

---

## 1 · Opening (≈ 30 s)

**Show:** the README on GitHub (top screenshot), then double-click `ANANTHAM.exe`.

**Say:** *"This is ANANTHAM, our solution to SIH26169 — an AI-based virtual camera tracking
system for coarse alignment of mobile free-space optical terminals. It simulates a
rate-limited pan-tilt camera, a moving laser beacon and real-world disturbances, and runs a
closed loop: perceive, validate, predict, control, recover."*

**Point at:** title bar *ANANTHAM — FSOC Coarse Alignment Console*, the four areas:
configuration dock (left), camera view + minimap (middle), telemetry cards (right),
live plots (bottom).

## 2 · The configuration panel (≈ 45 s)

1. Left dock → tab **Scene & Camera**. Point at *Screen 2000 × 2000*, *Res 640 × 480*,
   *FOV 4° × 3°*, *Fps 30*, *Max pan/tilt rate 5 °/s*, *Control rate 30 Hz*, and the grey
   **PS** labels next to each field.
2. Tab **Target**: *Size 10*, *Shape square*, *Start random*, *Motion circular*.
3. Show validation: set **Size (px)** to `25` → the field turns **red** and the reason
   appears under the panel (*outside PS range 5–20*). Set it back to `10`.
4. Point at the telemetry line under the state label:
   *1 px = 0.00625° ≈ 109.1 µrad | 5 °/s at 30 Hz ≈ 26.7 px/frame*.

**Say:** *"Every parameter in the problem statement is editable with its PS default and
range, and out-of-range values are flagged."*

## 3 · Acquisition from a random start (≈ 60 s)

1. **Scenario** dropdown → `circular`. **Seed** = `0`. Target tab → **Start** = `random`.
2. Press **▶ Start**.
3. The state is **SEARCH** (red). Point at the **minimap**: the cyan FOV box moves along the
   dashed square spiral from the screen centre; the green arc is the true target (simulation
   only).
4. When the beacon enters the view: **CANDIDATE** (cyan) → **LOCKED** (green) after three
   consistent detections. Point at *Acquisition time* on the cards.

**Say:** *"With one 4-degree camera the target can be anywhere on a 12.5-degree screen, so
we run a spiral search at the slew limit. Our analysis shows a full sweep needs up to 14
seconds, so the 2-second requirement cannot be met from a random start with one camera — we
report that honestly, and we measured an optional wide-field acquisition sensor that
does meet it."*

## 4 · Steady tracking (≈ 60 s)

1. Press **⟲ Reset**. Target tab → **Start** = `in_fov`. Press **▶ Start**.
2. It locks almost immediately. Point at:
   * camera view — **cyan box** (measured centroid), **orange ellipse** (Kalman prediction
     ±1σ) and dotted **predicted track**, **green dot** (truth);
   * cards — *Centroiding error* (≈ 0.02 px ≈ 2 µrad), *Tracking error*, *Lock retention*,
     *Target loss*, *Processing FPS* (well above 20);
   * plots — error under the red **10 px** line, FPS above the **20 FPS** line, pan/tilt rate
     inside the **±5 °/s** limit lines, green state timeline.
3. Press **⏸ Pause**, then **⏭ Step** three times to show frame-by-frame operation, then
   **▶ Start** to resume.

**Say:** *"The Kalman filter runs in the gimbal-compensated frame, so our own slew cancels
exactly; the controller uses velocity feed-forward within the actuator limits."*

## 5 · Disturbances, blind mode (≈ 75 s)

1. **Reset**. Scenario → `combined`. Target tab → **Start** = `in_fov`. **▶ Start**.
2. Open the **Disturbances** tab in the dock: point at Gaussian σ 10, Poisson, salt & pepper
   5 %, haze, turbulence *moderate*, jitter 10 px/frame, platform *circular* 10 px/frame.
3. Point at the noisy camera image and at the grey **×** marks (rejected clutter).
4. Click **Blind: OFF** → it becomes **Blind: ON** and the green truth dot disappears.

**Say:** *"Everything combined: noise, haze, turbulence, camera jitter and platform motion.
Blind mode hides every truth overlay — the tracker never sees ground truth; a unit test
enforces that boundary. The tracking-error card is red here: white camera jitter is a real
pointing error that no controller can cancel, and we report it rather than hide it."*

5. Click **Blind: ON** again to turn it off.

## 6 · Identity and perception (≈ 75 s)

1. **Reset**. Scenario → `blink`. Target tab → **Start** = `in_fov`. **▶ Start**.
2. Point at the **Target** tab: *Number of targets 2*, *Blink → Enabled*, *Freq 4 Hz*.
   Acquisition takes ≈ 0.5 s — the time to verify the blink code.
3. Open the **Perception Debug** tab: raw → 3×3 median → top-hat → threshold mask, the **CNN
   heatmap**, and the candidate table (*score, size match, SNR, CNN p, tracker used/rejected,
   reason*).
4. **Reset**, Scenario → `rain`, Start = `in_fov`, **▶ Start**, stay on Perception Debug:
   rain streaks and stars appear in the table as *rejected — size-mismatch*.

**Say:** *"A same-size distractor can only be separated by identity, so the designated beacon
carries a blink code verified in half a second. Every candidate goes through a classical
detector and a CNN verifier, and the table shows exactly why each blob was accepted or
rejected."*

## 7 · Evaluator MP4 mode (≈ 60 s)

1. **Reset**. Click **EVALUATOR MP4** in the top bar (blind mode switches ON automatically).
2. **Evaluator MP4** tab → **Browse…** next to *MP4 file* → select `demo\fog_eval.mp4`.
   The truth CSV next to it is filled in automatically.
3. Press **Run on video**, then switch to the **Tracking** tab to watch it lock.
4. When it finishes (20 s), go back to **Evaluator MP4**: *Detected 640×480 @ 30 fps — spot
   scale ≈ 9.4 px (adaptive)* and *Per-frame centroids: …_centroids.csv*.
5. Click **Export per-frame centroid CSV…**, save it, and open it in Notepad/Excel to show the
   columns `frame,time_s,x_px,y_px,state,confidence`.

**Say:** *"For evaluation we bypass the PTZ camera: any MP4, any resolution. The spot size is
estimated automatically and the same perception and tracking stack runs on the video."*

## 8 · Benchmark from the GUI (≈ 45 s)

1. Click **SIMULATION**, open the **Benchmark** tab.
2. Tick `circular`, `fog`, `jitter10`, `blink`; *seeds* `1`, *s* `10`, *acq* `spiral`,
   *start* `in_fov`. Press **Run benchmark** (runs in the background; the progress bar fills).
3. The results table appears, green/red against the PS thresholds. Press **Open report**.

**Say:** *"The full benchmark is 34 scenarios, 5 seeds each, both acquisition modes and both
start modes — 680 runs — plus a 714-run ablation."*

## 9 · Reports and results (≈ 60 s)

1. Top bar **Export Report** (after any run) → a dialog lists the written files in
   `results\gui\...`. Open the folder in Explorer.
2. Open `demo\combined_demo_report.pdf`: page 1 **PS PASS/FAIL** table and measured metrics,
   the configuration pages, and the plots page (histograms, error vs time, FPS, state
   timeline).
3. Open `docs/results/benchmark_report.pdf` (or the README **Measured results** section):
   the scenario matrix with the worst case highlighted, and the ablation table.

**Say:** *"Every number is logged automatically and reproducible from its seed. Our
benchmark shows centroiding error below 0.2 pixels in every run, zero false locks, and over
80 processing FPS — and it shows exactly where the requirements are not met and why."*

## 10 · Command line (optional, ≈ 30 s)

In Command Prompt:

```bat
ANANTHAM.exe run --preset circular --seed 3 --duration 10 --out demo
```

Show the printed summary with **[PASS]/[FAIL]** rows and the list of written files.

## 11 · Closing (≈ 15 s)

**Say:** *"ANANTHAM — simulation, perception with a CNN verifier, identity, prediction,
control and recovery, evaluated honestly against every PS requirement. Source code, the
Windows executable and the full technical report are on GitHub."* Show the repository page.

---

## YouTube upload template

**Title:** ANANTHAM — AI Virtual Camera Tracking for FSOC Coarse Alignment | SIH 2026 (SIH26169)

**Description:**

```
ANANTHAM is our solution to Smart India Hackathon 2026 problem statement SIH26169
(ISRO / Space Applications Centre): an AI-based virtual camera tracking system for coarse
alignment of mobile Free Space Optical Communication terminals.

Code, Windows executable and technical report: https://github.com/karthikeyavelivela/anantham

Chapters
0:00 Introduction
0:30 Configuration and PS parameters
1:15 Acquisition from a random start (spiral search)
2:15 Steady tracking, Kalman prediction, controller
3:15 Disturbances: noise, haze, turbulence, jitter, platform — blind mode
4:30 Identity (blink code) and perception debug (CNN verifier)
5:45 Evaluator MP4 mode — bypass the PTZ camera
6:45 Benchmark
7:30 Reports and results
8:30 Command line
9:00 Closing
```

Adjust the chapter times to your recording.

## Troubleshooting while recording

| problem | fix |
|---|---|
| SmartScreen blocks the exe | *More info → Run anyway* (the exe is not code-signed) |
| Window looks blurry | set Windows display scaling to 100 % |
| Speed 4× is not 4× faster | the machine is the limit; use 1× for the video |
| "Outside PS range — run anyway?" dialog | a field is red in the dock; fix it or click *Yes* deliberately |
| MP4 does not lock | check *FOV* on Scene & Camera matches the camera that recorded the video |
