class RiskManager:
    """
    WhaleBot Pro X 4.0 Risk Manager.

    Active for paper mode and prepared for testnet/live later.
    """

    def __init__(self, config):
        self.config = config

    def daily_loss_ok(self, daily_pnl):
        max_loss = float(self.config.get("max_daily_loss_usd", 25))
        return daily_pnl > -abs(max_loss)

    def can_open_position(self, state, symbol):
        if not self.daily_loss_ok(state.get("daily_pnl", 0)):
            return False, "max daily loss reached"

        max_pos = int(self.config.get("max_open_positions", 3))
        positions = state.get("positions", [])
        if len(positions) >= max_pos:
            return False, "max positions reached"

        if any(p.get("symbol") == symbol for p in positions):
            return False, "symbol already open"

        return True, "ok"

    def calculate_plan(self, signal, balance):
        entry = float(signal["price"])
        side = signal["side"]
        size = float(self.config.get("position_size_usd", 50))
        sl_pct = float(self.config.get("stop_loss_pct", 0.8))
        tp_pct = float(self.config.get("take_profit_pct", 1.4))

        if side == "LONG":
            sl = entry * (1 - sl_pct / 100)
            tp1 = entry * (1 + tp_pct / 100)
            tp2 = entry * (1 + (tp_pct * 1.7) / 100)
        else:
            sl = entry * (1 + sl_pct / 100)
            tp1 = entry * (1 - tp_pct / 100)
            tp2 = entry * (1 - (tp_pct * 1.7) / 100)

        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        rr = reward / risk if risk else 0

        return {
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "size_usd": size,
            "qty": size / entry if entry else 0,
            "risk_usd_est": size * sl_pct / 100,
            "reward_usd_est": size * tp_pct / 100,
            "rr": round(rr, 2)
        }
