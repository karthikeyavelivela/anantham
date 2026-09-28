"""FrameSource interface shared by the simulator and the MP4 evaluator input."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from ..geometry import CameraGeometry


@dataclass
class Frame:
    """One sensor frame as seen by the PAT stack (no ground truth in here)."""

    index: int
    t: float
    image: np.ndarray                  # uint8, grey (H, W) or BGR (H, W, 3)
    bore_px: tuple[float, float]       # commanded boresight, pointing-frame px
    pointing_deg: tuple[float, float]  # commanded pan/tilt (deg)
    wide: np.ndarray | None = None     # optional wide-FOV acquisition sensor image
    wide_scale: float = 1.0            # wide px → screen px factor
    render_ms: float = 0.0             # time spent producing the frame (not processing)


class FrameSource(ABC):
    """Produces frames and (optionally) accepts pan/tilt rate commands."""

    geometry: CameraGeometry
    fps: float
    #: True when commands physically move the camera (simulation); False when the
    #: camera is fixed (video) and the boresight is virtual.
    los_moves_with_command: bool = True
    #: Screen size in pointing px (search area); None for video.
    screen_px: tuple[float, float] | None = None

    @abstractmethod
    def read(self) -> Frame | None:
        """Return the next frame, or None at the end."""

    @abstractmethod
    def command(self, pan_rate_deg_s: float, tilt_rate_deg_s: float) -> tuple[float, float]:
        """Apply a rate command for the next frame; returns the rate actually applied."""

    def truth(self) -> dict | None:
        """Ground truth of the last frame (for metrics only — never for the PAT stack)."""
        return None

    @property
    def n_frames(self) -> int | None:
        """Total frame count if known."""
        return None

    def close(self) -> None:
        """Release resources."""
