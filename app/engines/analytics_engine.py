from app.core.state import STATE, LOCK

class AnalyticsEngine:
    """
    4.0 analytics summary.
    """

    def summary(self):
        with LOCK:
            closed = list(STATE.get("closed", []))
            equity_curve = list(STATE["equity_curve"])

        pnls = [float(t.get("pnl", 0)) for t in closed]
        wins = [p for p in pnls if p >= 0]
        losses = [p for p in pnls if p < 0]

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss else (gross_profit if gross_profit else 0)

        max_dd = 0
        peak = None
        for row in equity_curve:
            eq = row.get("equity", 0)
            peak = eq if peak is None else max(peak, eq)
            if peak:
                max_dd = min(max_dd, eq - peak)

        return {
            "total_trades": len(pnls),
            "wins": len(wins),
            "losses": len(losses),
            "winrate": round(len(wins) / len(pnls) * 100, 2) if pnls else 0,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "average_win": round(sum(wins) / len(wins), 2) if wins else 0,
            "average_loss": round(sum(losses) / len(losses), 2) if losses else 0,
            "max_drawdown": round(max_dd, 2)
        }
