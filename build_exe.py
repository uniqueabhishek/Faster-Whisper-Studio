# pyright: reportMissingModuleSource=false
import os
import subprocess
import sys

# Assets that must be present BEFORE bundling, or the build silently ships an exe
# that falls back to a system-PATH ffmpeg (defeating the offline design).
BUNDLED_FFMPEG = os.path.join("assets", "ffmpeg", "ffmpeg.exe")
BUNDLED_VC_REDIST = os.path.join("assets", "vc_redist.x64.exe")


def check_build_assets() -> bool:
    """Abort the build if the bundled ffmpeg is missing; warn on vc_redist."""
    if not os.path.exists(BUNDLED_FFMPEG):
        print(f"ERROR: {BUNDLED_FFMPEG} is missing.")
        print("Run `python download_ffmpeg.py` once before building so ffmpeg is")
        print("bundled into the exe (otherwise it silently depends on PATH ffmpeg).")
        return False
    if not os.path.exists(BUNDLED_VC_REDIST):
        print(f"WARNING: {BUNDLED_VC_REDIST} is missing "
              "(run `python download_vc_redist.py` if you ship the VC++ runtime).")
    return True


def build():
    if not check_build_assets():
        return

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
