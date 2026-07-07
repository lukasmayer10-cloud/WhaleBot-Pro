import time
from app.core.state import STATE, LOCK, timeline, notify, now
from app.engines.indicators import rsi, macd
from app.engines.analysis_engine import AnalysisEngine

def stars(ok):
    return "★★★★★" if ok else "★★☆☆☆"

def risk_label(score):
    if score >= 90:
        return "LOW"
    if score >= 78:
        return "MEDIUM"
    return "HIGH"

class StrategyEngine:
    def __init__(self, config):
        self.config = config
        self.ai = AnalysisEngine(config)

    def _recent_whales(self, symbol, side):
        cutoff = time.time() - self.config["cluster_window_sec"]
        with LOCK:
            whales = list(STATE["whales"])
        return [w for w in whales if w["symbol"] == symbol and w["side"] == side and w["time_raw"] >= cutoff]

    def _wall_confirmed(self, symbol, whale_side):
        want = "BUY_WALL" if whale_side == "BUY" else "SELL_WALL"
        cutoff = time.time() - 180
        with LOCK:
            walls = list(STATE["walls"])
        recent = [w for w in walls if w["symbol"] == symbol and w["side"] == want and w.get("time_raw", 0) >= cutoff]
        return len(recent) > 0, sum(w["value"] for w in recent)

    def evaluate_from_whale(self, symbol, whale_side):
        cluster = self._recent_whales(symbol, whale_side)
        cluster_value = sum(w["value"] for w in cluster)
        cluster_ok = len(cluster) >= self.config["cluster_count"]

        with LOCK:
            candles = STATE["candles"].get(symbol, [])
            price = STATE["prices"].get(symbol)

        if not candles or len(candles) < 35 or not price:
            return None

        closes = [c["c"] for c in candles]
        momentum = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
        rv = rsi(closes)
        _, _, hist = macd(closes)
        if rv is None or hist is None:
            return None

        if whale_side == "BUY":
            side = "LONG"
            momentum_ok = momentum >= self.config["min_momentum_pct"]
            rsi_ok = 38 <= rv <= 78
            macd_ok = hist > 0
        else:
            side = "SHORT"
            momentum_ok = momentum <= -self.config["min_momentum_pct"]
            rsi_ok = 22 <= rv <= 62
            macd_ok = hist < 0

        wall_ok, wall_value = self._wall_confirmed(symbol, whale_side)

        # Version 3.1 AI Decision Engine
        ai = self.ai.analyze_symbol(symbol, side)
        score = ai.get("score", 0)
        detail_scores = ai.get("scores", {})
        ai_reason = ai.get("reason", "")

        checks = {
            "whale": cluster_ok,
            "cluster": cluster_ok,
            "wall": wall_ok,
            "momentum": momentum_ok,
            "rsi": rsi_ok,
            "macd": macd_ok
        }
        star_map = {k: stars(v) for k, v in checks.items()}

        with LOCK:
            STATE["clusters"].appendleft({
                "ts": now(),
                "symbol": symbol,
                "side": whale_side,
                "count": len(cluster),
                "value": cluster_value,
                "wall_value": wall_value,
                "score": score,
                "risk": risk_label(score),
                "checks": checks,
                "stars": star_map,
                "detail_scores": detail_scores
            })
            STATE["stats"]["clusters"] += 1
            STATE["radar"][symbol] = {"score": score, "side": side, "reason": f"{len(cluster)} whales / {whale_side}", "updated": now()}
            STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "cluster", "side": whale_side, "price": price, "score": score})
            STATE["ai_decisions"][symbol] = ai

        timeline("Cluster check", symbol, f"{len(cluster)} whales | ${cluster_value:,.0f} | {score}%", "WHALE")

        if not (cluster_ok and momentum_ok and rsi_ok and macd_ok):
            with LOCK:
                STATE["stats"]["ignored"] += 1
            return None

        if score < self.config["min_confidence"]:
            with LOCK:
                STATE["stats"]["blocked_confidence"] += 1
            timeline("Signal blocked", symbol, f"{score}% below min {self.config['min_confidence']}%", "WARN")
            return None

        signal = {
            "ts": now(),
            "symbol": symbol,
            "side": side,
            "price": price,
            "score": score,
            "risk": risk_label(score),
            "reason": f"{ai_reason} | RSI {rv:.1f} | MACD {hist:.4f}",
            "checks": checks,
            "stars": star_map,
                "detail_scores": detail_scores,
            "detail_scores": detail_scores or {
                "whale": 90 if cluster_ok else 35,
                "cluster": min(100, len(cluster) * 25),
                "wall": 88 if wall_ok else 25,
                "momentum": 85 if momentum_ok else 30,
                "rsi": 82 if rsi_ok else 35,
                "macd": 86 if macd_ok else 35
            },
            "momentum": momentum,
            "rsi": rv,
            "macd_hist": hist
        }

        with LOCK:
            STATE["signals"].appendleft(signal)
            STATE["stats"]["signals"] += 1
            STATE["chart_markers"].append({"ts": now(), "symbol": symbol, "type": "signal", "side": side, "price": price, "score": score})

        timeline("Trade signal", symbol, f"{side} | {score}% | {risk_label(score)}", "TRADE")
        notify("⚡ Trade Signal", f"{symbol} {side} {score}%", "TRADE")
        return signal

def demo_signal(config, price=65000.0):
    symbol = "BTCUSDT"
    checks = {"whale": True, "cluster": True, "wall": True, "momentum": True, "rsi": True, "macd": True}
    star_map = {k: "★★★★★" for k in checks}
    return {
        "ts": now(),
        "symbol": symbol,
        "side": "LONG",
        "price": price,
        "score": 94,
        "risk": "LOW",
        "reason": "DEMO: Whale cluster + momentum + RSI/MACD + wall confirmed",
        "checks": checks,
        "stars": star_map,
                "detail_scores": detail_scores,
        "detail_scores": {"whale": 95, "cluster": 96, "wall": 90, "momentum": 88, "trend": 92, "rsi": 84, "macd": 86, "volume": 78, "volatility": 80},
        "momentum": 0.22,
        "rsi": 58,
        "macd_hist": 1.25
    }
