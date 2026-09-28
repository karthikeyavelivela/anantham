# Changelog

## 1.0.0
- M1: configuration schema with PS ranges and validation; analytic erf sub-pixel renderer;
  8 motion types; disturbances (noise, atmosphere, turbulence, jitter, platform); pan/tilt
  actuator with slew limiter; CLI `run` with frame dumps; deterministic seeding.
- M2: classical perception, constant-velocity Kalman in the pointing frame, state machine,
  PID + feed-forward controller, square-spiral search; per-frame CSV + JSON metrics.
- M3: identity gate, blink-code ID, persistence-checked manoeuvre handling, NIS-adaptive Q,
  measured-jitter adaptive R, COAST/RECOVER with local spiral, optional wide-FOV acquisition,
  turbulence; 34-scenario benchmark runner.
- M4: Evaluator MP4 mode (virtual boresight), `make-video` with mismatched Moffat PSF and
  truth CSV, adaptive spot scale.
- M5: domain-randomised dataset, CNN verifier + heatmap/offset refinement, ONNX Runtime
  inference, ablation study.
- M6: PyQt6 console (camera view, minimap, telemetry, live plots, config dock, perception
  debug, benchmark, evaluator MP4), QThread worker, blind mode.
- M7: PDF reports, documentation, PyInstaller spec, CI (Ubuntu + Windows).
