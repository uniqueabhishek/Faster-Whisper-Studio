"""Tests for the transcript timestamp / duration formatters.

These guard the fix that replaced the old truncating ``int(seconds)`` formatter
(which dropped sub-second precision and drifted every timestamp up to ~1s early).
"""

from transcriber import (
    format_timestamp, format_duration, resolve_quality, cpu_compute_type)


def test_resolve_quality_depth_mapping():
    assert resolve_quality("Fast Analysis (int8)") == {
        "compute_type": "int8", "beam_size": 5, "patience": 1.0}
    assert resolve_quality("Precise Analysis") == {
        "compute_type": "float32", "beam_size": 5, "patience": 1.0}
    assert resolve_quality("Deep Analysis") == {
        "compute_type": "float32", "beam_size": 10, "patience": 2.0}


def test_resolve_quality_gpu_uses_float16():
    # On CUDA every preset runs float16: int8 is unsupported on GPU and float16
    # halves VRAM vs float32 (the only way large-v3-turbo fits a small card).
    # beam_size still distinguishes the presets.
    assert resolve_quality("Fast Analysis (int8)", "cuda")["compute_type"] == "float16"
    assert resolve_quality("Precise Analysis", "cuda")["compute_type"] == "float16"
    assert resolve_quality("Deep Analysis", "cuda")["compute_type"] == "float16"
    assert resolve_quality("Deep Analysis", "cuda")["beam_size"] == 10


def test_cpu_compute_type_prefers_quality_on_fallback():
    # CPU is reached only after the GPU ladder (requested precision ->
    # int8_float16) is exhausted, so GPU machines stay on the GPU. When we do
    # land on CPU the user wants best quality, so GPU-only types map to float32;
    # an explicit int8 (Fast) choice is preserved.
    assert cpu_compute_type("float16") == "float32"
    assert cpu_compute_type("int8_float16") == "float32"
    assert cpu_compute_type("float32") == "float32"
    assert cpu_compute_type("int8") == "int8"


def test_format_timestamp_includes_milliseconds():
    assert format_timestamp(0) == "00:00.000"
    assert format_timestamp(1.4) == "00:01.400"
    assert format_timestamp(61.5) == "01:01.500"


def test_format_timestamp_includes_hours_when_needed():
    assert format_timestamp(3661.234) == "01:01:01.234"


def test_format_timestamp_does_not_truncate():
    # Regression: the previous int(seconds) impl rendered 12.9 as "00:12".
    assert format_timestamp(12.9) == "00:12.900"


def test_format_timestamp_rounds_to_nearest_millisecond():
    assert format_timestamp(1.23456) == "00:01.235"
    # Rollover when rounding pushes ms to 1000.
    assert format_timestamp(59.9996) == "01:00.000"


def test_format_timestamp_handles_bad_input():
    assert format_timestamp(-5) == "00:00.000"
    assert format_timestamp(float("nan")) == "00:00.000"
    assert format_timestamp(float("inf")) == "00:00.000"


def test_format_duration_rounds_to_nearest_second():
    assert format_duration(12.9) == "00:13"
    assert format_duration(59.6) == "01:00"
    assert format_duration(0) == "00:00"


def test_format_duration_includes_hours_when_needed():
    assert format_duration(3661) == "01:01:01"


def test_format_duration_handles_bad_input():
    assert format_duration(-1) == "00:00"
    assert format_duration(float("nan")) == "00:00"
    assert format_duration(float("inf")) == "00:00"
