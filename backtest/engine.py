"""Backtest engine: replays historical trades through the LIVE strategy code.

Fidelity notes (documented, not hidden):
- Uses app.engines.strategy_engine.StrategyEngine directly — the same gates,
  the same AI scoring, the same thresholds as the running bot. No reimplementation.
- Whale detection, cluster windows and evaluation throttling (1/sec/symbol)
  mirror the live MarketEngine.
- Position management mirrors the live v1 engine + PositionManager: SL/TP
  checked on EVERY historical trade tick (finer than the live 1s loop),
  break-even at 0.8R, trailing from 1.2R.
- Fees + entry slippage are applied (the live v1 engine charges none — the
  backtest is deliberately more pessimistic, using the paper_fee/slippage
  settings).
- LIMITATION: orderbook walls cannot be reconstructed from public archives.
  The wall score is 0 during backtests; by default the AI weights are
  renormalized without the wall factor so the confidence gate keeps the same
  meaning. Disable with renormalize_wall=False to see raw scores instead.
"""

import time
from collections import deque

from app.core.state import STATE, LOCK
from app.engines.strategy_engine import StrategyEngine
from backtest.data import iter_klines, iter_trades

class Backtester:
    def __init__(self, config, symbol, renormalize_wall=True):
        self.config = dict(config)
        self.symbol = symbol
        if renormalize_wall:
            weights = dict(self.config.get("ai_weights") or {})
            weights.setdefault("wall", 0.13)
            wall = weights.pop("wall")
            total = sum(weights.values()) or 1.0
            self.config["ai_weights"] = {k: v * (1 + wall / total) for k, v in weights.items()}
        self.strategy = StrategyEngine(self.config)
        self.trades = []
        self.equity_curve = []
        self._reset_state()

    def _reset_state(self):
        with LOCK:
            STATE["whales"] = deque(maxlen=800)
            STATE["walls"] = deque(maxlen=400)
            STATE["candles"] = {}
            STATE["prices"] = {}
            STATE["evaluations"] = deque(maxlen=100000)
            STATE["stats"]["evaluations"] = 0
            STATE["stats"]["reject_reasons"] = {}
            STATE["stats"]["whales_seen"] = 0
            STATE["stats"]["signals"] = 0

    # ------------------------------------------------------------- position

    def _open(self, signal, ts):
        entry_raw = signal["price"]
        side = signal["side"]
        slip = float(self.config.get("paper_slippage_pct", 0.02)) / 100
        entry = entry_raw * (1 + slip if side == "LONG" else 1 - slip)
        size = float(self.config.get("position_size_usd", 50))
        sl_pct = float(self.config.get("stop_loss_pct", 0.8)) / 100
        tp_pct = float(self.config.get("take_profit_pct", 1.4)) / 100
        if side == "LONG":
            sl, tp = entry * (1 - sl_pct), entry * (1 + tp_pct)
        else:
            sl, tp = entry * (1 + sl_pct), entry * (1 - tp_pct)
        return {
            "symbol": self.symbol, "side": side, "entry": entry, "qty": size / entry,
            "size_usd": size, "sl": sl, "tp": tp, "opened": ts, "score": signal["score"],
            "be_done": False, "trailing": False, "_sl0": sl,
        }

    def _manage(self, pos, price):
        """Break-even + trailing, same formulas as the live PositionManager."""
        entry, side = pos["entry"], pos["side"]
        risk = abs(entry - pos["_sl0"]) or 1e-12  # RR vs the ORIGINAL stop
        move = (price - entry) if side == "LONG" else (entry - price)
        rr = move / risk

        if self.config.get("break_even_enabled", True) and not pos["be_done"]:
            if rr >= float(self.config.get("break_even_at_rr", 0.8)):
                buf = float(self.config.get("break_even_buffer_pct", 0.03)) / 100
                new_sl = entry * (1 + buf) if side == "LONG" else entry * (1 - buf)
                pos["sl"] = max(pos["sl"], new_sl) if side == "LONG" else min(pos["sl"], new_sl)
                pos["be_done"] = True

        if self.config.get("trailing_stop_enabled", True):
            if rr >= float(self.config.get("trailing_start_rr", 1.2)):
                trail = float(self.config.get("trailing_stop_pct", 0.45)) / 100
                new_sl = price * (1 - trail) if side == "LONG" else price * (1 + trail)
                if (side == "LONG" and new_sl > pos["sl"]) or (side == "SHORT" and new_sl < pos["sl"]):
                    pos["sl"] = new_sl
                    pos["trailing"] = True

    def _try_exit(self, pos, price, ts):
        side = pos["side"]
        hit_sl = price <= pos["sl"] if side == "LONG" else price >= pos["sl"]
        hit_tp = price >= pos["tp"] if side == "LONG" else price <= pos["tp"]
        if not (hit_sl or hit_tp):
            return None
        exit_price = pos["sl"] if hit_sl else pos["tp"]
        reason = ("TRAIL" if pos["trailing"] else "BE" if pos["be_done"] else "SL") if hit_sl else "TP"
        raw = (exit_price - pos["entry"]) * pos["qty"] if side == "LONG" else (pos["entry"] - exit_price) * pos["qty"]
        fee = pos["size_usd"] * float(self.config.get("paper_fee_pct", 0.04)) / 100 * 2
        pos.update(exit=exit_price, closed=ts, reason=reason,
                   pnl=raw - fee, fees=fee, duration_sec=int(ts - pos["opened"]))
        return pos

    # ----------------------------------------------------------------- run

    def run(self, dates, progress=True):
        whale_min = float(self.config["whale_usd_min"])
        completed = deque(maxlen=200)
        forming = None
        open_pos = None
        last_eval = 0.0
        equity = float(self.config.get("paper_start_balance", 1000.0))
        n_trades_seen = 0

        for date in dates:
            klines = {int(k["t"] // 60): k for k in iter_klines(self.symbol, date)}
            if progress:
                print(f"  replaying {self.symbol} {date} ({len(klines)} candles)")
            cur_minute = None

            for ts, price, qty, is_sell in iter_trades(self.symbol, date):
                n_trades_seen += 1
                minute = int(ts // 60)

                if cur_minute is None:
                    cur_minute = minute
                if minute > cur_minute:
                    # finalize finished minutes with authoritative kline data
                    for m in range(cur_minute, minute):
                        k = klines.get(m)
                        if k:
                            completed.append(k)
                        elif forming and int(forming["t"] // 60) == m:
                            completed.append(forming)
                    forming = None
                    cur_minute = minute
                if forming is None:
                    forming = {"t": minute * 60.0, "o": price, "h": price, "l": price, "c": price, "v": 0.0}
                forming["h"] = max(forming["h"], price)
                forming["l"] = min(forming["l"], price)
                forming["c"] = price
                forming["v"] += qty

                # manage the open position on every tick
                if open_pos is not None:
                    self._manage(open_pos, price)
                    closed = self._try_exit(open_pos, price, ts)
                    if closed:
                        equity += closed["pnl"]
                        closed["equity"] = equity
                        self.trades.append(closed)
                        self.equity_curve.append((ts, equity))
                        open_pos = None

                value = price * qty
                if value < whale_min:
                    continue

                side = "SELL" if is_sell else "BUY"
                with LOCK:
                    STATE["whales"].appendleft({
                        "ts": "", "time_raw": ts, "symbol": self.symbol,
                        "side": side, "price": price, "qty": qty, "value": value,
                    })
                    STATE["stats"]["whales_seen"] += 1

                if open_pos is not None or len(completed) < 119:
                    continue
                if ts - last_eval < 1.0:  # live evaluation throttle
                    continue
                last_eval = ts

                with LOCK:
                    STATE["candles"][self.symbol] = list(completed)[-119:] + [dict(forming)]
                    STATE["prices"][self.symbol] = price

                signal = self.strategy.evaluate_from_whale(self.symbol, side, now_raw=ts)
                if signal:
                    open_pos = self._open(signal, ts)

        # close anything still open at the end, at last price
        if open_pos is not None:
            raw = (price - open_pos["entry"]) * open_pos["qty"] if open_pos["side"] == "LONG" \
                else (open_pos["entry"] - price) * open_pos["qty"]
            fee = open_pos["size_usd"] * float(self.config.get("paper_fee_pct", 0.04)) / 100 * 2
            open_pos.update(exit=price, closed=ts, reason="EOD", pnl=raw - fee, fees=fee,
                            duration_sec=int(ts - open_pos["opened"]))
            equity += open_pos["pnl"]
            open_pos["equity"] = equity
            self.trades.append(open_pos)

        return self.report(n_trades_seen)

    def report(self, n_ticks=0):
        pnls = [t["pnl"] for t in self.trades]
        wins = [p for p in pnls if p >= 0]
        losses = [p for p in pnls if p < 0]
        gp, gl = sum(wins), abs(sum(losses))
        peak, max_dd = None, 0.0
        for _, eq in self.equity_curve:
            peak = eq if peak is None else max(peak, eq)
            max_dd = min(max_dd, eq - peak)
        with LOCK:
            stats = {
                "whales_seen": STATE["stats"]["whales_seen"],
                "evaluations": STATE["stats"]["evaluations"],
                "reject_reasons": dict(STATE["stats"]["reject_reasons"]),
                "signals": STATE["stats"]["signals"],
            }
        start = float(self.config.get("paper_start_balance", 1000.0))
        return {
            "symbol": self.symbol,
            "ticks_replayed": n_ticks,
            "funnel": stats,
            "trades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "winrate_pct": round(len(wins) / len(pnls) * 100, 1) if pnls else 0,
            "total_pnl": round(sum(pnls), 2),
            "return_pct": round(sum(pnls) / start * 100, 2),
            "profit_factor": round(gp / gl, 2) if gl else (round(gp, 2) if gp else 0),
            "avg_win": round(gp / len(wins), 3) if wins else 0,
            "avg_loss": round(-gl / len(losses), 3) if losses else 0,
            "max_drawdown": round(max_dd, 2),
            "avg_duration_min": round(sum(t["duration_sec"] for t in self.trades) / len(self.trades) / 60, 1) if self.trades else 0,
            "exit_reasons": {r: sum(1 for t in self.trades if t["reason"] == r)
                             for r in {t["reason"] for t in self.trades}},
            "trade_log": [
                {k: (round(v, 6) if isinstance(v, float) else v)
                 for k, v in t.items() if not k.startswith("_")}
                for t in self.trades
            ],
        }
