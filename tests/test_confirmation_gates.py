"""Optional trend/volume confirmation gates (strategy-creator rules)."""

import pytest

from backtest import engine as bt_engine
from backtest.engine import Backtester
from tests.test_backtest import BASE_TS

def _short_against_uptrend(symbol, date):
    """Downtrend with SELL whales -> SHORT setup. Background volume is high
    (10/min) while the whale candle only carries ~1, so the whale minute is
    BELOW average volume — exactly what the volume gate must reject."""
    p = 60000.0
    for i in range(125):
        # downtrend overall so momentum/macd favor SHORT
        p *= 0.997 if i % 2 == 0 else 1.0015
        # 20 sub-whale trades per minute ($30k each): candle volume 10.0
        for k in range(20):
            yield (BASE_TS + i * 60 + k * 2, p, 0.5, True)
    # whale minute: only ~3.3 volume vs 10.0 average -> below-average volume
    t0 = BASE_TS + 125 * 60
    for j in range(3):
        yield (t0 + 1 + j * 1.6, p, 60000 / p, True)
    yield (t0 + 10, p * 0.98, 0.001, True)

@pytest.fixture
def config(original_config):
    cfg = dict(original_config)
    cfg["min_confidence"] = 50
    return cfg

def test_gates_off_by_default(config):
    assert not config.get("require_trend_confirmation", False)
    assert not config.get("require_volume_confirmation", False)

def test_volume_gate_blocks_thin_signal(monkeypatch, config):
    """The synthetic downtrend produces a SHORT signal normally; with the
    volume gate on, the thin synthetic volume must block it."""
    monkeypatch.setattr(bt_engine, "iter_klines", lambda s, d: iter([]))
    monkeypatch.setattr(bt_engine, "iter_trades", _short_against_uptrend)

    base = Backtester(config, "BTCUSDT").run(["2026-01-01"], progress=False)
    assert base["funnel"]["signals"] == 1  # sanity: passes without the gate

    cfg = dict(config)
    cfg["require_volume_confirmation"] = True
    gated = Backtester(cfg, "BTCUSDT").run(["2026-01-01"], progress=False)
    assert gated["funnel"]["signals"] == 0
    assert gated["funnel"]["reject_reasons"].get("volume", 0) >= 1
