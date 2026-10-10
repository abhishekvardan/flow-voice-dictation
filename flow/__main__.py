"""Entry point: python -m flow"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler


def _setup_logging() -> None:
    from .config import data_dir

    handlers: list[logging.Handler] = [
        RotatingFileHandler(data_dir() / "flow.log", maxBytes=2_000_000, backupCount=2, encoding="utf-8")
    ]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
    )
    for noisy in ("faster_whisper", "urllib3", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main() -> int:
    _setup_logging()

    import win32api
    import win32event
    import winerror
    from PySide6.QtWidgets import QApplication, QMessageBox

    mutex = win32event.CreateMutex(None, False, "Local\\FlowDictationReplica")
    already_running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS

    qapp = QApplication(sys.argv)
    qapp.setApplicationName("Flow")
    qapp.setQuitOnLastWindowClosed(False)

    if already_running:
        QMessageBox.information(None, "Flow", "Flow is already running. Look for the microphone icon in the system tray.")
        return 0

    from .app import FlowApp

    app = FlowApp(qapp)
    app.start()
    if "--settings" in sys.argv:
        app.open_settings()
    code = qapp.exec()
    del mutex
    return code


if __name__ == "__main__":
    sys.exit(main())
