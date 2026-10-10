"""Double-click launcher (no console window). Use `uv run python -m flow` to see logs."""

import os
import sys

if getattr(sys, "frozen", False):
    # In a PyInstaller build, Python's _ssl.pyd needs the exact OpenSSL it was built against.
    # Other copies of libssl-3-x64.dll / libcrypto-3-x64.dll on PATH (Git for Windows ships
    # OpenSSL 3.2) are found first and fail with "the specified procedure could not be found",
    # so put ours first and load them by absolute path before anything imports ssl.
    import ctypes

    _notes = []
    _base = sys._MEIPASS
    os.environ["PATH"] = _base + os.pathsep + os.environ.get("PATH", "")
    try:
        os.add_dll_directory(_base)
    except OSError as _exc:
        _notes.append(f"add_dll_directory failed: {_exc}")
    for _name in ("libcrypto-3-x64.dll", "libssl-3-x64.dll"):
        _path = os.path.join(_base, _name)
        if not os.path.exists(_path):
            _notes.append(f"{_name}: not bundled")
            continue
        try:
            ctypes.WinDLL(_path)
            _notes.append(f"{_name}: loaded")
        except OSError as _exc:
            _notes.append(f"{_name}: {_exc}")
    try:
        import ssl

        _notes.append(f"ssl ok: {ssl.OPENSSL_VERSION}")
    except Exception as _exc:  # noqa: BLE001
        _notes.append(f"ssl failed: {_exc}")
    if os.environ.get("FLOW_STARTUP_LOG") == "1":
        _folder = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Flow")
        os.makedirs(_folder, exist_ok=True)
        with open(os.path.join(_folder, "startup.log"), "a", encoding="utf-8") as _handle:
            _handle.write("\n".join([_base] + _notes) + "\n")
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flow.__main__ import main  # noqa: E402

if getattr(sys, "frozen", False):
    # A windowed build has no console, so a startup failure would vanish into a dialog.
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException:
        import traceback

        folder = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "Flow")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "crash.log"), "a", encoding="utf-8") as handle:
            handle.write(traceback.format_exc() + "\n")
        raise
else:
    sys.exit(main())
