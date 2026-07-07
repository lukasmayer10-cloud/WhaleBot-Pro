import random
import time
from app.core.state import STATE, LOCK, timeline, notify, now
from app.engines.strategy_engine import demo_signal
from app.engines.core_trading_engine import CoreTradingEngine
from app.engines.paper_engine_v2 import PaperTradingEngineV2

def inject_demo_market(config):
    symbol = "BTCUSDT"
    base = 65000 + random.random() * 700
    t = time.time()

    candles = []
    last = base - 300
    for i in range(120):
        o = last
        c = base - 300 + i * 3.8 + ((i % 7) - 3) * 4
        h = max(o, c) + 12 + (i % 3) * 4
        l = min(o, c) - 12 - (i % 4) * 3
        last = c
        candles.append({
            "t": int((t - (120 - i) * 60) * 1000),
            "o": o,
            "h": h,
            "l": l,
            "c": c,
            "v": 100 + i * 1.8
        })

    price = candles[-1]["c"]
    demo_whales = [420000, 310000, 540000, 290000]

    ai = {
        "symbol": symbol,
        "side": "LONG",
        "score": 94,
        "status": "TRADE_READY",
        "scores": {
            "whale": 95,
            "cluster": 96,
            "wall": 90,
            "momentum": 88,
            "trend": 92,
            "rsi": 84,
            "macd": 86,
            "volume": 78,
            "volatility": 80
        },
        "metrics": {
            "whale_value": sum(demo_whales),
            "whale_count": 4,
            "wall_value": 1200000,
            "momentum_pct": 0.62,
            "trend_pct": 0.24,
            "rsi": 58,
            "macd_hist": 1.25,
            "volatility": 0.12
        },
        "reason": "AI 94% | demo whales 4 | wall $1,200,000"
    }

    with LOCK:
        STATE["balance"] = STATE.get("balance") or 1000.0
        STATE["equity"] = STATE.get("equity") or STATE["balance"]
        STATE["prices"][symbol] = price
        STATE["price_change"][symbol] = 0.62
        STATE["candles"][symbol] = candles
        STATE["last_price_update"][symbol] = now()

        for i, value in enumerate(demo_whales):
            STATE["whales"].appendleft({
                "ts": now(),
                "time_raw": t - i * 7,
                "symbol": symbol,
                "side": "BUY",
                "price": price,
                "qty": value / price,
                "value": value,
                "confidence": 91 + i
            })
            STATE["stats"]["whales_seen"] += 1

        STATE["walls"].appendleft({
            "ts": now(),
            "time_raw": t,
            "symbol": symbol,
            "side": "BUY_WALL",
            "price": price * 0.997,
            "qty": 1200000 / price,
            "value": 1200000
        })
        STATE["walls"].appendleft({
            "ts": now(),
            "time_raw": t,
            "symbol": symbol,
            "side": "SELL_WALL",
            "price": price * 1.006,
            "qty": 820000 / price,
            "value": 820000
        })
        STATE["stats"]["walls_seen"] += 2

        STATE["clusters"].appendleft({
            "ts": now(),
            "symbol": symbol,
            "side": "BUY",
            "count": 4,
            "value": sum(demo_whales),
            "wall_value": 1200000,
            "score": 94,
            "risk": "LOW",
            "detail_scores": ai["scores"],
            "stars": {
                "whale": "★★★★★",
                "cluster": "★★★★★",
                "wall": "★★★★★",
                "momentum": "★★★★★",
                "trend": "★★★★★",
                "rsi": "★★★★★",
                "macd": "★★★★★"
            }
        })

        STATE["radar"][symbol] = {"score": 94, "side": "LONG", "reason": "demo cluster", "updated": now()}
        STATE["ai_decisions"][symbol] = ai
        STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "whale", "side": "BUY", "price": candles[-8]["c"], "score": 91})
        STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "cluster", "side": "BUY", "price": candles[-5]["c"], "score": 94})
        STATE["equity_curve"].append({"ts": now(), "equity": STATE["equity"]})

    timeline("Demo market", symbol, "4 BUY whales + buy wall injected", "SUCCESS")
    notify("🐋 Demo Market", "BTCUSDT cluster injected", "SUCCESS")

    core = CoreTradingEngine(config)
    setup = core.process_ai(ai)
    paper_v2 = PaperTradingEngineV2(config)
    paper_v2.open_from_setup(setup)

    signal = demo_signal(config, price)
    signal["detail_scores"] = ai["scores"]
    with LOCK:
        STATE["signals"].appendleft(signal)
        STATE["stats"]["signals"] += 1

    return signal
