"""Application entry point for Faster-Whisper GUI."""

from __future__ import annotations

import os
import sys
import logging
import tempfile
import traceback
from logging.handlers import RotatingFileHandler

# Fix for DLL load failed error: onnxruntime must be imported before PyQt5
try:
    import onnxruntime  # noqa: F401 pylint: disable=unused-import  # Must be imported before PyQt5
except ImportError:
    pass

# pylint: disable=no-name-in-module
from PyQt5.QtWidgets import QApplication, QMessageBox

from main_window import MainWindow
from ui_common import app_icon
from workers import EXECUTOR


def _set_app_user_model_id() -> None:
    """Give Windows an explicit AppUserModelID.

    Without this, a script launched via python(w).exe is grouped under the
    Python icon in the taskbar regardless of the window icon. Setting a stable
    ID makes the taskbar use our own application icon.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes  # pylint: disable=import-outside-toplevel
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "FasterWhisperGUI")
    except Exception:  # pylint: disable=broad-except
        # Cosmetic only — never let taskbar grouping crash startup.
        pass


def exception_hook(exctype, value, tb):
    """Global exception handler to catch unhandled exceptions."""
    error_msg = ''.join(traceback.format_exception(exctype, value, tb))
    logging.error("Unhandled exception:\n%s", error_msg)
    print(f"\n\nUNHANDLED EXCEPTION:\n{error_msg}")

    # Try to show error dialog if possible
    try:
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Critical)
        msg.setWindowTitle("Fatal Error")
        msg.setText(f"An unhandled error occurred:\n\n{str(value)}")
        msg.setDetailedText(error_msg)
        msg.exec_()
    except Exception:  # pylint: disable=broad-except
        # If the error handler fails (e.g. Qt not initialized), just ignore to prevent recursion
        pass


def _log_directory() -> str:
    """Pick a writable directory for the log file.

    The previous build logged to ``whisper_gui_debug.log`` in the current working
    directory with ``mode='w'`` — which wiped history every launch and, for an
    installed exe under Program Files, is typically NOT writable (so logging
    setup itself could fail). Prefer a per-user app-data dir, then the system
    temp dir, then the cwd as a last resort.
    """
    candidates = []
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(os.path.join(local_appdata, "FasterWhisperGUI", "logs"))
    candidates.append(os.path.join(tempfile.gettempdir(), "FasterWhisperGUI", "logs"))
    candidates.append(os.getcwd())

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            # Confirm it is actually writable.
            probe = os.path.join(directory, ".write_test")
            with open(probe, "w", encoding="utf-8"):
                pass
            os.remove(probe)
            return directory
        except OSError:
            continue
    return os.getcwd()


def _setup_logging() -> str:
    """Configure rotating file + console logging. Returns the log file path."""
    log_path = os.path.join(_log_directory(), "whisper_gui_debug.log")

    handlers: list[logging.Handler] = []
    try:
        # Rotate (append, keep history) instead of truncating every run.
        handlers.append(RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"))
    except OSError:
        # If even the chosen directory fails at open time, carry on with console
        # logging only rather than crashing the app over a log file.
        pass
    handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        handlers=handlers,
    )
    return log_path


def main() -> None:
    """Main application entry point."""
    # Install global exception hook
    sys.excepthook = exception_hook

    # Must run before any window is created so the taskbar groups under our icon.
    _set_app_user_model_id()

    # Setup logging to both a rotating file (in a writable per-user location)
    # and the console.
    log_path = _setup_logging()
    logging.info("Application starting... (log file: %s)", log_path)

    try:
        app = QApplication(sys.argv)
        app.setWindowIcon(app_icon())

        # --- LICENSE CHECK START ---
        try:
            import license_guard  # pylint: disable=import-outside-toplevel
            if not license_guard.verify_license_gui():
                sys.exit(1)
        except ImportError:
            QMessageBox.critical(
                None, "Security Error", "License module missing! Re-install application.")
            sys.exit(1)
        except Exception as e:  # pylint: disable=broad-exception-caught
            QMessageBox.critical(None, "Security Error",
                                 f"License check failed: {e}")
            sys.exit(1)
        # --- LICENSE CHECK END ---

        # Show main window with sidebar navigation, maximized to fill the screen.
        # The resize/center in MainWindow.__init__ remains the restore geometry,
        # so un-maximizing returns to a sensible centered size.
        window = MainWindow()
        window.showMaximized()

        sys.exit(app.exec())
    except Exception:  # pylint: disable=broad-except
        # Catch-all for any fatal crashes at the top level
        logging.exception("Fatal error in application")
        print(f"\n\nFATAL ERROR:\n{traceback.format_exc()}")
        input("Press Enter to exit...")
    finally:
        # Ensure all worker threads terminate cleanly
        EXECUTOR.shutdown(wait=False)


if __name__ == "__main__":
    main()
