# ANANTHAM — Metric definitions

Every number in the GUI, logs, reports, README and technical report is computed by
`anantham/metrics/summary.py` from the per-frame CSV (`<name>_frames.csv`) of an actual run.
Nothing is estimated by hand; a metric that cannot be computed is shown as
**"not measured"** (NaN in CSV/JSON).

## Conventions

* **Pixel centres** are at `i + 0.5`. The optical centre (boresight) of a W×H image is
  `(W/2, H/2)`; for 640×480 that is `(320.0, 240.0)`.
* **Pixel ↔ angle**: pinhole model, `x − cx = f·tan(θ)`, `f = (W/2)/tan(FOV_h/2)`.
  At the PS defaults (640 px, 4°) one pixel is 0.00625° ≈ 109.1 µrad, and a 5 °/s slew at
  30 Hz is 26.7 px/frame. Every log starts with this conversion line.
* **Frame time** `t = k / camera_rate`.
* **Post-acquisition frames**: from the first LOCKED frame (inclusive) to the end of the run.

## Ground-truth quantities (simulator side only)

| name | meaning |
|---|---|
| true apparent centre | where the designated beacon is actually rendered in the image: geometric position + platform offset + camera jitter + turbulence angle-of-arrival offset |
| true beacon (geometric) | geometric line-of-sight direction of the beacon incl. platform and jitter, **excluding** the turbulence AoA offset (an apparent, not a physical, displacement) |
| jitter-free position | geometric position without the white camera jitter (the part a controller can in principle remove) |

## Metrics

**Centroiding error** — per frame that has a track measurement and a visible designated
beacon: `|measured centroid − true apparent centre|` in image px. Reported: mean, RMSE,
P95, max, and RMSE in µrad (`RMSE × IFOV`).

**Tracking (pointing) error** — `|true beacon − boresight|` in image px, on LOCKED frames.
Always reported twice, never only one:

* *all locked frames* — includes the pull-in transient after every (re)lock;
* *steady state* — LOCKED frames at least 1 s after the latest (re)lock.

A third, diagnostic variant excludes the white camera jitter (*jitter-free*); it is always
labelled as such and never used for PASS/FAIL. In Evaluator MP4 mode the boresight is
virtual, so this becomes the *virtual pointing error*.

**Acquisition time** — run start → first LOCKED frame.

**Re-acquisition time** — for every LOCKED → not-LOCKED → LOCKED interval after the first
lock: the interval length. Reported: count, mean, max, and "unrecovered at end" when the
last loss never re-locked (this counts as FAIL). A diagnostic variant measures the time
from the target becoming visible again to re-lock (useful for occlusion / edge-exit tests).

**Lock retention rate** — post-acquisition frames that are LOCKED **and** have a measurement
**and** centroiding error ≤ 10 px, divided by *all* post-acquisition frames (frames in which
the target is occluded or off-screen count as not retained). **Target loss** =
1 − retention. Without truth (MP4 without a truth CSV) the 10 px criterion cannot be
applied and is dropped; the report says so.

**Detection coverage** — post-acquisition frames with a measurement, divided by
post-acquisition frames in which the designated beacon is inside the FOV. Always shown
next to accuracy so that rejecting frames can never hide failures.

**Wrong-target frames** — LOCKED frames whose measurement is > 10 px from the designated
beacon (i.e. locked on something else). **False-lock frames** — LOCKED frames while the
designated beacon is not in the FOV. In the *target absent* scenario PASS requires zero
LOCKED frames.

**Processing time** — wall time of perception + tracking + control per frame
(`time.perf_counter`, inside `PatSystem.process`). Rendering, disturbance generation,
logging and GUI drawing are excluded and logged separately (`render_ms`). Reported: mean,
P95, max; **processing FPS = 1000 / mean processing ms**.

**Simulation duration and camera rate** — frames / camera rate, and the camera rate.

## PS thresholds (PASS/FAIL)

| metric | PS requirement |
|---|---|
| Acquisition time | ≤ 2 s |
| Centroiding error (RMSE) | ≤ 10 px |
| Tracking error (RMSE, all locked frames) | ≤ 10 px |
| Tracking error (RMSE, steady state) | ≤ 10 px |
| Target loss | < 5 % |
| Re-acquisition time (max) | ≤ 1 s (n/a if no loss event; FAIL if unrecovered) |
| Processing speed | ≥ 20 FPS |
| Camera update rate | ≥ 30 Hz |
| Control update rate | ≥ 20 Hz |
| No false lock (target-absent scenario only) | 0 LOCKED frames |

A run "passes all" only if no row is FAIL (n/a rows do not fail).

## Benchmark aggregation

For each scenario / acquisition mode / start mode, over seeds: *mean* and *worst*
(max for errors, times and loss; min for FPS), and the fraction of seeds that pass all rows.
Every aggregated number is traceable to a per-run `*_summary.json` under `runs/`.
