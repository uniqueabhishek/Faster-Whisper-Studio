"""Build a hardened, PyArmor-obfuscated customer executable.

Unlike the previous version (which injected a customer HWID into an UNSIGNED
string-compare template whose HWID formula could never match get_hwid.py), this
obfuscates the REAL signed license_guard.py (Ed25519 verifier) before packaging,
then builds from the single committed FasterWhisperGUI.spec — so the obfuscated
build is identical to a normal build except the license check is hardened.

The customer still receives their machine-locked, signed license.dat (generate
it with admin_keygen.py) and ships it next to the exe.

Safety: obfuscation is staged into an isolated build dir, and the original
plaintext license_guard.py is ALWAYS restored via try/finally, so an interrupted
or failed build can never leave obfuscated source or a stray pyarmor_runtime in
your working tree (which a later `git add .` could otherwise commit).
"""

import os
import shutil
import subprocess
import sys

GUARD_FILE = "license_guard.py"
SPEC_FILE = "FasterWhisperGUI.spec"
OBF_DIR = os.path.join("build", "pyarmor_obf")


def _run(cmd):
    print("  $", " ".join(cmd))
    subprocess.check_call(cmd)


def main():
    print("\n--- HARDENED CUSTOMER BUILD (PyArmor + PyInstaller) ---")

    if shutil.which("pyarmor") is None:
        print("ERROR: PyArmor not found (pip install pyarmor).")
        print("Refusing to produce an UN-obfuscated 'hardened' build.")
        return 1
    if not os.path.exists(GUARD_FILE):
        print(f"ERROR: {GUARD_FILE} not found. Run this from the project root.")
        return 1
    if not os.path.exists(SPEC_FILE):
        print(f"ERROR: {SPEC_FILE} not found. The committed build spec is required.")
        return 1

    # Keep the real plaintext source so we can always restore it.
    with open(GUARD_FILE, "r", encoding="utf-8") as f:
        original_guard = f.read()

    staged_runtime_dirs = []
    try:
        # 1. Obfuscate the REAL signed license_guard.py into an isolated dir.
        print("\n[1/3] Obfuscating license_guard.py with PyArmor...")
        if os.path.exists(OBF_DIR):
            shutil.rmtree(OBF_DIR, ignore_errors=True)
        os.makedirs(OBF_DIR, exist_ok=True)
        _run(["pyarmor", "gen", "-O", OBF_DIR, GUARD_FILE])

        obf_guard = os.path.join(OBF_DIR, GUARD_FILE)
        if not os.path.exists(obf_guard):
            print("ERROR: PyArmor produced no obfuscated license_guard.py. Aborting.")
            return 1

        # Swap the obfuscated module in for the build and stage the pyarmor
        # runtime next to it so PyInstaller's import analysis collects it.
        shutil.copy(obf_guard, GUARD_FILE)
        for item in os.listdir(OBF_DIR):
            if item.startswith("pyarmor_runtime"):
                dest = item
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(os.path.join(OBF_DIR, item), dest)
                staged_runtime_dirs.append(dest)

        # 2. Build from the single committed spec (same config as a normal build).
        print("\n[2/3] Building with PyInstaller (committed spec)...")
        _run([sys.executable, "-m", "PyInstaller", "--clean", "-y", SPEC_FILE])

        print("\n[3/3] Build complete.")
        print(r"  Hardened exe: dist\FasterWhisperGUI\FasterWhisperGUI.exe")
        print("  Generate the customer's signed license.dat with admin_keygen.py")
        print("  and ship it alongside the exe.")
        return 0
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: build step failed: {exc}")
        return 1
    finally:
        # ALWAYS restore the plaintext source and remove staged runtime dirs so
        # the working tree is never left obfuscated/dirty.
        with open(GUARD_FILE, "w", encoding="utf-8") as f:
            f.write(original_guard)
        for d in staged_runtime_dirs:
            shutil.rmtree(d, ignore_errors=True)
        print("  Restored original license_guard.py.")


if __name__ == "__main__":
    sys.exit(main())
