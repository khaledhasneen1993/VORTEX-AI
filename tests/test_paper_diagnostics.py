import logging

from research.paper_hour import diagnostic_counts, session_args
from vortex.strategies import vote


def test_rejected_analysis_is_counted_without_entry_attempt():
    text = ('2026 INFO ANALYZE BTCUSDT decision_ms=1\n'
            '2026 DEBUG REJECT BTCUSDT reason=insufficient_history\n'
            '2026 INFO ENTRY_SKIP ETHUSDT reason=empty_candle_history\n')
    counts = diagnostic_counts(text)
    assert counts['signal_evaluations'] == 1
    assert counts['entry_attempts'] == 0
    assert counts['strategy_rejections'] == 1
    assert counts['entry_skips'] == 1


def test_early_history_rejection_is_observable(caplog):
    with caplog.at_level(logging.DEBUG, logger='vortex.votes'):
        assert vote('NEWUSDT', [], []) is None
    assert 'insufficient_5m_15m_history counts=0,0' in caplog.text


def test_diagnostics_opt_in_preserves_duration():
    args = session_args(['--duration-seconds', '1200', '--diagnostics'])
    assert args.diagnostics
    assert args.duration_seconds == 1200
    assert not session_args([]).diagnostics
