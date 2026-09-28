"""Synthetic evaluator-style MP4 + truth CSV (thin wrapper around ``anantham make-video``).

Example:
    python tools/make_test_video.py --preset fog --duration 10 --out test.mp4
"""

import sys

from anantham.cli import main

if __name__ == "__main__":
    main(["make-video", *sys.argv[1:]])
