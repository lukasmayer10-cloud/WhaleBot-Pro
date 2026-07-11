"""Historical data from Binance's public archive (data.binance.vision).

Daily zip files, cached locally under data/backtest/. No API key needed.
aggTrades files are large (BTC ~100MB+/day compressed) — everything streams,
nothing is loaded fully into memory."""

import csv
import io
import os
import zipfile
from pathlib import Path

import requests

BASE = "https://data.binance.vision/data/futures/um/daily"
_ROOT = Path(__file__).resolve().parents[1]

def cache_dir():
    return Path(os.getenv("WHALEBOT_DATA_DIR", _ROOT / "data")) / "backtest"

def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with requests.get(url, stream=True, timeout=60) as r:
        if r.status_code == 404:
            raise FileNotFoundError(f"No archive at {url} (date too recent or symbol wrong?)")
        r.raise_for_status()
        size = int(r.headers.get("content-length", 0))
        done = 0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if size:
                    print(f"\r  {dest.name}: {done / 1e6:.0f}/{size / 1e6:.0f} MB", end="", flush=True)
        print()
    tmp.replace(dest)

def _fetch(url, name):
    dest = cache_dir() / name
    if not dest.exists():
        print(f"  downloading {name} ...")
        _download(url, dest)
    return dest

def _rows(zip_path):
    """Stream CSV rows from a zip, skipping a header row if present."""
    with zipfile.ZipFile(zip_path) as z:
        inner = z.namelist()[0]
        with z.open(inner) as f:
            reader = csv.reader(io.TextIOWrapper(f, "utf-8"))
            for row in reader:
                if not row:
                    continue
                if not row[0].replace(".", "").isdigit():
                    continue  # header
                yield row

def _to_seconds(ts):
    """Binance archives mix ms and us timestamps; normalize to seconds."""
    ts = float(ts)
    if ts > 1e14:
        return ts / 1e6
    if ts > 1e11:
        return ts / 1e3
    return ts

def iter_klines(symbol, date):
    """Yield completed 1m candles: dicts with t (sec), o, h, l, c, v."""
    name = f"{symbol}-1m-{date}.zip"
    path = _fetch(f"{BASE}/klines/{symbol}/1m/{name}", name)
    for row in _rows(path):
        yield {
            "t": _to_seconds(row[0]),
            "o": float(row[1]),
            "h": float(row[2]),
            "l": float(row[3]),
            "c": float(row[4]),
            "v": float(row[5]),
        }

def iter_trades(symbol, date):
    """Yield every aggTrade: (ts_sec, price, qty, is_sell)."""
    name = f"{symbol}-aggTrades-{date}.zip"
    path = _fetch(f"{BASE}/aggTrades/{symbol}/{name}", name)
    for row in _rows(path):
        # agg_trade_id, price, quantity, first_id, last_id, transact_time, is_buyer_maker
        yield (
            _to_seconds(row[5]),
            float(row[1]),
            float(row[2]),
            row[6].strip().lower() == "true",
        )
