# Voice Activity Detection (VAD) in Faster-Whisper GUI

## What is VAD?
**Voice Activity Detection (VAD)** is a technique used to detect the presence or absence of human speech in an audio stream. This project integrates **Silero VAD**, a pre-trained, high-quality, and lightweight enterprise-grade VAD model.

Its primary job is to "listen" to the audio first and cut out all the silence, static, and background noise, passing only the actual speech to the heavy Whisper transcriber.

---

## How VAD is integrated
This project uses **faster-whisper's native Silero VAD (v6)** — the
`silero_vad_v6.onnx` model that ships inside the `faster-whisper` package and is
loaded by its own `get_vad_model()` / `SileroVADModel`. There is no app-side VAD
model file and no runtime patching: we call `faster_whisper.vad.get_speech_timestamps`
and let the library run its bundled model.

The v6 asset is pulled into frozen (PyInstaller) builds automatically by
`collect_all('faster_whisper')` in `FasterWhisperGUI.spec`, so offline use works
without shipping a separate copy.

---

## History: the retired v4 adapter
Earlier builds bundled an older **Silero VAD v4** model (`assets/silero_vad.onnx`)
and monkey-patched `faster_whisper.vad.get_vad_model` to load it through a custom
`SessionWrapper` adapter in `transcriber.py`. At the time, the library and the
available v4 model disagreed on the calling convention — the model **required** the
`sr` input and a `2 x Batch x 64` hidden-state shape, while the library sent neither
in that form — so the adapter injected `sr` and reshaped the `h`/`c` tensors to
bridge the gap.

That shim was removed once `faster-whisper` shipped Silero VAD **v6** and called it
with a matching interface (batched `[N, 576]` windows, `h`/`c` of `[1, 1, 128]`, no
`sr`). Running the native v6 model directly is both more accurate and far simpler —
it deleted ~90 lines of fragile reshaping code and a separately-downloaded model.

---

## Cutting-Edge Benefits
By successfully integrating this VAD solution, the project gains significant advantages:

### 1. 🚀 Extreme Performance
Whisper is a heavy, resource-intensive model. By filtering out silence *before* transcription, we often reduce the workload by 30-50%. For audio with frequent pauses (like conversations or lectures), transcription speed can **double or triple**.

### 2. 🧠 Hallucination Prevention
One of Whisper's known weaknesses is "hallucination"—inventing text (often repetitive phrases) when trying to transcribe pure silence or static. VAD eliminates this completely by ensuring Whisper never hears silence.

### 3. ⚡ Efficiency
Lower CPU and RAM usage. The VAD model is tiny and runs in milliseconds, saving the heavy compute power for where it's actually needed: speech.

### 4. 🎯 Studio-Grade Accuracy
With our custom tuning (padding and thresholds), the system now captures the subtle starts and ends of sentences that standard "out-of-the-box" VAD implementations often chop off.

---

## Meditation Mode Tuning
To handle audio with long pauses (like meditation), we adjusted the parameters:
- **Min Silence**: `5000ms` (5s) - The system waits for 5 full seconds of silence before deciding to cut.
- **Padding**: `2000ms` (2s) - It adds 2 seconds of "buffer" audio around every speech segment.

### Example: How it handles 10s Silence
If there is a **10-second silence** between two sentences:
1.  **Total Silence**: 10 seconds.
2.  **Padding Kept**:
    -   **2s** kept after the first sentence (to catch soft endings).
    -   **2s** kept before the second sentence (to catch breath/start).
    -   **Total Kept**: 4 seconds.
3.  **Total Cut**: 10s - 4s = **6 seconds** removed.

This ensures the transcription is faster (skipping 6s of dead air) while preserving the natural flow and preventing any soft speech from being lost.
