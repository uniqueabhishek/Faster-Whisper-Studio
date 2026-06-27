"""Locate an ffmpeg/ffprobe executable, preferring a binary bundled with the app.

The audio pipeline (conversion, slicing, silence detection, preprocessing) shells
out to ffmpeg. Rather than depend on the customer having ffmpeg on PATH — which
the shipped exe previously did, silently disabling preprocessing and the long-file
OOM guard when it was missing — the build bundles a static ffmpeg under
assets/ffmpeg/ (fetched by download_ffmpeg.py).

Resolution order:
  1. a user-updated copy in %LOCALAPPDATA%\\FasterWhisperGUI\\ffmpeg (Settings ->
     Update FFmpeg writes here; it is writable and survives app reinstalls),
  2. the copy bundled with the build,
  3. a system PATH entry (dev fallback).
"""

from __future__ import annotations

import os
import sys
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

_UPDATED_MARKER = ".updated"


def user_ffmpeg_dir() -> Path:
    """Per-user writable dir for a user-updated ffmpeg (overrides the bundled copy)."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return Path(base) / "FasterWhisperGUI" / "ffmpeg"


def _bundled_dir() -> Path:
    """Directory holding the ffmpeg binaries bundled with the build (source or frozen)."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]  # pylint: disable=protected-access
    else:
        base = Path(__file__).parent
    return base / "assets" / "ffmpeg"


def _resolve(name: str) -> Optional[str]:
    exe = f"{name}.exe" if os.name == "nt" else name
    user = user_ffmpeg_dir() / exe
    if user.exists():
        return str(user)
    bundled = _bundled_dir() / exe
    if bundled.exists():
        return str(bundled)
    return shutil.which(name)


def get_ffmpeg_path() -> Optional[str]:
    """Return the active ffmpeg path (user-updated > bundled > PATH), or None."""
    return _resolve("ffmpeg")


def get_ffprobe_path() -> Optional[str]:
    """Return the active ffprobe path (user-updated > bundled > PATH), or None."""
    return _resolve("ffprobe")


def ffmpeg_source() -> str:
    """Where the active ffmpeg comes from: 'updated' | 'bundled' | 'path' | 'none'."""
    exe = get_ffmpeg_path()
    if not exe:
        return "none"
    parent = Path(exe).parent
    if parent == user_ffmpeg_dir():
        return "updated"
    if parent == _bundled_dir():
        return "bundled"
    return "path"


def get_ffmpeg_updated_time() -> Optional[str]:
    """Human-readable date the active ffmpeg was fetched, or None.

    Prefers the ``.updated`` marker written by download_ffmpeg.fetch_ffmpeg (the
    real "when did I download this" time); falls back to the binary's own mtime.
    """
    exe = get_ffmpeg_path()
    if not exe:
        return None
    parent = Path(exe).parent
    if parent in (user_ffmpeg_dir(), _bundled_dir()):
        marker = parent / _UPDATED_MARKER
        if marker.exists():
            try:
                text = marker.read_text(encoding="utf-8").strip()
                if text:
                    return text
            except OSError:
                pass
    try:
        ts = os.path.getmtime(exe)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return None


def get_ffmpeg_version() -> Optional[str]:
    """First line of ``ffmpeg -version`` (e.g. 'ffmpeg version 7.1.1 ...'), or None."""
    exe = get_ffmpeg_path()
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "-version"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        lines = (result.stdout or "").strip().splitlines()
        return lines[0] if lines else None
    except Exception:  # pylint: disable=broad-except
        return None
