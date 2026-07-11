from collections import deque
import logging
import threading
import time

LOCK = threading.RLock()

_logger = logging.getLogger("whalebot")

# position ids: time-seeded monotonic counter, unique across both paper
# engines and across restarts (restored positions keep their old ids)
_next_id = int(time.time() * 1000)

def next_position_id():
    global _next_id
    with LOCK:
        _next_id += 1
        return _next_id

DEFAULT_BALANCE = 1000.0

STATE = {
    "version": "6.1 POSITION MANAGER",
    "running": False,
    "started_at": None,

    "balance": DEFAULT_BALANCE,
    "equity": DEFAULT_BALANCE,
    "daily_pnl": 0.0,
    "day": time.strftime("%Y-%m-%d"),
    "day_start_equity": DEFAULT_BALANCE,
    "wins": 0,
    "losses": 0,

    "prices": {},
    "price_change": {},
    "last_price_update": {},
    "candles": {},
    "orderbook": {},

    "walls": deque(maxlen=400),
    "whales": deque(maxlen=800),
    "clusters": deque(maxlen=400),
    "signals": deque(maxlen=300),
    "evaluations": deque(maxlen=120),
    "trade_setups": deque(maxlen=300),
    "core_decisions": {},
    "trade_lifecycle": {},
    "setup_history": {},
    "positions": [],
    "closed": deque(maxlen=300),
    "trade_journal": deque(maxlen=600),

    "timeline": deque(maxlen=400),
    "logs": deque(maxlen=700),
    "radar": {},
    "ai_decisions": {},
    "notifications": deque(maxlen=80),
    "chart_markers": deque(maxlen=300),
    "equity_curve": deque(maxlen=800),

    "system": {
        "stream": "OFF",
        "ping_ms": 0,
        "latency_ms": 0,
        "api": "PUBLIC",
        "engine": "IDLE"
    },

    "performance": {
        "total_trades": 0,
        "best_trade": 0.0,
        "worst_trade": 0.0,
        "profit_factor": 0.0
    },

    "stats": {
        "whales_seen": 0,
        "clusters": 0,
        "signals": 0,
        "ignored": 0,
        "walls_seen": 0,
        "blocked_confidence": 0,
        "wall_confirmed": 0,
        "evaluations": 0,
        "reject_reasons": {}
    }
}

def now():
    return time.strftime("%H:%M:%S")

_LOG_LEVELS = {"WARN": logging.WARNING, "ERROR": logging.ERROR}

def log(msg, level="INFO"):
    with LOCK:
        STATE["logs"].appendleft({"ts": now(), "level": level, "msg": msg})
    _logger.log(_LOG_LEVELS.get(level, logging.INFO), "%s %s", level, msg)

def timeline(event, symbol="", detail="", level="INFO"):
    with LOCK:
        STATE["timeline"].appendleft({
            "ts": now(),
            "event": event,
            "symbol": symbol,
            "detail": detail,
            "level": level
        })

def notify(title, body, level="INFO"):
    with LOCK:
        STATE["notifications"].appendleft({
            "ts": now(),
            "title": title,
            "body": body,
            "level": level
        })
    # optional Telegram forwarding; imported lazily to avoid an import cycle
    try:
        from app.core.alerts import send_alert
        send_alert(title, body, level)
    except Exception:
        pass

def _roll_day_locked():
    """Reset the daily PnL anchor when the calendar day changes.

    daily_pnl feeds the max-daily-loss risk check; without a rollover the
    bot would stay blocked forever after one bad day."""
    day = time.strftime("%Y-%m-%d")
    if STATE.get("day") != day:
        STATE["day"] = day
        STATE["day_start_equity"] = STATE.get("equity", STATE.get("balance", DEFAULT_BALANCE))

def update_equity_locked():
    """Recompute equity/daily_pnl from one source of truth.

    balance = realized cash, equity = balance + unrealized PnL of open
    positions, daily_pnl = equity change since the start of the day.
    Caller must hold LOCK."""
    _roll_day_locked()
    open_pnl = sum(float(p.get("pnl", 0.0)) for p in STATE.get("positions", []))
    STATE["equity"] = float(STATE.get("balance", DEFAULT_BALANCE)) + open_pnl
    STATE["daily_pnl"] = STATE["equity"] - float(STATE.get("day_start_equity", DEFAULT_BALANCE))

def record_close_locked(pnl):
    """Book a realized PnL: cash, win/loss counters, performance stats.

    Call after the position has been moved to STATE["closed"].
    Caller must hold LOCK."""
    pnl = float(pnl)
    STATE["balance"] = float(STATE.get("balance", DEFAULT_BALANCE)) + pnl
    if pnl >= 0:
        STATE["wins"] += 1
    else:
        STATE["losses"] += 1

    perf = STATE["performance"]
    perf["total_trades"] += 1
    perf["best_trade"] = max(perf.get("best_trade", 0.0), pnl)
    perf["worst_trade"] = min(perf.get("worst_trade", 0.0), pnl)
    pnls = [float(t.get("pnl", 0.0)) for t in STATE.get("closed", [])]
    gross_profit = sum(p for p in pnls if p >= 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    perf["profit_factor"] = round(gross_profit / gross_loss, 2) if gross_loss else round(gross_profit, 2)

    update_equity_locked()
    STATE["equity_curve"].append({"ts": now(), "equity": STATE["equity"]})

def ensure_state():
    with LOCK:
        if STATE.get("balance") is None:
            STATE["balance"] = DEFAULT_BALANCE
        if STATE.get("equity") is None:
            STATE["equity"] = STATE.get("balance", DEFAULT_BALANCE) + STATE.get("daily_pnl", 0.0)
        STATE.setdefault("day", time.strftime("%Y-%m-%d"))
        STATE.setdefault("day_start_equity", STATE.get("balance", DEFAULT_BALANCE))
        _roll_day_locked()
        STATE.setdefault("prices", {})
        STATE.setdefault("price_change", {})
        STATE.setdefault("last_price_update", {})
        STATE.setdefault("candles", {})
        STATE.setdefault("orderbook", {})
        STATE.setdefault("radar", {})
        STATE.setdefault("ai_decisions", {})
        STATE.setdefault("core_decisions", {})
        STATE.setdefault("setup_history", {})
        STATE.setdefault("trade_lifecycle", {})
