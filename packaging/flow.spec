# PyInstaller spec: build a windowed Flow.exe.
#
#   uv sync --extra build
#   uv run pyinstaller packaging/flow.spec --noconfirm
#
# Whisper models are NOT bundled; they download to %APPDATA%\Flow\models on first use.
# For GPU support the CUDA DLLs from the nvidia-* wheels are collected when they are installed.

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

binaries = []
hiddenimports = []
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

try:  # optional GPU runtime (uv sync --extra gpu)
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
