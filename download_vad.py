"""Build-time helper: fetch the Silero VAD model into assets/ (verified).

TLS verification is ON and the download is checked against a pinned SHA-256, so
a MITM or a changed source can't slip in a different/hostile ONNX model.
"""

import hashlib
import logging
import os
import ssl
import urllib.request

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("download_vad")

ASSETS_DIR = os.path.join(os.path.dirname(__file__), "assets")
VAD_PATH = os.path.join(ASSETS_DIR, "silero_vad.onnx")

# Silero VAD v4 (must match the VAD-v4 monkey patch in transcriber.py).
URL = "https://github.com/snakers4/silero-vad/raw/v4.0/files/silero_vad.onnx"
# SHA-256 of the known-good model. The download must match this exact file; if
# the source ever changes, verify the new model and update this pin.
EXPECTED_SHA256 = "a35ebf52fd3ce5f1469b2a36158dba761bc47b973ea3382b3186ca15b1f5af28"


def download_vad():
    os.makedirs(ASSETS_DIR, exist_ok=True)

    LOGGER.info("Downloading VAD model from %s ...", URL)
    req = urllib.request.Request(URL, headers={"User-Agent": "fwgui-build"})
    ctx = ssl.create_default_context()  # verifies cert chain + hostname (do NOT disable)
    with urllib.request.urlopen(req, context=ctx) as response:  # nosec - HTTPS, cert-verified
        data = response.read()

    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(
            f"VAD model SHA-256 mismatch.\n  expected {EXPECTED_SHA256}\n  got      {digest}\n"
            "Refusing to write an unverified model.")

    with open(VAD_PATH, "wb") as out_file:
        out_file.write(data)
    LOGGER.info("Verified + saved VAD model (%d bytes) to %s", len(data), VAD_PATH)


if __name__ == "__main__":
    download_vad()
