from app.core.state import STATE, LOCK, timeline, notify, now
import time

class CoreTradingEngine:
    """
    WhaleBot Pro X 5.2 Core Trading Engine.

    Final 5.x cleanup:
    - one active setup per symbol
    - short history per symbol
    - no duplicate timeline spam
    """

    def __init__(self, config):
        self.config = config
        self.last_emit = {}

    def _risk_check(self, symbol, side, score):
        with LOCK:
            positions = list(STATE.get("positions", []))
            daily_pnl = float(STATE.get("daily_pnl", 0))

        if daily_pnl <= -abs(float(self.config.get("max_daily_loss_usd", 25))):
            return False, "max daily loss reached"

        if len(positions) >= int(self.config.get("max_open_positions", 3)):
            return False, "max open positions reached"

        if any(p.get("symbol") == symbol for p in positions):
            return False, "symbol already open"

        if score < float(self.config.get("trade_quality_min_prepare", 70)):
            return False, "score below prepare threshold"

        return True, "risk ok"

    def _plan(self, symbol, side, price, score):
        entry = float(price)
        sl_pct = float(self.config.get("stop_loss_pct", 0.8))
        tp_pct = float(self.config.get("take_profit_pct", 1.4))
        size = float(self.config.get("position_size_usd", 50))

        if side == "SHORT":
            sl = entry * (1 + sl_pct / 100)
            tp1 = entry * (1 - tp_pct / 100)
            tp2 = entry * (1 - (tp_pct * 1.7) / 100)
        else:
            sl = entry * (1 - sl_pct / 100)
            tp1 = entry * (1 + tp_pct / 100)
            tp2 = entry * (1 + (tp_pct * 1.7) / 100)

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
            "risk_pct": sl_pct,
            "tp_pct": tp_pct,
            "rr": round(rr, 2),
            "score": score
        }

    def build_setup(self, ai_decision):
        symbol = ai_decision.get("symbol")
        side = ai_decision.get("side", "WATCH")
        score = int(ai_decision.get("score", 0))

        with LOCK:
            price = STATE.get("prices", {}).get(symbol)

        if not symbol or not price or side == "WATCH":
            return None

        plan = self._plan(symbol, side, price, score)
        risk_ok, risk_reason = self._risk_check(symbol, side, score)

        rr_min = float(self.config.get("risk_reward_min", 1.4))
        rr_ok = plan["rr"] >= rr_min

        quality = score
        if not rr_ok:
            quality = max(0, quality - 15)
        if not risk_ok:
            quality = max(0, quality - 25)

        prepare_min = int(self.config.get("trade_quality_min_prepare", 70))
        execute_min = int(self.config.get("trade_quality_min_execute", 85))

        if not risk_ok:
            action = "BLOCKED"
        elif quality >= execute_min:
            action = "PAPER_TRADE"
        elif quality >= prepare_min:
            action = "PREPARE"
        else:
            action = "WATCH"

        setup = {
            "ts": now(),
            "symbol": symbol,
            "side": side,
            "score": score,
            "quality": round(quality),
            "action": action,
            "risk_ok": risk_ok,
            "risk_reason": risk_reason,
            "rr_ok": rr_ok,
            "plan": plan,
            "ai": ai_decision,
            "trend": "STABLE",
            "rising": False,
            "explain": [
                f"AI Score {score}%",
                f"Risk: {risk_reason}",
                f"RR {plan['rr']}",
                f"Action {action}"
            ]
        }

        with LOCK:
            history = STATE.setdefault("setup_history", {}).setdefault(symbol, [])
            old = STATE.get("core_decisions", {}).get(symbol)

            # update one active setup per symbol
            # update trend from previous history
            if history:
                prev_q = history[-1].get("quality", setup["quality"])
                setup["rising"] = setup["quality"] > prev_q
                setup["trend"] = "RISING" if setup["quality"] > prev_q else "FALLING" if setup["quality"] < prev_q else "STABLE"

            STATE["core_decisions"][symbol] = setup

            # add compact history only if score/action changed or every few updates
            if not old or old.get("quality") != setup["quality"] or old.get("action") != setup["action"]:
                history.append({
                    "ts": setup["ts"],
                    "quality": setup["quality"],
                    "score": setup["score"],
                    "action": setup["action"],
                    "entry": setup["plan"]["entry"]
                })
                STATE["setup_history"][symbol] = history[-12:]

            # rebuild trade_setups from active decisions, newest first
            active = list(STATE["core_decisions"].values())
            active.sort(key=lambda x: (x.get("quality", 0), x.get("score", 0)), reverse=True)
            STATE["trade_setups"].clear()
            for item in active[:20]:
                item["history"] = STATE.get("setup_history", {}).get(item["symbol"], [])[-6:]
                STATE["trade_setups"].append(item)

        return setup

    def process_ai(self, ai_decision):
        setup = self.build_setup(ai_decision)
        if not setup:
            return None

        symbol = setup["symbol"]
        action = setup["action"]
        now_raw = time.time()
        last = self.last_emit.get(symbol, 0)
        last_key = self.last_emit.get(symbol + "_key")
        key = f"{action}:{setup['quality']}"

        # avoid timeline spam: only emit on action/quality change or every 30 sec
        if key != last_key or now_raw - last > 60:
            timeline("Core Engine", symbol, f"{action} | quality {setup['quality']}% | RR {setup['plan']['rr']}", "CORE")
            self.last_emit[symbol] = now_raw
            self.last_emit[symbol + "_key"] = key

        if action == "PAPER_TRADE" and key != last_key:
            notify("🧠 Core Trade Ready", f"{symbol} {setup['side']} quality {setup['quality']}%", "CORE")

        return setup
