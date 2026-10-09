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


def replay(monkeypatch,interval='5m',diagnostics=True,minute_override=None,exit_policy='baseline'):
    small,minute=fixture_history()
    monkeypatch.setattr(module,'analyze',candidate)
    return run_portfolio({'BTCUSDT':small},{'BTCUSDT':[]},
                         {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                         minute={'BTCUSDT':minute if minute_override is None else minute_override},
                         execution_interval=interval,diagnostics=diagnostics,
                         exit_policy=exit_policy)


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


def test_direction_inversion_is_symmetric_and_explicit():
    from dataclasses import replace
    from vortex.research_policy import filter_signal
    s=Signal('BTCUSDT','LONG',START,100,90,130,7,'fixture',
             features={'relative_volume':2},votes=('trend','breakout'))
    inverted=filter_signal(s,'invert-direction')
    assert inverted.side=='SHORT'
    assert inverted.stop==110 and inverted.target==70
    assert inverted.features['source_direction']==1
    assert inverted.votes==('contrarian:trend','contrarian:breakout')
    assert 'CONTRARIAN_RESEARCH_DIRECTION_INVERTED' in inverted.reason
    assert s.side=='LONG' and s.stop==90 and s.target==130
    short=replace(s,side='SHORT',stop=112,target=64)
    reverse=filter_signal(short,'invert-direction')
    assert reverse.side=='LONG' and reverse.stop==88 and reverse.target==136
    assert reverse.features['source_direction']==-1


def test_fixed_3r_uses_full_size_and_stop_first(monkeypatch):
    fixed=replay(monkeypatch,'1m',exit_policy='fixed-3r')
    trade=fixed['trades'][0]
    parts=trade['diagnostics']['partial_exits']
    assert len(parts)==1 and parts[0]['final']
    assert parts[0]['qty']==trade['diagnostics']['initial_qty']
    assert parts[0]['reason']=='stop'  # first minute has stop and target-side excursion
    assert trade['net_pnl']<0


def test_fixed_1r_closes_all_at_one_r(monkeypatch):
    small,minute=fixture_history()
    minute[375]=Candle(minute[375].ts,100,111,99,105,2,minute[375].close_ts)
    # Parent bar must reconcile with the edited minute close sequence.
    small[75]=Candle(small[75].ts,100,111,89,100,10,small[75].close_ts)
    monkeypatch.setattr(module,'analyze',candidate)
    report=run_portfolio({'BTCUSDT':small},{'BTCUSDT':[]},
                         {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                         minute={'BTCUSDT':minute},execution_interval='1m',
                         diagnostics=True,exit_policy='fixed-1r')
    trade=report['trades'][0]
    assert trade['diagnostics']['partial_exits'][0]['reason']=='target_1r'
    assert len(trade['diagnostics']['partial_exits'])==1


def test_unknown_exit_policy_rejected(monkeypatch):
    with pytest.raises(ValueError,match='Unknown exit policy'):
        replay(monkeypatch,exit_policy='invented')


def test_trend_pullback_requires_completed_aligned_histories():
    from dataclasses import replace
    from vortex.research_policy import trend_pullback
    small,_=fixture_history()
    assert trend_pullback('BTCUSDT',small[:60],small,5,macro=small*3) is None
    higher=[replace(c,close_ts=small[-1].close_ts+1) for c in small]
    assert trend_pullback('BTCUSDT',small,higher,5,macro=small*3) is None


def test_range_reversion_freezes_band_and_thresholds(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    small,_=fixture_history()
    small=[replace(c,open=100,high=101,low=99,close=100,volume=10) for c in small]
    # Reference is bars [-22:-2]. The setup is outside its frozen lower band;
    # current closes back inside with a bullish body and allowed relative volume.
    small[-22]=replace(small[-22],close=99)
    small[-2]=replace(small[-2],open=98,high=99,low=96,close=97,volume=10)
    small[-1]=replace(small[-1],open=98,high=100,low=97,close=99.8,volume=10)
    minute=[Candle(START+i*60000,99,100,98,99,2,START+(i+1)*60000-1)
            for i in range(85)]
    monkeypatch.setattr(policy,'adx',lambda _bars: 19.99)
    monkeypatch.setattr(policy,'atr',lambda _bars: 1.0)
    monkeypatch.setattr(policy,'rsi',lambda _prices,_period: 40.0)
    monkeypatch.setattr(policy,'confirm_1m',lambda bars,direction,close: direction==1)
    signal=policy.range_reversion('BTCUSDT',small,small,5,minute=minute)
    assert signal is not None and signal.side=='LONG'
    assert signal.stop==98.3 and signal.target==102.8
    assert signal.votes==('range_reversion',)
    assert signal.features['rsi7_decision']==40
    too_loud=list(small); too_loud[-1]=replace(too_loud[-1],volume=15.01)
    assert policy.range_reversion('BTCUSDT',too_loud,small,5,minute=minute) is None
    monkeypatch.setattr(policy,'adx',lambda _bars: 20.0)
    assert policy.range_reversion('BTCUSDT',small,small,5,minute=minute) is None


def test_range_reversion_requires_completed_minute_confirmation(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    small,_=fixture_history()
    small=[replace(c,open=100,high=101,low=99,close=100,volume=10) for c in small]
    small[-22]=replace(small[-22],close=99)
    small[-2]=replace(small[-2],open=98,high=99,low=96,close=97)
    small[-1]=replace(small[-1],open=98,high=100,low=97,close=99.8)
    minute=[Candle(START+i*60000,99,100,98,99,2,START+(i+1)*60000-1)
            for i in range(85)]
    monkeypatch.setattr(policy,'adx',lambda _bars: 10)
    monkeypatch.setattr(policy,'atr',lambda _bars: 1)
    monkeypatch.setattr(policy,'rsi',lambda _prices,_period: 35)
    monkeypatch.setattr(policy,'confirm_1m',lambda *_args: False)
    assert policy.range_reversion('BTCUSDT',small,small,5,minute=minute) is None
    future=list(minute); future[-1]=replace(future[-1],close_ts=small[-1].close_ts+1)
    monkeypatch.setattr(policy,'confirm_1m',lambda *_args: True)
    assert policy.range_reversion('BTCUSDT',small,small,5,minute=future) is None


def test_range_reversion_ablation_changes_only_minute_gate(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    small,_=fixture_history()
    small=[replace(c,open=100,high=101,low=99,close=100,volume=10) for c in small]
    small[-22]=replace(small[-22],close=99)
    small[-2]=replace(small[-2],open=98,high=99,low=96,close=97)
    small[-1]=replace(small[-1],open=98,high=100,low=97,close=99.8)
    minute=[Candle(START+i*60000,99,100,98,99,2,START+(i+1)*60000-1)
            for i in range(85)]
    monkeypatch.setattr(policy,'adx',lambda _bars: 10)
    monkeypatch.setattr(policy,'atr',lambda _bars: 1)
    monkeypatch.setattr(policy,'rsi',lambda _prices,_period: 35)
    monkeypatch.setattr(policy,'confirm_1m',lambda *_args: False)
    strict=policy.range_reversion('BTCUSDT',small,small,5,minute=minute)
    ablated=policy.range_reversion('BTCUSDT',small,small,5,minute=minute,
                                   require_minute_confirmation=False)
    assert strict is None and ablated is not None
    assert ablated.features['minute_confirmation_required']==0
    assert ablated.stop==98.3 and ablated.target==102.8


def test_compression_expansion_uses_prior_widths_and_frozen_gates(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    bars=[]
    for i in range(130):
        close=100 + (1 if i % 2 else -1)
        bars.append(Candle(START+i*900000,close,close+.2,close-.2,close,10,
                           START+(i+1)*900000-1))
    # Last 20 setup closes are tightly compressed relative to earlier widths.
    for i in range(109,129):
        close=100 + (.01 if i % 2 else -.01)
        bars[i]=replace(bars[i],open=close,high=close+.05,low=close-.05,close=close)
    bars[-1]=replace(bars[-1],open=100,high=102.2,low=99.8,close=102,volume=15)
    monkeypatch.setattr(policy,'atr',lambda _bars: 1.0)
    signal=policy.compression_expansion('BTCUSDT',bars,bars,5)
    assert signal is not None and signal.side=='LONG'
    assert signal.stop==100.5 and signal.target==106.5
    assert signal.features['relative_volume']==1.5
    assert signal.features['setup_bandwidth'] <= signal.features['compression_threshold']
    assert signal.votes==('compression_expansion',)
    quiet=list(bars); quiet[-1]=replace(quiet[-1],volume=14.99)
    assert policy.compression_expansion('BTCUSDT',quiet,quiet,5) is None


def test_compression_expansion_rejects_future_higher_and_short_history(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    small,_=fixture_history()
    assert policy.compression_expansion('BTCUSDT',small,small,5) is None
    bars=[Candle(START+i*900000,100,101,99,100,10,START+(i+1)*900000-1)
          for i in range(121)]
    future=[replace(bars[-1],close_ts=bars[-1].close_ts+1)]
    assert policy.compression_expansion('BTCUSDT',bars,future,5) is None


def test_compression_cost_ablation_reuses_frozen_e004_formula():
    from dataclasses import replace
    from vortex.research_policy import filter_signal
    signal=Signal('BTCUSDT','LONG',START,100,99.521,102,7,'compression',
                  votes=('compression_expansion',),atr_value=.319333)
    assert filter_signal(signal,'cost-floor') is None
    viable=replace(signal,stop=99.51)
    assert filter_signal(viable,'cost-floor') is viable
    assert viable.votes==('compression_expansion',)


def test_breakout_invalidation_exits_next_open_without_future_extremes(monkeypatch):
    from dataclasses import replace
    small,_=fixture_history()
    failed=list(small)
    failed[75]=replace(failed[75],open=100,high=101,low=97,close=98)
    def compression_candidate(sym,bars,higher,threshold,**kwargs):
        if len(bars)==75:
            return Signal(sym,'LONG',bars[-1].ts,100,90,130,7,'fixture',
                          features={'channel_high':99,'channel_low':95},
                          votes=('compression_expansion',),atr_value=10/1.5)
    monkeypatch.setattr(module,'analyze',compression_candidate)
    report=run_portfolio({'BTCUSDT':failed},{'BTCUSDT':[]},
                         {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                         execution_interval='5m',diagnostics=True,
                         exit_policy='breakout-invalidation')
    trade=report['trades'][0]
    assert trade['reason']=='breakout_invalidation'
    assert trade['exit_ts']==failed[76].ts
    assert trade['diagnostics']['terminal_bar']=={
        'ts':failed[76].ts,'low':failed[76].open,'high':failed[76].open,'open_exit':True}
    assert not trade['diagnostics']['exit_bar_ambiguous']


def test_breakout_invalidation_never_overrides_tp1(monkeypatch):
    from dataclasses import replace
    small,_=fixture_history()
    staged=list(small)
    staged[75]=replace(staged[75],open=100,high=111,low=97,close=98)
    def compression_candidate(sym,bars,higher,threshold,**kwargs):
        if len(bars)==75:
            return Signal(sym,'LONG',bars[-1].ts,100,90,130,7,'fixture',
                          features={'channel_high':99,'channel_low':95},
                          votes=('compression_expansion',),atr_value=10/1.5)
    monkeypatch.setattr(module,'analyze',compression_candidate)
    report=run_portfolio({'BTCUSDT':staged},{'BTCUSDT':[]},
                         {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                         execution_interval='5m',diagnostics=True,
                         exit_policy='breakout-invalidation')
    assert report['trades'][0]['reason']=='stop'
    assert [x['reason'] for x in report['trades'][0]['diagnostics']['partial_exits']]
    assert report['trades'][0]['diagnostics']['partial_exits'][0]['reason']=='tp1'


def test_breakout_invalidation_requires_channel_features(monkeypatch):
    small,_=fixture_history()
    monkeypatch.setattr(module,'analyze',candidate)
    with pytest.raises(ValueError,match='requires frozen channel'):
        run_portfolio({'BTCUSDT':small},{'BTCUSDT':[]},
                      {'BTCUSDT':Filters(.001,.001,5,.01)},Settings(),
                      execution_interval='5m',exit_policy='breakout-invalidation')


def test_compression_retest_is_exactly_one_completed_bar(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    bars=[]
    for i in range(131):
        close=100 + (1 if i % 2 else -1)
        bars.append(Candle(START+i*900000,close,close+.2,close-.2,close,10,
                           START+(i+1)*900000-1))
    for i in range(109,129):
        close=100 + (.01 if i % 2 else -.01)
        bars[i]=replace(bars[i],open=close,high=close+.05,low=close-.05,close=close)
    bars[129]=replace(bars[129],open=100,high=102.2,low=99.8,close=102,volume=15)
    bars[130]=replace(bars[130],open=101,high=101.7,low=100,close=101.5,volume=10)
    monkeypatch.setattr(policy,'atr',lambda _bars: 1.0)
    signal=policy.compression_retest('BTCUSDT',bars,bars,5)
    assert signal is not None and signal.side=='LONG'
    assert signal.ts==bars[-1].ts and signal.entry==101.5
    assert signal.stop==100 and signal.target==106
    assert signal.features['retest_delay_bars']==1
    assert signal.votes==('compression_retest',)
    failed=list(bars); failed[-1]=replace(failed[-1],open=101,close=100)
    assert policy.compression_retest('BTCUSDT',failed,failed,5) is None


def test_compression_retest_cuts_higher_history_at_expansion(monkeypatch):
    from dataclasses import replace
    import vortex.research_policy as policy
    small,_=fixture_history()
    bars=[replace(c,ts=START+i*900000,close_ts=START+(i+1)*900000-1)
          for i,c in enumerate((small*2)[:122])]
    observed=[]
    def spy(symbol, prior, higher, threshold, **options):
        observed.extend(higher)
        return Signal(symbol,'LONG',prior[-1].ts,100,99,103,7,'fixture',
                      features={'channel_high':100,'channel_low':95})
    monkeypatch.setattr(policy,'compression_expansion',spy)
    bars[-1]=replace(bars[-1],open=100,low=99,high=102,close=101)
    policy.compression_retest('BTCUSDT',bars,bars,5)
    assert observed and all(c.close_ts<=bars[-2].close_ts for c in observed)


def test_relative_strength_pair_is_atomic_and_uses_frozen_rank(monkeypatch):
    import vortex.research_policy as policy
    from dataclasses import replace
    small,_=fixture_history()
    histories={
        'AAAUSDT':[replace(c,close=100+i*.2) for i,c in enumerate(small)],
        'BBBUSDT':[replace(c,close=100-i*.2) for i,c in enumerate(small)],
        'CCCUSDT':small,
    }
    monkeypatch.setattr(policy,'atr',lambda _bars: 1.0)
    pair=policy.relative_strength_pair(histories,5)
    assert set(pair)=={'AAAUSDT','BBBUSDT'}
    assert pair['AAAUSDT'].side=='LONG' and pair['BBBUSDT'].side=='SHORT'
    assert pair['AAAUSDT'].features['pair_dispersion']>=.02
    assert (pair['AAAUSDT'].features['pair_exit_ts']
            - histories['AAAUSDT'][-1].close_ts - 1)==14_400_000
    reversed_pair=policy.relative_strength_pair(histories,5,contrarian=True)
    assert reversed_pair['AAAUSDT'].side=='SHORT'
    assert reversed_pair['BBBUSDT'].side=='LONG'
    assert reversed_pair['AAAUSDT'].votes==('relative_strength_reversal',)
    tied={key:small for key in histories}
    assert policy.relative_strength_pair(tied,5)=={}


def test_relative_strength_pair_reserves_half_margin_per_leg(monkeypatch):
    from dataclasses import replace
    symbols=('AAAUSDT','BBBUSDT')
    bars=[Candle(START+i*900000,100,101,99,100,10,START+(i+1)*900000-1)
          for i in range(80)]
    def pair(histories,threshold,**_options):
        current=next(iter(histories.values()))[-1]
        return {
            'AAAUSDT':Signal('AAAUSDT','LONG',current.ts,100,90,130,7,'pair'),
            'BBBUSDT':Signal('BBBUSDT','SHORT',current.ts,100,110,70,7,'pair'),
        }
    monkeypatch.setattr(module,'relative_strength_pair',pair)
    original=module.size_trade; calls=[]
    def sized(signal,equity,cfg,filt,committed_margin=0,max_new_margin=None):
        calls.append((committed_margin,max_new_margin))
        return original(signal,equity,cfg,filt,committed_margin,max_new_margin)
    monkeypatch.setattr(module,'size_trade',sized)
    cfg=replace(Settings(),symbols=symbols,timeframe='15m')
    report=run_portfolio({s:bars for s in symbols},{s:[] for s in symbols},
                         {s:Filters(.01,.01,5,.01) for s in symbols},cfg,
                         portfolio_policy='relative-strength-pair')
    assert report['open_positions']==['AAAUSDT','BBBUSDT']
    assert len(calls)==2 and calls[0][1]==pytest.approx(125)
    assert calls[0][0]==0 and 0<calls[1][0]<=125


def test_relative_strength_pair_cancels_both_when_one_leg_cannot_size(monkeypatch):
    from dataclasses import replace
    symbols=('AAAUSDT','BBBUSDT')
    bars=[Candle(START+i*900000,100,101,99,100,10,START+(i+1)*900000-1)
          for i in range(80)]
    def pair(histories,threshold,**_options):
        current=next(iter(histories.values()))[-1]
        return {
            'AAAUSDT':Signal('AAAUSDT','LONG',current.ts,100,90,130,7,'pair'),
            'BBBUSDT':Signal('BBBUSDT','SHORT',current.ts,100,110,70,7,'pair'),
        }
    monkeypatch.setattr(module,'relative_strength_pair',pair)
    calls=0
    def reject_second(*args,**kwargs):
        nonlocal calls
        calls+=1
        return (1,20) if calls%2 else None
    monkeypatch.setattr(module,'size_trade',reject_second)
    cfg=replace(Settings(),symbols=symbols,timeframe='15m')
    report=run_portfolio({s:bars for s in symbols},{s:[] for s in symbols},
                         {s:Filters(.01,.01,5,.01) for s in symbols},cfg,
                         portfolio_policy='relative-strength-pair')
    assert report['open_positions']==[] and report['closed_trades']==0


def test_pair_horizon_closes_survivors_at_frozen_open(monkeypatch):
    from dataclasses import replace
    symbols=('AAAUSDT','BBBUSDT')
    bars=[Candle(START+i*900000,100,101,99,100,10,START+(i+1)*900000-1)
          for i in range(80)]
    def pair(histories,threshold,**_options):
        current=next(iter(histories.values()))[-1]
        exit_ts=current.close_ts+1+14_400_000
        features={'pair_exit_ts':exit_ts}
        return {
            'AAAUSDT':Signal('AAAUSDT','LONG',current.ts,100,90,130,7,'pair',
                             features=features),
            'BBBUSDT':Signal('BBBUSDT','SHORT',current.ts,100,110,70,7,'pair',
                             features=features),
        }
    monkeypatch.setattr(module,'relative_strength_pair',pair)
    cfg=replace(Settings(),symbols=symbols,timeframe='15m')
    report=run_portfolio({s:bars for s in symbols},{s:[] for s in symbols},
                         {s:Filters(.01,.01,5,.01) for s in symbols},cfg,
                         diagnostics=True,exit_policy='pair-horizon',
                         portfolio_policy='relative-strength-reversal')
    assert report['closed_trades']==4
    assert {trade['reason'] for trade in report['trades']}=={'pair_horizon'}
    assert all(trade['exit_ts']-trade['entry_ts']==14_400_000
               for trade in report['trades'])
    assert all(trade['diagnostics']['terminal_bar']['open_exit']
               for trade in report['trades'])


def test_time_series_momentum_is_anchor_only_and_directional():
    from dataclasses import replace
    from vortex import research_policy as policy
    bars = [Candle(START+i*900000, 100+i*.03, 101+i*.03, 99+i*.03,
                   100+i*.03, 10, START+(i+1)*900000-1) for i in range(97)]
    anchored_close = ((bars[-1].close_ts + 1) // 14_400_000 + 1) * 14_400_000 - 1
    shift = anchored_close - bars[-1].close_ts
    bars = [replace(bar, ts=bar.ts+shift, close_ts=bar.close_ts+shift) for bar in bars]
    signal = policy.time_series_momentum('BTCUSDT', bars, [], 5)
    assert signal is not None and signal.side == 'LONG'
    assert signal.features['return_24h'] > .02
    assert signal.features['momentum_threshold'] == .02
    assert signal.features['pair_exit_ts'] == signal.ts + 900000 + 14_400_000
    reversal = policy.time_series_momentum('BTCUSDT', bars, [], 5, contrarian=True)
    assert reversal is not None and reversal.side == 'SHORT'
    assert reversal.features['source_direction'] == 1
    assert reversal.votes == ('time_series_reversal',)
    assert policy.time_series_momentum('BTCUSDT', bars[:-1], [], 5) is None
    off_anchor = [replace(bar, ts=bar.ts+900000, close_ts=bar.close_ts+900000)
                  for bar in bars]
    assert policy.time_series_momentum('BTCUSDT', off_anchor, [], 5) is None


def test_momentum_pullback_requires_completed_reclaim():
    from dataclasses import replace
    from vortex import research_policy as policy
    bars = [Candle(START+i*900000, 100+i*.03, 101+i*.03, 99+i*.03,
                   100+i*.03, 10, START+(i+1)*900000-1) for i in range(97)]
    bars[-2] = replace(bars[-2], open=102.6, high=103, low=101, close=102)
    bars[-1] = replace(bars[-1], open=102, high=104, low=101.5, close=103.5)
    signal = policy.momentum_pullback('BTCUSDT', bars, [], 5)
    assert signal is not None and signal.side == 'LONG'
    assert signal.votes == ('momentum_pullback',)
    no_reclaim = list(bars)
    no_reclaim[-1] = replace(no_reclaim[-1], open=103.5, close=102)
    assert policy.momentum_pullback('BTCUSDT', no_reclaim, [], 5) is None


def test_liquidity_sweep_reversal_uses_completed_range_and_wick():
    from vortex import research_policy as policy
    prior = [Candle(START+i*900000, 100, 101, 99, 100, 10,
                    START+(i+1)*900000-1) for i in range(21)]
    ts = START + 21*900000
    sweep = Candle(ts, 100, 101.2, 96, 100, 20, ts+899999)
    signal = policy.liquidity_sweep_reversal('BTCUSDT', [*prior, sweep], [], 5)
    assert signal is not None and signal.side == 'LONG'
    assert signal.stop < sweep.low and signal.target > signal.entry
    assert signal.features['wick_fraction'] >= .5
    assert signal.features['relative_volume'] >= 1.5
    continuation = policy.liquidity_sweep_reversal(
        'BTCUSDT', [*prior, sweep], [], 5, continuation=True)
    assert continuation is not None and continuation.side == 'SHORT'
    assert continuation.stop > continuation.entry
    assert continuation.votes == ('liquidity_sweep_continuation',)
    weak_volume = Candle(ts, 100, 101.2, 96, 100, 10, ts+899999)
    assert policy.liquidity_sweep_reversal('BTCUSDT', [*prior, weak_volume], [], 5) is None


def test_opening_range_breakout_is_one_frozen_daily_decision():
    from dataclasses import replace
    from vortex import research_policy as policy
    day = (START // 86_400_000 + 1) * 86_400_000
    bars = [Candle(day-4*900000+i*900000, 100, 101, 99, 100, 10,
                   day-4*900000+(i+1)*900000-1) for i in range(20)]
    bars[-1] = replace(bars[-1], open=100, high=104, low=99.5, close=103)
    signal = policy.opening_range_breakout('BTCUSDT', bars, [], 5)
    assert signal is not None and signal.side == 'LONG'
    assert signal.target > signal.entry and signal.stop < signal.entry
    assert signal.features['opening_range_high'] == 101
    off_time = [replace(bar, ts=bar.ts+900000, close_ts=bar.close_ts+900000)
                for bar in bars]
    assert policy.opening_range_breakout('BTCUSDT', off_time, [], 5) is None
