from app.core.state import STATE, LOCK, log, timeline, notify, now

class PaperTradingEngine:
    def __init__(self, config):
        self.config = config

    def can_open(self, symbol):
        with LOCK:
            if len(STATE["positions"]) >= self.config["max_open_positions"]:
                return False
            return not any(p["symbol"] == symbol for p in STATE["positions"])

    def open_position(self, signal):
        symbol = signal["symbol"]
        if not self.can_open(symbol):
            timeline("Trade skipped", symbol, "max positions or already open", "WARN")
            return

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
            "id": int(__import__("time").time() * 1000),
            "symbol": symbol,
            "side": side,
            "entry": entry,
            "mark": entry,
            "qty": qty,
            "size_usd": size,
            "sl": sl,
            "tp": tp,
            "pnl": 0.0,
            "score": signal["score"],
            "risk": signal["risk"],
            "reason": signal["reason"],
            "stars": signal.get("stars", {}),
            "opened": now()
        }

        with LOCK:
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
            positions = list(STATE["positions"])

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
                for live in STATE["positions"]:
                    if live["id"] == p["id"]:
                        live["mark"] = price
                        live["pnl"] = pnl
                STATE["daily_pnl"] = sum(x.get("pnl", 0) for x in STATE["positions"]) + sum(x.get("pnl", 0) for x in STATE["closed"])
                STATE["equity"] = STATE["balance"] + STATE["daily_pnl"]
                STATE["equity_curve"].append({"ts": now(), "equity": STATE["equity"]})

            if hit:
                self.close_position(p["id"], hit)

    def close_position(self, pos_id, reason="MANUAL"):
        with LOCK:
            pos = next((x for x in STATE["positions"] if x["id"] == pos_id), None)
            if not pos:
                return
            STATE["positions"] = [x for x in STATE["positions"] if x["id"] != pos_id]
            pnl = pos["pnl"]
            pos["closed"] = now()
            pos["close_reason"] = reason
            STATE["closed"].appendleft(pos)
            if pnl >= 0:
                STATE["wins"] += 1
            else:
                STATE["losses"] += 1
            STATE["performance"]["total_trades"] += 1
            STATE["performance"]["best_trade"] = max(STATE["performance"]["best_trade"], pnl)
            STATE["performance"]["worst_trade"] = min(STATE["performance"]["worst_trade"], pnl)
            STATE["chart_markers"].append({"ts": now(), "symbol": pos["symbol"], "type": "exit", "side": pos["side"], "price": pos["mark"], "pnl": pnl})

        timeline("Paper trade closed", pos["symbol"], f"{reason} | PnL {pnl:.2f}", "TRADE")
        notify("✅ Trade closed", f"{pos['symbol']} {reason} {pnl:.2f}", "TRADE")
