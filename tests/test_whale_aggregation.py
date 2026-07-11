"""Whale detection from raw @trade fills (futures @aggTrade is dead — see
market_engine._stream_names). A split market order must count as ONE whale."""

from collections import deque

from app.core.config import load_config
from app.core.state import STATE, LOCK
from app.engines.market_engine import MarketEngine

def _fresh_engine():
    cfg = load_config()
    cfg["whale_usd_min"] = 50000
    eng = MarketEngine(cfg)
    with LOCK:
        STATE["whales"] = deque(maxlen=800)
        STATE["stats"]["whales_seen"] = 0
    return eng

def _fill(price, qty, ts_ms, sell=False):
    return {"p": str(price), "q": str(qty), "T": ts_ms, "m": sell}

def test_split_order_counts_as_one_whale():
    eng = _fresh_engine()
    # $60k market buy split into 3 fills within 5ms
    for i in range(3):
        eng._on_trade("BTCUSDT", _fill(60000, 0.334, 1_700_000_000_000 + i * 2))
    with LOCK:
        assert STATE["stats"]["whales_seen"] == 1
        whale = STATE["whales"][0]
    assert whale["value"] >= 50000
    assert whale["side"] == "BUY"

def test_small_isolated_trades_are_not_whales():
    eng = _fresh_engine()
    for i in range(5):
        eng._on_trade("BTCUSDT", _fill(60000, 0.1, 1_700_000_000_000 + i * 1000))  # 1s apart
    with LOCK:
        assert STATE["stats"]["whales_seen"] == 0

def test_side_flip_resets_accumulator():
    eng = _fresh_engine()
    eng._on_trade("BTCUSDT", _fill(60000, 0.5, 1_700_000_000_000))               # $30k BUY
    eng._on_trade("BTCUSDT", _fill(60000, 0.5, 1_700_000_000_002, sell=True))    # $30k SELL
    with LOCK:
        assert STATE["stats"]["whales_seen"] == 0

def test_burst_emits_only_once():
    eng = _fresh_engine()
    for i in range(10):  # $300k total in one burst
        eng._on_trade("BTCUSDT", _fill(60000, 0.5, 1_700_000_000_000 + i * 3))
    with LOCK:
        assert STATE["stats"]["whales_seen"] == 1
