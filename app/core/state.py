from collections import deque
import threading
import time

LOCK = threading.RLock()

DEFAULT_BALANCE = 1000.0

DEFAULT_BALANCE = 1000.0

STATE = {
    "version": "6.1 POSITION MANAGER",
    "running": False,
    "started_at": None,

    "balance": DEFAULT_BALANCE,
    "equity": DEFAULT_BALANCE,
    "daily_pnl": 0.0,
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
        "fps": 60,
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
        "wall_confirmed": 0
    }
}

def now():
    return time.strftime("%H:%M:%S")

def log(msg, level="INFO"):
    with LOCK:
        STATE["logs"].appendleft({"ts": now(), "level": level, "msg": msg})

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

def ensure_state():
    with LOCK:
        if not STATE.get("balance"):
            STATE["balance"] = DEFAULT_BALANCE
        if not STATE.get("equity"):
            STATE["equity"] = STATE.get("balance", DEFAULT_BALANCE) + STATE.get("daily_pnl", 0.0)
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
