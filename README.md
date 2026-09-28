# ANANTHAM — FSOC Coarse Alignment Console

**AI-based virtual camera tracking for coarse alignment of mobile Free Space Optical
Communication terminals** · Smart India Hackathon 2026 · SIH26169 (ISRO / Space Applications Centre)

Anantham is a software laboratory for the coarse stage of Pointing, Acquisition and
Tracking (PAT) in mobile FSOC links. It generates a configurable virtual scene with one or
more moving optical beacons, renders the view of a rate-limited virtual pan-tilt camera,
injects realistic disturbances (atmospheric turbulence, haze, fog, rain, low light,
salt & pepper / Gaussian / Poisson noise, camera jitter, platform vibration), and runs a
closed loop: PERCEIVE → VALIDATE → PREDICT → CONTROL → RECOVER. It detects and identifies
the designated beacon, estimates its position and velocity, keeps it centred within
actuator limits, recovers after loss, and logs every performance metric the PS requires.
In Evaluator MP4 mode it bypasses the PTZ camera and runs the same perception and tracking
stack on external video.

![ANANTHAM console](docs/screenshot_gui.png)

## Quick start

```bash
pip install -r requirements.txt && pip install -e .
anantham gui                                                   # the console
anantham run --preset circular --seed 3 --duration 20 --out results/
anantham make-video --preset fog --out test.mp4                # synthetic MP4 + truth CSV
anantham video --input test.mp4 --truth test_truth.csv --out results/
anantham bench --scenarios all --seeds 5 --acq both --start both --out results/bench [--ablation]
```

Windows: download the `ANANTHAM-windows` artefact from CI (built on tags with
`pyinstaller anantham.spec`) and run `ANANTHAM.exe` — no Python needed.
Full instructions: [docs/USER_MANUAL.md](docs/USER_MANUAL.md).

## Architecture

```mermaid
flowchart LR
    subgraph TRUTH["Simulator (ground truth)"]
        S[scene + trajectories<br/>erf sub-pixel renderer] --> D[disturbances<br/>LOS → beacon → image → 8-bit]
        G[pan/tilt actuator<br/>slew limiter]
    end
    D --> F[FrameSource<br/>sim or MP4]
    G --> F
    F -- "image + commanded pan/tilt ONLY" --> P[PERCEIVE<br/>median · top-hat · MAD · signature]
    P --> V[VALIDATE<br/>CNN verifier, ONNX]
    V --> K[PREDICT<br/>identity gate · blink code · Kalman]
    K --> C[CONTROL<br/>PID + feed-forward]
    K --> R[RECOVER<br/>coast · local spiral · search]
    C --> G
    R --> G
    F -. truth .-> M[metrics · CSV · JSON · PDF]
    K -. telemetry .-> M
```

Ground truth never reaches perception, tracking or control — enforced by
`tests/test_boundary.py`. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/TECHNICAL_REPORT.md](docs/TECHNICAL_REPORT.md), metric definitions:
[docs/METRICS.md](docs/METRICS.md).

## Measured results

All numbers below are generated from benchmark output by `tools/insert_results.py`;
nothing is typed by hand.

<!-- RESULTS:meta -->
_not yet measured_
<!-- /RESULTS:meta -->

Runs passing each PS requirement (acquisition mode / start mode):

<!-- RESULTS:bench_headline -->
_not yet measured_
<!-- /RESULTS:bench_headline -->

Worst scenario groups:

<!-- RESULTS:worst -->
_not yet measured_
<!-- /RESULTS:worst -->

Ablation (in-FOV start, spiral acquisition):

<!-- RESULTS:ablation -->
_not yet measured_
<!-- /RESULTS:ablation -->

CNN verifier (held-out simulated ROIs):

<!-- RESULTS:cnn -->
_not yet measured_
<!-- /RESULTS:cnn -->

### Honest reading of the numbers

* With a single 4°×3° camera and a **random** start anywhere on the 12.5° screen, the
  2 s acquisition requirement is **not** met: the spiral search needs up to 14.1 s
  (analytic) at 5 °/s. It is met when the target starts inside the FOV, and with the
  OPTIONAL wide-FOV acquisition sensor.
* Tracking error is reported for *all locked frames* (includes the post-lock pull-in) and
  for the *steady state*; the first is often above 10 px because the gimbal is slew-limited.
* ±10/±20 px/frame white camera jitter sets a floor of J·√(2/3) px RMS on pointing error;
  the ±20 px/frame linear platform is limited by slew physics. See the failure analysis in
  the technical report.

## Repository layout

```
anantham/  config/ sim/ perception/ tracking/ control/ io/ metrics/ bench/ gui/ training/ pipeline/ models/
tools/     make_test_video.py  insert_results.py  anantham_entry.py
tests/     unit + integration tests (pytest)
docs/      USER_MANUAL · TECHNICAL_REPORT · ARCHITECTURE · METRICS · DEMO_SCRIPT
```

## Development

```bash
pip install -r requirements.txt && pip install -e .
ruff check anantham tests tools && pytest -q
anantham train --samples 60000 --epochs 12      # retrain the CNN (needs torch, onnx)
pyinstaller anantham.spec --noconfirm           # one-folder build → dist/ANANTHAM/
```

License: MIT.
