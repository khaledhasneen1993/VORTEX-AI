"""Basket state, cost units and crash safety; synthetic cases, not performance."""

import json
from dataclasses import replace

import pytest
from dotenv import dotenv_values

from vortex.basket import Candidate, add_group, open_group, projected_net
from vortex.basket_config import BasketPolicy
from vortex.config import Settings
from vortex.configure import configure
from vortex.models import Signal
from vortex.operations import OperationsPolicy
from vortex.paper import PaperBroker
from vortex.paper_experiment import PaperExperiment
from vortex.phase2 import RiskPolicy
from vortex.risk import Filters

NOW = 305000
SYMBOLS = ["AUSDT", "BUSDT", "CUSDT", "DUSDT", "EUSDT", "FUSDT"]
FILT = Filters(0.00001, 0.00001, 1, 0.001)


def setup(tmp_path):
    cfg = Settings(
        basket=BasketPolicy(enabled=True),
        starting_equity=20,
        max_positions=5,
        max_margin_fraction=0.60,
        max_daily_loss=0.25,
        cooldown_minutes=5,
        data_dir=tmp_path,
        experiment=PaperExperiment(enabled=True, capture_enabled=True),
        phase2=RiskPolicy(correlation_filter=False),
        operations=OperationsPolicy(
            funding_guard=False, liquidity_guard=False, volatility_slip_factor=0, modeled_latency_ms=0
        ),
    )
    return PaperBroker(cfg)


def candidates(now=NOW, symbols=SYMBOLS, prices=None, filters=FILT):
    ts = now // 300000 * 300000 - 300000
    return [
        Candidate(
            Signal(
                s,
                "LONG",
                ts,
                (prices or {}).get(s, 10),
                (prices or {}).get(s, 10) - 0.3,
                11,
                10 - i // 2,
                "synthetic",
                features={"strong_signal": 1, "weighted_long": 3, "adx_5m": 30},
                votes=("trend",),
                atr_value=0.1,
            ),
            filters,
            ts + 299999,
        )
        for i, s in enumerate(symbols)
    ]


def quotes(prices=None):
    return {s: ((prices or {}).get(s, 10), (prices or {}).get(s, 10) + 0.001) for s in SYMBOLS}


def opened(tmp_path):
    b = setup(tmp_path)
    assert open_group(b, list(reversed(candidates())), quotes(), NOW, {})[0]
    return b


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_rank_five_fixed_margin_and_no_partial_group(tmp_path):
    b = setup(tmp_path)
    before = b.wallet
    assert not open_group(b, candidates(symbols=SYMBOLS[:4]), quotes(), NOW, {})[0]
    assert b.wallet == before and not b.positions and not b.state_file.exists()
    assert not b.open(candidates()[0].signal, 10, 10.001, FILT, quotes(), NOW)[0]
    assert open_group(b, list(reversed(candidates())), quotes(), NOW, {})[0]
    assert list(b.positions) == SYMBOLS[:5]
    assert all(p.opened_ts == NOW and 1.9999 <= p.margin <= 2 for p in b.positions.values())
    assert len(rows(b.entries_file)) == 5
    assert PaperBroker(b.cfg).basket == b.basket


def test_stale_or_minimum_prevents_whole_group(tmp_path):
    b = setup(tmp_path)
    assert not open_group(b, candidates(), quotes(), 390001, {})[0]
    assert not open_group(b, candidates(filters=replace(FILT, min_notional=100)), quotes(), NOW, {})[0]
    assert not b.positions


def test_group_target_net_of_costs_flattens_losers_too(tmp_path):
    b = opened(tmp_path)
    # Four winners pay for the losing fifth; account return is not the target unit.
    prices = {s: 10.13 for s in SYMBOLS[:4]}
    prices[SYMBOLS[4]] = 9.9
    book = quotes(prices)
    expected = projected_net(b, book)
    assert expected > b.basket["total_margin"] * 0.03
    assert expected < b.cfg.starting_equity * 0.03
    events = b.mark(book, NOW + 10000)
    assert len(events) == 5 and any(e["net_pnl"] < 0 for e in events)
    assert not b.positions and b.basket["phase"] == "CLOSED"
    assert b.basket["realized_net"] == pytest.approx(expected)
    assert b.wallet == pytest.approx(20 + expected)
    assert b.reserve.reserved == pytest.approx(expected * 0.5)
    assert b.protection.streak == 0 and b.gate.consecutive_losses == 0
    assert rows(b.baskets_file)[-1]["action"] == "closed"


def test_legacy_individual_target_is_ignored_and_deadline_closes_loss(tmp_path):
    b = opened(tmp_path)
    book = quotes({SYMBOLS[0]: 10.2, SYMBOLS[1]: 9.9, SYMBOLS[2]: 9.9, SYMBOLS[3]: 9.9, SYMBOLS[4]: 9.9})
    assert b.mark(book, NOW + 20000) == []
    events = b.mark(book, NOW + 900000)
    assert len(events) == 5 and all(e["reason"] == "basket_max_duration" for e in events)
    assert b.protection.streak == 1 and b.gate.consecutive_losses == 1


def test_missing_quote_latches_deadline_and_recovery_never_refills(tmp_path):
    b = opened(tmp_path)
    book = quotes()
    del book[SYMBOLS[2]]
    assert projected_net(b, book) is None
    assert len(b.mark(book, NOW + 900000)) == 4
    assert b.basket["phase"] == "CLOSING" and list(b.positions) == [SYMBOLS[2]]
    b = PaperBroker(b.cfg)
    assert not open_group(b, candidates(NOW + 900000), quotes(), NOW + 900000, {})[0]
    assert len(b.mark(quotes(), NOW + 910000)) == 1 and b.basket["phase"] == "CLOSED"
    assert len(rows(b.trades_file)) == 5


def test_member_stop_triggers_whole_group_and_account_floor_remains(tmp_path):
    b = opened(tmp_path)
    events = b.mark(quotes({SYMBOLS[0]: 8.9}), NOW + 10000)
    assert len(events) == 5 and all(e["reason"] == "basket_member_price_stop" for e in events)
    b = opened(tmp_path / "floor")
    events = b.mark(quotes({s: 8.9 for s in SYMBOLS}), NOW + 10000)
    assert len(events) == 5 and all(e["reason"] == "account_equity_floor" for e in events)
    assert b.account_floor_halted
    assert not open_group(b, candidates(NOW + 300000), quotes(), NOW + 300000, {})[0]


def test_half_margin_add_strongest_two_once_and_updated_denominator(tmp_path):
    b = opened(tmp_path)
    prices = {s: 10.2 for s in SYMBOLS}
    prices.update({SYMBOLS[0]: 9.6, SYMBOLS[1]: 9.6})
    book = quotes(prices)
    cs = candidates(NOW + 300000, prices=prices)
    initial_margin = b.basket["total_margin"]
    initial_stops = {s: p.stop for s, p in b.positions.items()}
    assert not add_group(b, cs, book, NOW + 299999, {})[0]
    assert projected_net(b, book) < 0
    ok, reason = add_group(b, list(reversed(cs)), book, NOW + 300000, {})
    assert ok, reason
    assert b.basket["added_symbols"] == SYMBOLS[:2]
    assert b.basket["total_margin"] == pytest.approx(initial_margin * 1.2, abs=0.0001)
    for s in SYMBOLS[:2]:
        assert b.positions[s].margin == pytest.approx(b.basket["initial_margins"][s] * 1.5, abs=0.0001)
        assert b.positions[s].entry < b.positions[s].anchor_entry
    assert {s: p.stop for s, p in b.positions.items()} == initial_stops
    b = PaperBroker(b.cfg)
    assert not add_group(b, cs, book, NOW + 310000, {})[0]
    assert len(rows(b.pyramids_file)) == 2


def test_second_add_failure_leaves_both_untouched_and_never_retries(tmp_path):
    b = opened(tmp_path)
    prices = {s: 10.2 for s in SYMBOLS}
    prices.update({SYMBOLS[0]: 9.6, SYMBOLS[1]: 9.6})
    cs = candidates(NOW + 300000, prices=prices)
    cs[1] = replace(cs[1], filters=replace(FILT, min_notional=100))
    qty = {s: p.qty for s, p in b.positions.items()}
    wallet = b.wallet
    assert not add_group(b, cs, quotes(prices), NOW + 300000, {})[0]
    assert b.wallet == wallet and {s: p.qty for s, p in b.positions.items()} == qty
    assert not b.pyramids_file.exists()
    b = PaperBroker(b.cfg)
    assert not add_group(b, candidates(NOW + 300000, prices=prices), quotes(prices), NOW + 310000, {})[0]


def test_group_journal_recovery_is_idempotent_after_partial_append(tmp_path, monkeypatch):
    b = setup(tmp_path)
    original = b._write_journal

    def fail(event):
        if event["kind"] == "batch":
            original(event["events"][0])
        raise OSError("simulated append failure")

    monkeypatch.setattr(b, "_write_journal", fail)
    with pytest.raises(OSError):
        open_group(b, candidates(), quotes(), NOW, {})
    recovered = PaperBroker(b.cfg)
    assert len(recovered.positions) == 5 and recovered.pending_journal is None
    assert len(rows(recovered.entries_file)) == 5
    assert len(rows(recovered.baskets_file)) == 1
    assert len(PaperBroker(b.cfg).positions) == 5 and len(rows(recovered.entries_file)) == 5


def test_policy_is_opt_in_saved_state_cannot_switch_modes(tmp_path):
    b = opened(tmp_path)
    with pytest.raises(ValueError, match="Basket policy changed"):
        PaperBroker(replace(b.cfg, basket=BasketPolicy(), max_margin_fraction=0.25))
    path = tmp_path / ".env"
    configure(path, 20, basket=True)
    values = dotenv_values(path)
    assert values["BASKET_ENABLED"] == "true" and values["MAX_MARGIN_FRACTION"] == "0.60"
    configure(path, 20)
    assert dotenv_values(path)["BASKET_ENABLED"] == "false"
    assert dotenv_values(path)["MAX_MARGIN_FRACTION"] == "0.25"


def test_cli_basket_collects_before_opening_and_stops_on_uncertain_write(tmp_path, monkeypatch):
    from vortex import basket_live, cli, live_scan
    from vortex.live_scan import Prepared
    from vortex.models import Candle

    cfg = replace(setup(tmp_path).cfg, symbols=tuple(SYMBOLS))
    monkeypatch.setattr(cli.Settings, "from_env", lambda: cfg)
    monkeypatch.setenv("USE_RADAR", "false")
    state = {"collected": 0}

    class Public:
        def __init__(self, **kwargs):
            pass

        def metadata(self):
            return {s: {} for s in SYMBOLS}

        def server_ms(self):
            return NOW

        def quotes(self, **kwargs):
            return quotes()

        def symbol_filters(self, symbol):
            return FILT

    class Scanner:
        def __init__(self, *args):
            pass

        def results(self, symbols, now, on_wait, *, reserve_seconds=0):
            assert reserve_seconds == 20
            for s in reversed(symbols):
                assert not (tmp_path / "entries.jsonl").exists()
                on_wait()
                state["collected"] += 1
                bar = Candle(0, 10, 11, 9, 10, 100, close_ts=299999)
                yield s, Prepared([bar], [bar], [bar], [bar], None, None, None, NOW)

        def close(self):
            state["closed"] = True

    def signal(symbol, *args, **kwargs):
        return next(c.signal for c in candidates() if c.signal.symbol == symbol)

    monkeypatch.setattr(cli, "Market", Public)
    monkeypatch.setattr(live_scan, "CandidateScanner", Scanner)
    monkeypatch.setattr(basket_live, "analyze", signal)
    monkeypatch.setattr("vortex.signal_features.feature_snapshot", lambda *args: {})
    assert cli.main(["paper", "--once"]) == 0
    assert state["closed"] and state["collected"] == 6
    assert list(PaperBroker(cfg).positions) == SYMBOLS[:5]
    monkeypatch.setattr(
        basket_live.BasketLoop, "cycle", lambda self: (_ for _ in ()).throw(OSError("uncertain write"))
    )
    assert cli.main(["paper"]) == 2  # Fatal, not a retry that trades mutated memory.


def test_pair_refused_by_portfolio_risk_and_five_dollar_add_minimum(tmp_path):
    b = opened(tmp_path)
    all_down = {s: 9.9 for s in SYMBOLS}
    assert not add_group(b, candidates(NOW + 300000, prices=all_down), quotes(all_down), NOW + 300000, {})[0]
    assert not b.pyramids_file.exists()
    b = opened(tmp_path / "minimum")
    prices = {s: 10.2 for s in SYMBOLS}
    prices.update({SYMBOLS[0]: 9.6, SYMBOLS[1]: 9.6})
    assert not add_group(
        b,
        candidates(NOW + 300000, prices=prices, filters=replace(FILT, min_notional=5)),
        quotes(prices),
        NOW + 300000,
        {},
    )[0]
    assert not b.pyramids_file.exists()


def test_post_request_quote_clock_blocks_late_group_without_another_request(tmp_path):
    from vortex.basket_live import BasketLoop

    b = setup(tmp_path)

    class SlowPublic:
        calls = 0

        def server_ms(self):
            self.calls += 1
            assert self.calls == 1, "No time request may stale the already validated book"
            return NOW

        def quotes(self, **kwargs):
            self.quotes_checked_ms = 390001  # Guard/recovery request used up the signal window.
            return quotes()

    loop = BasketLoop(SlowPublic(), b, None, None, None, None, None, SYMBOLS, False)
    checked, book = loop._quotes(tuple(SYMBOLS))
    assert checked == 390001
    assert not open_group(b, candidates(), book, checked, {})[0]
    assert not b.positions
