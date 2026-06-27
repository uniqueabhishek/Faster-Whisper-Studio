"""Audio preprocessing utilities for Faster-Whisper GUI."""

from __future__ import annotations

import logging
import subprocess
import tempfile
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

# Import transcriber to ensure VAD model patches are applied
# This MUST be imported before any faster_whisper.vad imports
try:
    import transcriber  # noqa: F401
    LOGGER = logging.getLogger(__name__)
    LOGGER.info("Transcriber imported - VAD patches applied")
except ImportError:
    LOGGER = logging.getLogger(__name__)
    LOGGER.warning("Could not import transcriber - VAD may not work correctly")


@dataclass
class PreprocessingConfig:
    """Configuration for audio preprocessing operations."""
    # Enable/disable flags
    convert_to_wav: bool = True
    trim_silence: bool = False
    normalize_audio: bool = False
    reduce_noise: bool = False
    remove_music: bool = False

    # Noise Reduction parameters
    noise_reduction_nr: float = 12.0      # Noise reduction strength (dB)
    noise_reduction_nf: float = -25.0     # Noise floor (dB)
    noise_reduction_gs: int = 3           # Gain smoothing (0-10)

    # Music Removal parameters
    music_highpass_freq: int = 200        # High-pass filter cutoff (Hz)
    music_lowpass_freq: int = 3500        # Low-pass filter cutoff (Hz)

    # Normalization parameters
    normalize_target_db: float = -20.0    # Target loudness (LUFS)
    normalize_true_peak: float = -1.5     # True peak limit (dB)
    normalize_loudness_range: int = 11    # Loudness range

    # VAD parameters
    vad_min_silence_ms: int = 3000        # Min silence duration (ms)
    vad_speech_pad_ms: int = 1000         # Speech padding (ms)
    vad_threshold: float = 0.1            # Detection threshold

    # WAV Conversion parameters
    wav_sample_rate: int = 16000          # Sample rate (Hz)
    wav_channels: int = 1                 # Channels (1=mono, 2=stereo)
    wav_bit_depth: int = 16               # Bit depth (16, 24, or 32)

    output_dir: Optional[Path] = None


def convert_to_wav_16khz_mono(
    input_path: Path,
    output_path: Path,
    sample_rate: int = 16000,
    channels: int = 1,
    bit_depth: int = 16,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Convert any audio format to WAV using ffmpeg with configurable parameters.

    Args:
        input_path: Path to input audio file
        output_path: Path where converted WAV will be saved
        sample_rate: Target sample rate in Hz (default: 16000)
        channels: Number of audio channels - 1=mono, 2=stereo (default: 1)
        bit_depth: Bit depth - 16, 24, or 32 (default: 16)
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Converting %s to %dHz %s %d-bit WAV...",
                   input_path.name, sample_rate,
                   "mono" if channels == 1 else "stereo", bit_depth)

        # Map bit depth to codec
        codec_map = {
            16: "pcm_s16le",
            24: "pcm_s24le",
            32: "pcm_s32le"
        }
        codec = codec_map.get(bit_depth, "pcm_s16le")

        # ffmpeg -i input -ar <sample_rate> -ac <channels> -c:a <codec> output.wav
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-ar", str(sample_rate),
            "-ac", str(channels),
            "-c:a", codec,
            str(output_path)
        ]

        # Use Popen to allow cancellation
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        # Poll for completion while checking for cancellation
        while True:
            if cancel_check and cancel_check():
                process.kill()
                LOGGER.info("Conversion cancelled for %s", input_path.name)
                # Clean up partial file
                if output_path.exists():
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                return False

            if process.poll() is not None:
                break

            import time
            time.sleep(0.1)

        if process.returncode != 0:
            LOGGER.error("ffmpeg conversion failed with return code: %d", process.returncode)
            return False

        LOGGER.info("Successfully converted %s to WAV", input_path.name)
        return True

    except Exception as e:
        LOGGER.error("Conversion failed for %s: %s", input_path.name, str(e))
        return False


def normalize_audio(
    input_path: Path,
    output_path: Path,
    target_db: float = -20.0,
    true_peak: float = -1.5,
    loudness_range: int = 11,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Normalize audio volume using ffmpeg loudnorm filter (EBU R128 standard).

    Args:
        input_path: Path to input audio file
        output_path: Path where normalized audio will be saved
        target_db: Target integrated loudness in LUFS (default: -20.0)
        true_peak: True peak limit in dB (default: -1.5)
        loudness_range: Loudness range target (default: 11)
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Normalizing %s to %s LUFS (TP: %s, LRA: %s)...",
                   input_path.name, target_db, true_peak, loudness_range)

        # ffmpeg loudnorm filter for EBU R128 normalization
        # I = integrated loudness target
        # TP = true peak target
        # LRA = loudness range target
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", f"loudnorm=I={target_db}:TP={true_peak}:LRA={loudness_range}",
            str(output_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        while True:
            if cancel_check and cancel_check():
                process.kill()
                LOGGER.info("Normalization cancelled for %s", input_path.name)
                if output_path.exists():
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                return False

            if process.poll() is not None:
                break

            import time
            time.sleep(0.1)

        if process.returncode != 0:
            LOGGER.error("ffmpeg normalization failed with return code: %d", process.returncode)
            return False

        LOGGER.info("Successfully normalized %s", input_path.name)
        return True

    except Exception as e:
        LOGGER.error("Normalization failed for %s: %s", input_path.name, str(e))
        return False


def reduce_noise(
    input_path: Path,
    output_path: Path,
    noise_reduction: float = 12.0,
    noise_floor: float = -25.0,
    gain_smooth: int = 3,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Apply noise reduction using ffmpeg afftdn filter (FFT-based adaptive denoiser).

    Args:
        input_path: Path to input audio file
        output_path: Path where denoised audio will be saved
        noise_reduction: Noise reduction strength in dB (default: 12.0, range: 5-30)
        noise_floor: Noise floor threshold in dB (default: -25.0, range: -50 to -20)
        gain_smooth: Gain smoothing/artifact reduction (default: 3, range: 0-10)
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Reducing noise in %s (nr=%s, nf=%s, gs=%s)...",
                   input_path.name, noise_reduction, noise_floor, gain_smooth)

        # afftdn = FFT Denoiser
        # nr = noise reduction strength (dB)
        # nf = noise floor threshold (dB)
        # gs = gain smoothing for artifact reduction
        filter_str = f"afftdn=nr={noise_reduction}:nf={noise_floor}:gs={gain_smooth}"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", filter_str,
            str(output_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        while True:
            if cancel_check and cancel_check():
                process.kill()
                LOGGER.info("Noise reduction cancelled for %s", input_path.name)
                if output_path.exists():
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                return False

            if process.poll() is not None:
                break

            import time
            time.sleep(0.1)

        if process.returncode != 0:
            LOGGER.error("ffmpeg noise reduction failed with return code: %d", process.returncode)
            return False

        LOGGER.info("Successfully reduced noise in %s", input_path.name)
        return True

    except Exception as e:
        LOGGER.error("Noise reduction failed for %s: %s", input_path.name, str(e))
        return False


def remove_music(
    input_path: Path,
    output_path: Path,
    highpass_freq: int = 200,
    lowpass_freq: int = 3500,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Remove background music using ffmpeg bandpass filter to isolate speech frequencies.

    This uses a combination of filters to suppress music while preserving speech:
    - High-pass filter to remove low-frequency music/bass
    - Low-pass filter to remove high frequencies outside speech range

    Args:
        input_path: Path to input audio file
        output_path: Path where processed audio will be saved
        highpass_freq: High-pass filter cutoff in Hz (default: 200, range: 80-300)
        lowpass_freq: Low-pass filter cutoff in Hz (default: 3500, range: 3000-4000)
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Removing background music from %s (HPF: %dHz, LPF: %dHz)...",
                   input_path.name, highpass_freq, lowpass_freq)

        # Use a combination of filters to isolate speech frequencies:
        # 1. highpass=f=<freq>: Remove frequencies below threshold (removes bass/low music)
        # 2. lowpass=f=<freq>: Remove frequencies above threshold (human speech range)

        # Speech-optimized filter chain
        filter_chain = f"highpass=f={highpass_freq},lowpass=f={lowpass_freq}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", filter_chain,
            str(output_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        while True:
            if cancel_check and cancel_check():
                process.kill()
                LOGGER.info("Music removal cancelled for %s", input_path.name)
                if output_path.exists():
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                return False

            if process.poll() is not None:
                break

            import time
            time.sleep(0.1)

        if process.returncode != 0:
            LOGGER.error("ffmpeg music removal failed with return code: %d", process.returncode)
            return False

        LOGGER.info("Successfully removed music from %s", input_path.name)
        return True

    except Exception as e:
        LOGGER.error("Music removal failed for %s: %s", input_path.name, str(e))
        return False


def trim_silence_vad(
    input_path: Path,
    output_path: Path,
    min_silence_ms: int = 3000,
    speech_pad_ms: int = 1000,
    threshold: float = 0.1,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Use VAD (Voice Activity Detection) to remove silence segments from audio.
    This concatenates all detected speech segments, removing silence from anywhere in the audio.
    Reuses the existing silero_vad.onnx model.

    Args:
        input_path: Path to input audio file
        output_path: Path where trimmed audio will be saved
        min_silence_ms: Minimum silence duration to remove in ms (default: 3000)
        speech_pad_ms: Speech padding/buffer in ms (default: 1000)
        threshold: Speech detection threshold 0.0-1.0 (default: 0.1)
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Trimming silence from %s using VAD (min_silence=%dms, pad=%dms, threshold=%.2f)...",
                   input_path.name, min_silence_ms, speech_pad_ms, threshold)

        # Import dependencies for VAD
        try:
            import numpy as np
            import soundfile as sf

            # Import VAD functions (reuse existing patch from transcriber.py)
            from faster_whisper.vad import get_speech_timestamps, VadOptions

        except ImportError as e:
            LOGGER.error("Missing dependencies for VAD trimming: %s", str(e))
            LOGGER.info("Falling back to simple silence trimming with ffmpeg...")
            return _trim_silence_ffmpeg(input_path, output_path, cancel_check)

        # Load audio
        audio, sample_rate = sf.read(str(input_path))

        if cancel_check and cancel_check():
            return False

        # Convert to mono if stereo
        if len(audio.shape) > 1:
            audio = np.mean(audio, axis=1)

        # Resample to 16kHz for VAD if needed
        if sample_rate != 16000:
            try:
                import librosa
                audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
                sample_rate = 16000
            except ImportError:
                LOGGER.warning("librosa not available for resampling, using original sample rate")

        if cancel_check and cancel_check():
            return False

        # Configure VAD options with user-specified parameters
        vad_options = VadOptions(
            min_silence_duration_ms=min_silence_ms,
            speech_pad_ms=speech_pad_ms,
            threshold=threshold
        )

        # Get speech timestamps using proper VAD function
        speech_timestamps = get_speech_timestamps(
            audio,
            vad_options=vad_options,
            sampling_rate=sample_rate
        )

        if cancel_check and cancel_check():
            return False

        # If no speech detected, keep the original file
        if not speech_timestamps:
            LOGGER.warning("No speech detected in %s, keeping original", input_path.name)
            # Copy the file instead of trimming
            import shutil
            shutil.copy2(str(input_path), str(output_path))
            return True

        # Extract ALL speech segments and concatenate them
        speech_segments = []

        LOGGER.info("Found %d speech segments in %s", len(speech_timestamps), input_path.name)

        for i, segment in enumerate(speech_timestamps):
            if cancel_check and cancel_check():
                return False

            # get_speech_timestamps returns sample indices, not seconds
            start_sample = segment['start']
            end_sample = segment['end']

            # Extract this speech segment
            speech_chunk = audio[start_sample:end_sample]
            speech_segments.append(speech_chunk)

            LOGGER.debug("Segment %d: %.2fs - %.2fs (duration: %.2fs)",
                        i + 1, start_sample / sample_rate, end_sample / sample_rate,
                        (end_sample - start_sample) / sample_rate)

        # Concatenate all speech segments
        trimmed_audio = np.concatenate(speech_segments)

        if cancel_check and cancel_check():
            return False

        # Save trimmed audio
        sf.write(str(output_path), trimmed_audio, sample_rate)

        duration_removed = (len(audio) - len(trimmed_audio)) / sample_rate
        LOGGER.info("Removed %.2f seconds of silence from %s (kept %d speech segments)",
                   duration_removed, input_path.name, len(speech_timestamps))
        return True

    except Exception as e:
        LOGGER.error("VAD trimming failed for %s: %s", input_path.name, str(e))
        # Fallback to ffmpeg silence trimming
        LOGGER.info("Falling back to ffmpeg silence trimming...")
        return _trim_silence_ffmpeg(input_path, output_path, cancel_check)


def _trim_silence_ffmpeg(
    input_path: Path,
    output_path: Path,
    cancel_check: Optional[Callable[[], bool]] = None
) -> bool:
    """
    Fallback: trim silence using ffmpeg silenceremove filter.

    Args:
        input_path: Path to input audio file
        output_path: Path where trimmed audio will be saved
        cancel_check: Optional callable that returns True if cancellation is requested

    Returns:
        True if successful, False otherwise
    """
    try:
        LOGGER.info("Trimming silence from %s using ffmpeg...", input_path.name)

        # silenceremove filter
        # start_periods=1: remove silence from beginning
        # start_duration=0.5: minimum silence duration to remove (0.5s)
        # start_threshold=-50dB: silence threshold
        # stop_periods=-1: remove silence from end
        # stop_duration=0.5
        # stop_threshold=-50dB
        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-af", "silenceremove=start_periods=1:start_duration=0.5:start_threshold=-50dB:stop_periods=-1:stop_duration=0.5:stop_threshold=-50dB",
            str(output_path)
        ]

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        while True:
            if cancel_check and cancel_check():
                process.kill()
                LOGGER.info("Silence trimming cancelled for %s", input_path.name)
                if output_path.exists():
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                return False

            if process.poll() is not None:
                break

            import time
            time.sleep(0.1)

        if process.returncode != 0:
            LOGGER.error("ffmpeg silence trimming failed with return code: %d", process.returncode)
            return False

        LOGGER.info("Successfully trimmed silence from %s", input_path.name)
        return True

    except Exception as e:
        LOGGER.error("Silence trimming failed for %s: %s", input_path.name, str(e))
        return False


def preprocess_audio(
    input_path: Path,
    config: PreprocessingConfig,
    cancel_check: Optional[Callable[[], bool]] = None,
    progress_callback: Optional[Callable[[str, int], None]] = None
) -> Optional[Path]:
    """
    Apply all selected preprocessing operations to an audio file.

    Args:
        input_path: Path to input audio file
        config: Preprocessing configuration
        cancel_check: Optional callable that returns True if cancellation is requested
        progress_callback: Optional callable that takes (step_name: str, step_progress: int)
                          to report progress for each preprocessing step

    Returns:
        Path to preprocessed file if successful, None otherwise
    """
    import shutil

    # Check if ffmpeg is available
    if not shutil.which("ffmpeg"):
        LOGGER.error("ffmpeg not found. Cannot preprocess audio.")
        return None

    # Bound the temp-dir leak from earlier no-output-dir runs.
    _cleanup_stale_preprocess_dirs()

    try:
        # Determine output directory
        if config.output_dir:
            output_dir = config.output_dir
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Create temp directory
            output_dir = Path(tempfile.mkdtemp(prefix="whisper_preprocess_"))

        # Generate output filename
        output_filename = f"{input_path.stem}_preprocessed.wav"
        final_output = output_dir / output_filename

        # Track current file (starts as input, gets replaced with each step)
        current_file = input_path
        temp_files = []

        # Calculate total enabled steps for progress tracking
        enabled_steps = []
        if config.convert_to_wav:
            enabled_steps.append("Converting to WAV")
        if config.reduce_noise:
            enabled_steps.append("Removing Background Noise")
        if config.remove_music:
            enabled_steps.append("Removing Background Music")
        if config.normalize_audio:
            enabled_steps.append("Normalizing Audio Volume")
        if config.trim_silence:
            enabled_steps.append("Trimming Silence (VAD)")

        total_steps = len(enabled_steps)
        current_step = 0

        # Helper to emit step progress
        def emit_step_progress(step_name: str):
            nonlocal current_step
            if progress_callback:
                # Calculate progress: (current_step / total_steps) * 100
                step_percent = int((current_step / total_steps) * 100) if total_steps > 0 else 0
                progress_callback(step_name, step_percent)
            current_step += 1

        # Step 1: Convert to WAV (with configurable parameters)
        if config.convert_to_wav:
            emit_step_progress("Converting to WAV")
            temp_wav = output_dir / f"{input_path.stem}_temp_wav.wav"
            if not convert_to_wav_16khz_mono(
                current_file, temp_wav,
                sample_rate=config.wav_sample_rate,
                channels=config.wav_channels,
                bit_depth=config.wav_bit_depth,
                cancel_check=cancel_check
            ):
                _cleanup_temp_files(temp_files)
                return None
            temp_files.append(temp_wav)
            current_file = temp_wav

        # Step 2: Reduce Noise (works best on full spectrum before filtering)
        if config.reduce_noise:
            emit_step_progress("Removing Background Noise")
            temp_denoised = output_dir / f"{input_path.stem}_temp_denoised.wav"
            if not reduce_noise(
                current_file, temp_denoised,
                noise_reduction=config.noise_reduction_nr,
                noise_floor=config.noise_reduction_nf,
                gain_smooth=config.noise_reduction_gs,
                cancel_check=cancel_check
            ):
                _cleanup_temp_files(temp_files)
                return None
            temp_files.append(temp_denoised)
            current_file = temp_denoised

        # Step 3: Remove Music (isolate speech frequencies before normalization)
        if config.remove_music:
            emit_step_progress("Removing Background Music")
            temp_no_music = output_dir / f"{input_path.stem}_temp_no_music.wav"
            if not remove_music(
                current_file, temp_no_music,
                highpass_freq=config.music_highpass_freq,
                lowpass_freq=config.music_lowpass_freq,
                cancel_check=cancel_check
            ):
                _cleanup_temp_files(temp_files)
                return None
            temp_files.append(temp_no_music)
            current_file = temp_no_music

        # Step 4: Normalize Audio (on speech-band only for accurate loudness targeting)
        if config.normalize_audio:
            emit_step_progress("Normalizing Audio Volume")
            temp_normalized = output_dir / f"{input_path.stem}_temp_normalized.wav"
            if not normalize_audio(
                current_file, temp_normalized,
                target_db=config.normalize_target_db,
                true_peak=config.normalize_true_peak,
                loudness_range=config.normalize_loudness_range,
                cancel_check=cancel_check
            ):
                _cleanup_temp_files(temp_files)
                return None
            temp_files.append(temp_normalized)
            current_file = temp_normalized

        # Step 5: Trim Silence with VAD (works best on normalized, clean speech)
        if config.trim_silence:
            emit_step_progress("Trimming Silence (VAD)")
            temp_trimmed = output_dir / f"{input_path.stem}_temp_trimmed.wav"
            if not trim_silence_vad(
                current_file, temp_trimmed,
                min_silence_ms=config.vad_min_silence_ms,
                speech_pad_ms=config.vad_speech_pad_ms,
                threshold=config.vad_threshold,
                cancel_check=cancel_check
            ):
                _cleanup_temp_files(temp_files)
                return None
            temp_files.append(temp_trimmed)
            current_file = temp_trimmed

        # Copy final result to output path
        if current_file != final_output:
            shutil.copy2(str(current_file), str(final_output))

        # Cleanup temp files
        _cleanup_temp_files(temp_files)

        LOGGER.info("Preprocessing completed: %s -> %s", input_path.name, final_output.name)
        return final_output

    except Exception as e:
        LOGGER.error("Preprocessing failed for %s: %s", input_path.name, str(e))
        return None


def _cleanup_stale_preprocess_dirs(max_age_seconds: float = 3600) -> None:
    """Reap leftover ``whisper_preprocess_*`` temp dirs from earlier runs.

    When no output dir is configured, preprocessing stages its results under a
    ``mkdtemp`` dir whose final ``_preprocessed.wav`` is consumed later by
    transcription, so the dir can't be deleted on return. To keep this from
    growing without bound in %TEMP%, remove such dirs older than
    ``max_age_seconds`` at the start of each preprocessing run.
    """
    import shutil
    import time

    temp_root = Path(tempfile.gettempdir())
    now = time.time()
    try:
        stale_dirs = list(temp_root.glob("whisper_preprocess_*"))
    except OSError:
        return

    for directory in stale_dirs:
        try:
            if directory.is_dir() and (now - directory.stat().st_mtime) > max_age_seconds:
                shutil.rmtree(directory, ignore_errors=True)
                LOGGER.info("Removed stale preprocess temp dir: %s", directory)
        except OSError:
            pass


def _cleanup_temp_files(temp_files: list[Path]) -> None:
    """Clean up temporary files."""
    for temp_file in temp_files:
        try:
            if temp_file.exists():
                os.unlink(temp_file)
        except Exception as e:
            LOGGER.warning("Failed to delete temp file %s: %s", temp_file, str(e))
