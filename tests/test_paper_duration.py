from pathlib import Path

import pytest

from research.paper_hour import session_args


def test_twenty_minute_session_has_separate_output():
    args = session_args(['--duration-seconds', '1200', '--output', 'runs/radar-20m'])
    assert args.duration_seconds == 20 * 60
    assert args.output == Path('runs/radar-20m')


def test_hour_workflow_keeps_original_duration_and_artifact_path():
    args = session_args([])
    assert args.duration_seconds == 3600
    assert args.output == Path('runs/radar-one-hour')


@pytest.mark.parametrize('seconds', ['0', '-1', '3601'])
def test_unsupported_duration_rejected(seconds):
    with pytest.raises(SystemExit):
        session_args(['--duration-seconds', seconds])
