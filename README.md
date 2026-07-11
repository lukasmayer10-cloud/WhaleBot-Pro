# WhaleBot Pro X 6.1 - POSITION MANAGER

Binance Futures whale radar + paper trading dashboard. Paper mode only — no
real orders, live/testnet execution is hard-disabled.

## Quick start

```bash
npm run setup        # creates .venv and installs Python deps (one time)
npm run dev          # dev server on http://127.0.0.1:8080
npm start            # production server (waitress)
npm test             # run the test suite
```

Windows without npm: `run_windows.bat` (unchanged).

## Docker

```bash
npm run docker:up    # build + run, dashboard on http://127.0.0.1:8080
npm run docker:logs  # follow logs
npm run docker:down  # stop
```

`./data` (SQLite: balance, trades, equity history) and `./logs` are mounted
from the host, so account state **survives container restarts**.

## Show it live (Cloudflare)

Two options, honest trade-offs:

1. **Quick tunnel** (fastest, free) — run the bot locally or in Docker, then:
   ```bash
   brew install cloudflared   # once
   npm run tunnel             # prints a public https://*.trycloudflare.com URL
   ```
2. **Cloudflare Containers** (`deploy/cloudflare/`) — `npm run deploy:cf`
   after `wrangler login`. Requires a **paid Workers plan**. Caveats: the
   container sleeps without traffic (bot stops watching the market) and its
   disk is ephemeral (trade history resets on recycle). Good for demos; for a
   24/7 bot use Docker on a VPS / Fly.io / Railway instead.

Note: Cloudflare *Workers* (the free JS runtime) cannot host this app — it is
a Python process with background threads and long-lived websockets.

## Configuration

Copy `.env.example` to `.env`. Optional: Telegram alerts
(`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`) for trade opens/closes and stream
warnings. Strategy parameters live in `config/settings.json` and in the
dashboard settings panel.

## Operations

- `GET /healthz` — 200 when healthy, 503 when running with stale market data.
  Reports per-symbol price age, websocket age, reconnect count, thread count.
- Logs: `logs/whalebot.log` (rotating) + in-dashboard live log.
- Persistence: SQLite at `data/whalebot.db` (override with `WHALEBOT_DATA_DIR`).
- Market data: one combined Binance websocket for all symbols with exponential
  backoff and a staleness watchdog that force-reconnects silent streams.
- Stream names are chosen empirically: on the futures endpoint `@aggTrade`
  and `@depth20@1000ms` deliver nothing — the bot subscribes to `@trade`
  (re-aggregated in-process for whale detection) and `@depth20@500ms`.

## Backtesting

```bash
npm run backtest -- --symbol BTCUSDT --days 7
npm run backtest -- --symbol ETHUSDT --days 14 --min-confidence 80
```

Replays Binance Futures history (public archives, no API key) through the
**same StrategyEngine code the live bot runs** — same gates, same AI scoring.
SL/TP/break-even/trailing are simulated on every historical trade tick, with
paper fees + slippage applied. Prints the decision funnel (whales →
evaluations → signals, rejections per gate) and winrate / profit factor /
max drawdown; the full trade log lands in `data/backtest/report-*.json`.

Known limitation: orderbook walls are not in the public archives, so the wall
factor is 0 during backtests; AI weights are renormalized to compensate
(disable with `--raw-wall-weight`).

## Dashboard honesty

The dashboard shows only measured values: websocket age, per-symbol tick
freshness, evaluations per minute, and a decision funnel with gate-by-gate
rejection records (actual vs required per gate). If the bot isn't trading,
the "Letzte Evaluationen" panel tells you exactly which gate said no.

## Trade Lifecycle

```text
WAIT → PREPARE → READY → ENTER → MANAGE → BREAK_EVEN → TP1 → TRAILING → TP2 → EXIT
BLOCKED (risk check failed)
```

## Safety

- Keine echten Orders
- Kein Testnet Order Execution
- Kein Binance Live Trading
- Nur Paper Mode

## Test

```bash
npm test             # 16 offline tests: indicators, accounting, API, persistence
```

Manual check after `Demo Market`: open position appears, PnL updates live,
TP progress + management status visible, closed trades show exit reason.
CI (GitHub Actions) runs compile checks, JS syntax check, pytest and a Docker
build on every push.
