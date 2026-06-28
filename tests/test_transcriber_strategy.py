"""Tests for the GPU-usability gate, device-aware chunking strategy, and the
adaptive sub-chunking that keeps CPU float32 reliable on long files.

These guard the change that stops the app from using a GPU it can't actually run
the model on (too little VRAM / missing cuDNN -> uncatchable inference crash) and
makes the CPU path survive the full-file STFT OOM via small, adaptively-split
chunks.
"""

from collections import namedtuple
from pathlib import Path

import pytest

import transcriber as t
from transcriber import (
    Transcriber, TranscriptionConfig, MIN_CUDA_VRAM_BYTES,
    ADAPTIVE_CHUNK_FLOOR_SEC, CPU_CHUNK_THRESHOLD_MIN)


@pytest.fixture(autouse=True)
def _clear_gpu_caches():
    """The gate helpers are lru_cached; clear around every test so monkeypatched
    inputs aren't masked by a value cached in another test."""
    for fn in (t.gpu_is_usable, t._cudnn_available, t._cuda_vram_bytes):
        fn.cache_clear()
    yield
    for fn in (t.gpu_is_usable, t._cudnn_available, t._cuda_vram_bytes):
        fn.cache_clear()


# --- GPU usability gate ----------------------------------------------------

def test_gpu_gated_off_without_cudnn(monkeypatch):
    monkeypatch.setattr(t, "_cudnn_available", lambda: False)
    assert t.gpu_is_usable() is False


def test_gpu_gated_off_when_vram_below_threshold(monkeypatch):
    monkeypatch.setattr(t, "_cudnn_available", lambda: True)
    monkeypatch.setattr(t, "_cuda_vram_bytes", lambda: 2 * 1024 ** 3)  # 2 GB
    assert t.gpu_is_usable() is False


def test_gpu_gated_off_when_vram_unknown(monkeypatch):
    monkeypatch.setattr(t, "_cudnn_available", lambda: True)
    monkeypatch.setattr(t, "_cuda_vram_bytes", lambda: None)
    assert t.gpu_is_usable() is False


def test_gpu_usable_when_cudnn_and_vram_ok(monkeypatch):
    monkeypatch.setattr(t, "_cudnn_available", lambda: True)
    monkeypatch.setattr(t, "_cuda_vram_bytes", lambda: MIN_CUDA_VRAM_BYTES)
    assert t.gpu_is_usable() is True


def test_detect_device_cpu_when_gpu_present_but_gated(monkeypatch):
    import ctranslate2
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(t, "gpu_is_usable", lambda: False)
    assert t.detect_device() == "cpu"


def test_detect_device_cuda_when_present_and_usable(monkeypatch):
    import ctranslate2
    monkeypatch.setattr(ctranslate2, "get_cuda_device_count", lambda: 1)
    monkeypatch.setattr(t, "gpu_is_usable", lambda: True)
    assert t.detect_device() == "cuda"


# --- Device-aware chunking threshold ---------------------------------------

def _bare(device, duration):
    """A Transcriber without a loaded model, with a fixed probed duration."""
    tr = Transcriber.__new__(Transcriber)
    tr._config = TranscriptionConfig(model_name="x", device=device)
    tr._probe_duration = lambda _p: duration
    return tr


def test_cpu_chunks_midlength_files():
    # 23 min on CPU -> chunk (the file that originally OOM'd in standard mode).
    _, smart, clen = _bare("cpu", 23 * 60)._resolve_strategy(Path("x.wav"))
    assert smart is True and clen is None


def test_cpu_short_file_not_chunked():
    # Below the CPU threshold -> standard processing.
    _, smart, _ = _bare("cpu", (CPU_CHUNK_THRESHOLD_MIN - 1) * 60)._resolve_strategy(Path("x.wav"))
    assert smart is False


def test_cuda_keeps_40_minute_threshold():
    # GPU holds the model in VRAM; a 23-min file does not need chunking...
    _, smart, _ = _bare("cuda", 23 * 60)._resolve_strategy(Path("x.wav"))
    assert smart is False
    # ...but a 50-min file still does.
    _, smart2, _ = _bare("cuda", 50 * 60)._resolve_strategy(Path("x.wav"))
    assert smart2 is True


# --- Adaptive sub-chunking on MemoryError ----------------------------------

_FakeSeg = namedtuple("_FakeSeg", ["start", "end", "text"])


def _adaptive_transcriber(transcribe_fn):
    """Bare CPU transcriber whose slice is a no-op and whose model.transcribe is
    supplied by the test. _slice_audio records the requested span duration so the
    fake model can decide whether to 'OOM'."""
    tr = Transcriber.__new__(Transcriber)
    tr._config = TranscriptionConfig(model_name="x", device="cpu")
    state = {"dur": None}

    def fake_slice(_input, _start, duration, cancel_check=None):
        state["dur"] = duration
        return Path("nonexistent_dummy_chunk.wav")  # _safe_unlink no-ops (absent)

    class _FakeModel:
        def transcribe(self, _path, **_kw):
            return transcribe_fn(state["dur"])

    tr._slice_audio = fake_slice
    tr._model = _FakeModel()
    return tr


def test_adaptive_subchunking_splits_until_it_fits():
    # OOM for spans wider than 80 s; succeed (one segment) at/below it. A 300 s
    # span should recurse 300 -> 150 -> 75 and yield 4 ordered segments, never
    # raising and never discarding earlier spans.
    def transcribe(dur):
        if dur > 80:
            raise MemoryError("Unable to allocate")
        return ([_FakeSeg(0.0, min(dur, 1.0), "ok")], None)

    tr = _adaptive_transcriber(transcribe)
    segs = list(tr._yield_span(Path("in.wav"), 0.0, 300.0, {}, None))

    assert len(segs) == 4
    starts = [s.start for s in segs]
    assert starts == sorted(starts)          # ordered onto the original timeline
    assert starts[0] == 0.0 and starts[-1] == 225.0


def test_adaptive_subchunking_raises_at_floor():
    # Always OOM -> recursion bottoms out at the floor and surfaces the error.
    def transcribe(_dur):
        raise MemoryError("Unable to allocate")

    tr = _adaptive_transcriber(transcribe)
    with pytest.raises(MemoryError):
        list(tr._yield_span(Path("in.wav"), 0.0, 2 * ADAPTIVE_CHUNK_FLOOR_SEC, {}, None))


def test_non_memory_error_is_not_retried():
    # A genuine model error must surface immediately, not trigger sub-chunking.
    def transcribe(_dur):
        raise ValueError("bad model")

    tr = _adaptive_transcriber(transcribe)
    with pytest.raises(ValueError):
        list(tr._yield_span(Path("in.wav"), 0.0, 300.0, {}, None))
