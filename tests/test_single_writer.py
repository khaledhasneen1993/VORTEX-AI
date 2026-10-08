"""Two workers must never trade the same state ledger simultaneously."""
import pytest
from vortex.locks import ProcessLock, AlreadyRunning


def test_single_writer_blocks_second_worker(tmp_path):
    path = tmp_path / "paper.lock"
    with ProcessLock(path):
        with pytest.raises(AlreadyRunning):
            ProcessLock(path).acquire()
    with ProcessLock(path):
        assert path.exists()


def test_testnet_and_paper_locks_are_independent(tmp_path):
    with ProcessLock(tmp_path / "testnet.lock"), ProcessLock(tmp_path / "paper.lock"):
        with pytest.raises(AlreadyRunning):
            ProcessLock(tmp_path / "testnet.lock").acquire()


def test_reset_lock_survives_stale_pid_file_after_process_crash(tmp_path):
    file = tmp_path / "paper.lock"
    file.write_text("999999")  # stale PID is NOT proof of a live lock
    with ProcessLock(file):
        assert file.read_text().strip().isdigit()
