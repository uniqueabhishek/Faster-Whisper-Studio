"""Transcription utilities for Faster-Whisper GUI app."""

from __future__ import annotations
from faster_whisper import WhisperModel

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, List, Optional

try:
    from faster_whisper import WhisperModel
    import faster_whisper.vad
    import faster_whisper.transcribe

    LOGGER = logging.getLogger(__name__)

    import sys
    import os
    import time

    # Monkey patch VAD model path for offline use
    if getattr(sys, 'frozen', False):
        # If running as a bundled exe, look in the temporary folder
        _VAD_PATH = Path(sys._MEIPASS) / "assets" / "silero_vad.onnx"
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
                                input_feed[key] = val.reshape(2, batch_size, 64)
                            elif val.shape != (2, batch_size, 64):
                                # Fallback if shape is weird or size mismatch: reset to zeros
                                input_feed[key] = np.zeros((2, batch_size, 64), dtype=np.float32)
                        else:
                            # Not in input feed, initialize zeros
                            input_feed[key] = np.zeros((2, batch_size, 64), dtype=np.float32)

                # 3. Run session
                outputs = self._session.run(output_names, input_feed, run_options)

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
    LOGGER = logging.getLogger(__name__)
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


class Transcriber:
    """High-level wrapper around Faster-Whisper."""

    def __init__(self, config: TranscriptionConfig) -> None:
        self._config = config
        self._model: WhisperModel = self._load_model()

    def _load_model(self) -> WhisperModel:
        LOGGER.info("Model path used: %s", self._config.model_name)
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

        LOGGER.info("Loading local offline model: %s", model_path)
        LOGGER.info("Device: %s, Compute type: %s",
                    self._config.device, self._config.compute_type)

        try:
            return WhisperModel(
                str(model_path),
                device=self._config.device,
                compute_type=self._config.compute_type,
            )
        except Exception as e:
            LOGGER.error("Failed to load model: %s", str(e))
            raise

    def _convert_to_wav(self, input_path: Path) -> Optional[Path]:
        """Converts input to 16kHz mono WAV using ffmpeg to fix duration issues."""
        import subprocess
        import tempfile
        import shutil
        import os
        import wave

        if not shutil.which("ffmpeg"):
            LOGGER.warning("ffmpeg not found. Skipping audio repair.")
            return None

        # Optimization: Check if file is already 16kHz mono WAV
        if input_path.suffix.lower() == ".wav":
            try:
                with wave.open(str(input_path), "rb") as wf:
                    # Check: 1 channel, 16kHz, 16-bit (2 bytes)
                    if (wf.getnchannels() == 1 and
                        wf.getframerate() == 16000 and
                        wf.getsampwidth() == 2):
                        LOGGER.info("File is already 16kHz mono WAV. Skipping conversion.")
                        return None
            except Exception:
                # If any error reading wav header, proceed to ffmpeg
                pass

        try:
            # Create temp file path
            fd, temp_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            temp_path = Path(temp_path)

            LOGGER.info("Repairing audio with ffmpeg: %s -> %s", input_path, temp_path)

            # ffmpeg -i input -ar 16000 -ac 1 -c:a pcm_s16le output.wav
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                str(temp_path)
            ]

            # Run ffmpeg (suppress output unless error)
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if temp_path.exists() and temp_path.stat().st_size > 0:
                LOGGER.info("Audio repair successful.")
                return temp_path
            else:
                LOGGER.error("ffmpeg produced empty file.")
                return None

        except Exception as e:
            LOGGER.error("Audio repair failed: %s", str(e))
            return None

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
    ) -> TranscriptionResult:
        LOGGER.info("=== TRANSCRIBE_FILE CALLED ===")
        LOGGER.info("Input: %s", input_path)
        LOGGER.info("Output: %s", output_path)

        if not input_path.is_file():
            raise FileNotFoundError(f"Input file not found: {input_path}")

        # Try to repair/convert audio first
        temp_wav = self._convert_to_wav(input_path)
        actual_input = temp_wav if temp_wav else input_path

        bs = beam_size if beam_size is not None else self._config.beam_size
        lang = language if language else self._config.language

        LOGGER.info("Calling model.transcribe() with beam_size=%d, vad_filter=%s, language=%s, prompt=%s...",
                    bs, vad_filter, lang, initial_prompt)

        start_time = time.time()
        # Standard Speech VAD parameters (More responsive)
        vad_params = dict(
            min_silence_duration_ms=3000,
            speech_pad_ms=1000,
            threshold=0.1,
        ) if vad_filter else None

        try:
            segments, info = self._model.transcribe(
                str(actual_input),
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
        except Exception as e:
            # Fallback for VAD errors (e.g. invalid model file or missing dependencies)
            if vad_filter and ("ONNXRuntimeError" in str(e) or "INVALID_PROTOBUF" in str(e)):
                LOGGER.warning(f"VAD failed to load ({e}). Retrying with VAD disabled.")
                segments, info = self._model.transcribe(
                    str(actual_input),
                    language=lang,
                    beam_size=bs,
                    best_of=self._config.best_of,
                    vad_filter=False,
                    initial_prompt=initial_prompt,
                )
            else:
                raise e
        LOGGER.info("Model.transcribe() completed")

        total_duration = info.duration
        LOGGER.info("Audio duration: %.2fs", total_duration)

        LOGGER.info("Processing segments...")
        lines: List[str] = []

        def format_timestamp(seconds: float) -> str:
            mm, ss = divmod(int(seconds), 60)
            hh, mm = divmod(mm, 60)
            if hh > 0:
                return f"{hh:02d}:{mm:02d}:{ss:02d}"
            return f"{mm:02d}:{ss:02d}"

        ai_processed_duration = 0.0
        for segment in segments:
            ai_processed_duration += (segment.end - segment.start)
            if getattr(segment, "text", "").strip():
                if add_timestamps:
                    start_str = format_timestamp(segment.start)
                    end_str = format_timestamp(segment.end)
                    lines.append(f"[{start_str} -> {end_str}] {segment.text.strip()}")
                else:
                    lines.append(segment.text.strip())

            # Update progress
            if progress_callback and total_duration > 0:
                current_time = segment.end
                percent = int((current_time / total_duration) * 100)
                progress_callback(min(percent, 100))

        text = "\n".join(lines)
        LOGGER.info("Processed %d text lines", len(lines))

        # --- Generate Transcription Report ---
        vad_status = "Active" if vad_filter else "Not Active"
        timestamp_status = "Yes" if add_timestamps else "No"

        # Map beam_size to Word Analysis Depth name
        depth_name = "Custom"
        if bs == 5 and self._config.compute_type == "int8":
            depth_name = "Fast Analysis (int8)"
        elif bs == 5 and self._config.compute_type == "float32":
            depth_name = "Precise Analysis (float32)"
        elif bs == 10:
            depth_name = "Deep Analysis (float32)"

        vad_removed_duration = max(0.0, total_duration - ai_processed_duration) if vad_filter else 0.0

        report = [
            "\n\n" + "="*30,
            "TRANSCRIPTION REPORT",
            "="*30,
            f"Model Used: {self._config.model_name}",
            f"Word Analysis Depth: {depth_name} (Beam Size: {bs})",
            f"Smart Silence Removal (VAD): {vad_status}",
            f"Timestamp Added: {timestamp_status}",
            f"Language: {lang}",
            f"Task: {task.capitalize()}",
            "-"*30,
            f"Total Audio Duration: {format_timestamp(total_duration)}",
            f"VAD Removed Duration: {format_timestamp(vad_removed_duration)}",
            f"AI Processed Duration: {format_timestamp(ai_processed_duration)}",
            f"Processing Time: {format_timestamp(time.time() - start_time)}",
            "="*30
        ]

        report_str = "\n".join(report)

        if add_report:
            text += report_str

        # Log the report so it shows in the GUI
        LOGGER.info(report_str)



        # Cleanup temp file
        if temp_wav and temp_wav.exists():
            try:
                LOGGER.info("Removing temp file: %s", temp_wav)
                os.unlink(temp_wav)
            except Exception as e:
                LOGGER.warning("Failed to remove temp file: %s", e)

        resolved_output: Optional[Path] = None
        if output_path is not None:
            LOGGER.info("Saving to file...")
            resolved_output = output_path
            resolved_output.parent.mkdir(parents=True, exist_ok=True)
            resolved_output.write_text(text, encoding="utf-8")
            LOGGER.info("Saved transcription to %s", resolved_output)

        LOGGER.info("Creating result object...")
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
