"""Fetch a static ffmpeg/ffprobe — at build time and from Settings -> Update FFmpeg.

Build use (run ONCE before building):  python download_ffmpeg.py
  -> downloads into assets/ffmpeg/ (gitignored), which the spec bundles.

Runtime use: the Settings dialog calls fetch_ffmpeg(user_ffmpeg_dir()) to drop a
newer ffmpeg into the per-user override dir, which the resolver prefers.

LICENSING — READ THIS: for a closed-source COMMERCIAL product, prefer an LGPL
ffmpeg build. Many "static"/"essentials" builds enable GPL components (x264,
etc.) and would extend GPL obligations to your distribution — the same class of
issue already flagged for PyQt5. The default URL is an LGPL "shared" build
(ffmpeg.exe + libav DLLs). Change FFMPEG_ZIP_URL only to a source you have
vetted, and pin FFMPEG_ZIP_SHA256 after a verified first run.

TLS verification is left ON (urllib's default) intentionally.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

# LGPL Windows build (ffmpeg.exe/ffprobe.exe + libav DLLs under <root>/bin/).
FFMPEG_ZIP_URL = (
    "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"
    "ffmpeg-master-latest-win64-lgpl-shared.zip"
)
# Pin the SHA-256 of the downloaded zip for integrity/reproducibility. Leave ""
# to skip with a warning; fill it in after one verified download.
FFMPEG_ZIP_SHA256 = ""

DEST_DIR = Path("assets") / "ffmpeg"
WANTED_EXES = ("ffmpeg.exe", "ffprobe.exe")

StatusFn = Callable[[str], None]


def _download(url: str, dest: Path, say: StatusFn) -> None:
    say(f"Downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "fwgui-build"})
    with urllib.request.urlopen(req) as resp, open(dest, "wb") as f:  # nosec - HTTPS, cert-verified
        shutil.copyfileobj(resp, f)
    say(f"Downloaded {dest.stat().st_size // (1024 * 1024)} MB")


def _verify(path: Path, sha256: str, say: StatusFn) -> bool:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not sha256:
        say(f"WARNING: no SHA-256 pinned. Zip digest: {digest}")
        return True
    if digest.lower() != sha256.lower():
        say(f"ERROR: SHA-256 mismatch (expected {sha256}, got {digest})")
        return False
    say("SHA-256 verified.")
    return True


def fetch_ffmpeg(
    dest_dir: Path,
    url: str = FFMPEG_ZIP_URL,
    sha256: str = FFMPEG_ZIP_SHA256,
    status: Optional[StatusFn] = None,
) -> bool:
    """Download + extract ffmpeg/ffprobe (and any DLLs) into dest_dir.

    Returns True on success. ``status`` receives human-readable progress lines.
    """
    say = status or print
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "ffmpeg.zip"
        try:
            _download(url, zip_path, say)
        except Exception as exc:  # pylint: disable=broad-except
            say(f"ERROR: download failed: {exc}")
            return False

        if not _verify(zip_path, sha256, say):
            return False

        say("Extracting...")
        try:
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(tmp_path)
        except Exception as exc:  # pylint: disable=broad-except
            say(f"ERROR: extract failed: {exc}")
            return False

        bin_dir = next((c.parent for c in tmp_path.rglob("ffmpeg.exe")), None)
        if bin_dir is None:
            say("ERROR: ffmpeg.exe not found in the archive.")
            return False

        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        copied = []
        for item in bin_dir.iterdir():
            if item.suffix.lower() == ".dll" or item.name in WANTED_EXES:
                shutil.copy2(item, dest / item.name)
                copied.append(item.name)

        if not any(e in copied for e in WANTED_EXES):
            say("ERROR: expected executables were not copied.")
            return False

        # Record the fetch time so the UI can show "Last updated" (copy2 keeps
        # the binary's own build mtime, not when it was fetched here).
        try:
            (dest / ".updated").write_text(
                datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        except OSError:
            pass

        say(f"Done. Copied {len(copied)} file(s) into {dest}")
        return True


def main() -> int:
    ok = fetch_ffmpeg(DEST_DIR)
    if ok and not FFMPEG_ZIP_SHA256:
        print("Tip: pin FFMPEG_ZIP_SHA256 (printed above) for reproducible builds.")
    print("These files are gitignored and bundled by FasterWhisperGUI.spec.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
