"""Optional Telegram alerts.

Enabled when TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set (e.g. in .env).
Sends from a single daemon thread with a bounded queue so a slow/unreachable
Telegram API can never block a trading thread. TRADE/WHALE spam is filtered:
only the levels in TELEGRAM_ALERT_LEVELS (default: TRADE,ERROR,WARN) are sent.
"""

import os
import queue
import threading

import requests

_QUEUE = queue.Queue(maxsize=100)
_started = False
_start_lock = threading.Lock()

def _enabled():
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"))

def _levels():
    raw = os.getenv("TELEGRAM_ALERT_LEVELS", "TRADE,ERROR,WARN")
    return {x.strip().upper() for x in raw.split(",") if x.strip()}

def _worker():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    session = requests.Session()
    while True:
        text = _QUEUE.get()
        try:
            session.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
        except Exception:
            pass  # alerts are best-effort by design

def send_alert(title, body, level="INFO"):
    if not _enabled() or level.upper() not in _levels():
        return
    global _started
    with _start_lock:
        if not _started:
            threading.Thread(target=_worker, daemon=True, name="telegram-alerts").start()
            _started = True
    try:
        _QUEUE.put_nowait(f"{title}\n{body}")
    except queue.Full:
        pass
