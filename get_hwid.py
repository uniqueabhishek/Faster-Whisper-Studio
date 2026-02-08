import hashlib
import wmi
import os


def get_machine_id():
    """
    Generates a unique Machine ID (HWID) based on hardware serials.
    MUST MATCH logic in license_guard.py exactly!
    """
    try:
        c = wmi.WMI()
        try:
            board = c.Win32_BaseBoard()[0].SerialNumber.strip()
        except:
            board = "UnknownBoard"

        try:
            cpu = c.Win32_Processor()[0].ProcessorId.strip()
        except:
            cpu = "UnknownCPU"

        try:
            disk = c.Win32_DiskDrive(MediaType="Fixed hard disk media")[
                0].SerialNumber.strip()
        except:
            # Fallback if no fixed disk found
            disk = "UnknownDisk"

        raw_id = f"{board}-{cpu}-{disk}"
        return hashlib.sha256(raw_id.encode()).hexdigest()
    except Exception as e:
        print(f"Error generating HWID: {e}")
        return "ERROR_GENERATING_HWID"


def main():
    print("--- HARDWARE ID EXTRACTOR ---")
    print("Scanning system hardware...")

    hwid = get_machine_id()

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
