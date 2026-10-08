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


def test_minute_ohlc_must_reconcile(monkeypatch):
    small,minute=fixture_history()
    from dataclasses import replace
    minute[0]=replace(minute[0],high=150)
    with pytest.raises(ValueError,match='does not reconcile'):
        replay(monkeypatch,'1m',minute_override=minute)


def test_confirmation_cuts_all_histories_and_reprices():
    from vortex.research_policy import confirmed_breakout
    from dataclasses import replace
    small,minute=fixture_history()
    small=small[:75]
    small[-1]=replace(small[-1],close=102,high=103)
    observed=[]
    def spy(sym,bars,higher,threshold,**kw):
        observed.append((bars,higher,kw))
        assert all(c.close_ts<=bars[-1].close_ts for c in higher+(kw['macro'] or [])+kw['minute'])
        return Signal(sym,'LONG',bars[-1].ts,100,90,130,7,'fixture',votes=('trend','breakout'))
    s=confirmed_breakout(spy,'BTCUSDT',small,small,5,macro=None,minute=minute)
    assert s is not None
    assert s.ts==small[-1].ts and s.entry==102
    assert s.stop==92 and s.target==132
    assert s.features['confirmation_delay_bars']==1
    assert len(observed[0][0])==74
    rejected=list(small)
    rejected[-1]=replace(rejected[-1],close=99)
    assert confirmed_breakout(spy,'BTCUSDT',rejected,rejected,5,macro=None,minute=minute) is None


def test_cost_floor_rejects_small_move_and_preserves_baseline():
    from vortex.research_policy import filter_signal
    from dataclasses import replace
    s=Signal('BTCUSDT','LONG',START,100,99.521,102,7,'fixture')
    assert filter_signal(s,'cost-floor') is None
    assert filter_signal(s,'baseline') is s
    large=replace(s,stop=99.51)
    assert filter_signal(large,'cost-floor') is large
    assert filter_signal(replace(s,stop=float('nan')),'cost-floor') is None
