from flask import Flask, render_template, jsonify, request

from app.core.config import load_config, save_config
from app.core.state import STATE, LOCK, log, ensure_state, ensure_state, ensure_state
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

def create_app():
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    @app.route("/")
    def index():
        return render_template("index.html")

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
        signal = inject_demo_market(CONFIG)
        paper_trader.open_position(signal)
        return jsonify({"ok": True})

    @app.route("/api/settings", methods=["POST"])
    def settings():
        global CONFIG
        data = request.json or {}
        allowed = [
            "whale_usd_min", "cluster_count", "cluster_window_sec",
            "min_confidence", "stop_loss_pct", "take_profit_pct",
            "position_size_usd", "max_open_positions", "orderbook_wall_usd_min"
        ]
        for k in allowed:
            if k in data:
                try:
                    CONFIG[k] = int(data[k]) if k in ["cluster_count", "cluster_window_sec", "min_confidence", "max_open_positions"] else float(data[k])
                except Exception:
                    pass
        save_config(CONFIG)
        market_engine.config = CONFIG
        paper_trader.config = CONFIG
        log("Settings updated", "SUCCESS")
        return jsonify({"ok": True, "config": CONFIG})

    @app.route("/api/close/<int:pos_id>", methods=["POST"])
    def close(pos_id):
        paper_v2.close(pos_id, "MANUAL") or paper_trader.close_position(pos_id, "MANUAL")
        return jsonify({"ok": True})



    @app.route("/api/core")
    def core():
        with LOCK:
            return jsonify({
                "setups": list(STATE["trade_setups"])[:50],
                "decisions": STATE["core_decisions"],
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
        with LOCK:
            wins, losses = STATE["wins"], STATE["losses"]
            winrate = (wins / (wins + losses) * 100) if wins + losses else 0
            return jsonify({
                "version": STATE.get("version", "6.1 POSITION MANAGER"),
                "running": STATE["running"],
                "mode": CONFIG.get("mode", "paper"),
                "balance": STATE["balance"],
                "equity": STATE["equity"],
                "daily_pnl": STATE["daily_pnl"],
                "wins": wins,
                "losses": losses,
                "winrate": winrate,
                "prices": STATE["prices"],
                "price_change": STATE["price_change"],
                "last_price_update": STATE["last_price_update"],
                "candles": STATE["candles"],
                "orderbook": STATE["orderbook"],
                "walls": list(STATE["walls"])[:120],
                "whales": list(STATE["whales"])[:120],
                "clusters": list(STATE["clusters"])[:80],
                "signals": list(STATE["signals"])[:80],
                "trade_setups": list(STATE["trade_setups"])[:80],
                "core_decisions": STATE["core_decisions"],
                "setup_history": STATE.get("setup_history", {}),
                "positions": STATE["positions"],
                "closed": list(STATE["closed"])[:80],
                "trade_journal": list(STATE.get("trade_journal", []))[:120],
                "trade_lifecycle": STATE.get("trade_lifecycle", {}),
                "timeline": list(STATE["timeline"])[:120],
                "logs": list(STATE["logs"])[:160],
                "radar": STATE["radar"],
                "ai_decisions": STATE["ai_decisions"],
                "notifications": list(STATE["notifications"])[:20],
                "chart_markers": list(STATE["chart_markers"])[:120],
                "equity_curve": list(STATE["equity_curve"])[-180:],
                "performance": STATE["performance"],
                "system": STATE["system"],
                "stats": STATE["stats"],
                "config": CONFIG
            })

    return app
