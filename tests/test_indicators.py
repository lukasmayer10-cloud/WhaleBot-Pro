import random

from app.engines.indicators import ema, ema_series, macd, rsi

def _series(n=150, seed=7):
    random.seed(seed)
    vals = [100.0]
    for _ in range(n):
        vals.append(vals[-1] * (1 + random.uniform(-0.01, 0.01)))
    return vals

def _reference_macd(values):
    """The original O(n^2) implementation, kept as the oracle."""
    if len(values) < 35:
        return None, None, None
    line = ema(values, 12) - ema(values, 26)
    series = []
    for i in range(26, len(values) + 1):
        a = ema(values[:i], 12)
        b = ema(values[:i], 26)
        if a is not None and b is not None:
            series.append(a - b)
    sig = ema(series, 9) if len(series) >= 9 else None
    hist = line - sig if sig is not None else None
    return line, sig, hist

def test_macd_matches_reference():
    for seed in [1, 7, 42]:
        vals = _series(seed=seed)
        old = _reference_macd(vals)
        new = macd(vals)
        assert all(abs(a - b) < 1e-9 for a, b in zip(old, new))

def test_macd_short_input():
    assert macd([1.0] * 10) == (None, None, None)
    assert macd([1.0] * 34) == (None, None, None)

def test_ema_series_alignment():
    vals = _series()
    series = ema_series(vals, 20)
    assert len(series) == len(vals)
    assert series[18] is None
    assert abs(series[-1] - ema(vals, 20)) < 1e-9

def test_rsi_bounds():
    vals = _series()
    v = rsi(vals)
    assert 0 <= v <= 100
    assert rsi([1.0] * 5) is None
    assert rsi(list(range(1, 30))) == 100  # only gains
