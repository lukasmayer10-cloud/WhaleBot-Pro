import time

from flask import Flask, render_template, jsonify, request

from app.core.config import load_config, save_config
from app.core.state import STATE, LOCK, log, ensure_state
from app.core import persistence
from app.engines.market_engine import MarketEngine
from app.engines.trading_engine import PaperTradingEngine
from app.engines.paper_engine_v2 import PaperTradingEngineV2
from app.engines.demo_engine import inject_demo_market
from app.engines.exchange_layer import BinanceFuturesTestnet
from app.engines.orderflow_engine import OrderflowEngine
from app.engines.analytics_engine import AnalyticsEngine

CONFIG = load_config()
market_engine = MarketEngine(CONFIG)
paper_trader = PaperTradingEngine(CONFIG)
paper_v2 = PaperTradingEngineV2(CONFIG)
exchange = BinanceFuturesTestnet(CONFIG)
orderflow = OrderflowEngine(CONFIG)
analytics = AnalyticsEngine()

# key -> (cast, min, max); values outside the range are rejected
SETTINGS_SCHEMA = {
    "whale_usd_min": (float, 1000.0, 1e9),
    "cluster_count": (int, 1, 100),
    "cluster_window_sec": (int, 10, 3600),
    "min_confidence": (int, 0, 100),
    "stop_loss_pct": (float, 0.05, 50.0),
    "take_profit_pct": (float, 0.05, 100.0),
    "position_size_usd": (float, 1.0, 1e7),
    "max_open_positions": (int, 1, 50),
    "orderbook_wall_usd_min": (float, 1000.0, 1e9),
}

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    ensure_state()
    persistence.init_db()
    persistence.restore_state()

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/healthz")
    def healthz():
        health = market_engine.health()
        with LOCK:
            health["balance"] = STATE["balance"]
            health["open_positions"] = len(STATE["positions"])
        health["db"] = str(persistence.db_path())
        return jsonify(health), (200 if health["healthy"] else 503)

    @app.route("/api/start", methods=["POST"])
    def start():
        ensure_state()
        with LOCK:
            if STATE["running"]:
                return jsonify({"ok": True})
            STATE["running"] = True
        market_engine.start()
        return jsonify({"ok": True})

    @app.route("/api/stop", methods=["POST"])
    def stop():
        with LOCK:
            STATE["running"] = False
        market_engine.stop()
        return jsonify({"ok": True})

    @app.route("/api/demo-market", methods=["POST"])
    def demo_market():
        ensure_state()
        inject_demo_market(CONFIG)
        return jsonify({"ok": True})

    @app.route("/api/settings", methods=["POST"])
    def settings():
        data = request.get_json(silent=True) or {}
        rejected = []
        for k, (cast, lo, hi) in SETTINGS_SCHEMA.items():
            if k not in data:
                continue
            try:
                v = cast(float(data[k]))
            except (TypeError, ValueError):
                rejected.append(k)
                continue
            if lo <= v <= hi:
                CONFIG[k] = v
            else:
                rejected.append(k)
        save_config(CONFIG)
        log("Settings updated" + (f" (rejected: {', '.join(rejected)})" if rejected else ""), "SUCCESS")
        return jsonify({"ok": True, "config": CONFIG, "rejected": rejected})

    @app.route("/api/close/<int:pos_id>", methods=["POST"])
    def close(pos_id):
        with LOCK:
            pos = next((p for p in STATE["positions"] if p.get("id") == pos_id), None)
            engine = pos.get("engine", "v1") if pos else None
        if engine == "v1":
            paper_trader.close_position(pos_id, "MANUAL")
        elif engine == "v2":
            paper_v2.close(pos_id, "MANUAL")
        return jsonify({"ok": pos is not None})

    @app.route("/api/core")
    def core():
        with LOCK:
            setups = list(STATE["trade_setups"])[:50]
            decisions = dict(STATE["core_decisions"])
        return jsonify({
            "setups": setups,
            "decisions": decisions,
            "enabled": CONFIG.get("core_engine_enabled", True),
            "mode": CONFIG.get("execution_mode", "paper")
        })

    @app.route("/api/platform")
    def platform():
        symbol = CONFIG.get("active_chart_symbol", "BTCUSDT")
        return jsonify({
            "exchange": exchange.status(),
            "orderflow": orderflow.snapshot(symbol),
            "analytics": analytics.summary(),
            "platform": {
                "version": "6.1 POSITION MANAGER",
                "execution_mode": CONFIG.get("execution_mode", "paper"),
                "live_enabled": CONFIG.get("allow_live_trading", False),
                "testnet_enabled": CONFIG.get("allow_testnet_trading", False)
            }
        })

    @app.route("/api/state")
    def state():
        ensure_state()
        chart_symbol = request.args.get("chart") or CONFIG.get("active_chart_symbol", "BTCUSDT")
        health = market_engine.health()
        # copy everything under the lock, serialize outside it so the JSON
        # encoder never blocks the websocket/engine threads
        with LOCK:
            wins, losses = STATE["wins"], STATE["losses"]
            eval_cutoff = time.time() - 60
            health["evals_last_min"] = sum(
                1 for e in STATE["evaluations"] if e.get("time_raw", 0) >= eval_cutoff
            )
            payload = {
                "version": STATE.get("version", "6.1 POSITION MANAGER"),
                "running": STATE["running"],
                "mode": CONFIG.get("mode", "paper"),
                "balance": STATE["balance"],
                "equity": STATE["equity"],
                "daily_pnl": STATE["daily_pnl"],
                "wins": wins,
                "losses": losses,
                "winrate": (wins / (wins + losses) * 100) if wins + losses else 0,
                "prices": dict(STATE["prices"]),
                "price_change": dict(STATE["price_change"]),
                "last_price_update": dict(STATE["last_price_update"]),
                # only the charted symbol: full candle sets for every symbol
                # made this payload ~6x bigger and the UI ignores the rest
                "candles": {chart_symbol: list(STATE["candles"].get(chart_symbol, []))},
                "orderbook": dict(STATE["orderbook"]),
                "walls": list(STATE["walls"])[:120],
                "whales": list(STATE["whales"])[:120],
                "clusters": list(STATE["clusters"])[:80],
                "signals": list(STATE["signals"])[:80],
                "evaluations": list(STATE["evaluations"])[:30],
                "trade_setups": list(STATE["trade_setups"])[:80],
                "core_decisions": dict(STATE["core_decisions"]),
                "setup_history": dict(STATE.get("setup_history", {})),
                "positions": list(STATE["positions"]),
                "closed": list(STATE["closed"])[:80],
                "trade_journal": list(STATE.get("trade_journal", []))[:120],
                "trade_lifecycle": dict(STATE.get("trade_lifecycle", {})),
                "timeline": list(STATE["timeline"])[:120],
                "logs": list(STATE["logs"])[:160],
                "radar": dict(STATE["radar"]),
                "ai_decisions": dict(STATE["ai_decisions"]),
                "notifications": list(STATE["notifications"])[:20],
                "chart_markers": list(STATE["chart_markers"])[:120],
                "equity_curve": list(STATE["equity_curve"])[-180:],
                "performance": dict(STATE["performance"]),
                "system": dict(STATE["system"]),
                "stats": dict(STATE["stats"]),
                "health": health,
                "config": CONFIG
            }
        return jsonify(payload)

    return app
