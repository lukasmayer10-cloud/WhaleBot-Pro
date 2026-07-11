import time

from app.core.state import STATE, LOCK, log, timeline, notify, now, record_close_locked, update_equity_locked, next_position_id
from app.core import persistence

class PaperTradingEngine:
    def __init__(self, config):
        self.config = config

    def _can_open_locked(self, symbol):
        if len(STATE["positions"]) >= self.config["max_open_positions"]:
            return False
        return not any(p["symbol"] == symbol for p in STATE["positions"])

    def open_position(self, signal):
        symbol = signal["symbol"]
        entry = signal["price"]
        side = signal["side"]
        size = self.config["position_size_usd"]
        qty = size / entry

        if side == "LONG":
            sl = entry * (1 - self.config["stop_loss_pct"] / 100)
            tp = entry * (1 + self.config["take_profit_pct"] / 100)
        else:
            sl = entry * (1 + self.config["stop_loss_pct"] / 100)
            tp = entry * (1 - self.config["take_profit_pct"] / 100)

        pos = {
            "id": next_position_id(),
            "engine": "v1",
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "mark": entry,
            "current": entry,
            "qty": qty,
            "size_usd": size,
            "sl": sl,
            "tp": tp,
            "pnl": 0.0,
            "score": signal["score"],
            "risk": signal["risk"],
            "reason": signal["reason"],
            "stars": signal.get("stars", {}),
            "opened": now(),
            "opened_raw": time.time(),
            "duration_sec": 0
        }

        with LOCK:
            # check + append under one lock so concurrent whale-stream
            # threads cannot exceed max positions or double-open a symbol
            if not self._can_open_locked(symbol):
                timeline("Trade skipped", symbol, "max positions or already open", "WARN")
                return
            STATE["positions"].append(pos)
            STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "entry", "side": side, "price": entry, "score": signal["score"]})
            STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "sl", "side": side, "price": sl})
            STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "tp", "side": side, "price": tp})
            STATE["equity_curve"].append({"ts": now(), "equity": STATE["equity"]})

        log(f"{side} PAPER opened {symbol} @ {entry:.4f} | score {signal['score']}%", "TRADE")
        timeline("Paper trade opened", symbol, f"{side} @ {entry:.2f}", "TRADE")
        notify("📈 Paper Trade", f"{symbol} {side} opened", "TRADE")

    def update_positions(self, prices):
        with LOCK:
            positions = [p for p in STATE["positions"] if p.get("engine", "v1") == "v1"]

        to_close = []
        for p in positions:
            price = prices.get(p["symbol"])
            if not price:
                continue

            if p["side"] == "LONG":
                pnl = (price - p["entry"]) * p["qty"]
                hit = "TP" if price >= p["tp"] else "SL" if price <= p["sl"] else None
            else:
                pnl = (p["entry"] - price) * p["qty"]
                hit = "TP" if price <= p["tp"] else "SL" if price >= p["sl"] else None

            with LOCK:
                p["mark"] = price
                p["current"] = price
                p["pnl"] = pnl
                p["duration_sec"] = int(time.time() - p.get("opened_raw", time.time()))

            if hit:
                to_close.append((p["id"], hit))

        with LOCK:
            update_equity_locked()

        for pos_id, reason in to_close:
            self.close_position(pos_id, reason)

    def close_position(self, pos_id, reason="MANUAL"):
        with LOCK:
            pos = next((x for x in STATE["positions"] if x["id"] == pos_id), None)
            if not pos:
                return None
            STATE["positions"] = [x for x in STATE["positions"] if x["id"] != pos_id]
            pnl = pos["pnl"]
            pos["closed"] = now()
            pos["closed_raw"] = time.time()
            pos["close_reason"] = reason
            STATE["closed"].appendleft(pos)
            record_close_locked(pnl)
            STATE["chart_markers"].append({"ts": now(), "symbol": pos["symbol"], "type": "exit", "side": pos["side"], "price": pos["mark"], "pnl": pnl})

        persistence.save_trade(pos)
        timeline("Paper trade closed", pos["symbol"], f"{reason} | PnL {pnl:.2f}", "TRADE")
        notify("✅ Trade closed", f"{pos['symbol']} {reason} {pnl:.2f}", "TRADE")
        return pos
