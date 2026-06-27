"""Tests for the transcript timestamp / duration formatters.

These guard the fix that replaced the old truncating ``int(seconds)`` formatter
(which dropped sub-second precision and drifted every timestamp up to ~1s early).
"""

from transcriber import format_timestamp, format_duration, resolve_quality


def test_resolve_quality_depth_mapping():
    assert resolve_quality("Fast Analysis (int8)") == {
        "compute_type": "int8", "beam_size": 5, "patience": 1.0}
    assert resolve_quality("Precise Analysis (float32)") == {
        "compute_type": "float32", "beam_size": 5, "patience": 1.0}
    assert resolve_quality("Deep Analysis (float32)") == {
        "compute_type": "float32", "beam_size": 10, "patience": 2.0}


def test_resolve_quality_gpu_promotes_int8_to_float16():
    assert resolve_quality("Fast Analysis (int8)", "cuda")["compute_type"] == "float16"
    # float32 paths are unchanged on GPU.
    assert resolve_quality("Deep Analysis (float32)", "cuda")["compute_type"] == "float32"


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
