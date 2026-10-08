"""Execution-order tests, not claims about market performance."""
import pytest
from vortex.models import Candle, Signal
from vortex.config import Settings
from vortex.risk import Filters
from vortex.portfolio import run_portfolio
import vortex.portfolio as module

START = 1788220800000


def fixture_history():
    small = [Candle(START+i*300000, 100, 101, 99, 100, 10, START+(i+1)*300000-1)
             for i in range(80)]
    minute = [Candle(START+i*60000, 100, 101, 99, 100, 2, START+(i+1)*60000-1)
              for i in range(400)]
    t = small[75].ts
    small[75] = Candle(t,100,111,89,100,10,t+299999)
    minute[375] = Candle(t,100,111,99,100,2,t+59999)
    minute[377] = Candle(t+120000,100,101,89,100,2,t+179999)
    return small,minute


def candidate(sym,bars,higher,threshold,**kwargs):
    if len(bars)==75:
        return Signal(sym,'LONG',bars[-1].ts,100,90,130,7,'fixture',
                      features={'relative_volume':2},votes=('trend','breakout'),atr_value=10/1.5)


def replay(monkeypatch,interval='5m',diagnostics=True,minute_override=None):
    small,minute=fixture_history()
    monkeypatch.setattr(module,'analyze',candidate)
    return run_portfolio({'BTCUSDT':small},{'BTCUSDT':[]},
                         {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                         minute={'BTCUSDT':minute if minute_override is None else minute_override},
                         execution_interval=interval,diagnostics=diagnostics)


def test_diagnostics_preserve_coarse_pnl(monkeypatch):
    traced=replay(monkeypatch)
    plain=replay(monkeypatch,diagnostics=False)
    assert traced['realized_net_pnl']==plain['realized_net_pnl']
    assert traced['total_fees']==plain['total_fees']
    trade=traced['trades'][0]; d=trade['diagnostics']
    assert d['exit_bar_ambiguous']
    assert d['initial_stop']==pytest.approx(90.03)
    assert d['signal_features']['relative_volume']==2
    assert sum(x['net_pnl'] for x in d['partial_exits'])==pytest.approx(trade['net_pnl'])
    assert d['total_fees']==pytest.approx(traced['total_fees'])
    assert d['mfe_price_before_exit_bar']==0 # do not credit post-exit bar highs


def test_minutes_resolve_sequence_without_future_candle(monkeypatch):
    coarse=replay(monkeypatch)
    fine=replay(monkeypatch,'1m')
    assert coarse['realized_net_pnl']<0
    assert fine['realized_net_pnl']>0
    t=fine['trades'][0]
    assert [p['reason'] for p in t['diagnostics']['partial_exits']]==['tp1','stop']
    assert t['exit_ts']==t['entry_ts']+60000
    assert sum(p['qty'] for p in t['diagnostics']['partial_exits'])==pytest.approx(t['diagnostics']['initial_qty'])
    assert t['diagnostics']['terminal_bar']['low']==99


def test_missing_minute_refuses_replay(monkeypatch):
    _,minute=fixture_history()
    with pytest.raises(ValueError,match='Missing or malformed'):
        replay(monkeypatch,'1m',minute_override=minute[1:])


def test_entry_policy_is_opt_in_and_frozen():
    from vortex.research_policy import filter_signal
    from dataclasses import replace
    s=Signal('BTCUSDT','LONG',START,100,90,130,7,'fixture',features={'ema9_distance_atr':2.0})
    assert filter_signal(s,'extension-cap') is s
    stretched=replace(s,features={'ema9_distance_atr':2.01})
    assert filter_signal(stretched,'extension-cap') is None
    assert filter_signal(stretched,'baseline') is stretched
    assert filter_signal(replace(s,features={}),'extension-cap') is None
