# ANANTHAM — Demo video script (≈ 4 min)

| time | on screen | narration |
|---|---|---|
| 0:00–0:20 | Title card, then the console at 1920×1080 | "ANANTHAM is a software laboratory for the coarse stage of pointing, acquisition and tracking for mobile free-space optical terminals — SIH26169." |
| 0:20–0:45 | Configuration dock: Scene & Camera tab; hover a field, set target size to 25 → turns red | "Every problem-statement parameter is editable with its PS default and range. Out-of-range values are flagged with the PS limit." |
| 0:45–1:25 | Scenario *circular*, seed 0, Start. Point at state label SEARCH → CANDIDATE → LOCKED; cyan box, orange ellipse, minimap spiral | "From the screen centre the single camera runs a square spiral. A track starts only from a compact, size-matched, non-edge blob and locks after three consistent detections. The Kalman filter runs in the gimbal-compensated frame, so our own slew is removed exactly." |
| 1:25–1:50 | Telemetry cards + live plots, px↔µrad line | "Centroiding error in pixels and micro-radians, tracking error, lock retention, processing FPS — all measured live against the PS thresholds." |
| 1:50–2:20 | Scenario *combined* (noise, haze, turbulence, jitter, platform, distractor); toggle Blind mode | "Everything combined. Blind mode hides every truth overlay: the tracker never sees ground truth — a unit test enforces that boundary." |
| 2:20–2:45 | Scenario *blink* in Perception Debug tab: candidate table, one track rejected | "A same-size distractor can only be told apart by identity: the designated beacon blinks at a known frequency, verified within half a second." |
| 2:45–3:05 | Scenario *occlusion*: COAST (amber) → RECOVER → LOCKED | "After loss we coast on the prediction, search locally, and re-acquire; every re-acquisition interval is logged." |
| 3:05–3:35 | EVALUATOR MP4 tab: load test.mp4, Run, export centroid CSV | "Evaluator mode bypasses the PTZ camera: your MP4, any resolution, adaptive spot scale, and a per-frame centroid CSV." |
| 3:35–4:00 | Benchmark tab / benchmark_report.pdf with the worst case highlighted | "Thirty-plus scenarios, five seeds each, both acquisition modes. Every number in our report comes from these runs — including the ones that fail the spec, and why." |
