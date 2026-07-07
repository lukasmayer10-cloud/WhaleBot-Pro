import time
import itertools
from app.core.state import STATE, LOCK, timeline, notify, now

_ID = itertools.count(1000)

class PaperTradingEngineV2:
    """
    WhaleBot Pro X 6.0 Paper Trading Engine.

    Handles:
    - open paper positions from core setups
    - live PnL
    - SL / TP auto close
    - fees / slippage
    - closed trades
    - journal rows
    """

    def __init__(self, config):
        self.config = config
        self.last_open_by_symbol = {}

    def can_open(self, symbol):
        cooldown = int(self.config.get("paper_trade_cooldown_sec", 20))
        last = self.last_open_by_symbol.get(symbol, 0)
        if time.time() - last < cooldown:
            return False, "cooldown"

        with LOCK:
            positions = STATE.get("positions", [])
            if any(p.get("symbol") == symbol for p in positions):
                return False, "already open"
            if len(positions) >= int(self.config.get("paper_max_positions", self.config.get("max_open_positions", 3))):
                return False, "max positions"
        return True, "ok"

    def open_from_setup(self, setup):
        if not setup or setup.get("action") != "PAPER_TRADE":
            return None

        symbol = setup["symbol"]
        ok, reason = self.can_open(symbol)
        if not ok:
            timeline("Paper Engine", symbol, f"open skipped: {reason}", "WARN")
            return None

        plan = setup.get("plan", {})
        side = setup.get("side", "LONG")
        raw_entry = float(plan.get("entry") or 0)
        if raw_entry <= 0:
            return None

        slip = float(self.config.get("paper_slippage_pct", 0.02)) / 100
        fee_pct = float(self.config.get("paper_fee_pct", 0.04)) / 100
        size = float(plan.get("size_usd", self.config.get("position_size_usd", 50)))

        entry = raw_entry * (1 + slip if side == "LONG" else 1 - slip)
        qty = size / entry if entry else 0
        fee_open = size * fee_pct

        pos = {
            "id": next(_ID),
            "symbol": symbol,
            "side": side,
            "state": "MANAGE",
            "entry": entry,
            "current": entry,
            "sl": float(plan.get("sl", 0)),
            "tp": float(plan.get("tp1", 0)),
            "tp2": float(plan.get("tp2", 0)),
            "qty": qty,
            "size_usd": size,
            "score": setup.get("quality", setup.get("score", 0)),
            "rr": plan.get("rr", 0),
            "pnl": -fee_open,
            "pnl_pct": 0,
            "fee_open": fee_open,
            "fee_close": 0,
            "fees": fee_open,
            "opened_ts": now(),
            "opened_raw": time.time(),
            "duration_sec": 0,
            "reason": "Core Engine PAPER_TRADE",
            "setup": setup
        }

        with LOCK:
            STATE["positions"].append(pos)
            STATE["trade_lifecycle"][symbol] = "MANAGE"
            STATE["stats"]["signals"] = STATE["stats"].get("signals", 0) + 1

        self.last_open_by_symbol[symbol] = time.time()
        timeline("Paper Trade", symbol, f"opened {side} @ {entry:.4f}", "TRADE")
        notify("📈 Paper Trade Open", f"{symbol} {side} @ {entry:.4f}", "TRADE")
        return pos

    def update(self, prices):
        to_close = []
        with LOCK:
            positions = list(STATE.get("positions", []))

        for pos in positions:
            symbol = pos["symbol"]
            price = prices.get(symbol)
            if not price:
                continue

            side = pos["side"]
            entry = float(pos["entry"])
            qty = float(pos["qty"])
            size = float(pos["size_usd"])
            fee_pct = float(self.config.get("paper_fee_pct", 0.04)) / 100

            raw_pnl = (price - entry) * qty if side == "LONG" else (entry - price) * qty
            fee_close = size * fee_pct
            pnl = raw_pnl - pos.get("fee_open", 0) - fee_close
            pnl_pct = pnl / size * 100 if size else 0

            pos["current"] = price
            pos["pnl"] = pnl
            pos["pnl_pct"] = pnl_pct
            pos["fee_close"] = fee_close
            pos["fees"] = pos.get("fee_open", 0) + fee_close
            pos["duration_sec"] = int(time.time() - pos.get("opened_raw", time.time()))

            hit_tp = price >= pos["tp"] if side == "LONG" else price <= pos["tp"]
            hit_sl = price <= pos["sl"] if side == "LONG" else price >= pos["sl"]

            if self.config.get("paper_auto_close", True):
                if hit_tp:
                    to_close.append((pos["id"], "TP"))
                elif hit_sl:
                    to_close.append((pos["id"], "SL"))

        with LOCK:
            # write updated position objects back
            current_ids = {p["id"]: p for p in positions}
            STATE["positions"] = [current_ids.get(p["id"], p) for p in STATE.get("positions", [])]

        for pid, reason in to_close:
            self.close(pid, reason)

    def close(self, pos_id, reason="MANUAL"):
        with LOCK:
            positions = STATE.get("positions", [])
            idx = next((i for i, p in enumerate(positions) if p.get("id") == pos_id), None)
            if idx is None:
                return None
            pos = positions.pop(idx)

            pnl = float(pos.get("pnl", 0))
            STATE["balance"] += pnl
            STATE["equity"] = STATE["balance"] + sum(float(p.get("pnl", 0)) for p in positions)
            STATE["daily_pnl"] += pnl

            if pnl >= 0:
                STATE["wins"] += 1
            else:
                STATE["losses"] += 1

            pos["closed_ts"] = now()
            pos["closed_raw"] = time.time()
            pos["close_reason"] = reason
            pos["state"] = "EXIT"

            STATE["closed"].appendleft(pos)
            STATE["trade_journal"].appendleft(pos)
            STATE["equity_curve"].append({"ts": now(), "equity": STATE["equity"]})
            STATE["trade_lifecycle"][pos["symbol"]] = "EXIT"

        timeline("Paper Trade", pos["symbol"], f"closed {reason} | PnL {pnl:+.2f}", "TRADE")
        notify("✅ Paper Trade Closed", f"{pos['symbol']} {reason} PnL {pnl:+.2f}", "TRADE")
        return pos
