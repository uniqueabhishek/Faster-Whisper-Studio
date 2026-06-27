# pyright: reportMissingModuleSource=false
import os
import subprocess
import sys

def build():
    # Check if PyInstaller is installed
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("PyInstaller is not installed. Installing it...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Build from the single committed spec so this path and the hardened
    # customer path (build_for_customer.py) stay in sync.
    spec = "FasterWhisperGUI.spec"
    if not os.path.exists(spec):
        print(f"ERROR: {spec} not found. The canonical build spec is required.")
        return

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "-y",
        spec,
    ]

    print("Building executable with command:")
    print(" ".join(cmd))

    subprocess.check_call(cmd)

    print("\nBuild complete!")
    print(f"Executable is located in: {os.path.join('dist', 'FasterWhisperGUI', 'FasterWhisperGUI.exe')}")

if __name__ == "__main__":
    build()
