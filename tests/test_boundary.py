"""R1 sensor boundary: perception / tracking / control / PAT never import ground truth."""

import ast
import pathlib
import subprocess
import sys

import anantham

PKG = pathlib.Path(anantham.__file__).parent
FORBIDDEN = ("anantham.sim", "anantham.metrics", "anantham.bench", "anantham.io.sim_source",
             "anantham.pipeline.session")
GUARDED = ["perception", "tracking", "control", "pipeline/pat.py", "io/base.py", "geometry.py"]


def _module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(PKG.parent).with_suffix("")
    return ".".join(rel.parts)


def _resolve(mod: str, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    base = mod.split(".")[: -node.level]
    return ".".join(base + ([node.module] if node.module else []))


def _files():
    for g in GUARDED:
        p = PKG / g
        yield from ([p] if p.suffix == ".py" else sorted(p.rglob("*.py")))


def test_static_imports():
    bad = []
    for f in _files():
        mod = _module_name(f)
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _resolve(mod, node)
                names = [base] + [f"{base}.{a.name}" for a in node.names]
            for n in names:
                if any(n == fb or n.startswith(fb + ".") for fb in FORBIDDEN):
                    bad.append((str(f), n))
    assert not bad, bad


def test_runtime_imports():
    code = (
        "import sys\n"
        "import anantham.perception.classical, anantham.perception.scale, anantham.perception.cnn\n"
        "import anantham.tracking.kalman, anantham.tracking.gate, anantham.tracking.state_machine\n"
        "import anantham.control.controller, anantham.control.search, anantham.pipeline.pat\n"
        f"bad = [m for m in sys.modules if m.startswith({FORBIDDEN!r})]\n"
        "assert not bad, bad\n")
    subprocess.run([sys.executable, "-c", code], check=True)


def test_boundary_banner_present():
    src = (PKG / "pipeline" / "session.py").read_text(encoding="utf-8")
    assert "SENSOR BOUNDARY" in src
