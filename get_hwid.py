import os

# Single source of truth: reuse the exact same logic the app uses to verify
# licenses. This guarantees the ID a customer sends matches what license_guard
# computes at runtime — they can never drift apart.
from license_guard import get_machine_id, HWID_UNAVAILABLE


def main():
    print("--- HARDWARE ID EXTRACTOR ---")
    print("Scanning system hardware...")

    hwid = get_machine_id()

    if hwid == HWID_UNAVAILABLE:
        # Fail closed: don't emit a spoofable ID. The app would reject a license
        # bound to this anyway, so guide the user to support instead.
        print("\nERROR: Could not read a stable hardware ID from this machine.")
        print("Please contact the software vendor for assistance.")
        input("\nPress Enter to exit...")
        return

    filename = "machine_id.txt"
    with open(filename, "w") as f:
        f.write(hwid)

    print(f"\nSUCCESS!")
    print(f"Machine ID: {hwid}")
    print(f"Saved to file: {os.path.abspath(filename)}")
    print("\nACTION: Please send 'machine_id.txt' to the software vendor.")

    # Pause so user can see it if double-clicked
    input("\nPress Enter to exit...")


if __name__ == "__main__":
    main()
