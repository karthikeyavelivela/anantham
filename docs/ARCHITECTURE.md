# ANANTHAM — Architecture

## Closed loop and the sensor boundary

```mermaid
flowchart LR
    subgraph TRUTH["Simulator side (ground truth)"]
        SC[sim/scene.py<br/>world, trajectories,<br/>erf sub-pixel renderer] --> DI[sim/disturbances.py<br/>LOS → beacon → image → 8-bit]
        CAM[sim/camera.py<br/>pan/tilt, slew limiter]
    end
    subgraph SRC["io/ FrameSource"]
        SS[sim_source.py]
        VS[video_source.py<br/>MP4, virtual boresight]
    end
    subgraph PAT["PAT stack — sees ONLY image + commanded pointing"]
        P[PERCEIVE<br/>perception/classical.py] --> V[VALIDATE<br/>perception/cnn.py ONNX]
        V --> T[PREDICT<br/>tracking/kalman.py<br/>gate.py, state_machine.py]
        T --> C[CONTROL<br/>control/controller.py]
        T --> R[RECOVER / ACQUIRE<br/>control/search.py]
    end
    DI --> SS
    CAM --> SS
    SS -- "Frame(image, commanded pan/tilt)" --> P
    VS -- "Frame(image, virtual boresight)" --> P
    C -- "rate command (deg/s)" --> SS
    R -- "rate command" --> SS
    SS -. "truth (metrics only)" .-> M[metrics/logger.py<br/>summary.py, report.py]
    VS -. "truth CSV (optional)" .-> M
    PAT -- "PatOutput telemetry" --> M
```

The boundary is enforced in three ways:

1. `pipeline/session.py` is the only module that touches both sides; the boundary is marked
   with a banner comment in `Session.step`.
2. `tests/test_boundary.py` parses every module in `perception/`, `tracking/`, `control/`,
   `pipeline/pat.py`, `io/base.py`, `geometry.py` and fails on any import of `anantham.sim`,
   `anantham.metrics`, `anantham.bench`, `anantham.io.sim_source` or `anantham.pipeline.session`.
3. The same test imports the PAT packages in a fresh interpreter and checks that no
   forbidden module was loaded transitively.

What the PAT stack is allowed to know: the image(s), the commanded pan/tilt, and published
sensor / designation specifications from the config (FOV, resolution, frame rate, slew
limits, the designated beacon's nominal size and blink code). Jitter magnitude is **not**
given to the tracker — it is measured online from second differences of the measurements.

## Packages

| package | role |
|---|---|
| `config/` | dataclass schema with PS ranges as metadata, validation, YAML presets |
| `geometry.py` | pinhole camera model, px ↔ angle, rate conversions |
| `sim/` | trajectories (8 motion types), scene & renderer, disturbances, pan/tilt actuator |
| `io/` | `FrameSource` interface: `SimSource` (closed loop), `VideoSource` (MP4, virtual boresight) |
| `perception/` | classical detector, CNN verifier (ONNX Runtime), adaptive spot scale |
| `tracking/` | constant-velocity Kalman (+ noise estimator, IMM stub), identity gate & blink code, state machine |
| `control/` | PID + feed-forward controller, square-spiral search, wide-FOV hand-off |
| `pipeline/` | `PatSystem` (one PAT iteration), `Session` (main loop, boundary, outputs) |
| `metrics/` | per-frame logger, PS metric summary + PASS/FAIL, PDF / text reports |
| `bench/` | scenario table, parallel benchmark runner, ablation |
| `training/` | domain-randomised dataset, PyTorch training, ONNX export |
| `gui/` | PyQt6 console, QThread worker, widgets |

## State machine

```mermaid
stateDiagram-v2
    [*] --> SEARCH
    SEARCH --> CANDIDATE: non-edge blob, size-match ≥ 0.7
    CANDIDATE --> LOCKED: N=3 consistent detections (+ blink code verified)
    CANDIDATE --> SEARCH: tentative tracks die / rejected
    LOCKED --> COAST: no gated measurement
    COAST --> LOCKED: gated measurement
    COAST --> RECOVER: ~0.33 s without measurement
    RECOVER --> CANDIDATE: re-detection in the growing gate (re-confirm N frames)
    RECOVER --> SEARCH: recovery time-out (2 s)
```

## Data products per run

`<name>_frames.csv` (deterministic), `<name>_timing.csv`, `<name>_centroids.csv`
(`frame,time_s,x_px,y_px,state,confidence`), `<name>_summary.json`, `<name>_config.yaml`
(config + seed), `<name>.log` (geometry line, PAT facts, state transitions),
`<name>_report.pdf`.
