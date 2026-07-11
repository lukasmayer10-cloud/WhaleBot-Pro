import requests
from requests.adapters import HTTPAdapter, Retry

BASE = "https://fapi.binance.com"

# one pooled session: keep-alive avoids a new TLS handshake per call
# (the price loop polls every symbol every few seconds)
SESSION = requests.Session()
_adapter = HTTPAdapter(
    pool_connections=4,
    pool_maxsize=16,
    max_retries=Retry(total=2, backoff_factor=0.3, status_forcelist=[429, 500, 502, 503, 504]),
)
SESSION.mount("https://", _adapter)

def price(symbol):
    r = SESSION.get(f"{BASE}/fapi/v1/ticker/price", params={"symbol": symbol.upper()}, timeout=6)
    r.raise_for_status()
    return float(r.json()["price"])

def candles(symbol, interval="1m", limit=120):
    r = SESSION.get(
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
