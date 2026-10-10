# PyInstaller spec: build a windowed Flow.exe.
#
#   uv sync --extra build
#   uv run pyinstaller packaging/flow.spec --noconfirm
#
# Whisper models are NOT bundled; they download to %APPDATA%\Flow\models on first use.
# For GPU support the CUDA DLLs from the nvidia-* wheels are collected when they are installed.

import os
import pathlib
import sys

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

binaries = []
hiddenimports = []

# PyInstaller resolves dependent DLLs through PATH, so another OpenSSL on the machine (Git for
# Windows ships 3.2) gets bundled instead of the one this Python was built against, and _ssl then
# fails with "the specified procedure could not be found". Add the right files first: the TOC keeps
# the first entry for a given name.
_dlls = pathlib.Path(sys.base_prefix) / "DLLs"
for _name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll", "libffi-8.dll", "sqlite3.dll"):
    _path = _dlls / _name
    if _path.exists():
        binaries.append((str(_path), "."))
for package in ("ctranslate2", "av", "onnxruntime", "sounddevice", "tokenizers"):
    try:
        binaries += collect_dynamic_libs(package)
    except Exception:
        pass
for package in ("faster_whisper", "onnxruntime"):
    try:
        hiddenimports += collect_submodules(package)
    except Exception:
        pass

# The CUDA runtime from the nvidia-* wheels is ~1.2 GB, which triples the size of the build, so it
# is opt-in: set FLOW_BUNDLE_CUDA=1 to ship GPU support inside the exe. Without it the packaged app
# runs Whisper on the CPU unless those DLLs are already on the machine's PATH.
if os.environ.get("FLOW_BUNDLE_CUDA") == "1":
    try:
        binaries += collect_dynamic_libs("nvidia")
    except Exception:
        pass

a = Analysis(
    ["../run.pyw"],
    pathex=[".."],
    binaries=binaries,
    datas=[],
    hiddenimports=hiddenimports + ["win32timezone"],
    excludes=["tkinter", "matplotlib", "pytest", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Flow",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # tray app: no console window
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Flow",
)
