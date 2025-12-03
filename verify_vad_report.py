
def format_timestamp(seconds: float) -> str:
    mm, ss = divmod(int(seconds), 60)
    hh, mm = divmod(mm, 60)
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"

def test_report_logic(vad_filter: bool, total_duration: float, ai_processed_duration: float):
    print(f"Testing with vad_filter={vad_filter}, total={total_duration}, ai={ai_processed_duration}")

    # Logic from transcriber.py
    vad_removed_duration = max(0.0, total_duration - ai_processed_duration) if vad_filter else 0.0

    print(f"VAD Removed Duration: {format_timestamp(vad_removed_duration)}")

    if vad_filter == False and vad_removed_duration != 0.0:
        print("FAIL: VAD is off but removed duration is not 0")
    elif vad_filter == True and vad_removed_duration == 0.0 and total_duration > ai_processed_duration:
        print("FAIL: VAD is on and there is a difference, but removed duration is 0")
    else:
        print("PASS")
    print("-" * 20)

if __name__ == "__main__":
    # Case 1: VAD Off, some silence (simulated by difference in duration)
    test_report_logic(vad_filter=False, total_duration=100.0, ai_processed_duration=80.0)

    # Case 2: VAD On, some silence
    test_report_logic(vad_filter=True, total_duration=100.0, ai_processed_duration=80.0)

    # Case 3: VAD Off, no silence
    test_report_logic(vad_filter=False, total_duration=100.0, ai_processed_duration=100.0)
