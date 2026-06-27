"""Transcription utilities for Faster-Whisper GUI app."""
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false

from __future__ import annotations

import sys
import os
import math
import time
import logging
import subprocess
import re
import shutil
import wave
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from collections import namedtuple

from ffmpeg_utils import get_ffmpeg_path

LOGGER = logging.getLogger(__name__)

# Prefer a bundled ffmpeg (assets/ffmpeg/); fall back to PATH, then the bare name
# so behavior degrades to the previous PATH lookup when nothing is bundled.
_FFMPEG = get_ffmpeg_path() or "ffmpeg"

try:
    from faster_whisper import WhisperModel
    import faster_whisper.vad
    import faster_whisper.transcribe

    # Monkey patch VAD model path for offline use
    if getattr(sys, 'frozen', False):
        # If running as a bundled exe, look in the temporary folder
        _VAD_PATH = Path(sys._MEIPASS) / "assets" / \
            "silero_vad.onnx"  # pylint: disable=protected-access
    else:
        _VAD_PATH = Path(__file__).parent / "assets" / "silero_vad.onnx"

    LOGGER.info("Checking VAD path for patch: %s", _VAD_PATH)

    if _VAD_PATH.exists():
        import numpy as np

        class SessionWrapper:
            def __init__(self, session):
                self._session = session
                self._inputs = [i.name for i in session.get_inputs()]
                LOGGER.info("VAD Model inputs: %s", self._inputs)

            def run(self, output_names, input_feed, run_options=None):
                # Get input audio and batch size
                audio_input = input_feed.get('input')
                if audio_input is None:
                    return self._session.run(output_names, input_feed, run_options)

                batch_size = audio_input.shape[0]

                # 1. Inject sr if missing and required
                if 'sr' in self._inputs and 'sr' not in input_feed:
                    input_feed['sr'] = np.array([16000], dtype=np.int64)

                # 2. Prepare h/c
                # faster_whisper passes state as (1, batch, 128) or similar "old style" shape.
                # We need to reshape it to (2, batch, 64) for VAD v4.
                for key in ['h', 'c']:
                    if key in self._inputs:
                        if key in input_feed:
                            val = input_feed[key]
                            # If it comes in as (1, batch, 128), reshape to (2, batch, 64)
                            # BUT only if the total size matches!
                            required_size = 2 * batch_size * 64
                            if val.ndim == 3 and val.shape[0] == 1 and val.shape[2] == 128 and val.size == required_size:
                                input_feed[key] = val.reshape(
                                    2, batch_size, 64)
                            elif val.shape != (2, batch_size, 64):
                                # Fallback if shape is weird or size mismatch: reset to zeros
                                input_feed[key] = np.zeros(
                                    (2, batch_size, 64), dtype=np.float32)
                        else:
                            # Not in input feed, initialize zeros
                            input_feed[key] = np.zeros(
                                (2, batch_size, 64), dtype=np.float32)

                # 3. Run session
                outputs = self._session.run(
                    output_names, input_feed, run_options)

                # 4. Reshape outputs back to (1, batch, 128) to satisfy faster_whisper
                # outputs is usually [prob, h, c]
                if len(outputs) == 3:
                    prob, h_out, c_out = outputs

                    # Reshape h_out (2, B, 64) -> (1, B, 128)
                    if h_out.shape == (2, batch_size, 64):
                        h_out = h_out.reshape(1, batch_size, 128)

                    # Reshape c_out (2, B, 64) -> (1, B, 128)
                    if c_out.shape == (2, batch_size, 64):
                        c_out = c_out.reshape(1, batch_size, 128)

                    return [prob, h_out, c_out]

                return outputs

            def get_outputs(self):
                return self._session.get_outputs()

        def _get_local_vad_model():
            LOGGER.info("Instantiating local VAD model from: %s", _VAD_PATH)
            model = faster_whisper.vad.SileroVADModel(str(_VAD_PATH))
            # Wrap the session to inject 'sr' if needed
            model.session = SessionWrapper(model.session)
            return model

        # Patch faster_whisper.vad.get_vad_model
        if hasattr(faster_whisper.vad, "get_vad_model"):
            faster_whisper.vad.get_vad_model = _get_local_vad_model
            LOGGER.info("Patched faster_whisper.vad.get_vad_model")

        # Patch faster_whisper.transcribe.get_vad_model (crucial if it was imported directly)
        if hasattr(faster_whisper.transcribe, "get_vad_model"):
            faster_whisper.transcribe.get_vad_model = _get_local_vad_model
            LOGGER.info("Patched faster_whisper.transcribe.get_vad_model")

    else:
        LOGGER.warning("VAD model not found at %s. Patch skipped.", _VAD_PATH)

    LOGGER.info("faster_whisper imported successfully")
except ImportError as e:
    LOGGER.error("Failed to import faster_whisper: %s", str(e))
    raise

# Check for CTranslate2
try:
    import ctranslate2
    LOGGER.info("ctranslate2 version: %s", ctranslate2.__version__)
except ImportError:
    LOGGER.warning("ctranslate2 not found - this may cause issues")


@dataclass(frozen=True)
class TranscriptionConfig:
    model_name: str
    device: str = "cpu"
    compute_type: str = "int8"
    language: Optional[str] = None
    beam_size: int = 5
    best_of: int = 5
    cpu_threads: int = 0  # 0 = auto-detect and use all cores
    num_workers: int = 1  # Number of parallel workers for transcription
    # Audio chunk length in seconds (None = auto-detect based on duration)
    chunk_length: Optional[int] = None


@dataclass(frozen=True)
class TranscriptionResult:
    input_path: Path
    output_path: Optional[Path]
    text: str
    duration_seconds: float


AUDIO_VIDEO_EXTS: tuple[str, ...] = (
    ".mp3",
    ".wav",
    ".m4a",
    ".flac",
    ".ogg",
    ".mp4",
    ".mkv",
    ".webm",
)


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


# Lightweight stand-in for faster-whisper's TranscriptionInfo, used when we
# assemble segments ourselves (the smart-chunking path) and have no real info
# object from the model. Defined once here rather than re-declared inline.
_TranscriptionInfo = namedtuple(
    "TranscriptionInfo", ["duration", "language", "language_probability"])


class Transcriber:
    """High-level wrapper around Faster-Whisper."""

    def __init__(self, config: TranscriptionConfig) -> None:
        self._config = config
        self._model: WhisperModel = self._load_model()

    def _load_model(self) -> WhisperModel:
        model_path = Path(self._config.model_name)

        if not model_path.exists() or not model_path.is_dir():
            raise ValueError(
                "Wrong model selected. This file is not a Whisper model."
            )

        expected_files = ["model.bin", "model.int8.bin", "config.json"]
        if not any((model_path / f).exists() for f in expected_files):
            raise ValueError(
                "Wrong model selected. This file is not a Whisper model."
            )

        LOGGER.info("Loading model: %s (%s)", model_path.name,
                    self._config.compute_type)

        try:
            return WhisperModel(
                str(model_path),
                device=self._config.device,
                compute_type=self._config.compute_type,
                cpu_threads=self._config.cpu_threads,
                num_workers=self._config.num_workers,
            )
        except Exception as e:
            LOGGER.error("Failed to load model: %s", str(e))
            raise

    def prepare_audio(self, input_path: Path, cancel_check=None) -> Optional[Path]:
        """Converts input to 16kHz mono WAV using ffmpeg to fix duration issues.
           Returns Path to temp file if converted, or None if original is fine.
           cancel_check: Optional callable that returns True if cancellation is requested.
        """
        if not get_ffmpeg_path():
            LOGGER.warning("ffmpeg not found (no bundled binary or PATH entry). "
                           "Skipping audio repair.")
            return None

        # Optimization: Check if file is already 16kHz mono WAV
        if input_path.suffix.lower() == ".wav":
            try:
                with wave.open(str(input_path), "rb") as wf:
                    channels = wf.getnchannels()
                    framerate = wf.getframerate()
                    sampwidth = wf.getsampwidth()

                    # Check: 1 channel, 16kHz, 16-bit (2 bytes)
                    if channels == 1 and framerate == 16000 and sampwidth == 2:
                        LOGGER.info(
                            "✓ File is already 16kHz mono WAV. Skipping conversion: %s", input_path.name)
                        return None
                    else:
                        LOGGER.info("File format: %dHz, %d channel(s), %d-bit. Conversion needed: %s",
                                    framerate, channels, sampwidth * 8, input_path.name)
            except Exception as e:  # pylint: disable=broad-except
                # If any error reading wav header, proceed to ffmpeg
                LOGGER.debug(
                    "Could not read WAV header for %s: %s. Will convert.", input_path.name, str(e))

        try:
            # Create temp file path
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            temp_path = Path(temp_path)

            LOGGER.info("Repairing audio with ffmpeg: %s -> %s",
                        input_path, temp_path)

            # ffmpeg -i input -ar 16000 -ac 1 -c:a pcm_s16le output.wav
            cmd = [
                _FFMPEG, "-y",
                "-i", str(input_path),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(temp_path)
            ]

            # Use Popen to allow cancellation
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW
            )

            while True:
                if cancel_check and cancel_check():
                    process.kill()
                    LOGGER.info("Audio preparation cancelled.")
                    # Cleanup partial file
                    if temp_path.exists():
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass
                    raise Exception("Cancelled")

                if process.poll() is not None:
                    break

                time.sleep(0.1)

            if process.returncode != 0:
                LOGGER.warning(
                    "ffmpeg failed with return code: %d", process.returncode)
                return None

            LOGGER.info("Audio repair successful.")
            return temp_path

        except Exception as e:  # pylint: disable=broad-except
            if str(e) == "Cancelled":
                raise
            LOGGER.error("Audio repair failed: %s", str(e))
            return None

    def _slice_audio(self, input_path: Path, start: float, duration: float,
                     cancel_check: Optional[Callable[[], bool]] = None) -> Optional[Path]:
        """Extract a slice of audio to a temporary WAV file.

        ``cancel_check``: optional callable returning True to abort. When it
        fires, the ffmpeg process is killed and ``Exception("Cancelled")`` is
        raised so the chunked transcription unwinds promptly instead of blocking
        for the full slice.
        """
        temp_path = None
        try:
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            temp_path = Path(temp_path)

            # Simple ffmpeg slice
            cmd = [
                _FFMPEG, "-y",
                "-i", str(input_path),
                "-ss", str(start),
                "-t", str(duration),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(temp_path)
            ]

            # Use Popen + polling so a cancel request can kill ffmpeg mid-slice.
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )

            while True:
                if cancel_check and cancel_check():
                    process.kill()
                    raise Exception("Cancelled")
                if process.poll() is not None:
                    break
                time.sleep(0.1)

            if process.returncode != 0:
                LOGGER.error(
                    "Failed to slice audio: ffmpeg returned %d", process.returncode)
                if temp_path and temp_path.exists():
                    try:
                        os.unlink(temp_path)
                    except OSError:
                        pass
                return None

            return temp_path
        except Exception as e:  # pylint: disable=broad-except
            if temp_path and temp_path.exists():
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass
            if str(e) == "Cancelled":
                raise
            LOGGER.error("Failed to slice audio: %s", e)
            return None

    def _find_nearest_silence(self, input_path: Path, start_search: float, search_window: float = 600.0) -> float:
        """Find the best silence point to split audio using ffmpeg.
           Returns timestamp of silence center, or start_search + search_window/2 if none found.
        """
        # Limit search to end of file to avoid errors
        duration = 0
        try:
            if input_path.suffix == ".wav":
                with wave.open(str(input_path), "rb") as wf:
                    duration = wf.getnframes() / wf.getframerate()
        except Exception:
            pass

        if duration > 0 and start_search >= duration:
            return start_search

        actual_search_end = start_search + search_window
        if duration > 0:
            actual_search_end = min(actual_search_end, duration)

        actual_window = actual_search_end - start_search
        if actual_window <= 0:
            return start_search

        # Default fallback: hard split at 10 minutes from start_search (or half window)
        fallback_split = start_search + (actual_window / 2)

        try:
            # Run silencedetect filter
            # We look for silence > 0.5s with -30dB threshold
            cmd = [
                _FFMPEG, "-y",
                "-i", str(input_path),
                "-ss", str(start_search),
                "-t", str(actual_window),
                "-af", "silencedetect=n=-30dB:d=0.5",
                "-f", "null",
                "-"
            ]

            # Capture stderr because ffmpeg writes filter output there
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                encoding="utf-8",
                errors="ignore",
                check=False
            )

            output = result.stderr

            # Parse silence_start: 12.345
            # We want to find the silence that is closest to our ideal split point?
            # Or just the longest one?
            # User wants 10-20 min chunks.
            # Smartest strategy: Find ANY valid silence in the window.
            # Ideally picking the one in the middle of the window is safest to keep chunks balanced,
            # but picking the longest one is safest for audio integrity.
            # Let's pick the longest silence in the window.

            # Match paired silence_start -> silence_end to avoid misalignment
            silence_pairs = re.findall(
                r"silence_start: ([\d\.]+).*?silence_end: ([\d\.]+)", output, re.DOTALL)

            if not silence_pairs:
                LOGGER.info(
                    "No silence found in window %.1f-%.1f. Using hard split.", start_search, actual_search_end)
                return fallback_split

            # When using -ss before -i, ffmpeg resets filter timestamps to 0
            silences = []
            for s_str, e_str in silence_pairs:
                s = float(s_str)
                e = float(e_str)
                if e > s:  # Validate that end is after start
                    duration = e - s
                    center = s + (duration / 2)
                    silences.append((center, duration))

            if not silences:
                return fallback_split

            # Pick silence with max duration
            best_silence = max(silences, key=lambda x: x[1])
            best_relative_time = best_silence[0]

            final_split_time = start_search + best_relative_time
            LOGGER.info(
                "Smart split found at %.2fs (Silence duration: %.2fs)", final_split_time, best_silence[1])
            return final_split_time

        except Exception as e:  # pylint: disable=broad-except
            LOGGER.warning("Smart split failed: %s. using hard split.", e)
            return fallback_split

    MIN_CHUNK_DURATION = 600   # 10 minutes
    MAX_CHUNK_DURATION = 1200  # 20 minutes

    def _transcribe_chunked(self, input_path: Path, total_duration: float, transcribe_kwargs: dict,
                            cancel_check: Optional[Callable[[], bool]] = None):
        """Generator that yields segments by processing audio in chunks (safe for low memory).

        ``cancel_check``: optional callable returning True to abort between
        chunks and during the (now killable) per-chunk slice.
        """

        # Remove chunk_length to prevent nested chunking issues
        chunk_kwargs = transcribe_kwargs.copy()
        if 'chunk_length' in chunk_kwargs:
            chunk_kwargs.pop('chunk_length')

        current_time = 0.0

        while current_time < total_duration:
            if cancel_check and cancel_check():
                raise Exception("Cancelled")

            # We want a chunk between 10 and 20 minutes.
            # So we search for silence between [current+10m, current+20m]

            search_start = current_time + self.MIN_CHUNK_DURATION

            # If remaining audio is less than MIN_CHUNK_DURATION, just take it all
            if search_start >= total_duration:
                chunk_duration = total_duration - current_time
                split_point = total_duration
            else:
                # Calculate search window
                # If total remaining is less than MAX_CHUNK_DURATION, cap it
                end_limit = min(
                    current_time + self.MAX_CHUNK_DURATION, total_duration)
                search_window = end_limit - search_start

                if search_window <= 0:
                    # e.g. exactly 10 mins left
                    split_point = end_limit
                else:
                    split_point = self._find_nearest_silence(
                        input_path, search_start, search_window)

            # Safety check: Ensure we advance
            if split_point <= current_time:
                split_point = current_time + self.MIN_CHUNK_DURATION
            split_point = min(split_point, total_duration)

            chunk_duration = split_point - current_time

            LOGGER.info(
                "Processing chunk: %.1f - %.1f (Duration: %.1f)", current_time, split_point, chunk_duration)

            temp_chunk = self._slice_audio(
                input_path, current_time, chunk_duration, cancel_check=cancel_check)
            if not temp_chunk:
                # A failed slice would otherwise silently truncate the transcript
                # while the caller still marks the file "completed". Fail loudly
                # so the file is recorded as failed instead of partially-done.
                raise RuntimeError(
                    f"Failed to create audio slice at {current_time:.1f}s. "
                    "Aborting chunked transcription to avoid silent truncation.")

            try:
                segments, _ = self._model.transcribe(
                    str(temp_chunk), **chunk_kwargs)

                for segment in segments:
                    # Adjust timestamps relative to the original file
                    new_start = segment.start + current_time
                    new_end = segment.end + current_time

                    # Create a new segment with adjusted timestamps
                    # Check if segment has _replace (namedtuple) or needs reconstruction
                    if hasattr(segment, '_replace'):
                        # Older faster-whisper versions use namedtuples
                        yield segment._replace(start=new_start, end=new_end)
                    else:
                        # Newer versions use Segment class - create modified copy
                        from faster_whisper.transcribe import Segment
                        yield Segment(
                            id=segment.id,
                            seek=segment.seek,
                            start=new_start,
                            end=new_end,
                            text=segment.text,
                            tokens=segment.tokens,
                            temperature=segment.temperature,
                            avg_logprob=segment.avg_logprob,
                            compression_ratio=segment.compression_ratio,
                            no_speech_prob=segment.no_speech_prob,
                            words=segment.words if hasattr(segment, 'words') else None,
                        )

            except Exception as e:  # pylint: disable=broad-except
                LOGGER.error(
                    "Error processing chunk starting at %.1f: %s", current_time, e)
                # Try to continue if possible, or raise if critical
                # For memory error, we really want to stop or retry smaller?
                # Since we are already chunking, raising is appropriate.
                raise e
            finally:
                if temp_chunk.exists():
                    try:
                        os.unlink(temp_chunk)
                    except OSError:
                        pass

            current_time = split_point

    def _probe_duration(self, audio_path: Path) -> float:
        """Return audio duration in seconds via the WAV header, or 0.0 if unknown."""
        try:
            with wave.open(str(audio_path), "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception as e:  # pylint: disable=broad-except
            LOGGER.warning("Could not determine audio duration: %s", e)
            return 0.0

    def _resolve_strategy(self, actual_input: Path) -> tuple[float, bool, Optional[int]]:
        """Decide the processing strategy for the input.

        Returns ``(full_duration_seconds, use_smart_chunking, chunk_length)``.
        Files longer than 40 minutes use smart (physical) chunking to bound
        memory. A user-configured ``chunk_length`` disables auto-detection.
        """
        if self._config.chunk_length is not None:
            chunk_length = self._config.chunk_length
            if chunk_length:
                LOGGER.info("Using custom internal chunk length: %ds", chunk_length)
            return 0.0, False, chunk_length

        full_duration = self._probe_duration(actual_input)
        if full_duration <= 0.0:
            LOGGER.warning("Proceeding with standard processing (unknown duration).")
            return 0.0, False, None

        duration_minutes = full_duration / 60
        LOGGER.info("Audio duration: %.1f minutes", duration_minutes)
        if duration_minutes > 40:
            LOGGER.info(
                "Long audio detected (%.1f min). Using Smart Chunking (physical "
                "splitting) to prevent memory errors.", duration_minutes)
            return full_duration, True, None

        LOGGER.info("Normal duration file (%.1f min). Standard processing.",
                    duration_minutes)
        return full_duration, False, None

    def _build_transcribe_kwargs(self, lang, bs, vad_filter, initial_prompt,
                                 task, patience, chunk_length) -> dict:
        """Assemble the keyword arguments passed to ``WhisperModel.transcribe``."""
        vad_params = dict(
            min_silence_duration_ms=3000,
            speech_pad_ms=1000,
            threshold=0.1,
        ) if vad_filter else None

        kwargs = dict(
            language=lang,
            beam_size=bs,
            best_of=self._config.best_of,
            vad_filter=vad_filter,
            vad_parameters=vad_params,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            task=task,
            patience=patience,
        )
        # Only add chunk_length if it's set (for standard processing).
        if chunk_length is not None:
            kwargs['chunk_length'] = chunk_length
        return kwargs

    def _run_transcription(self, actual_input, transcribe_kwargs, use_smart_chunking,
                           full_duration, lang, bs, vad_filter, initial_prompt,
                           task, patience, cancel_check):
        """Run the model (or smart-chunked generator) with memory/VAD fallbacks.

        Returns ``(segments, info)``. On a memory error during standard
        processing, retries via smart chunking; on a VAD load error, retries
        with VAD disabled (preserving the task/patience the primary call used).
        """
        try:
            if use_smart_chunking:
                segments = self._transcribe_chunked(
                    actual_input, full_duration, transcribe_kwargs,
                    cancel_check=cancel_check)
                info = _TranscriptionInfo(
                    duration=full_duration,
                    language=lang if lang else "unknown",
                    language_probability=1.0)
                return segments, info

            return self._model.transcribe(
                str(actual_input),
                **transcribe_kwargs  # type: ignore[arg-type]
            )
        except Exception as e:  # pylint: disable=broad-except
            error_str = str(e)
            is_memory_error = (
                "MemoryError" in error_str or "Unable to allocate" in error_str
                or isinstance(e, MemoryError) or "ArrayMemoryError" in error_str)

            if is_memory_error and not use_smart_chunking:
                LOGGER.warning(
                    "Memory Error detected during standard processing (%s). "
                    "Switching to safer Smart Chunking.", error_str)

                # We need duration if we didn't get it before.
                if full_duration == 0.0:
                    full_duration = self._probe_duration(actual_input)
                    if full_duration <= 0.0:
                        LOGGER.error(
                            "Could not determine duration for chunking fallback.")
                        raise

                segments = self._transcribe_chunked(
                    actual_input, full_duration, transcribe_kwargs,
                    cancel_check=cancel_check)
                info = _TranscriptionInfo(
                    duration=full_duration,
                    language=lang if lang else "unknown",
                    language_probability=1.0)
                return segments, info

            # Fallback for VAD load errors: retry with VAD disabled. (Smart
            # chunking calls _model.transcribe internally, so its VAD errors
            # bubble up here too.)
            if vad_filter and ("ONNXRuntimeError" in error_str or "INVALID_PROTOBUF" in error_str):
                LOGGER.warning("VAD failed to load (%s). Retrying with VAD disabled.", e)
                return self._model.transcribe(
                    str(actual_input),
                    language=lang,
                    beam_size=bs,
                    best_of=self._config.best_of,
                    vad_filter=False,
                    initial_prompt=initial_prompt,
                    task=task,
                    patience=patience,
                )

            raise

    def _render_segments(self, segments, total_duration, add_timestamps,
                         progress_callback, cancel_check) -> tuple[List[str], float]:
        """Iterate model segments into transcript lines, honoring cancellation.

        Returns ``(lines, ai_processed_duration)``.
        """
        lines: List[str] = []
        ai_processed_duration = 0.0
        last_progress = -1
        last_log_time = time.time()

        for segment in segments:
            # Honor cancellation between segments. faster-whisper streams
            # segments lazily, so this is observed within one segment (seconds),
            # making a long single file genuinely interruptible.
            if cancel_check and cancel_check():
                raise Exception("Cancelled")

            # Log progress every 60 seconds.
            if time.time() - last_log_time >= 60.0:
                audio_progress = segment.end if hasattr(segment, 'end') else 0
                progress_pct = (audio_progress / total_duration *
                                100) if total_duration > 0 else 0
                LOGGER.info("Progress: %.0f%% complete", progress_pct)
                last_log_time = time.time()

            ai_processed_duration += (segment.end - segment.start)
            text_content = segment.text.strip() if segment.text else ""
            if text_content:
                if add_timestamps:
                    start_str = format_timestamp(segment.start)
                    end_str = format_timestamp(segment.end)
                    lines.append(f"[{start_str} -> {end_str}] {text_content}")
                else:
                    lines.append(text_content)

            # Update progress (only when it changes by >=1% to reduce overhead).
            if progress_callback and total_duration > 0:
                percent = int((segment.end / total_duration) * 100)
                if percent != last_progress:
                    progress_callback(min(percent, 100))
                    last_progress = percent

        return lines, ai_processed_duration

    def _build_report(self, bs, vad_filter, add_timestamps, lang, task,
                      total_duration, vad_removed_duration, ai_processed_duration,
                      elapsed_seconds) -> str:
        """Assemble the human-readable transcription report appended to output."""
        vad_status = "Active" if vad_filter else "Not Active"
        timestamp_status = "Yes" if add_timestamps else "No"

        # Map beam_size to Word Analysis Depth name.
        depth_name = "Custom"
        if bs == 5 and self._config.compute_type == "int8":
            depth_name = "Fast Analysis (int8)"
        elif bs == 5 and self._config.compute_type == "float32":
            depth_name = "Precise Analysis (float32)"
        elif bs == 10:
            depth_name = "Deep Analysis (float32)"

        report = [
            "\n\n" + "=" * 30,
            "TRANSCRIPTION REPORT",
            "=" * 30,
            f"Model Used: {self._config.model_name}",
            f"Word Analysis Depth: {depth_name} (Beam Size: {bs})",
            f"Smart Silence Removal (VAD): {vad_status}",
            f"Timestamp Added: {timestamp_status}",
            f"Language: {lang}",
            f"Task: {task.capitalize()}",
            "-" * 30,
            f"Total Audio Duration: {format_duration(total_duration)}",
            f"VAD Removed Duration: {format_duration(vad_removed_duration)}",
            f"AI Processed Duration: {format_duration(ai_processed_duration)}",
            f"Processing Time: {format_duration(elapsed_seconds)}",
            "=" * 30,
        ]
        return "\n".join(report)

    def transcribe_file(
        self,
        input_path: Path,
        output_path: Optional[Path] = None,
        progress_callback: Optional[Callable[[int], None]] = None,
        beam_size: Optional[int] = None,
        vad_filter: bool = False,
        language: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        task: str = "transcribe",
        patience: float = 1.0,
        add_timestamps: bool = True,
        add_report: bool = True,
        pre_converted_path: Optional[Path] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> TranscriptionResult:
        LOGGER.info("Starting transcription: %s", input_path.name)

        if not input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Use pre-converted audio if provided, otherwise convert now. When we
        # create the temp file ourselves we also clean it up below; if the
        # caller passed pre_converted_path, the caller owns its lifecycle.
        temp_wav = pre_converted_path if pre_converted_path else self.prepare_audio(input_path)
        actual_input = temp_wav if temp_wav else input_path

        bs = beam_size if beam_size is not None else self._config.beam_size
        lang = language if language else self._config.language

        full_duration, use_smart_chunking, chunk_length = self._resolve_strategy(actual_input)
        start_time = time.time()
        transcribe_kwargs = self._build_transcribe_kwargs(
            lang, bs, vad_filter, initial_prompt, task, patience, chunk_length)

        segments, info = self._run_transcription(
            actual_input, transcribe_kwargs, use_smart_chunking, full_duration,
            lang, bs, vad_filter, initial_prompt, task, patience, cancel_check)
        total_duration = info.duration

        LOGGER.info("Processing audio (Duration: %s)",
                    format_duration(total_duration))
        lines, ai_processed_duration = self._render_segments(
            segments, total_duration, add_timestamps, progress_callback, cancel_check)
        text = "\n".join(lines)

        vad_removed_duration = max(
            0.0, total_duration - ai_processed_duration) if vad_filter else 0.0
        report_str = self._build_report(
            bs, vad_filter, add_timestamps, lang, task, total_duration,
            vad_removed_duration, ai_processed_duration, time.time() - start_time)
        if add_report:
            text += report_str

        # Log the report so it shows in the GUI.
        LOGGER.info(report_str)

        # Cleanup temp file ONLY if we created it internally.
        if not pre_converted_path and temp_wav and temp_wav.exists():
            try:
                os.unlink(temp_wav)
            except Exception as e:  # pylint: disable=broad-except
                LOGGER.warning("Failed to remove temp file: %s", e)

        resolved_output: Optional[Path] = None
        if output_path is not None:
            resolved_output = output_path
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(text, encoding="utf-8")
            LOGGER.info("Saved: %s", resolved_output.name)
        return TranscriptionResult(
            input_path=input_path,
            output_path=resolved_output,
            text=text,
            duration_seconds=float(getattr(info, "duration", 0.0)),
        )

    def iter_media_files(
        self, root: Path, recursive: bool = True
    ) -> Iterable[Path]:
        if not root.is_dir():
            raise NotADirectoryError(f"Not a directory: {root}")

        iterator = root.rglob("*") if recursive else root.iterdir()

        for path in iterator:
            if path.is_file() and path.suffix.lower() in AUDIO_VIDEO_EXTS:
                yield path

    def transcribe_folder(
        self,
        input_dir: Path,
        output_dir: Path,
        recursive: bool = True,
    ) -> List[TranscriptionResult]:
        output_dir.mkdir(parents=True, exist_ok=True)
        results: List[TranscriptionResult] = []

        for media_path in self.iter_media_files(input_dir, recursive):
            output_path = output_dir / f"{media_path.stem}.txt"
            try:
                result = self.transcribe_file(media_path, output_path)
            except FileNotFoundError:
                continue
            results.append(result)

        return results
