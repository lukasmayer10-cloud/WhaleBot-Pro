import json
import threading
import time
import websocket

from app.core.state import STATE, LOCK, log, timeline, notify, now, ensure_state
from app.engines.binance_public import price, candles
from app.engines.strategy_engine import StrategyEngine
from app.engines.trading_engine import PaperTradingEngine
from app.engines.paper_engine_v2 import PaperTradingEngineV2
from app.engines.position_manager import PositionManager
from app.engines.analysis_engine import AnalysisEngine
from app.engines.core_trading_engine import CoreTradingEngine

class MarketEngine:
    def __init__(self, config):
        self.config = config
        self.running = False
        self.threads = []
        self.strategy = StrategyEngine(config)
        self.ai = AnalysisEngine(config)
        self.trader = PaperTradingEngine(config)
        self.paper_v2 = PaperTradingEngineV2(config)
        self.position_manager = PositionManager(config)
        self.core = CoreTradingEngine(config)

    def start(self):
        ensure_state()
        if self.running:
            return
        self.running = True
        with LOCK:
            STATE["system"]["stream"] = "LIVE"
            STATE["system"]["engine"] = "RUNNING"
            STATE["started_at"] = time.time()
        log("Market Engine 3.2 started", "SUCCESS")

        for symbol in self.config["symbols"]:
            for target in [self._price_loop, self._aggtrade_ws, self._orderbook_ws]:
                t = threading.Thread(target=target, args=(symbol,), daemon=True)
                t.start()
                self.threads.append(t)

        t = threading.Thread(target=self._position_loop, daemon=True)
        t.start()
        self.threads.append(t)

    def stop(self):
        self.running = False
        with LOCK:
            STATE["system"]["stream"] = "OFF"
            STATE["system"]["engine"] = "IDLE"
        log("Market Engine stopping", "WARN")

    def _price_loop(self, symbol):
        while self.running:
            try:
                start = time.time()
                p = price(symbol)
                cs = candles(symbol, limit=120)
                latency = int((time.time() - start) * 1000)

                with LOCK:
                    old = STATE["prices"].get(symbol)
                    move = ((p - old) / old) * 100 if old else 0.0
                    STATE["prices"][symbol] = p
                    STATE["candles"][symbol] = cs
                    STATE["price_change"][symbol] = move
                    STATE["last_price_update"][symbol] = now()
                    STATE["system"]["latency_ms"] = latency
                    STATE["system"]["ping_ms"] = latency

                ai = self.ai.analyze_symbol(symbol)

                with LOCK:
                    STATE["ai_decisions"][symbol] = ai
                    STATE["radar"][symbol] = {
                        "score": ai.get("score", 0),
                        "side": ai.get("side", "WATCH"),
                        "reason": ai.get("reason", "AI watch"),
                        "updated": now()
                    }

                if ai.get("score", 0) >= self.config.get("trade_quality_min_prepare", 70):
                    setup = self.core.process_ai(ai)
                    if self.config.get('auto_open_paper_trade', True):
                        self.paper_v2.open_from_setup(setup)

            except Exception as e:
                log(f"Price loop {symbol}: {e}", "WARN")
            time.sleep(5)

    def _aggtrade_ws(self, symbol):
        url = f"wss://fstream.binance.com/ws/{symbol.lower()}@aggTrade"
        while self.running:
            try:
                log(f"Connecting {symbol} whale stream", "INFO")
                ws = websocket.WebSocketApp(url, on_message=lambda ws, msg: self._on_trade(symbol, msg))
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log(f"Whale WS {symbol}: {e}", "WARN")
            time.sleep(4)

    def _orderbook_ws(self, symbol):
        url = f"wss://fstream.binance.com/ws/{symbol.lower()}@depth20@1000ms"
        while self.running:
            try:
                log(f"Connecting {symbol} orderbook stream", "INFO")
                ws = websocket.WebSocketApp(url, on_message=lambda ws, msg: self._on_orderbook(symbol, msg))
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log(f"Orderbook WS {symbol}: {e}", "WARN")
            time.sleep(4)

    def _on_trade(self, symbol, message):
        try:
            d = json.loads(message)
            p = float(d["p"])
            q = float(d["q"])
            value = p * q
            side = "SELL" if d.get("m") else "BUY"

            with LOCK:
                old = STATE["prices"].get(symbol)
                STATE["prices"][symbol] = p
                if old:
                    STATE["price_change"][symbol] = ((p - old) / old) * 100

            if value < self.config["whale_usd_min"]:
                return

            whale = {
                "ts": now(),
                "time_raw": time.time(),
                "symbol": symbol,
                "side": side,
                "price": p,
                "qty": q,
                "value": value,
                "confidence": min(99, int(65 + min(32, value / self.config["whale_usd_min"] * 7)))
            }

            with LOCK:
                STATE["whales"].appendleft(whale)
                STATE["stats"]["whales_seen"] += 1
                STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "whale", "side": side, "price": p, "score": whale["confidence"]})

            timeline("Whale detected", symbol, f"{side} ${value:,.0f}", "WHALE")
            notify("🐋 Whale erkannt", f"{symbol} {side} ${value:,.0f}", "WHALE")

            signal = self.strategy.evaluate_from_whale(symbol, side)
            if signal:
                self.trader.open_position(signal)

        except Exception as e:
            log(f"Trade parse {symbol}: {e}", "WARN")

    def _on_orderbook(self, symbol, message):
        try:
            d = json.loads(message)
            bids = [[float(p), float(q)] for p, q in d.get("b", [])[:20]]
            asks = [[float(p), float(q)] for p, q in d.get("a", [])[:20]]
            walls = []
            for side, rows in [("BUY_WALL", bids), ("SELL_WALL", asks)]:
                for p, q in rows:
                    value = p * q
                    if value >= self.config["orderbook_wall_usd_min"]:
                        walls.append({"ts": now(), "time_raw": time.time(), "symbol": symbol, "side": side, "price": p, "qty": q, "value": value})
            with LOCK:
                STATE["orderbook"][symbol] = {"bids": bids, "asks": asks}
                for wall in walls:
                    STATE["walls"].appendleft(wall)
                    STATE["stats"]["walls_seen"] += 1
        except Exception as e:
            log(f"Orderbook parse {symbol}: {e}", "WARN")

    def _position_loop(self):
        while self.running:
            with LOCK:
                prices = dict(STATE["prices"])
            self.trader.update_positions(prices)
            self.position_manager.manage(prices)
            self.paper_v2.update(prices)
            time.sleep(1)
