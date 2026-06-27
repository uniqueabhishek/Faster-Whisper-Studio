"""Build-time helper: fetch the VC++ redistributable into assets/ (verified).

TLS verification is ON (urllib default) and the download is checked against a
pinned SHA-256 before being written.
"""

import hashlib
import logging
import os
import urllib.request

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("download_vc")

VC_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
VC_PATH = os.path.join(ASSETS_DIR, "vc_redist.x64.exe")
# SHA-256 of the known-good installer. The 'latest' URL updates over time, so if
# Microsoft ships a newer redist this will fail by design - verify the new
# (Authenticode-signed) installer and update this pin.
EXPECTED_SHA256 = "cc0ff0eb1dc3f5188ae6300faef32bf5beeba4bdd6e8e445a9184072096b713b"


def download_vc():
    os.makedirs(ASSETS_DIR, exist_ok=True)

    if os.path.exists(VC_PATH):
        LOGGER.info("VC++ installer already exists at: %s", VC_PATH)
        return

    LOGGER.info("Downloading VC++ Redistributable from %s ...", VC_URL)
    req = urllib.request.Request(VC_URL, headers={"User-Agent": "fwgui-build"})
    with urllib.request.urlopen(req) as response:  # nosec - HTTPS, cert-verified
        data = response.read()

    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(
            f"VC++ redist SHA-256 mismatch.\n  expected {EXPECTED_SHA256}\n  got      {digest}\n"
            "Refusing to write an unverified installer.")

    with open(VC_PATH, "wb") as out_file:
        out_file.write(data)
    LOGGER.info("Verified + saved VC++ installer (%d bytes) to %s", len(data), VC_PATH)


if __name__ == "__main__":
    download_vc()
