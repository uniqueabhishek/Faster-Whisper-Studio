"""Application entry point for Faster-Whisper GUI."""

from __future__ import annotations

import sys
import logging
import traceback

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


def main() -> None:
    """Main application entry point."""
    # Install global exception hook
    sys.excepthook = exception_hook

    # Must run before any window is created so the taskbar groups under our icon.
    _set_app_user_model_id()

    # Setup logging to both file and console
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler("whisper_gui_debug.log", mode='w'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logging.info("Application starting...")

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

        # Show main window with sidebar navigation
        window = MainWindow()
        window.show()

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
