import requests

BASE = "https://fapi.binance.com"

def price(symbol):
    r = requests.get(f"{BASE}/fapi/v1/ticker/price", params={"symbol": symbol.upper()}, timeout=6)
    r.raise_for_status()
    return float(r.json()["price"])

def candles(symbol, interval="1m", limit=120):
    r = requests.get(
        f"{BASE}/fapi/v1/klines",
        params={"symbol": symbol.upper(), "interval": interval, "limit": limit},
        timeout=8
    )
    r.raise_for_status()
    return [{
        "t": int(k[0]),
        "o": float(k[1]),
        "h": float(k[2]),
        "l": float(k[3]),
        "c": float(k[4]),
        "v": float(k[5])
    } for k in r.json()]
