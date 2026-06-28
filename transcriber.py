"""Transcription utilities for Faster-Whisper GUI app."""
# pyright: reportAttributeAccessIssue=false, reportOptionalMemberAccess=false

from __future__ import annotations

import os
import time
import logging
import math
import subprocess
import re
import shutil
import wave
import tempfile
import ctypes
import functools
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, List, Optional
from collections import namedtuple

from ffmpeg_utils import get_ffmpeg_path

LOGGER = logging.getLogger(__name__)

# Prefer a bundled ffmpeg (assets/ffmpeg/); fall back to PATH, then the bare name
# so behavior degrades to the previous PATH lookup when nothing is bundled.
_FFMPEG = get_ffmpeg_path() or "ffmpeg"

# --- GPU usability gate ----------------------------------------------------
# A CUDA device is only worth using if it can actually run large-v3-turbo: it
# needs room for the float16 weights (~770 MB) plus the CUDA/cuDNN context and
# beam-search activations, which together exceed the 2 GB on small laptop GPUs
# (they OOM at load). 4 GB cleanly excludes such cards while admitting real
# discrete GPUs.
MIN_CUDA_VRAM_BYTES = 4 * 1024 ** 3

# --- CPU smart-chunking knobs ----------------------------------------------
# CPU float32 keeps the full-size model resident in RAM, so faster-whisper's
# full-file STFT can OOM on long files. On CPU we chunk far earlier and far
# smaller than on GPU (where VRAM holds the model and full-file processing is
# fine).
CPU_CHUNK_THRESHOLD_MIN = 8     # minutes; CPU files longer than this get chunked
CPU_MIN_CHUNK_DURATION = 120    # 2 min (GPU/very-long path keeps MIN_CHUNK_DURATION)
CPU_MAX_CHUNK_DURATION = 300    # 5 min (GPU/very-long path keeps MAX_CHUNK_DURATION)
# If a chunk still hits a MemoryError, halve it and retry down to this floor
# before giving up — self-tunes to the machine without discarding earlier work.
ADAPTIVE_CHUNK_FLOOR_SEC = 60

try:
    from faster_whisper import WhisperModel
    # faster-whisper ships and uses Silero VAD v6 natively (faster_whisper/
    # assets/silero_vad_v6.onnx, loaded via get_vad_model()). We no longer
    # monkey-patch in a bundled v4 model + shim; the v6 asset is pulled into
    # frozen builds by collect_all('faster_whisper') in the PyInstaller spec.
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


# Re-exported from the dependency-free ``formatters`` module so existing callers
# (and tests) that do ``from transcriber import format_duration`` keep working.
from formatters import format_timestamp, format_duration  # noqa: E402  pylint: disable=wrong-import-position


@functools.lru_cache(maxsize=1)
def _cudnn_available() -> bool:
    """True if the cuDNN op library CTranslate2 needs at inference can be loaded.

    CTranslate2 loads cuDNN lazily inside native code on the first transcribe;
    if it's missing the process dies with an uncatchable 0xC0000409 (we observed
    "cudnn_ops_infer64_8.dll not found"). An EXPLICIT load here hands control back
    to Python (OSError on failure), so we can detect the gap up front and stay on
    CPU instead of hard-crashing mid-transcription. Loading also pulls cuDNN's own
    dependencies, so a success means the whole chain is usable.
    """
    name = ("cudnn_ops_infer64_8.dll" if os.name == "nt"
            else "libcudnn_ops_infer.so.8")
    try:
        ctypes.CDLL(name)
        return True
    except OSError:
        return False


@functools.lru_cache(maxsize=1)
def _cuda_vram_bytes() -> Optional[int]:
    """Total VRAM of the first CUDA GPU in bytes via nvidia-smi, or None."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
        if out.returncode != 0 or not out.stdout.strip():
            return None
        first = out.stdout.strip().splitlines()[0].strip()
        return int(first) * 1024 * 1024  # MiB -> bytes
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("Could not query GPU VRAM (%s).", exc)
        return None


@functools.lru_cache(maxsize=1)
def gpu_is_usable() -> bool:
    """True only if the CUDA GPU can actually run the model end-to-end.

    Guards two independent failures a bare device count misses: missing cuDNN
    (inference hard-crashes) and too-little VRAM (the model OOMs at load). Either
    one => stay on CPU. Memoized; the hardware is fixed for the process lifetime.
    """
    if not _cudnn_available():
        LOGGER.warning("GPU gated off: cuDNN not available — using CPU.")
        return False
    vram = _cuda_vram_bytes()
    if vram is None:
        LOGGER.warning("GPU gated off: could not determine VRAM — using CPU.")
        return False
    if vram < MIN_CUDA_VRAM_BYTES:
        LOGGER.warning(
            "GPU gated off: VRAM %d MB < %d MB minimum for this model — using CPU.",
            vram // (1024 * 1024), MIN_CUDA_VRAM_BYTES // (1024 * 1024))
        return False
    return True


def detect_device() -> str:
    """Return 'cuda' only if a GPU is present AND can actually run the model.

    CTranslate2's device count says a GPU exists, but not whether cuDNN is
    installed or whether there's enough VRAM. ``gpu_is_usable()`` checks both, so
    a too-small/cuDNN-less card (which would OOM at load or hard-crash at the
    first transcribe) falls back to CPU here instead of crashing later.
    """
    try:
        import ctranslate2  # pylint: disable=import-outside-toplevel
        if ctranslate2.get_cuda_device_count() > 0 and gpu_is_usable():
            return "cuda"
    except Exception as exc:  # pylint: disable=broad-except
        LOGGER.info("GPU detection unavailable (%s). Using CPU.", exc)
    return "cpu"


def resolve_quality(depth_label: str, device: str = "cpu") -> dict:
    """Map a UI 'analysis depth' label to engine settings.

    Keeps this policy out of the GUI. beam_size/patience are device-independent;
    compute_type is adjusted for the device: GPU always runs float16 (the
    recommended Whisper GPU precision and the only way large-v3-turbo fits a
    small card), CPU keeps the requested precision (float32 for Precise/Deep,
    int8 for Fast).
    """
    label = (depth_label or "").lower()
    if "deep" in label:
        compute_type, beam_size, patience = "float32", 10, 2.0
    elif "precise" in label:
        compute_type, beam_size, patience = "float32", 5, 1.0
    else:  # Fast / default
        compute_type, beam_size, patience = "int8", 5, 1.0
    if device == "cuda":
        # float16 on GPU regardless of preset: int8 isn't supported on CUDA, and
        # float16 halves VRAM vs float32 with a quality delta below the model's
        # own decoding noise. beam_size still distinguishes Precise (5) / Deep (10).
        compute_type = "float16"
    return {"compute_type": compute_type, "beam_size": beam_size, "patience": patience}


def cpu_compute_type(compute_type: str) -> str:
    """Pick a CPU compute type for the (now rare) GPU->CPU fallback.

    We only reach CPU after the whole GPU ladder is exhausted (the requested
    precision AND int8_float16, which has ~4x smaller weights and fits tiny
    cards). So a GPU machine stays on the GPU; CPU is for boxes with no usable
    CUDA at all. When we do land here the user asked for the best possible CPU
    quality, which is ``float32`` — so the GPU-only types (``float16`` /
    ``int8_float16`` / ``int8_float32``, none valid on CPU) map to ``float32``.
    A user who explicitly picked ``int8`` (Fast) keeps it.
    """
    if compute_type in ("float16", "int8_float16", "int8_float32"):
        return "float32"
    return compute_type


# Lightweight stand-in for faster-whisper's TranscriptionInfo, used when we
# assemble segments ourselves (the smart-chunking path) and have no real info
# object from the model. Defined once here rather than re-declared inline.
_TranscriptionInfo = namedtuple(
    "TranscriptionInfo", ["duration", "language", "language_probability"])


class Transcriber:
    """High-level wrapper around Faster-Whisper."""

    def __init__(self, config: TranscriptionConfig) -> None:
        self._config = config
        # Set True if a CUDA load failed and we transparently loaded on CPU,
        # so the GUI can tell the user they're on the slower path.
        self.fell_back_to_cpu = False
        # Set to (requested, used) if the GPU couldn't fit the requested
        # precision and we loaded a smaller GPU precision instead (e.g. asked
        # float16, got int8_float16 because the card is too small for float16).
        self.gpu_precision_downgraded: Optional[tuple[str, str]] = None
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

        device = self._config.device
        compute_type = self._config.compute_type
        LOGGER.info("Loading model: %s (%s, %s)",
                    model_path.name, device, compute_type)

        # Pure-CPU machine (no CUDA): load at the requested precision and let a
        # failure propagate — there's nowhere lower to fall.
        if device != "cuda":
            try:
                return self._build_model(model_path, device, compute_type)
            except Exception as e:
                LOGGER.error("Failed to load model: %s", str(e))
                raise

        # CUDA: walk a precision ladder so a small card stays on the GPU instead
        # of dropping to slow CPU. A GPU load fails almost only on CUDA
        # out-of-memory; the requested float16 weights may not fit a 2GB card,
        # but int8_float16 (~4x smaller weights, float16 compute) usually does.
        gpu_ladder = [compute_type]
        if "int8" not in compute_type:
            gpu_ladder.append("int8_float16")
        last_gpu_err: Optional[Exception] = None
        for ct in gpu_ladder:
            try:
                model = self._build_model(model_path, "cuda", ct)
            except Exception as e:  # pylint: disable=broad-except
                last_gpu_err = e
                LOGGER.warning("GPU load at %s failed (%s).", ct, e)
                continue
            if ct != compute_type:
                # Loaded on the GPU, but at a lower precision than requested.
                self.gpu_precision_downgraded = (compute_type, ct)
                self._config = replace(self._config, compute_type=ct)
                LOGGER.warning(
                    "GPU too small for %s; loaded %s on GPU instead "
                    "(weights quantized, compute stays float16).",
                    compute_type, ct)
            else:
                LOGGER.info("Model loaded on GPU (%s).", ct)
            return model

        # Whole GPU ladder exhausted — fall back to CPU at the best quality the
        # user asked for (float32), which is slower but always has room.
        cpu_compute = cpu_compute_type(compute_type)
        LOGGER.warning(
            "All GPU attempts failed (%s). Falling back to CPU (%s).",
            last_gpu_err, cpu_compute)
        try:
            model = self._build_model(model_path, "cpu", cpu_compute)
        except Exception as cpu_e:
            LOGGER.error("CPU fallback also failed: %s", cpu_e)
            raise

        # Reflect the device/compute_type that actually loaded so the report and
        # the GUI's reload check see reality, not the original request.
        self._config = replace(
            self._config, device="cpu", compute_type=cpu_compute)
        self.fell_back_to_cpu = True
        LOGGER.info("Model loaded on CPU after GPU fallback.")
        return model

    def _build_model(self, model_path: Path, device: str,
                     compute_type: str) -> WhisperModel:
        """Instantiate the CTranslate2 Whisper model on a specific device."""
        return WhisperModel(
            str(model_path),
            device=device,
            compute_type=compute_type,
            cpu_threads=self._config.cpu_threads,
            num_workers=self._config.num_workers,
        )

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
            fd, temp_path = tempfile.mkstemp(prefix="fwgui_", suffix=".wav")
            os.close(fd)
            temp_path = Path(temp_path)

            LOGGER.info("Preparing audio (converting to 16kHz mono WAV)...")

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

            try:
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
            finally:
                # Reap the child even if the poll loop raised, so the handle never
                # leaks.
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass

            if process.returncode != 0:
                LOGGER.warning(
                    "ffmpeg failed with return code: %d", process.returncode)
                return None

            LOGGER.info("Audio prepared.")
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
            fd, temp_path = tempfile.mkstemp(prefix="fwgui_", suffix=".wav")
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

            try:
                while True:
                    if cancel_check and cancel_check():
                        process.kill()
                        raise Exception("Cancelled")
                    if process.poll() is not None:
                        break
                    time.sleep(0.1)
            finally:
                # Reap the child even if the poll loop raised (no handle leak).
                if process.poll() is None:
                    try:
                        process.kill()
                    except OSError:
                        pass

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
            # Classify the cause so the log distinguishes disk-full / permissions
            # / other ffmpeg failures rather than an opaque message.
            detail = type(e).__name__
            if isinstance(e, OSError) and e.errno is not None:
                detail = f"{detail}(errno={e.errno})"
            LOGGER.error("Failed to slice audio (%s): %s", detail, e)
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
                    "No silence found in window %s-%s. Using hard split.",
                    format_duration(start_search), format_duration(actual_search_end))
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
                "Smart split found at %s (silence %.1fs)",
                format_duration(final_split_time), best_silence[1])
            return final_split_time

        except Exception as e:  # pylint: disable=broad-except
            LOGGER.warning("Smart split failed: %s. using hard split.", e)
            return fallback_split

    MIN_CHUNK_DURATION = 600   # 10 minutes
    MAX_CHUNK_DURATION = 1200  # 20 minutes

    @staticmethod
    def _is_memory_error(e: Exception) -> bool:
        """True for the ways numpy/the runtime report an out-of-memory."""
        error_str = str(e)
        return ("MemoryError" in error_str or "Unable to allocate" in error_str
                or isinstance(e, MemoryError) or "ArrayMemoryError" in error_str)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        """Delete a temp file, ignoring 'already gone' / OS errors."""
        try:
            if path.exists():
                os.unlink(path)
        except OSError:
            pass

    def _yield_span(self, input_path: Path, start: float, duration: float,
                    chunk_kwargs: dict,
                    cancel_check: Optional[Callable[[], bool]] = None):
        """Transcribe one ``[start, start+duration]`` span, yielding segments with
        timestamps shifted back onto the original file.

        On a MemoryError the span is halved and each half retried, recursing down
        to ``ADAPTIVE_CHUNK_FLOOR_SEC``. This self-tunes chunk size to the machine
        and, because it runs inside the streaming generator, preserves every
        segment already yielded from earlier spans (no discard-on-failure).
        Non-memory errors, and OOMs at the floor, re-raise.
        """
        if cancel_check and cancel_check():
            raise Exception("Cancelled")

        temp_chunk = self._slice_audio(
            input_path, start, duration, cancel_check=cancel_check)
        if not temp_chunk:
            # A failed slice would otherwise silently truncate the transcript
            # while the caller still marks the file "completed". Fail loudly so
            # the file is recorded as failed instead of partially-done.
            raise RuntimeError(
                f"Failed to create audio slice at {format_duration(start)}. "
                "Aborting chunked transcription to avoid silent truncation.")

        try:
            segments, _ = self._model.transcribe(str(temp_chunk), **chunk_kwargs)
            for segment in segments:
                # Adjust timestamps relative to the original file.
                new_start = segment.start + start
                new_end = segment.end + start
                if hasattr(segment, '_replace'):
                    # Older faster-whisper versions use namedtuples.
                    yield segment._replace(start=new_start, end=new_end)
                else:
                    # Newer versions use the Segment class - copy with new times.
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
            half = duration / 2
            if self._is_memory_error(e) and half >= ADAPTIVE_CHUNK_FLOOR_SEC:
                LOGGER.warning(
                    "MemoryError on span [%s -> %s]; splitting in half (%s each) "
                    "and retrying — earlier audio is kept.",
                    format_duration(start), format_duration(start + duration),
                    format_duration(half))
                # Free this span's slice before recursing so retries don't pile
                # up on disk (the finally below is then a no-op).
                self._safe_unlink(temp_chunk)
                yield from self._yield_span(
                    input_path, start, half, chunk_kwargs, cancel_check)
                yield from self._yield_span(
                    input_path, start + half, half, chunk_kwargs, cancel_check)
                return
            # Non-memory error, or already at the floor: surface it.
            LOGGER.error(
                "Error processing span [%s -> %s] (%s): %s",
                format_duration(start), format_duration(start + duration),
                type(e).__name__, e)
            raise
        finally:
            self._safe_unlink(temp_chunk)

    def _transcribe_chunked(self, input_path: Path, total_duration: float, transcribe_kwargs: dict,
                            cancel_check: Optional[Callable[[], bool]] = None):
        """Generator yielding segments by processing audio in physical chunks
        (safe for low memory).

        Chunk size is device-aware — small on CPU (the float32 model is resident
        in RAM, where faster-whisper's full-file STFT can OOM) and larger on GPU.
        A chunk that still OOMs is adaptively sub-divided by ``_yield_span``.

        ``cancel_check``: optional callable returning True to abort between
        chunks and during the (now killable) per-chunk slice.
        """
        # Remove chunk_length to prevent nested chunking issues.
        chunk_kwargs = transcribe_kwargs.copy()
        chunk_kwargs.pop('chunk_length', None)

        if self._config.device == "cpu":
            min_dur, max_dur = CPU_MIN_CHUNK_DURATION, CPU_MAX_CHUNK_DURATION
        else:
            min_dur, max_dur = self.MIN_CHUNK_DURATION, self.MAX_CHUNK_DURATION

        current_time = 0.0
        while current_time < total_duration:
            if cancel_check and cancel_check():
                raise Exception("Cancelled")

            # Aim for a chunk between min_dur and max_dur, split on silence.
            search_start = current_time + min_dur
            if search_start >= total_duration:
                split_point = total_duration
            else:
                end_limit = min(current_time + max_dur, total_duration)
                search_window = end_limit - search_start
                if search_window <= 0:
                    split_point = end_limit
                else:
                    split_point = self._find_nearest_silence(
                        input_path, search_start, search_window)

            # Safety check: ensure we always advance.
            if split_point <= current_time:
                split_point = current_time + min_dur
            split_point = min(split_point, total_duration)

            chunk_duration = split_point - current_time
            LOGGER.info(
                "Processing chunk: %s - %s (duration %s)",
                format_duration(current_time), format_duration(split_point),
                format_duration(chunk_duration))

            yield from self._yield_span(
                input_path, current_time, chunk_duration, chunk_kwargs, cancel_check)

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
        Long files use smart (physical) chunking to bound memory. The threshold
        is device-aware: CPU keeps the full-size float32 model resident in RAM
        (where faster-whisper's full-file STFT can OOM), so it chunks far earlier
        than GPU, which holds the model in VRAM and handles full files fine. A
        user-configured ``chunk_length`` disables auto-detection.
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
        threshold_minutes = (CPU_CHUNK_THRESHOLD_MIN
                             if self._config.device == "cpu" else 40)
        if duration_minutes > threshold_minutes:
            LOGGER.info(
                "Audio duration: %s - long file, using smart chunking "
                "(physical splitting) to prevent memory errors.",
                format_duration(full_duration))
            return full_duration, True, None

        LOGGER.info("Audio duration: %s - standard processing.",
                    format_duration(full_duration))
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
            if self._is_memory_error(e) and not use_smart_chunking:
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
        render_start = time.time()
        last_log_time = render_start

        for segment in segments:
            # Honor cancellation between segments. faster-whisper streams
            # segments lazily, so this is observed within one segment (seconds),
            # making a long single file genuinely interruptible.
            if cancel_check and cancel_check():
                raise Exception("Cancelled")

            # Log progress every 60 seconds, with elapsed time and an ETA so a
            # long transcription shows how far along it is and how long is left.
            if time.time() - last_log_time >= 60.0:
                audio_progress = segment.end if hasattr(segment, 'end') else 0
                frac = (audio_progress / total_duration) if total_duration > 0 else 0
                elapsed = time.time() - render_start
                eta_str = format_duration(
                    elapsed / frac - elapsed) if frac > 0.01 else "--:--"
                LOGGER.info("Progress: %3.0f%%  |  elapsed %s  |  ETA %s",
                            frac * 100, format_duration(elapsed), eta_str)
                last_log_time = time.time()

            seg_duration = segment.end - segment.start
            if math.isfinite(seg_duration) and seg_duration >= 0:
                ai_processed_duration += seg_duration
            else:
                LOGGER.warning(
                    "Ignoring segment with non-finite timestamps in the duration "
                    "metric: start=%s end=%s", segment.start, segment.end)
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

        # Map beam_size to Word Analysis Depth name, showing the precision that
        # actually ran (float16 / int8_float16 on GPU, float32 on CPU).
        ct = self._config.compute_type
        depth_name = "Custom"
        if bs == 5 and ct == "int8":
            depth_name = "Fast Analysis (int8)"
        elif bs == 5:
            depth_name = f"Precise Analysis ({ct})"
        elif bs == 10:
            depth_name = f"Deep Analysis ({ct})"

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
