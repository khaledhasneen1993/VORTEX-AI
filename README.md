# VORTEX-AI — five-position PAPER basket system

A lightweight Binance USDT-M public-data simulator for Termux/Linux. The current
smart basket strategy is the default and only supported deployment. No exchange
API keys, signed orders, real wallets or mainnet execution. Adoption means the
user selected this strategy; it does not establish profitability.

| Rule | Current behavior |
| --- | --- |
| Virtual starting balance | 100 USDT by default; selectable for each new session |
| Market selection | Up to 30 liquid Radar movers; completed 5m/15m/1h history |
| Group entry | Exactly five eligible signals ranked by strength, opened together or none |
| Initial margin / leverage | 10% of group-start equity per member, rounded down; maximum 5x |
| Total margin | Maximum 60% of frozen group-start equity and current available capital |
| Group target | Before 10 minutes: net 3% of all posted margins, including adds |
| After 10 minutes | Close all five at any strictly positive net after modeled costs |
| Group loss stop | 10% of fixed session starting balance; -10 USDT from 100 |
| Holding time | No 15-minute expiry; exits still require protection or profit condition |
| Smart averaging | Losing members only; fresh aligned signals, at least 0.5 entry ATR further adverse |
| Add limits | First decision after 5 minutes, then at least 5 minutes apart, maximum 3 rounds; request capped by initial member margin |
| Other protection | Original 10% member-price stop; permanent 25% account floor; risk/funding/depth/correlation guards |
| Flow / volume spike | Enabled; flow is an extra voter, unavailable data abstains |
| Recorder / health | Enabled, bounded sampled REST data and structured decisions |

From 100 USDT, initial group margin is approximately 50 USDT and its initial
3% target approximately 1.50 USDT. A 10-USDT group stop can erase several wins.
Fees, reserve, order minimums, risk limits and lot rounding can prevent entries
or adds. Price winners are untouched. No doubling, forced five-add batch,
missing-slot refill or guaranteed four groups per hour.

## Termux / Linux

Stop the previous session with Ctrl+C before updating. Migration creates a new
virtual wallet and preserves old sessions and open-position evidence.

```bash
cd ~/VORTEX-20M
source .venv/bin/activate
git pull --ff-only origin main
python -m pip install -e .
python -m vortex.configure --equity 100
bash run_paper.sh 3600
```

`run_paper.sh` supports 1200, 3600, 10800, 14400 and 21600 seconds; default is
three hours. Starting equity defaults to 100; override it explicitly with
`STARTING_EQUITY=20 bash run_paper.sh 3600`. All launches use the same basket
policy. The old `--basket` argument remains a harmless compatibility alias.
The timer ends observation and saves open positions without invented closes.

For continuous PAPER operation: `python -m vortex.cli paper`.
For a custom bounded run:

```bash
RUN_DIR="runs/vortex-basket-$(date -u +%Y%m%d-%H%M%S)-$$"
mkdir -p runs
printf '%s\n' "$RUN_DIR" > runs/latest-paper-path.txt
python -m vortex.session --duration-seconds 3600 --starting-equity 100 --diagnostics --output "$RUN_DIR"
```

To inspect/export the latest 100-USDT session using the migrated configuration:

```bash
RUN_DIR="$(cat runs/latest-paper-path.txt)"
tail -n 80 "$RUN_DIR/session.log"
STARTING_EQUITY=100 DATA_DIR="$RUN_DIR/state" python -m vortex.cli status
RESULT="$HOME/storage/downloads/VORTEX-basket-$(date -u +%Y%m%d-%H%M%S).zip"
python -m zipfile -c "$RESULT" "$RUN_DIR"
echo "$RESULT"
```

Status is strictly read-only. Use the saved starting balance and exact policies;
never change saved-wallet policy to bypass a halt. Old individual/older basket
wallets are historical evidence; migration does not silently convert them.

## Configuration, safety and validation

[approved.py](vortex/approved.py) is the deployment source;
[.env.example](.env.example) lists defaults. Internal constructor defaults and
persisted legacy fields remain for state validation and PAPER safety fixtures,
not selectable deployment strategies. Removed: signed TESTNET adapters, legacy
OHLC replay, unused WebSocket/microstructure adapters and unrelated launch assets.
No month-long historical simulation of this strategy exists yet.

The broker preserves flock, journals, atomic durable state, idempotent recovery,
halt on uncertain writes and stale-price rejection. REST data outages can still
defer exits and exceed nominal stops. Funding cashflows and liquidation are not
simulated. Recorder observations are sampled, not complete trade/depth history.

The repository has one build workflow checking code and deterministic tests.
After a successful main build it prunes older completed runs. A passing build
establishes software checks, not profits or uninterrupted exchange data.

```bash
python -m pip install -e '.[dev]'
python -m compileall -q vortex tests
python -m ruff check --select E9,F63,F7,F82 vortex tests
python -m pytest -q
```

Read [strategy](docs/STRATEGY.md), [basket contract](docs/BASKETS.md),
[risk](docs/RISK.md), [operations](docs/OPERATIONS.md),
[architecture](docs/ARCHITECTURE.md), [validation](docs/VALIDATION.md),
and [latest review](docs/REVIEW.md).
