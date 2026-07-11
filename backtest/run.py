"""CLI: python -m backtest.run --symbol BTCUSDT --days 3

Replays Binance Futures history through the live strategy code and prints
winrate / profit factor / drawdown plus the gate-rejection funnel."""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import load_config
from backtest.data import cache_dir
from backtest.engine import Backtester

def date_range(days, end=None):
    # archives lag ~1 day; default to ending the day before yesterday (UTC)
    end = end or (dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=2))
    return [str(end - dt.timedelta(days=i)) for i in range(days - 1, -1, -1)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--end", help="last date YYYY-MM-DD (default: 2 days ago)")
    ap.add_argument("--min-confidence", type=int, help="override min_confidence")
    ap.add_argument("--whale-min", type=float, help="override whale_usd_min")
    ap.add_argument("--raw-wall-weight", action="store_true",
                    help="do NOT renormalize AI weights for the missing wall data")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="override any config key, e.g. --set cluster_count=2")
    args = ap.parse_args()

    config = load_config()
    if args.min_confidence is not None:
        config["min_confidence"] = args.min_confidence
    if args.whale_min is not None:
        config["whale_usd_min"] = args.whale_min
    for pair in args.set:
        key, _, raw = pair.partition("=")
        if raw.lower() in ("true", "false"):
            val = raw.lower() == "true"
        else:
            try:
                val = int(raw)
            except ValueError:
                try:
                    val = float(raw)
                except ValueError:
                    val = raw
        config[key] = val
        print(f"override: {key} = {val!r}")

    end = dt.date.fromisoformat(args.end) if args.end else None
    dates = date_range(args.days, end)
    print(f"Backtest {args.symbol} {dates[0]} .. {dates[-1]} | "
          f"whale_min ${config['whale_usd_min']:,.0f} | min_conf {config['min_confidence']}%")

    bt = Backtester(config, args.symbol, renormalize_wall=not args.raw_wall_weight)
    report = bt.run(dates)

    f = report["funnel"]
    print("\n=== FUNNEL ===")
    print(f"ticks {report['ticks_replayed']:,} -> whales {f['whales_seen']:,} -> "
          f"evaluations {f['evaluations']:,} -> signals {f['signals']}")
    if f["reject_reasons"]:
        top = sorted(f["reject_reasons"].items(), key=lambda x: -x[1])
        print("rejected by gate: " + ", ".join(f"{k} {v:,}" for k, v in top))

    print("\n=== RESULT ===")
    for k in ["trades", "wins", "losses", "winrate_pct", "total_pnl", "return_pct",
              "profit_factor", "avg_win", "avg_loss", "max_drawdown", "avg_duration_min",
              "exit_reasons"]:
        print(f"{k:18} {report[k]}")

    out = cache_dir() / f"report-{args.symbol}-{dates[0]}-{dates[-1]}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f"\nfull report: {out}")

if __name__ == "__main__":
    main()
