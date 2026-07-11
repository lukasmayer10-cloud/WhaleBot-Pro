"""SQLite persistence: account, closed trades, open positions, equity curve.

All writes go through a module lock and a single WAL-mode connection so the
websocket threads, the position loop and the web workers can share it safely.
Set WHALEBOT_DATA_DIR to relocate the database (used by tests and Docker)."""

import json
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

from app.core.state import STATE, LOCK, log

_ROOT = Path(__file__).resolve().parents[2]
_DB_LOCK = threading.Lock()
_conn = None

def _data_dir():
    return Path(os.getenv("WHALEBOT_DATA_DIR", _ROOT / "data"))

def db_path():
    return _data_dir() / "whalebot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    closed_at REAL NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    pnl REAL NOT NULL,
    close_reason TEXT,
    engine TEXT,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE TABLE IF NOT EXISTS equity_curve (
    ts REAL PRIMARY KEY,
    equity REAL NOT NULL
);
"""

def init_db():
    global _conn
    with _DB_LOCK:
        if _conn is not None:
            return
        _data_dir().mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(db_path(), check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute("PRAGMA synchronous=NORMAL")
        _conn.executescript(_SCHEMA)
        _conn.commit()

def close_db():
    global _conn
    with _DB_LOCK:
        if _conn is not None:
            try:
                _conn.commit()
                _conn.close()
            except Exception:
                pass
            _conn = None

def _set_account(cur, key, value):
    cur.execute(
        "INSERT INTO account(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, json.dumps(value)),
    )

ACCOUNT_KEYS = ["balance", "wins", "losses", "daily_pnl", "day", "day_start_equity", "performance", "stats"]

def save_account():
    """Persist the account snapshot. Reads state under LOCK, writes outside it."""
    with LOCK:
        snapshot = {k: STATE.get(k) for k in ACCOUNT_KEYS}
    try:
        with _DB_LOCK:
            if _conn is None:
                return
            cur = _conn.cursor()
            for k, v in snapshot.items():
                _set_account(cur, k, v)
            _conn.commit()
    except Exception as e:
        log(f"Persistence account save: {e}", "WARN")

def save_open_positions():
    """Snapshot open paper positions so a restart doesn't lose them."""
    with LOCK:
        positions = json.loads(json.dumps(STATE.get("positions", []), default=str))
    try:
        with _DB_LOCK:
            if _conn is None:
                return
            cur = _conn.cursor()
            _set_account(cur, "open_positions", positions)
            _conn.commit()
    except Exception as e:
        log(f"Persistence positions save: {e}", "WARN")

def save_trade(pos):
    """Append one closed trade and refresh the account snapshot."""
    try:
        row = json.dumps(pos, default=str)
        with _DB_LOCK:
            if _conn is None:
                return
            _conn.execute(
                "INSERT INTO trades(closed_at, symbol, side, pnl, close_reason, engine, data) "
                "VALUES(?, ?, ?, ?, ?, ?, ?)",
                (
                    float(pos.get("closed_raw", time.time())),
                    pos.get("symbol", ""),
                    pos.get("side", ""),
                    float(pos.get("pnl", 0.0)),
                    pos.get("close_reason", ""),
                    pos.get("engine", ""),
                    row,
                ),
            )
            _conn.commit()
    except Exception as e:
        log(f"Persistence trade save: {e}", "WARN")
    save_account()
    save_open_positions()

def save_equity_point(ts_raw, equity):
    try:
        with _DB_LOCK:
            if _conn is None:
                return
            _conn.execute(
                "INSERT OR REPLACE INTO equity_curve(ts, equity) VALUES(?, ?)",
                (float(ts_raw), float(equity)),
            )
            # keep the table bounded
            _conn.execute(
                "DELETE FROM equity_curve WHERE ts NOT IN "
                "(SELECT ts FROM equity_curve ORDER BY ts DESC LIMIT 5000)"
            )
            _conn.commit()
    except Exception as e:
        log(f"Persistence equity save: {e}", "WARN")

def restore_state():
    """Load persisted account/trades back into STATE. Call once on boot."""
    try:
        with _DB_LOCK:
            if _conn is None:
                return False
            rows = dict(_conn.execute("SELECT key, value FROM account").fetchall())
            trades = _conn.execute(
                "SELECT data FROM trades ORDER BY closed_at DESC LIMIT 300"
            ).fetchall()
            curve = _conn.execute(
                "SELECT ts, equity FROM equity_curve ORDER BY ts DESC LIMIT 800"
            ).fetchall()
    except Exception as e:
        log(f"Persistence restore: {e}", "WARN")
        return False

    if not rows and not trades:
        return False

    with LOCK:
        for key in ACCOUNT_KEYS:
            if key in rows:
                value = json.loads(rows[key])
                if isinstance(STATE.get(key), dict) and isinstance(value, dict):
                    STATE[key].update(value)
                else:
                    STATE[key] = value
        if "open_positions" in rows:
            restored = json.loads(rows["open_positions"]) or []
            existing = {p.get("id") for p in STATE.get("positions", [])}
            for pos in restored:
                if pos.get("id") not in existing:
                    STATE["positions"].append(pos)
        closed = [json.loads(r[0]) for r in trades]
        STATE["closed"] = deque(closed, maxlen=300)
        STATE["trade_journal"] = deque(closed, maxlen=600)
        STATE["equity_curve"] = deque(
            [{"ts": time.strftime("%H:%M:%S", time.localtime(ts)), "equity": eq} for ts, eq in reversed(curve)],
            maxlen=800,
        )
        open_pnl = sum(float(p.get("pnl", 0.0)) for p in STATE.get("positions", []))
        STATE["equity"] = float(STATE.get("balance", 1000.0)) + open_pnl

    log(f"Restored account + {len(closed)} trades from {db_path().name}", "SUCCESS")
    return True
