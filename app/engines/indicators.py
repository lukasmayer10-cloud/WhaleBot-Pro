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

def macd(values):
    if len(values) < 35:
        return None, None, None
    e12 = ema(values, 12)
    e26 = ema(values, 26)
    if e12 is None or e26 is None:
        return None, None, None
    line = e12 - e26
    series = []
    for i in range(26, len(values) + 1):
        a = ema(values[:i], 12)
        b = ema(values[:i], 26)
        if a is not None and b is not None:
            series.append(a - b)
    sig = ema(series, 9) if len(series) >= 9 else None
    hist = line - sig if sig is not None else None
    return line, sig, hist
