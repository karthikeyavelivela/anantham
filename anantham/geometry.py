"""Pinhole camera geometry shared by the simulator and the tracking stack.

This module holds *only* sensor geometry (a published camera specification) and is
therefore allowed on both sides of the sensor boundary.

Conventions
-----------
* Image pixel ``i`` spans ``[i, i+1)``; its centre is at ``i + 0.5``. The optical
  centre of a W×H image is therefore ``(W/2, H/2)``.
* The *pointing frame* (a.k.a. screen px) is the gimbal-compensated az/el-equivalent
  frame expressed in nominal pixels: ``u = screen_w/2 + az_deg / ifov_h``. The screen is
  an angular grid with the camera's nominal IFOV, so screen px and pointing px coincide.
* Inside the image the exact pinhole relation ``x = cx + f·tan(Δaz)`` is used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraGeometry:
    """Pinhole model of a ``width``×``height`` camera with a ``fov_h×fov_v`` field."""

    width: int
    height: int
    fov_h_deg: float
    fov_v_deg: float

    @property
    def cx(self) -> float:
        """Optical centre x (pixel-centre convention)."""
        return self.width / 2.0

    @property
    def cy(self) -> float:
        """Optical centre y (pixel-centre convention)."""
        return self.height / 2.0

    @property
    def fx(self) -> float:
        """Focal length in pixels, horizontal."""
        return (self.width / 2.0) / math.tan(math.radians(self.fov_h_deg / 2.0))

    @property
    def fy(self) -> float:
        """Focal length in pixels, vertical."""
        return (self.height / 2.0) / math.tan(math.radians(self.fov_v_deg / 2.0))

    @property
    def ifov_h_deg(self) -> float:
        """Nominal (linearised) horizontal IFOV in degrees per pixel."""
        return self.fov_h_deg / self.width

    @property
    def ifov_v_deg(self) -> float:
        """Nominal (linearised) vertical IFOV in degrees per pixel."""
        return self.fov_v_deg / self.height

    @property
    def ifov_urad(self) -> float:
        """Nominal horizontal IFOV in micro-radians per pixel."""
        return math.radians(self.ifov_h_deg) * 1e6

    # --- image offsets <-> angles ------------------------------------------------
    def offset_px_to_deg(self, dx: float, dy: float) -> tuple[float, float]:
        """Image offset from the optical centre (px) → angle from boresight (deg)."""
        return (math.degrees(math.atan(dx / self.fx)), math.degrees(math.atan(dy / self.fy)))

    def offset_deg_to_px(self, daz: float, del_: float) -> tuple[float, float]:
        """Angle from boresight (deg) → image offset from the optical centre (px)."""
        return (self.fx * math.tan(math.radians(daz)), self.fy * math.tan(math.radians(del_)))

    def image_to_pointing(self, x: float, y: float, bore_u: float, bore_v: float
                          ) -> tuple[float, float]:
        """Image position → pointing-frame position given the boresight (pointing px)."""
        daz, delv = self.offset_px_to_deg(x - self.cx, y - self.cy)
        return bore_u + daz / self.ifov_h_deg, bore_v + delv / self.ifov_v_deg

    def pointing_to_image(self, u: float, v: float, bore_u: float, bore_v: float
                          ) -> tuple[float, float]:
        """Pointing-frame position → image position given the boresight (pointing px)."""
        dx, dy = self.offset_deg_to_px((u - bore_u) * self.ifov_h_deg,
                                       (v - bore_v) * self.ifov_v_deg)
        return self.cx + dx, self.cy + dy

    # --- rates ---------------------------------------------------------------------
    def rate_deg_s_to_px_frame(self, rate_deg_s: float, fps: float, axis: str = "h") -> float:
        """Angular rate (deg/s) → nominal pixels per frame."""
        ifov = self.ifov_h_deg if axis == "h" else self.ifov_v_deg
        return rate_deg_s / fps / ifov

    def px_frame_to_deg_s(self, px_per_frame: float, fps: float, axis: str = "h") -> float:
        """Nominal pixels per frame → angular rate (deg/s)."""
        ifov = self.ifov_h_deg if axis == "h" else self.ifov_v_deg
        return px_per_frame * ifov * fps

    def describe(self, fps: float, pan_rate: float, tilt_rate: float) -> dict:
        """Human-readable conversion table for the UI and logs."""
        return {
            "pixel_deg": self.ifov_h_deg,
            "pixel_urad": self.ifov_urad,
            "focal_px": self.fx,
            "pinhole_1px_at_centre_deg": math.degrees(math.atan(1.0 / self.fx)),
            "max_pan_px_per_frame": self.rate_deg_s_to_px_frame(pan_rate, fps, "h"),
            "max_tilt_px_per_frame": self.rate_deg_s_to_px_frame(tilt_rate, fps, "v"),
            "fov_px": [self.width, self.height],
        }

    def conversion_text(self, fps: float, pan_rate: float, tilt_rate: float) -> str:
        """One-line description of px↔angle conversion (shown in UI and log)."""
        d = self.describe(fps, pan_rate, tilt_rate)
        return (f"1 px = {d['pixel_deg']:.5f}° ≈ {d['pixel_urad']:.1f} µrad | "
                f"{pan_rate:g} °/s at {fps:g} Hz ≈ {d['max_pan_px_per_frame']:.1f} px/frame")
