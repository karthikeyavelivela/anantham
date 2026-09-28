"""Synthetic evaluator-style MP4 + truth CSV generator (``anantham make-video``).

Default: a FIXED camera looks at the screen centre and the beacon moves inside the FOV,
which is what an evaluator video typically looks like. The beacon is rendered with a
Moffat PSF (not the Gaussian the centroid assumes), random sub-pixel phase, 8-bit
quantisation and MP4 compression, so the centroid errors measured on these videos are
credible (lesson 12h). ``--moving-camera`` records the closed-loop PTZ view instead.
"""

from __future__ import annotations

import copy
import csv
from pathlib import Path

import cv2

from .config import Config, config_hash, save_config
from .sim.camera import PanTiltCamera
from .sim.scene import Scene


def make_test_video(cfg: Config, out: str | Path, fixed_camera: bool = True,
                    realism: bool = True) -> dict:
    """Write ``out`` (MP4) and ``<out stem>_truth.csv``; returns a description dict."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cfg = copy.deepcopy(cfg)
    cam = cfg.camera
    W, H = cam.res_w, cam.res_h
    box = None
    if fixed_camera:
        m = cfg.target.size_px + 30
        cx, cy = cam.screen_w_px / 2, cam.screen_h_px / 2
        box = (cx - W / 2 + m, cy - H / 2 + m, cx + W / 2 - m, cy + H / 2 - m)
        if cfg.target.start == "random":
            cfg.target.start = "in_fov"
        cfg.target.radius_px = min(cfg.target.radius_px, 0.35 * H)
    scene = Scene(cfg, cfg.run.seed, box=box, psf_model="moffat" if realism else "gaussian")
    camera = PanTiltCamera(cam)
    n = int(round(cfg.run.duration_s * cam.fps))
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), cam.fps, (W, H),
                             cam.color)
    if not writer.isOpened():
        raise RuntimeError(f"cannot open MP4 writer for {out}")
    truth_path = out.with_name(out.stem + "_truth.csv")
    pat = None
    if not fixed_camera:
        from .pipeline.pat import PatSystem

        cfg.perception.mode = "classical"
        pat = PatSystem(cfg, camera.geom, cam.fps, True,
                        (float(cam.screen_w_px), float(cam.screen_h_px)))
    with open(truth_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["frame", "time_s", "x_px", "y_px", "visible"])
        for k in range(n):
            scene.advance(k)
            bu, bv = camera.boresight_px
            img, truth = scene.render(bu, bv)
            writer.write(img)
            b = truth["beacons"][0]
            vis = b["in_fov"]
            w.writerow([k, f"{k / cam.fps:.5f}", f"{b['app_x']:.4f}" if vis else "",
                        f"{b['app_y']:.4f}" if vis else "", int(vis)])
            if pat is not None:
                from .io.base import Frame

                o = pat.process(Frame(k, k / cam.fps, img, (bu, bv), (camera.pan, camera.tilt)))
                camera.command(*o.rate_cmd_deg_s)
    writer.release()
    cfg_path = out.with_name(out.stem + "_config.yaml")
    save_config(cfg, cfg_path)
    return {"video": str(out), "truth": str(truth_path), "config": str(cfg_path), "frames": n,
            "fps": cam.fps, "size": [W, H], "fixed_camera": fixed_camera,
            "psf_model": "moffat (mismatched)" if realism else "gaussian (ideal)",
            "seed": cfg.run.seed, "config_hash": config_hash(cfg)}
