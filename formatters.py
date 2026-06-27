"""Time-formatting helpers shared across the app.

Extracted from transcriber.py so non-transcription modules (e.g. the audio
preprocessing path) can format durations as mm:ss without importing transcriber
-- which would pull in the heavy ``faster_whisper`` / CTranslate2 stack as a
side effect. These functions depend only on the standard library.
"""

from __future__ import annotations

import math


def format_timestamp(seconds: float) -> str:
    """Format an absolute position as ``HH:MM:SS.mmm`` (``MM:SS.mmm`` under 1h).

    Rounds to the nearest millisecond. The previous implementation truncated to
    whole seconds (``int(seconds)``), so every emitted timestamp drifted up to
    ~1s early and lost all sub-second precision. Used for the per-segment
    ``[start -> end]`` markers in the transcript.
    """
    if seconds is None or not math.isfinite(seconds) or seconds < 0:  # None / NaN / inf / negative
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"
    return f"{minutes:02d}:{secs:02d}.{millis:03d}"


def format_duration(seconds: float) -> str:
    """Format an elapsed duration as ``HH:MM:SS``, rounded to the nearest second.

    Used for the human-readable report fields (total/processed/processing time)
    where millisecond precision would only add noise.
    """
    if seconds is None or not math.isfinite(seconds) or seconds < 0:  # None / NaN / inf / negative
        seconds = 0.0
    total_secs = int(round(seconds))
    hours, rem = divmod(total_secs, 3600)
    minutes, secs = divmod(rem, 60)
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
