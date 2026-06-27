"""Tests for SessionState/SessionManager persistence and status transitions."""

import threading

from session_manager import SessionManager


def _mgr(tmp_path):
    return SessionManager(session_dir=tmp_path / "sessions")


def test_create_and_roundtrip(tmp_path):
    mgr = _mgr(tmp_path)
    files = [tmp_path / "a.mp3", tmp_path / "b.mp3"]
    state = mgr.create_session(
        input_files=files, model_path="model", beam_size=7, task="translate")

    assert state.beam_size == 7
    assert state.task == "translate"
    assert len(state.files) == 2

    loaded = mgr.load_session(state.session_id)
    assert loaded is not None
    assert loaded.session_id == state.session_id
    assert loaded.beam_size == 7
    assert loaded.task == "translate"
    assert [f.path for f in loaded.files] == [str(p) for p in files]
    assert all(f.status == "pending" for f in loaded.files)


def test_status_transitions_and_properties(tmp_path):
    mgr = _mgr(tmp_path)
    files = [tmp_path / "a.mp3", tmp_path / "b.mp3", tmp_path / "c.mp3"]
    state = mgr.create_session(input_files=files, model_path="m")

    assert len(state.pending_files) == 3
    assert state.progress_percent == 0
    assert not state.is_complete

    mgr.update_file_status(state, str(files[0]), "completed", output_path="out.txt")
    mgr.update_file_status(state, str(files[1]), "failed", error="boom")

    assert len(state.completed_files) == 1
    assert len(state.failed_files) == 1
    assert state.completed_files[0].output_path == "out.txt"
    assert state.failed_files[0].error == "boom"
    assert len(state.pending_files) == 1
    assert not state.is_complete
    assert state.progress_percent == 66  # int(2/3 * 100)

    mgr.update_file_status(state, str(files[2]), "completed")
    assert state.is_complete
    assert state.progress_percent == 100


def test_interrupted_processing_is_resumable(tmp_path):
    mgr = _mgr(tmp_path)
    files = [tmp_path / "a.mp3"]
    state = mgr.create_session(input_files=files, model_path="m")

    mgr.update_file_status(state, str(files[0]), "processing")
    # A file left mid-"processing" by an interrupted run must be treated as
    # pending so resume re-processes it (and the batch is not "complete").
    assert len(state.pending_files) == 1
    assert not state.is_complete


def test_started_at_set_on_processing(tmp_path):
    mgr = _mgr(tmp_path)
    files = [tmp_path / "a.mp3"]
    state = mgr.create_session(input_files=files, model_path="m")
    mgr.update_file_status(state, str(files[0]), "processing")
    assert state.files[0].started_at is not None


def test_load_missing_returns_none(tmp_path):
    mgr = _mgr(tmp_path)
    assert mgr.load_session("nonexistent_session") is None


def test_delete_session(tmp_path):
    mgr = _mgr(tmp_path)
    state = mgr.create_session(input_files=[tmp_path / "a.mp3"], model_path="m")
    assert mgr.load_session(state.session_id) is not None
    mgr.delete_session(state.session_id)
    assert mgr.load_session(state.session_id) is None


def test_concurrent_updates_never_corrupt_the_file(tmp_path):
    # Regression: concurrent json.dump from multiple worker threads previously
    # produced a torn/truncated session file that load_session silently dropped
    # (returning None), defeating resume. The atomic write + lock must keep the
    # on-disk file valid and reflect every update.
    mgr = _mgr(tmp_path)
    n = 24
    files = [tmp_path / f"f{i}.mp3" for i in range(n)]
    state = mgr.create_session(input_files=files, model_path="m")

    def worker(i):
        mgr.update_file_status(
            state, str(files[i]), "completed", output_path=f"out{i}.txt")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = mgr.load_session(state.session_id)
    assert loaded is not None, "session file was torn/corrupt (load returned None)"
    assert len(loaded.completed_files) == n
    assert state.is_complete
