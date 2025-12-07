# pyright: reportMissingModuleSource=false
import os
import subprocess
import sys

def build():
    # Check if PyInstaller is installed
    try:
        import PyInstaller
    except ImportError:
        print("PyInstaller is not installed. Installing it...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])

    # Define build arguments
    # --noconsole: Don't show a terminal window
    # --add-data: Include the assets folder
    # --name: Name of the executable
    # --clean: Clean cache
    # --y: Overwrite output directory

    separator = ";" if os.name == 'nt' else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",
        "--clean",
        "-y",
        "--name", "FasterWhisperGUI",
        f"--add-data", f"assets{separator}assets",
        "--hidden-import", "df",
        "--hidden-import", "torchaudio",
        "--hidden-import", "soundfile",
        "--hidden-import", "faster_whisper",
        "--collect-all", "deepfilternet",
        "--collect-all", "onnxruntime",
        "--collect-all", "faster_whisper",
        "--collect-all", "ctranslate2",
        "--collect-all", "tokenizers",
        "app.py"
    ]

    print("Building executable with command:")
    print(" ".join(cmd))

    subprocess.check_call(cmd)

    print("\nBuild complete!")
    print(f"Executable is located in: {os.path.join('dist', 'FasterWhisperGUI', 'FasterWhisperGUI.exe')}")

if __name__ == "__main__":
    build()
