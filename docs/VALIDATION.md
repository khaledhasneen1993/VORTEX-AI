# Validation boundary

The sole deployed strategy is the smart five-position PAPER basket policy selected
from 82540c4. Adoption changes deployment defaults and removes unused modules;
it does not tune voters after seeing results or prove profitability.

Retained deterministic tests cover actual basket selection, margins, net targets,
ten-minute exits, original/group/account stops, losing-only adds, round limits,
state validation, partial closing, journal replay, flock, uncertain writes, quote
freshness, bounded scans, timing, recorder integrity and read-only monitoring.
Tests for deleted signed adapters and legacy historical engines are removed.
A smaller test count after cleanup is not a performance result.

The supplied one-hour 100-USDT session used 82540c4: twenty entries, three completed
groups with aggregate +0.632983385 USDT net, five positions still open. Last complete
marked equity was 99.808873218 USDT at 00:52:03 Jordan time on 2026-10-12. Later data
failures prevent a verified end-of-session equity. All three completed groups used
the ten-minute positive-net exit. Five add decisions produced no additions.

The same session recorded seventeen public-time failures, eight missing WUSDT quote
failures and recorder STOPPING_TIMEOUT with unsealed data. These are unresolved
operational gaps, not clean stability evidence. See [REVIEW](REVIEW.md).

Funding cashflows/liquidation remain unmodeled. Full historical Radar, order filters,
flow and depth are required to validate a matching month-long replay. The obsolete
OHLC engines have been removed; a matching historical engine has not been built.

Next checks: fix/measure time and quote continuity; explain every add prefilter skip;
run another unchanged PAPER policy and reconcile closed PnL, floating exposure,
reserve, costs and timestamp freshness. Do not count stale equity as final equity.
