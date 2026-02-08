# Security Strategy for Bundled Executable

This document outlines the multi-layered security approach designed to protect the **Faster Whisper GUI App** from unauthorized distribution and usage.

## 1. Core Security Architecture

Our security model relies on three main pillars:
1.  **Hardware Binding (HWID)**: Restricting the application to a specific physical machine.
2.  **Cryptographic Verification**: Ensuring license integrity using public-key cryptography.
3.  **Code Obfuscation & Bundling**: Making reverse engineering difficult.

---

## 2. Implementation Details

### A. Hardware ID (HWID) Locking
**Objective**: Prevent the `.exe` from running if copied to another computer.

*   **Mechanism**:
    *   We generate a unique **Hardware ID** based on immutable system properties (Motherboard Serial, CPU ID, UUID).
    *   This HWID is computed at runtime and compared against the permitted HWID.
*   **Implementation**:
    *   `get_hwid.py`: A script provided to the customer to extract their distinct HWID.
    *   **Validation**: The main application (`license_guard.py`) checks `current_hwid == license_hwid` on every launch.

### B. Asymmetric Licensing (Ed25519)
**Objective**: Prevent users from forging their own license files.

*   **Mechanism**:
    *   We use **Ed25519** (Edwards-curve Digital Signature Algorithm) for high-speed, high-security signing.
    *   **Keys**:
        *   `private_key.pem`: Kept offline by the **Admin** (YOU). Used to sign licenses.
        *   `public_key.pem`: Embedded into the client application. Used to verify licenses.
*   **Workflow**:
    1.  **Admin** runs `admin_keygen.py` -> Enters Customer Name, HWID, Expiry.
    2.  Script signs this data with the `Private Key` -> Generates `license_*.dat`.
    3.  **User** places `license_*.dat` next to the `.exe`.
    4.  **App** uses the embedded `Public Key` to verify the signature. If valid + HWID matches + Not Expired -> **Access Granted**.

### C. Code Protection (PyArmor + PyInstaller)
**Objective**: Prevent attackers from extracting source code or bypassing checks.

*   **PyInstaller**:
    *   Bundles the Python interpreter and all dependencies into a single `.exe`.
    *   *Weakness*: Python bytecode can be extracted (`pyinstxtractor`) and decompiled.
*   **PyArmor (Planned/Integrated)**:
    *   Obfuscates the Python scripts *before* bundling.
    *   Encrypts the bytecode so it cannot be easily decompiled if extracted.
    *   **Integration**: We added `pyarmor` to `pyproject.toml`. The build pipeline should run `pyarmor gen` before `pyinstaller`.

---

## 3. Security Workflow (Admin vs. User)

### Admin (Developer) Side
1.  **Setup**: Run `setup_security.py` **ONCE**.
    *   Generates `admin_keys/private_key.pem` (KEEP SAFE).
    *   Generates `license_guard.py` with the **Public Key** embedded directly into the code.
2.  **Issue License**:
    *   Ask Customer for their HWID (using `get_hwid.exe` or script).
    *   Run `uv run admin_keygen.py`.
    *   Input details -> Send the resulting `.dat` file to the customer.

### User Side
1.  **Installation**: Download `FasterWhisperGUI.exe` and the provided `license.dat`.
2.  **Execution**:
    *   User runs the app.
    *   App silently verifies integrity.
    *   If check fails (Wrong PC, Fake License, Expired) -> App exits immediately or shows an error.

## 4. Future Improvements
*   **Online Validation**: (Optional) Check against a server for real-time revocation.
*   **Anti-Tamper**: Add checksums to ensure `license_guard.py` wasn't modified (PyArmor handles some of this).
