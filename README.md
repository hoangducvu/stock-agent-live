# Nexlara: existing execution engine + optional AI research

The current server deployment is maintained in `src/` (engine and API), `dist/`
(dashboard), and the `Containerfile.*` / Quadlet deployment scripts. Older
root-level Python modules and `frontend/` in GitHub belong to the earlier desktop
version; use the deployment and entry points described in this document.

The bot remains the existing Alpaca/Python trading engine. The optional research
layer selects and contextualizes candidates; it cannot submit orders, change
configuration, reduce stops, or veto protective exits. All deployment APIs remain
paper-only. Email/Google registration and the old Slack command controller remain
deferred. Slack incoming-webhook notifications are now configurable in Settings.

## Existing architecture and integration

`data_feed.py` fetches Alpaca bars and calculates indicators locally.
`strategy_selector.py` evaluates checked strategies; `main.py` generates signals,
tracks `LivePosition` records and checks exits. `risk_manager.py` sizes positions,
checks buying power, maximum concurrent positions, daily loss and equity halts.
`order_manager.py` submits limits, reconciles broker fills/cancellations and places
stops. The existing partial-fill/ambiguous-order safeguards remain in use.
`backend/main.py` supervises that engine. Its existing private Caddy login covers
all pages and APIs. Credentials/settings stay encrypted in the data volume.

```
Market data → existing strategy signal → exchange/opening/eligibility filters
  → persisted cached/fresh advisory decision → deterministic risk checks
  → original OrderManager → actual broker fills/stops/position tracking
```

`research/worker.py` is a separate supervised process. It has read-only broker
adapters and no order-execution imports. The price/exit loop never waits for an AI
request: it queues a signal and skips the entry until a valid decision plus fresh
quote/exposure checks are available. Broker client-order IDs and durable setup
intents prevent repeating an ambiguous submission. A restart does not blindly
resume trading; reconcile broker positions/orders and use the existing readiness
flow. Research jobs, budgets, watchlists, cache, evidence changes and signal intent
survive restarts in `/app/data/research.sqlite3` (WAL SQLite).

The unused old `claude_layer.py` has a permissive error fallback. It is **not** the
new integration and is never invoked by the new entry gate.

## Install and configure

The Overview displays broker account equity history with 1-day, 1-week, 1-month,
3-month and 1-year periods. Hover or focus the chart and use arrow keys to inspect
observations. Equity includes cash and holdings; its change also includes cash
deposits and withdrawals. The current broker equity snapshot extends the chart
between history refreshes without inventing historical observations.

Balances, open positions, the latest 50 orders, and engine activity refresh every
five seconds while the page is visible. Broker history refreshes once a minute;
the Research tab refreshes its report and scan progress every 15 seconds while
visible. Polling does not reload saved settings or replace form edits. Account
and chart-period changes discard obsolete responses. Broker outages mark the
view stale and preserve its last known values. Full readiness checks remain
separate from these read-only account updates.

Use the existing rootless Podman deployment as `opc`:

```bash
cd ~/nexlara-deployment/nexlara-oracle
bash deploy-paper-workspace.sh --stage-only   # safe while an engine is running
# Install only with the engine stopped; Stop may close existing paper positions.
bash deploy-paper-workspace.sh && sudo bash https/verify.sh
```

The update runs Python and production-form tests, builds both images, checks
requirements/nginx, backs up existing units/volumes, and retains rollback images.
It never starts trading. `.containerignore` excludes data/logs/env files from
images. Broker, Slack and AI secrets must never be pasted into chat or logs.

AI is **disabled by default** and always disabled without a saved user key, so unconfigured research does not stop the original
algorithm. The opening restriction still defaults to 30 minutes for new entries;
protective exits are unaffected. To configure the optional provider:

```bash
mkdir -p ~/.config/nexlara
chmod 700 ~/.config/nexlara
cp config-examples/research.env.example ~/.config/nexlara/research.env
chmod 600 ~/.config/nexlara/research.env
# Edit privately with your preferred editor. Prototype web research needs no evidence file;
# verify model/pricing. Add the AI key and enable AI through the Settings page.
```

The deploy script attaches this host environment file to the API Quadlet when it
exists. Reinstall/restart the API to apply changed environment values; stop the
engine deliberately first. The API passes risk/schedule policy variables to engine children. Managed engines reload the saved AI opt-in/key-presence policy, so removing a key disables AI without stopping protective exits. Provider keys are not passed to the broker child.
The independent worker reads encrypted broker and AI settings; it does not require a
second broker connection form. The bundled provider uses the official Anthropic
SDK, pinned configurable Haiku 4.5 model ID, `max_retries=0` and a request timeout.
Alternative providers implement the `Provider` protocol in `research/provider.py`.
No model is auto-upgraded and no model/profitability claims are assumed.

### Company evidence

Alpaca supplies prices, exchange sessions, account state and news. It does **not**
supply the complete fundamentals/forward earnings source required by this design.
The managed deployment now defaults to **prototype mode**: local screening first,
then up to three company research requests, each with at most two hosted web
searches. Research asks for financial results, cash flow/debt, sector, earnings,
catalysts and risks, preferring filings and investor-relations releases. Only
URLs actually returned by the provider are accepted. This validates provenance,
not the truth of every model interpretation; missing facts remain missing.

Company findings are cached for seven days. New material-news headlines, earnings
within the configured buffer, or a price move of at least 5% invalidate them.
News freshness is only as complete as the existing Alpaca news feed. Research
failures and unavailable news do not approve new swing entries. At most one paid
company attempt per trading day prevents repeated failed requests. Known
intraday holdings are excluded from the after-close AI review; up to three other
holdings are reviewed in one compact call. Reviews remain advisory.

`AI_PROTOTYPE_MODE=true` caps daily requests at eight, searches at six and the
**estimated daily spend at $0.20**, even when older environment values are larger.
The default model remains Haiku 4.5; explicitly choosing a more expensive model
uses its own budget rates and can exhaust the allowance sooner. Search requests
reserve 20,000 input tokens + 1,200 output tokens + two $0.01 searches, then settle
against actual token/search usage. Unknown timeout charges retain their reserve.
**This is an application budget guard, not a guaranteed provider billing cap:**
hosted search can return more tokens than the reservation estimated. Actual costs
are recorded and further calls stop when the allowance is exhausted. Paid data
subscriptions and taxes are outside this counter. Provider/account spending
controls are separate. No paid calls are made by tests or deployment checks.

Prototype swing entries reuse the daily approved watchlist with deterministic
quote/exposure checks and no per-signal AI calls. Scalping bypasses the AI gate
and retains the original broker/risk checks. Disabling AI still restores the
original algorithm. Set `AI_PROTOTYPE_MODE=false` to use the original extended
research/entry-validation configuration instead.

`EvidenceFile` remains an optional provider-fed point-in-time adapter. In extended
mode it is required when fundamentals/earnings checks are enabled. To use it, populate `/app/data/research-evidence.json` through your licensed/verified data
pipeline, using `config-examples/research-evidence.example.json` as the schema.
The example ticker/source is deliberately invalid and must not be traded.

Each record needs the ticker, sector, current fundamental metrics, next earnings
date, data `as_of`, `observed_at`, and genuine source references. Future-dated,
missing-source, observation older than seven days, or financial data older than
120 days is rejected. No fundamentals/earnings = no evidence-dependent candidate.
A replacement live provider can implement `get(ticker, now)` without changing the
engine. ETFs require an explicitly appropriate evidence/event policy; they are
not silently assigned company fundamentals. Existing-position sector evidence is
required to validate concentration. Earnings within three calendar days block
entries. Provider entitlements and IEX liquidity limitations can exclude stocks;
missing premarket prices/volumes or macro volatility data are not fabricated.

## Schedules and research behavior

All schedules use `America/New_York`; DST and holidays come from Alpaca's exchange
calendar including actual early-close times, never weekday guesses. Calendar
outages block entries/research rather than assuming the market is open.

- **08:30 ET:** fetch previous completed daily bars for every active, tradable US
  equity returned by Alpaca, plus SPY/QQQ, sector ETFs and existing holdings.
  There is no alphabetical count cutoff or exchange whitelist; the old
  `AI_UNIVERSE_LIMIT` and `AI_UNIVERSE_SYMBOLS` overrides are ignored.
  Process history in bounded batches and record coverage, missing/stale data,
  and progress. A failed batch blocks AI research on an incomplete scan.
  Locally compute 50/200-day averages, RSI, MACD, ATR, momentum, relative volume,
  dollar liquidity and benchmark-relative strength. Filter on price, liquidity,
  trend, RSI and volatility, then rank the entire usable universe and shortlist
  up to three in prototype mode (ten in extended mode). Only after the full
  scan and ranking, research uncached shortlisted companies, apply verified
  fundamentals/earnings requirements, then batch into one practical model
  request, shrinking locally if the token ceiling demands it. Zero BUY results
  is valid. Research itself never buys anything.
- **09:30:** existing price monitoring continues with no automatic opening AI
  request. Entries wait until 10:00 by default; exits always run. To permit early
  entries explicitly change both opening delay and entry start configuration.
- **10:00 onward:** only actual qualifying signals enter the research queue.
  Recheck current quotes, spreads, trading status, liquidity, portfolio and sector
  exposure and upcoming earnings. A model BUY is advisory; the original signal
  must still be present and broker risk checks still pass before submission.
- **Close + 15 minutes:** normally 16:15 ET, or 13:15 after a 13:00 early close.
  Wait for the completed session daily bar, then review holdings and watchlist.
  Late data retries persist with a lease; no duplicate completed daily run.
  Recommendations are advisory. They never modify stops or generate exits.

Optional **Swing Trend Following** appears in the strategy checkboxes. It uses
completed daily trend/RSI/momentum inputs, deterministic ATR risk and configurable
10–90 calendar-day discretionary holding limits. Stops can exit sooner. Whole
shares permit GTC protective stops across sessions. Intraday strategies use the adaptive scalp exits documented below; RSI
strategies keep their existing exits; checking this strategy does not transform
those into multi-month positions. Choose the strategies suited to the intended
holding horizon. Splits/corporate actions still require broker reconciliation;
raw research bars are conservative and not a claim of adjusted-history accuracy.

## Cost controls, validation and persistence

Defaults: 20 requests/day, $1/day, 12,000 total reserved tokens/request, at most ten
candidates, 30-minute unchanged-analysis cooldown, 25-second provider timeout.
Prices are operator-configured USD per million input/output tokens; the example
uses $1/$5 for the pinned model. Verify prices before enabling another model.
Daily budgets use New York dates and atomic SQLite reservations **before** calls.
Actual provider usage settles costs. Unknown-charge timeouts retain the entire
reservation, including after crashes. Schema-invalid paid responses count too.
No unbounded SDK retries, periodic price-tick model calls, or hidden tool calls.
UTF-8 prompt-byte bounds plus protocol overhead conservatively reserve input cost.

Cache keys include task, ticker snapshots, strategy/setup, regime, model and input
version. Material price moves, new news or changed earnings/fundamentals invalidate
pending decisions. Fresh quote/exposure checks continue without AI; cooldowns do
not suppress exits. Model replies are strict Pydantic JSON, bounded to supplied
tickers/actions, timestamps and source references. Unknown sources, stale or
contradictory BUYs, malformed/extra fields and incomplete responses are rejected.
External text is data, never executable code or policy. Missing credentials,
budget, data or provider availability denies new AI-dependent entries.

SQLite stores universe/screening, input snapshots, validated research reports,
watchlists, signals, cache, cooldowns, token/cost usage, job leases, risk rejections,
order intents/results, broker fill audit, portfolio snapshots and system errors.
The Research page shows status, usage, watchlist and reports. Structured audit
rows include UTC timestamps, event kind/key and JSON context. Provider exception
messages and credentials are never logged. Back up the data volume while respecting
SQLite WAL consistency; retain encrypted settings and its key together securely.

## Slack notifications

In **Settings → Slack trade notifications**, enable notifications and enter an
incoming webhook plus optional channel label. The webhook is encrypted and never
returned to the browser. Save, then click **Send test notification** to authorize
a test message. Actual broker fill records are queued durably and delivered by
the worker independently of monitoring. No Slack trading commands or broad Slack
account tokens are required. Incoming webhooks are bound to their Slack channel;
the channel label is informational. Webhook delivery failures are retried with
bounded attempts and may duplicate a notification after an ambiguous timeout;
they cannot create or duplicate a trade.

## Testing, paper validation and shutdown

```bash
node tests/test_workspace_form.mjs
# Full dependency suite is run in the network-disabled candidate API image:
bash deploy-paper-workspace.sh --stage-only
# Read-only actual broker readiness summary, no credentials in output:
bash check-paper-connection.sh
```

Tests mock provider, Slack and broker responses; they never submit real orders.
Local host dependencies differ from the API image, so full integration tests must
pass there. Missing AI/fundamental credentials cannot be replaced by fixtures in
production. After configuring evidence/provider and paper account, review the
Research/Readiness pages, start the paper engine, and observe real paper fills,
stop placement, cancellations, holding behavior and costs over complete sessions.
No end-to-end provider/broker validation is claimed before that observation.

To stop trading, use the existing **Stop & close positions** control; it cancels
orders and attempts liquidation. Confirm the resulting state in Alpaca, especially
when closed. A hard process kill can leave broker positions/stops outstanding;
never assume a successful process stop proves all positions closed. To disable
AI while retaining the original signal path, turn off AI in Settings or remove
the saved key. No trading-engine restart is required for this change. Daily loss and equity halt controls
remain independent. The HTTP API always rejects live trading; AI approval never
enables it. Any future live activation requires a separate reviewed execution
configuration and account validation, outside this paper release.

## Honest A/B/C/D and walk-forward evaluation

`PYTHONPATH=src python3 -m research.evaluate /absolute/path/to/replay.json` compares:

A. Original deterministic strategy opportunities/fills.
B. A restricted to archived premarket approvals observed before each entry.
C. B plus archived entry validations available before entry.
D. C plus recorded advisory postmarket reviews (identical execution until a
separately tested deterministic exit policy consumes reviews).

Input requires `point_in_time_attested: true`, `initial_equity`, `trades`,
`daily_marks`, `benchmark_prices`, optional actual `ai_usage`, and optional
`walk_forward_windows`. Trades need unique `id`, `ticker`, `side`, `qty`,
`signal_time`, `entry_time`, `exit_time`, point-in-time `entry_fill`/`exit_fill`,
fees/slippage costs and archived decisions with `action`, `observed_at`, and
`data_as_of`. Marks include all session timestamps and symbol prices; benchmark
rows include timestamps/prices. Walk-forward windows require `train_end <
test_start < test_end`. Use out-of-sample signals generated without future data;
this tool does not fit a model or re-create the original algorithm's entire data
pipeline. A data adapter for licensed historical PIT constituents/news/fundamentals
is still required for a credible large-universe historical study.

It reports total return, meaningful annualization (one-year minimum), daily-mark
maximum drawdown/Sharpe, profit factor, win rate, average wins/losses, turnover,
fees/spread/slippage, holding period, benchmark-relative return and recorded AI
costs, including net return after AI costs. It rejects future signals/evidence and
missing prices/fills, and never calls today's LLM to manufacture past decisions.
Unavailable archived decisions cannot qualify AI variants. Survivorship/PIT
correctness of supplied data remains the data owner's responsibility. Short
replays assume supplied quantities/fills and conservative cash limits; they do
not model borrow availability, recalls, splits or historical margin financing.
No profitability improvements or historical results are claimed.


### Provider contracts

The calendar adapter uses Alpaca's [exchange calendar, including early closes](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1).
The pinned model's example price comes from the [official Haiku 4.5 model page](https://platform.claude.com/docs/en/models/haiku-4-5/overview).
Slack uses [incoming webhooks](https://api.slack.com/messaging/webhooks), separate
from Slack command permissions. Verify provider availability and current prices
when supplying credentials; availability is not inferred from installed packages.

To install a real licensed/verified evidence snapshot into the existing volume:

```bash
volume_path=$(podman volume inspect nexlara-data --format '{{.Mountpoint}}')
podman unshare install -m 600 /secure/path/real-evidence.json "$volume_path/research-evidence.json"
```

Replace the source path with your own feed output, not the example file. Update
snapshots atomically from the real provider, retain point-in-time observation
metadata, and confirm its coverage/licensing and earnings freshness.


## Optional user AI API key

Settings has a separate **Optional AI research API** form, using the currently
supported Anthropic/Claude provider. Enter your own key, choose whether to enable
AI, then save. Saving alone does not make a paid request or prove the key works.
The key is encrypted in the existing settings volume, omitted from every status
response and never returned to the browser. Blank input preserves an existing
saved key; **Remove key & disable AI** explicitly erases it. With no saved key,
AI is always off, even if a server environment contains an old key or AI_ENABLED.
A saved key alone also leaves AI off until explicitly opted in. The worker checks
saved opt-in/key state before each provider request; an already submitted remote
request may finish after a removal, but no later request falls back to a host key.
The original deterministic algorithm remains available when AI is off. Evidence,
earnings and risk gates still apply when AI is enabled. Other AI providers need
their own adapter; this field is not an OpenAI or arbitrary-endpoint key input.


## Startup with existing holdings and pending orders

Broker positions and pending orders are informational in Readiness. A flat
account is no longer required to Start, and the market may be closed. Successful
read-only broker reconciliation is still required; an unavailable broker API is
not treated as an empty account. Startup submits, cancels and closes no orders.
Existing holdings (including shorts) are tagged EXTERNAL: monitored and counted
in position/exposure limits, without inventing original strategy/stop ownership
or automatically applying an intraday exit to them. Manage those prior holdings
and their protective orders in Alpaca. New engine trades use their normal exits.
Pending symbols are excluded from new entries, and pending new symbols count
against the position maximum. Pending liquidation/stop orders are not replaced.
The explicit Stop & close positions / emergency kill policy still attempts to
close positions; starting is separate from issuing that stop command.

### Model choices and Malta schedule

The AI form supports Haiku 4.5 (default), Sonnet 4.6, Opus 4.6 and Sonnet 5.5.
Budget input/output rates are selected atomically with the model from
`research/models.py`: $1/$5, $3/$15, $5/$25 and $2/$10 per million tokens,
respectively (official standard rates checked 26 October 2026). The same daily
cost/call ceiling applies. Actual access depends on the owner's API account;
saving the model does not probe access or trigger a paid request. Unsupported
sampling parameters are omitted, including temperature for Sonnet 5.5.
Switching models invalidates entry setup/cache identity; queued signals using the
old model are superseded, and a worker never silently sends an old-model request
after the preference changes. Completed daily research is not automatically
rerun solely because a dropdown changed. No model is automatically enabled.

The Research page translates broker sessions to Europe/Malta. On 26 October 2026:
research 13:30, US open 14:30, signal validation from 15:00, review 21:15 Malta time.
There is no automatic AI request at the open. These offsets change with US and
European daylight saving; the UI derives each session rather than fixing GMT+1.
Without sourced fundamentals/earnings evidence (web research in prototype mode or a configured feed), research cannot approve
candidates even if the API key is saved and AI enabled. The model receives compact
provider-sourced data; it does not browse the web or generate an unsourced stock
universe. Missing evidence is not replaced by the model's memory.

Official model specifications and rates:
[Sonnet 4.6](https://platform.claude.com/docs/en/models/sonnet-4-6/overview),
[Opus 4.6](https://platform.claude.com/docs/en/models/opus-4-6/overview),
[Sonnet 5.5](https://platform.claude.com/docs/en/models/sonnet-5-5/overview).


### Adaptive intraday exits

EMA/VWAP, ORB, EMA Pullback, Donchian, News Momentum and EMA/VWAP Short
use `scalp_exits.py`. Initial stops are 1.5 ATR from entry. There is no fixed
profit target. After a 1 ATR favourable move, the local trailing stop follows
at 0.75 ATR and can only tighten, including when volatility increases. An
opposing EMA9/EMA21 state triggers an exit. Long and short logic is symmetric.
ORB retains its original entry signal but now uses this ATR exit policy.

At 30 minutes elapsed since the recorded entry, the next engine check attempts
an exit even if indicators are missing. The engine still checks every five
minutes; this is not a guarantee of liquidation exactly at 30 minutes. Broker
outages, polling failures, rejected orders or missing fills can delay exits.
The existing 30-minutes-before-session-close cutoff remains in place.
Initial broker protective orders remain in place where supported; local
trailing changes do not replace those orders on every candle. Exits reuse the
existing cancellation, fill reconciliation and partial-fill handling.
Swing strategies and externally owned holdings are excluded. On restart,
unknown broker holdings continue to be classified EXTERNAL, so their original
entry time and scalp management are not guessed or automatically restored.

Environment overrides (set on the engine):
`NEXLARA_SCALP_MAX_HOLD_MINUTES=30`, `NEXLARA_SCALP_STOP_ATR=1.5`,
`NEXLARA_SCALP_TRAIL_ACTIVATE_ATR=1`, `NEXLARA_SCALP_TRAIL_ATR=0.75`.
This is a paper-trading policy, not a demonstrated improvement in returns.


### Margin allocation across position slots

The requested margin allocation profile migrates saved schema-3 settings to
schema 4: `allocation_mode=fill_slots`, 20 simultaneous positions, 5% buying-power
buffer and gross exposure ceiling of 400% of current equity. The broker's actual
buying power and multiplier can reduce that ceiling. The existing per-order cap,
daily loss limit, equity floor and selected strategies are retained. Position
limit can be set from 1 to 50. Only qualifying signals create orders; this is
capacity permission, not a promise of full investment or improved performance.

The next order budget is usable remaining capacity divided by remaining slots,
capped by maximum order value. For $20,000 intraday buying power, $5,000 equity,
4x multiplier and 20 empty slots, the first budget is $950 with the 5% buffer.
Existing positions and exposure-increasing pending orders consume capacity/slots;
protective closing orders do not. Unknown pending-order values fail closed.
Broker state is rechecked before submission. Shorts count by gross absolute
exposure, not netted against longs. Symbol-specific broker margin requirements
can still reject an order.

Swing/RSI entries also require `regt_buying_power` and are capped at the smaller
of that balance and 2x equity (or a lower broker multiplier), less existing gross
exposure and the buffer. The conservative gross test includes intraday holdings,
so an intraday-heavy account may temporarily have no swing capacity. Missing
overnight data never falls back to intraday margin. Prototype AI concentration
checks use 30% of the configured gross exposure ceiling as the sector ceiling;
the old 60%-of-equity AI portfolio cap does not constrain the margin profile.
The prototype shortlist excludes already-held stocks so its three company
research slots focus on potential additions. Daily reviews remain limited to
three holdings by the prototype budget; deterministic exits manage all owned
positions regardless of AI review coverage.

`percentage` allocation remains available to restore percentage-of-buying-power
sizing. Its percentage field is not used by slot allocation. The dashboard's
**Risk baseline equity** is the former Reference capital: a fixed configured
reference for the absolute equity floor/account-migration ratio, not live equity
and not an input to trade sizing. The separate daily loss baseline is persisted
for the trading day and is not reset when settings change.

Trading settings cannot be changed while the engine is active. Stage images with
`bash deploy-paper-workspace.sh --stage-only`; install only once the engine is
inactive. The dashboard's explicit Stop & close action attempts to close
positions, so account for that when scheduling the update. Neither staging nor
installation starts trading automatically.

### Larger position sizes and closing summaries

Managed settings schema 5 defaults to a **10× position size multiplier** and a
**$10,000 maximum order value**. This scales each strategy's normal slot or
percentage allocation before applying the order cap and fresh broker capacity.
On the synthetic $5,000-equity / $20,000 intraday-buying-power account with twenty
slots and a 5% reserve, the initial scalp budget rises from $950 to $9,500.
For the same price move, a previous $5 gain or loss would be approximately $50.
Actual fills, capacity, fees and slippage affect the result. No dollar profit or
loss minimum is enforced; all strategy exits retain their existing behavior.
Swing orders use overnight buying power. Larger orders consume capacity sooner.
The multiplier is editable from 1 to 20 in Settings. The migration preserves
credentials, strategies, position count, daily-loss and equity-halt settings;
a saved schema-5 configuration is not reset on later reads. Standalone engine
configuration retains its conservative defaults unless explicitly overridden.

The overview now displays a persistent **End-of-day summary**, requested from
broker history five minutes after the exchange-calendar close, including early
closes. It reports closing equity, account P&L, filled orders, fills, and buy/sell
volume for the regular session. Account P&L includes unrealized changes and
manual trades; fill counts are not round-trip counts or a win rate. Reports are
scoped by paper account and session and saved atomically under `data/summaries/`.
The dashboard checks once per minute, generates the latest completed session on
first visit, and retries unavailable broker data. This works while the trading
engine is stopped. Existing console summaries remain available in engine logs.
Broker API fields follow the official [portfolio history documentation](https://docs.alpaca.markets/us/reference/getaccountportfoliohistory-1)
and [account activities documentation](https://docs.alpaca.markets/us/docs/account-activities).

Runtime account data, credentials, logs and deployment backups are excluded
from Git. To rotate the HTTPS password, `https/change-password.sh` now prompts
securely instead of embedding a deployment password in source.
