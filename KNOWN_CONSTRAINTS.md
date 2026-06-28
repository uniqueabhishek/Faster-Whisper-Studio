# Known Constraints & Gotchas

Non-obvious operational constraints for this project. Read before bumping
dependencies, changing the Python version, or touching the GPU path.

_Last updated: 2026-06-28_

---

## 1. Do NOT upgrade `setuptools` to ≥ 81 (while on ctranslate2 4.4.0)

At startup you'll see a harmless warning:

```
ctranslate2\__init__.py:8: UserWarning: pkg_resources is deprecated as an API ...
Refrain from using this package or pin to Setuptools<81.
```

- **It is cosmetic** — nothing is broken. It fires because **ctranslate2 4.4.0** imports the
  deprecated `pkg_resources` (their code, not ours), and we are deliberately pinned to
  `ctranslate2==4.4.0`.
- **The trap:** setuptools **81 removes `pkg_resources` entirely**. If setuptools ever jumps to
  ≥ 81 while ctranslate2 is 4.4.0, that `import pkg_resources` becomes a hard `ImportError` and
  **the app won't start.**
- **Current state (safe):** setuptools **80.9.0**, pinned in `uv.lock` (still ships
  `pkg_resources`, only warns).
- **Action:** keep `setuptools < 81`. Be careful with `uv lock --upgrade`. The real fix is a future
  ctranslate2 release that drops `pkg_resources` — adopt it only when you intentionally bump ctranslate2.
- To silence just the warning (optional, cosmetic): add to the top of `app.py`, before any import:
  `warnings.filterwarnings("ignore", message="pkg_resources is deprecated")`.

## 2. Hard-pinned core dependencies

- `ctranslate2 == 4.4.0` (transcription contract + CUDA/cuDNN ABI).
- `faster-whisper >= 1.0, < 2`, `librosa < 1`, `PySide6 < 7`.
- Don't bump these without re-running an end-to-end transcription, not just the unit tests.

## 3. Python is pinned to 3.12 because of Smart App Control

- Windows **Smart App Control (SAC, enforced)** blocks uv's **unsigned** CPython **3.10.19**
  ("An Application Control policy has blocked this file") → the launcher fails to start.
- `.python-version` is **3.12** because 3.12.12 is currently SAC-trusted. `uv sync` reinstalls the
  same locked deps on it.
- SAC has **no per-file exclusion**. If it ever blocks 3.12 too, switch to a **signed python.org**
  interpreter (PSF-signed, SAC-trusted) rather than disabling SAC (which is irreversible).

## 4. The GPU is used only when it can actually run the model

`detect_device()` / `gpu_is_usable()` in `transcriber.py` require **both**:

1. **cuDNN loadable**, AND
2. **total VRAM ≥ 4 GB** (`MIN_CUDA_VRAM_BYTES`).

Otherwise it runs on **CPU**. Why both — a successful GPU *load* does **not** mean inference works:

- `float16` weights OOM at load on a 2 GB card.
- `int8_float16` loads, but inference **hard-crashes** (`0xC0000409`, uncatchable) if cuDNN is
  missing — so cuDNN must be checked **before** transcribing, not via try/except.

This dev laptop is an **NVIDIA MX450, 2 GB, no cuDNN → always CPU** (by design).

## 5. cuDNN is required for any GPU use and is NOT bundled

- CTranslate2 4.4.0 needs **cuDNN 8** (`cudnn_ops_infer64_8.dll`, `cudnn_cnn_infer64_8.dll`, …).
  The ctranslate2 wheel ships only `cudnn64_8.dll` (~0.3 MB); the heavy op libs are absent.
- **cuDNN 9 will NOT work** — different DLL names / ABI.
- To enable GPU on capable (≥ 4 GB) machines, bundle the matching cuDNN 8 DLLs **at build time**
  (planned) so they sit on the runtime DLL search path next to ctranslate2's CUDA libs. Then the
  cuDNN gate passes and VRAM becomes the only filter. (cuDNN 8 Windows DLLs come from NVIDIA's
  redist zip, not a Windows pip wheel.)

## 6. CPU float32 is the quality path; reliability comes from chunking

- CPU keeps the ~1.5 GB float32 model resident in RAM, so faster-whisper's full-file STFT OOM'd on
  long files (the original `MemoryError`).
- Mitigations in `transcriber.py`: CPU files > 8 min are smart-chunked into **2–5 min** pieces, and
  a chunk that still OOMs is **adaptively halved** down to a 60 s floor (`_yield_span`) without
  discarding already-transcribed audio.
- Speed reality: **~2.9× realtime** on CPU float32 (≈ 11 min for a 23-min file). Slow but full
  quality and reliable — the intended trade-off on hardware that can't use the GPU.
