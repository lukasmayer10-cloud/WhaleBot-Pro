from app.core.state import STATE, LOCK, timeline, notify, now

class PositionManager:
    """
    WhaleBot Pro X 6.1 Position Manager.

    Manages paper positions:
    - break even
    - trailing stop
    - TP1 marker / partial-close preparation
    - TP2 target
    """

    def __init__(self, config):
        self.config = config

    def _rr_now(self, pos, price):
        side = pos.get("side", "LONG")
        entry = float(pos.get("entry", 0))
        sl = float(pos.get("sl", 0))
        if not entry or not sl:
            return 0
        risk = abs(entry - sl)
        if risk <= 0:
            return 0
        move = (price - entry) if side == "LONG" else (entry - price)
        return move / risk

    def manage(self, prices):
        events = []

        with LOCK:
            positions = list(STATE.get("positions", []))

        for pos in positions:
            symbol = pos.get("symbol")
            price = prices.get(symbol)
            if not price:
                continue

            side = pos.get("side", "LONG")
            entry = float(pos.get("entry", 0))
            rr = self._rr_now(pos, price)

            pos.setdefault("manager", {
                "break_even": False,
                "tp1": False,
                "tp2": False,
                "trailing": False,
                "last_action": "MANAGE",
                "updated": now()
            })

            mgr = pos["manager"]
            action_events = []

            # Break even
            if self.config.get("break_even_enabled", True) and not mgr.get("break_even"):
                trigger = float(self.config.get("break_even_at_rr", 0.8))
                if rr >= trigger:
                    buffer_pct = float(self.config.get("break_even_buffer_pct", 0.03)) / 100
                    new_sl = entry * (1 + buffer_pct if side == "LONG" else 1 - buffer_pct)
                    if side == "LONG":
                        pos["sl"] = max(float(pos.get("sl", 0)), new_sl)
                    else:
                        pos["sl"] = min(float(pos.get("sl", 10**18)), new_sl)
                    mgr["break_even"] = True
                    mgr["last_action"] = "BREAK_EVEN"
                    mgr["updated"] = now()
                    action_events.append(("BREAK_EVEN", f"SL moved to BE {pos['sl']:.4f}"))

            # TP1 flag / partial close preparation
            if self.config.get("tp1_partial_enabled", True) and not mgr.get("tp1"):
                tp1 = float(pos.get("tp", 0))
                hit_tp1 = price >= tp1 if side == "LONG" else price <= tp1
                if tp1 and hit_tp1:
                    mgr["tp1"] = True
                    mgr["last_action"] = "TP1"
                    mgr["updated"] = now()
                    pct = self.config.get("tp1_close_pct", 50)
                    action_events.append(("TP1", f"TP1 reached | partial {pct}% prepared"))

            # Trailing Stop
            if self.config.get("trailing_stop_enabled", True):
                start_rr = float(self.config.get("trailing_start_rr", 1.2))
                trail_pct = float(self.config.get("trailing_stop_pct", 0.45)) / 100
                if rr >= start_rr:
                    if side == "LONG":
                        new_sl = price * (1 - trail_pct)
                        if new_sl > float(pos.get("sl", 0)):
                            pos["sl"] = new_sl
                            mgr["trailing"] = True
                            mgr["last_action"] = "TRAILING"
                            mgr["updated"] = now()
                            action_events.append(("TRAILING", f"trail SL {new_sl:.4f}"))
                    else:
                        new_sl = price * (1 + trail_pct)
                        if new_sl < float(pos.get("sl", 10**18)):
                            pos["sl"] = new_sl
                            mgr["trailing"] = True
                            mgr["last_action"] = "TRAILING"
                            mgr["updated"] = now()
                            action_events.append(("TRAILING", f"trail SL {new_sl:.4f}"))

            # TP2 marker
            if self.config.get("tp2_enabled", True) and not mgr.get("tp2"):
                tp2 = float(pos.get("tp2", 0))
                hit_tp2 = price >= tp2 if side == "LONG" else price <= tp2
                if tp2 and hit_tp2:
                    mgr["tp2"] = True
                    mgr["last_action"] = "TP2"
                    mgr["updated"] = now()
                    action_events.append(("TP2", "TP2 reached"))

            pos["rr_now"] = round(rr, 2)
            pos["manager"] = mgr

            for event, detail in action_events:
                events.append((symbol, event, detail))

        with LOCK:
            by_id = {p["id"]: p for p in positions if "id" in p}
            STATE["positions"] = [by_id.get(p.get("id"), p) for p in STATE.get("positions", [])]
            for symbol, event, detail in events:
                STATE["trade_lifecycle"][symbol] = event

        for symbol, event, detail in events:
            timeline("Position Manager", symbol, detail, event)
            notify("🧭 Position Manager", f"{symbol}: {detail}", event)

        return events
