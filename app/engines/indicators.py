def ema(values, period):
    if len(values) < period:
        return None
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e

def ema_series(values, period):
    if len(values) < period:
        return []
    out = []
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    out.extend([None] * (period - 1))
    out.append(e)
    for v in values[period:]:
        e = v * k + e * (1 - k)
        out.append(e)
    return out

def rsi(values, period=14):
    if len(values) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        gains.append(max(d, 0))
        losses.append(abs(min(d, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def macd(values, fast=12, slow=26, signal=9):
    if len(values) < slow + signal:
        return None, None, None
    fast_series = ema_series(values, fast)
    slow_series = ema_series(values, slow)
    line_series = [
        f - s for f, s in zip(fast_series, slow_series)
        if f is not None and s is not None
    ]
    if len(line_series) < signal:
        return None, None, None
    line = line_series[-1]
    sig = ema(line_series, signal)
    hist = line - sig if sig is not None else None
    return line, sig, hist
