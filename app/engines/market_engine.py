import json
import random
import threading
import time
import websocket

from app.core.state import STATE, LOCK, log, timeline, notify, now, ensure_state
from app.core import persistence
from app.engines.binance_public import price, candles
from app.engines.strategy_engine import StrategyEngine
from app.engines.trading_engine import PaperTradingEngine
from app.engines.paper_engine_v2 import PaperTradingEngineV2
from app.engines.position_manager import PositionManager
from app.engines.analysis_engine import AnalysisEngine
from app.engines.core_trading_engine import CoreTradingEngine

WS_BASE = "wss://fstream.binance.com/stream"
STALE_WS_SEC = 90       # no websocket message for this long -> force reconnect
STALE_PRICE_SEC = 60    # /healthz reports degraded beyond this

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
        self._start_lock = threading.Lock()
        self._ws = None
        self._ws_lock = threading.Lock()
        self._last_ws_msg = 0.0
        self._ws_connects = 0
        self._last_eval = {}
        self._price_ref = {}
        self._last_price_raw = {}
        self._trade_acc = {}

    # ------------------------------------------------------------- lifecycle

    def start(self):
        ensure_state()
        with self._start_lock:
            if self.running:
                return
            self.running = True
            self.threads = []
            self._last_ws_msg = 0.0

            with LOCK:
                STATE["system"]["stream"] = "LIVE"
                STATE["system"]["engine"] = "RUNNING"
                STATE["started_at"] = time.time()
            log("Market Engine started", "SUCCESS")

            for symbol in self.config["symbols"]:
                t = threading.Thread(target=self._price_loop, args=(symbol,), daemon=True, name=f"price-{symbol}")
                t.start()
                self.threads.append(t)

            for target, name in [(self._combined_ws_loop, "binance-ws"),
                                 (self._position_loop, "positions"),
                                 (self._watchdog_loop, "watchdog")]:
                t = threading.Thread(target=target, daemon=True, name=name)
                t.start()
                self.threads.append(t)

    def stop(self):
        with self._start_lock:
            self.running = False
            self._close_ws()
            with LOCK:
                STATE["system"]["stream"] = "OFF"
                STATE["system"]["engine"] = "IDLE"
            log("Market Engine stopping", "WARN")

    def health(self):
        """Stream/price freshness for /healthz."""
        now_raw = time.time()
        with LOCK:
            running = self.running
            prices = dict(self._last_price_raw)
        price_ages = {s: round(now_raw - t, 1) for s, t in prices.items()}
        ws_age = round(now_raw - self._last_ws_msg, 1) if self._last_ws_msg else None
        stale = [s for s, age in price_ages.items() if age > STALE_PRICE_SEC]
        healthy = (not running) or (bool(price_ages) and not stale)
        return {
            "running": running,
            "healthy": healthy,
            "ws_last_msg_age_sec": ws_age,
            "ws_reconnects": self._ws_connects,
            "price_age_sec": price_ages,
            "stale_symbols": stale,
            "threads_alive": sum(1 for t in self.threads if t.is_alive()),
        }

    def _sleep(self, seconds):
        """Sleep in small slices so stop() takes effect quickly."""
        end = time.time() + seconds
        while self.running and time.time() < end:
            time.sleep(min(0.5, max(0.0, end - time.time())))

    # ------------------------------------------------------------ websockets

    def _stream_names(self):
        names = []
        for symbol in self.config["symbols"]:
            s = symbol.lower()
            # NOTE: on the futures endpoint @aggTrade (and @1000ms depth)
            # silently deliver nothing (verified empirically) — @trade and
            # @500ms depth are the streams that actually flow. Raw trades are
            # re-aggregated in _on_trade so whale detection keeps aggTrade
            # semantics.
            names.append(f"{s}@trade")
            names.append(f"{s}@depth20@500ms")
        return names

    def _close_ws(self):
        with self._ws_lock:
            ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass

    def _combined_ws_loop(self):
        """One connection for every stream, with exponential backoff + jitter."""
        url = f"{WS_BASE}?streams={'/'.join(self._stream_names())}"
        backoff = 1.0
        while self.running:
            connected_at = time.time()
            try:
                log(f"Connecting Binance combined stream ({len(self._stream_names())} streams)", "INFO")
                ws = websocket.WebSocketApp(url, on_message=self._on_combined_message)
                with self._ws_lock:
                    if not self.running:
                        return
                    self._ws = ws
                self._ws_connects += 1
                ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                log(f"Combined WS: {e}", "WARN")
            finally:
                with self._ws_lock:
                    if self._ws is not None:
                        self._ws = None
            if not self.running:
                return
            # stable for a while -> treat the drop as fresh, reset backoff
            if time.time() - connected_at > 30:
                backoff = 1.0
            delay = backoff + random.uniform(0, backoff / 2)
            log(f"Stream reconnect in {delay:.1f}s", "WARN")
            self._sleep(delay)
            backoff = min(backoff * 2, 60.0)

    def _on_combined_message(self, ws, message):
        try:
            wrapper = json.loads(message)
            stream = wrapper.get("stream", "")
            data = wrapper.get("data", {})
            self._last_ws_msg = time.time()
            symbol, _, kind = stream.partition("@")
            symbol = symbol.upper()
            if kind.startswith(("trade", "aggTrade")):
                self._on_trade(symbol, data)
            elif kind.startswith("depth"):
                self._on_orderbook(symbol, data)
        except Exception as e:
            log(f"WS message parse: {e}", "WARN")

    def _watchdog_loop(self):
        """Force a reconnect when the combined stream goes silent."""
        while self.running:
            self._sleep(10)
            if not self.running:
                return
            last = self._last_ws_msg
            if last and time.time() - last > STALE_WS_SEC:
                log(f"Stream silent for {int(time.time() - last)}s, forcing reconnect", "WARN")
                notify("⚠️ Stream watchdog", "Binance stream stale, reconnecting", "WARN")
                self._last_ws_msg = time.time()  # give the reconnect time to land
                self._close_ws()

    # ------------------------------------------------------------ data loops

    def _price_loop(self, symbol):
        candle_refresh = float(self.config.get("candle_refresh_sec", 20))
        last_candle_fetch = 0.0
        while self.running:
            try:
                start = time.time()
                p = price(symbol)
                if start - last_candle_fetch >= candle_refresh:
                    cs = candles(symbol, limit=120)
                    last_candle_fetch = start
                else:
                    cs = None
                latency = int((time.time() - start) * 1000)

                with LOCK:
                    if cs is None:
                        cs = STATE["candles"].get(symbol, [])
                    else:
                        STATE["candles"][symbol] = cs
                    if cs:
                        self._price_ref[symbol] = cs[0]["c"]
                    ref = self._price_ref.get(symbol)
                    STATE["prices"][symbol] = p
                    STATE["price_change"][symbol] = ((p - ref) / ref) * 100 if ref else 0.0
                    STATE["last_price_update"][symbol] = now()
                    STATE["system"]["latency_ms"] = latency
                    STATE["system"]["ping_ms"] = latency
                self._last_price_raw[symbol] = time.time()

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
            self._sleep(5)

    def _on_trade(self, symbol, d):
        try:
            p = float(d["p"])
            q = float(d["q"])
            side = "SELL" if d.get("m") else "BUY"
            t = float(d.get("T") or d.get("E") or time.time() * 1000) / 1000

            ref = self._price_ref.get(symbol)
            with LOCK:
                STATE["prices"][symbol] = p
                if ref:
                    STATE["price_change"][symbol] = ((p - ref) / ref) * 100
            self._last_price_raw[symbol] = time.time()

            # re-aggregate raw fills: one large market order arrives as many
            # small trades within a few ms — sum consecutive same-side fills
            # so whale detection keeps aggTrade semantics
            acc = self._trade_acc.get(symbol)
            if acc and acc["side"] == side and t - acc["last_t"] <= 0.1:
                acc["value"] += p * q
                acc["qty"] += q
                acc["price"] = p
                acc["last_t"] = t
            else:
                acc = {"side": side, "value": p * q, "qty": q, "price": p, "last_t": t, "emitted": False}
                self._trade_acc[symbol] = acc

            if acc["value"] < self.config["whale_usd_min"] or acc["emitted"]:
                return
            acc["emitted"] = True
            value = acc["value"]

            whale = {
                "ts": now(),
                "time_raw": time.time(),
                "symbol": symbol,
                "side": side,
                "price": p,
                "qty": acc["qty"],
                "value": value,
                "confidence": min(99, int(65 + min(32, value / self.config["whale_usd_min"] * 7)))
            }

            with LOCK:
                STATE["whales"].appendleft(whale)
                STATE["stats"]["whales_seen"] += 1
                STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "whale", "side": side, "price": p, "score": whale["confidence"]})

            timeline("Whale detected", symbol, f"{side} ${value:,.0f}", "WHALE")
            notify("🐋 Whale erkannt", f"{symbol} {side} ${value:,.0f}", "WHALE")

            # throttle full strategy evaluation to once per second per symbol
            # so whale bursts don't spin the CPU; whales above are always recorded
            last = self._last_eval.get(symbol, 0.0)
            if time.time() - last >= 1.0:
                self._last_eval[symbol] = time.time()
                signal = self.strategy.evaluate_from_whale(symbol, side)
                if signal:
                    self.trader.open_position(signal)

        except Exception as e:
            log(f"Trade parse {symbol}: {e}", "WARN")

    def _on_orderbook(self, symbol, d):
        try:
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
        last_curve = 0.0
        last_snapshot = 0.0
        while self.running:
            try:
                with LOCK:
                    prices = dict(STATE["prices"])
                self.trader.update_positions(prices)
                self.position_manager.manage(prices)
                self.paper_v2.update(prices)

                now_raw = time.time()
                if now_raw - last_curve >= 5.0:
                    last_curve = now_raw
                    with LOCK:
                        has_positions = bool(STATE["positions"])
                        equity = STATE["equity"]
                        if has_positions:
                            STATE["equity_curve"].append({"ts": now(), "equity": equity})
                    if has_positions:
                        persistence.save_equity_point(now_raw, equity)
                if now_raw - last_snapshot >= 5.0:
                    last_snapshot = now_raw
                    persistence.save_open_positions()
            except Exception as e:
                log(f"Position loop: {e}", "WARN")
            self._sleep(1)
