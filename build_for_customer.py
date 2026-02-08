import os
import shutil
import subprocess

TEMPLATE_FILE = "license_guard_hardcoded.tpl"
OUTPUT_FILE = "license_guard.py"
MAIN_SCRIPT = "app.py"  # Your main entry point


def main():
    print("\n--- SECURE BUILDER FOR CUSTOMER (PyArmor + PyInstaller) ---")
    print("This tool creates a HARDENED, NODE-LOCKED executable.")

    # 1. Get Target ID
    target_id = input(
        "\nEnter Customer's Machine ID (from get_hwid.py): ").strip()
    if not target_id:
        print("Error: ID cannot be empty.")
        return

    # 2. Inject ID into license_guard.py
    print(f"\n[1/4] Injecting ID ({target_id}) into code...")

    if not os.path.exists(TEMPLATE_FILE):
        print(f"Error: Missing template {TEMPLATE_FILE}")
        return

    global_setup_complete = False

    # Backup existing if present (to be safe)
    if os.path.exists(OUTPUT_FILE):
        shutil.copy(OUTPUT_FILE, f"{OUTPUT_FILE}.bak")

    with open(TEMPLATE_FILE, "r") as f:
        template = f.read()

    # Write the PLAIN TEXT version first (needed as input for PyArmor)
    final_code = template.replace("{{TARGET_HWID}}", target_id)
    with open(OUTPUT_FILE, "w") as f:
        f.write(final_code)

    # 3. Obfuscate with PyArmor
    print(f"\n[2/4] Obfuscating security module with PyArmor...")
    if shutil.which("pyarmor") is None:
        print("Error: PyArmor not found. Run 'pip install pyarmor'")
        print("Falling back to standard compilation (NOT SECURE)...")
    else:
        try:
            # Clean previous build
            if os.path.exists("dist/obf"):
                shutil.rmtree("dist/obf", ignore_errors=True)

            # Run PyArmor
            # We obfuscate license_guard.py in place (or swap it)
            # Strategy: Gen to 'dist/obf', then copy BACK to current dir to let PyInstaller find it easily
            # (We will restore from .bak later)

            subprocess.check_call(
                ["pyarmor", "gen", "-O", "dist/obf", OUTPUT_FILE])

            # Verify obfuscation happened
            if os.path.exists(f"dist/obf/{OUTPUT_FILE}"):
                print("      Obfuscation successful. Swapping files for build...")
                # Copy the OBFUSCATED file over the real one
                shutil.copy(f"dist/obf/{OUTPUT_FILE}", OUTPUT_FILE)

                # Copy the pyarmor_runtime (required for it to run)
                # usage: pyarmor 8 generates a folder 'pyarmor_runtime_xxxx'
                # We need to ensure PyInstaller picks this up.
                # The easiest way is to leave it in the root for PyInstaller to find.
                for item in os.listdir("dist/obf"):
                    if item.startswith("pyarmor_runtime"):
                        if os.path.exists(item):
                            shutil.rmtree(item)
                        shutil.copytree(f"dist/obf/{item}", item)
            else:
                print("Warning: PyArmor output not found. Using plain text.")

        except Exception as e:
            print(f"Error during obfuscation: {e}")
            print("Proceeding with plain text (Insecure)...")

    # 4. Compile with PyInstaller
    print("\n[3/4] Compiling with PyInstaller...")

    exe_name = f"FasterWhisper_Locked_{target_id[:6]}"

    # Note: --clean is important.
    # We add --hidden-import if needed, but usually PyInstaller finds the runtime if it's in the root
    cmd = [
        "pyinstaller",
        "--noconsole",
        "--onefile",
        "--name", exe_name,
        "--clean",
        MAIN_SCRIPT
    ]

    print(f"      Running: {' '.join(cmd)}")
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"Error during compilation: {e}")
        # Restore before exit
        if os.path.exists(f"{OUTPUT_FILE}.bak"):
            shutil.copy(f"{OUTPUT_FILE}.bak", OUTPUT_FILE)
        return

    # 5. Cleanup / Restore
    print("\n[4/4] Cleaning up...")

    # Restore the original plain text file (or the template-based one)
    # actually we should restore the one we backed up, or just delete the temp one
    if os.path.exists(f"{OUTPUT_FILE}.bak"):
        shutil.copy(f"{OUTPUT_FILE}.bak", OUTPUT_FILE)
        os.remove(f"{OUTPUT_FILE}.bak")
        print("      Restored original source code.")

    # Remove runtime from root (keep it clean)
    for item in os.listdir("."):
        if item.startswith("pyarmor_runtime"):
            shutil.rmtree(item)

    print("\n[SUCCESS] Build Complete!")
    print(f"      Secure EXE: dist\\{exe_name}.exe")
    print(f"      Send ONLY this file to the customer.")


if __name__ == "__main__":
    main()
