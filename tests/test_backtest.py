"""Backtester test with synthetic data — no network, deterministic.

The price series alternates +0.3% / -0.15% per minute: a steady uptrend with
pullbacks so RSI sits in the entry band (~67), momentum and MACD are positive.
Three $60k BUY whales then form a cluster and must produce exactly one signal.
"""

import json
from pathlib import Path

import pytest

from backtest import engine as bt_engine
from backtest.engine import Backtester

BASE_TS = 1_700_000_000 - (1_700_000_000 % 60)

def _synthetic_trades(symbol, date):
    p = 100.0
    # 125 quiet minutes to build the candle history
    for i in range(125):
        p *= 1.003 if i % 2 == 0 else 0.9985
        yield (BASE_TS + i * 60, p, 0.001, False)
    # whale cluster: 3 BUY trades of ~$60k, spaced past the 1s eval throttle
    t0 = BASE_TS + 125 * 60
    for j in range(3):
        yield (t0 + 1 + j * 1.6, p, 60000 / p, False)
    # price runs up: the open LONG must exit at TP
    yield (t0 + 10, p * 1.02, 0.001, False)
    yield (t0 + 12, p * 1.03, 0.001, False)

@pytest.fixture
def config(original_config):
    cfg = dict(original_config)
    cfg["min_confidence"] = 50  # keep the AI-score gate out of this test's way
    return cfg

def test_backtest_full_flow(monkeypatch, config):
    monkeypatch.setattr(bt_engine, "iter_klines", lambda s, d: iter([]))
    monkeypatch.setattr(bt_engine, "iter_trades", _synthetic_trades)

    bt = Backtester(config, "BTCUSDT")
    report = bt.run(["2026-01-01"], progress=False)

    # funnel: 3 whales -> 3 evaluations -> 1 signal (first two lack cluster size)
    f = report["funnel"]
    assert f["whales_seen"] == 3
    assert f["evaluations"] == 3
    assert f["signals"] == 1
    assert f["reject_reasons"].get("cluster") == 2

    # exactly one trade, closed at TP, profitable after fees
    assert report["trades"] == 1
    assert report["wins"] == 1
    assert report["exit_reasons"] == {"TP": 1}
    trade = report["trade_log"][0]
    assert trade["side"] == "LONG"
    assert trade["pnl"] > 0
    assert report["profit_factor"] > 0

    # gate records carry actual vs required values
    from app.core.state import STATE
    ev = list(STATE["evaluations"])
    rejected = [e for e in ev if e["outcome"] == "REJECTED"]
    assert rejected and rejected[-1]["gates"]["cluster"]["actual"] == 1
    assert rejected[-1]["gates"]["cluster"]["required"] == config["cluster_count"]

def test_backtest_wall_weight_renormalized(config):
    bt = Backtester(config, "BTCUSDT", renormalize_wall=True)
    weights = bt.config["ai_weights"]
    assert "wall" not in weights
    assert abs(sum(weights.values()) - 1.0) < 1e-6

def test_backtest_report_is_json_serializable(monkeypatch, config):
    monkeypatch.setattr(bt_engine, "iter_klines", lambda s, d: iter([]))
    monkeypatch.setattr(bt_engine, "iter_trades", _synthetic_trades)
    report = Backtester(config, "BTCUSDT").run(["2026-01-01"], progress=False)
    json.dumps(report)
