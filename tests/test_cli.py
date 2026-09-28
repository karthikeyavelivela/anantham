"""CLI works on consoles with a legacy code page (Windows cp1252)."""

import os
import subprocess
import sys


def test_run_prints_on_cp1252_console(tmp_path):
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    r = subprocess.run([sys.executable, "-m", "anantham.cli", "run", "--preset", "circular",
                        "--duration", "1", "--perception", "classical", "--no-pdf",
                        "--out", str(tmp_path)], env=env, capture_output=True)
    assert r.returncode == 0, r.stderr.decode("utf-8", "replace")
    assert b"PASS" in r.stdout
