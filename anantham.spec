# PyInstaller spec — one-folder Windows build that launches straight into the GUI.
# Build:  pyinstaller anantham.spec --noconfirm   → dist/ANANTHAM/ANANTHAM.exe
# The same executable also accepts the CLI sub-commands (run / video / bench / make-video).
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = [("anantham/config/presets/*.yaml", "anantham/config/presets"),
         ("anantham/models/verifier.onnx", "anantham/models"),
         ("anantham/models/verifier_card.json", "anantham/models")]
datas += collect_data_files("onnxruntime")
binaries = collect_dynamic_libs("onnxruntime")

a = Analysis(
    ["tools/anantham_entry.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=["anantham.gui.app", "pyqtgraph", "scipy.special", "scipy.special._cdflib",
                   "matplotlib.backends.backend_pdf", "matplotlib.backends.backend_agg"],
    excludes=["torch", "tkinter", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="ANANTHAM", console=True,
          icon=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="ANANTHAM", upx=False)
