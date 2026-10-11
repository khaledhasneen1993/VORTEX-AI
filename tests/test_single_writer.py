"""Two workers must never trade the same state ledger simultaneously."""

import pytest

from vortex.locks import AlreadyRunning, ProcessLock


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
    file.write_text("999999")
    with ProcessLock(file):
        assert file.read_text().strip().isdigit()


def test_status_does_not_recover_or_write_under_active_worker(tmp_path, monkeypatch, capsys):
    import json
    from vortex import cli
    from vortex.config import Settings
    from vortex.paper import PaperBroker

    cfg = Settings(data_dir=tmp_path)
    writer = PaperBroker(cfg)
    writer.pending_journal = {"kind": "entry", "event_id": "pending-entry"}
    writer.save()
    before = writer.state_file.read_bytes()
    monkeypatch.setattr(cli.Settings, "from_env", lambda: cfg)
    with ProcessLock(tmp_path / "paper.lock"):
        assert cli.main(["status"]) == 0
        assert json.loads(capsys.readouterr().out)["journal_recovery_pending"]
        assert writer.state_file.read_bytes() == before
        assert not writer.entries_file.exists()
    # Only a writable restart replays the event, exactly once.
    with ProcessLock(tmp_path / "paper.lock"):
        recovered = PaperBroker(cfg)
        assert recovered.pending_journal is None
        PaperBroker(cfg)
        assert len(writer.entries_file.read_text().splitlines()) == 1


def test_read_only_snapshot_cannot_mutate_or_create_folder(tmp_path):
    from vortex.config import Settings
    from vortex.paper import PaperBroker

    folder = tmp_path / "missing"
    reader = PaperBroker(Settings(data_dir=folder), read_only=True)
    for action in (reader.save, reader._finish_pending, lambda: reader.reset_halt(True)):
        with pytest.raises(PermissionError):
            action()
    assert not folder.exists()


def test_state_rename_and_new_journal_sync_parent(tmp_path, monkeypatch):
    from vortex.config import Settings
    from vortex.paper import PaperBroker

    broker = PaperBroker(Settings(data_dir=tmp_path))
    calls = []
    def sync_parent():
        assert broker.state_file.exists()  # Rename precedes directory durability.
        calls.append(True)
    monkeypatch.setattr(broker, "_sync_folder", sync_parent)
    broker.save()
    event = {"kind": "entry", "event_id": "durable"}
    broker._write_journal(event)
    broker._write_journal(event)
    assert len(calls) == 2  # State rename and first journal creation only.
    def fail():
        raise OSError("directory sync uncertain")
    monkeypatch.setattr(broker, "_sync_folder", fail)
    with pytest.raises(OSError, match="uncertain"):
        broker.save()


def test_nonbasket_loop_stops_on_uncertain_write(tmp_path, monkeypatch):
    from vortex import cli
    from vortex.config import Settings
    from vortex.paper import PaperBroker

    cfg = Settings(data_dir=tmp_path)
    monkeypatch.setattr(cli.Settings, "from_env", lambda: cfg)
    class Public:
        def __init__(self, **kwargs):
            pass
        def metadata(self):
            return {s: {} for s in cfg.symbols}
        def server_ms(self):
            return 305000
        def quotes(self, **kwargs):
            return {}
    monkeypatch.setattr(cli, "Market", Public)
    def fail(*args):
        raise OSError("uncertain state write")
    monkeypatch.setattr(PaperBroker, "mark", fail)
    monkeypatch.setattr(cli.time, "sleep", lambda _: pytest.fail("Must not retry uncertain write"))
    assert cli.main(["paper"]) == 2
    with ProcessLock(tmp_path / "paper.lock"):
        pass  # Fatal stop releases the writer lock.
