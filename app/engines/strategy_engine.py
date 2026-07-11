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

    def _recent_whales(self, symbol, side, now_raw):
        cutoff = now_raw - self.config["cluster_window_sec"]
        with LOCK:
            whales = list(STATE["whales"])
        return [w for w in whales if w["symbol"] == symbol and w["side"] == side and w["time_raw"] >= cutoff]

    def _wall_confirmed(self, symbol, whale_side, now_raw):
        want = "BUY_WALL" if whale_side == "BUY" else "SELL_WALL"
        cutoff = now_raw - 180
        with LOCK:
            walls = list(STATE["walls"])
        recent = [w for w in walls if w["symbol"] == symbol and w["side"] == want and w.get("time_raw", 0) >= cutoff]
        return len(recent) > 0, sum(w["value"] for w in recent)

    def _record_evaluation(self, entry, failed_gates):
        with LOCK:
            STATE["evaluations"].appendleft(entry)
            STATE["stats"]["evaluations"] += 1
            reasons = STATE["stats"].setdefault("reject_reasons", {})
            for gate in failed_gates:
                reasons[gate] = reasons.get(gate, 0) + 1

    def evaluate_from_whale(self, symbol, whale_side, now_raw=None):
        """Evaluate a potential entry after a whale trade.

        now_raw lets the backtester replay history with original timestamps;
        live callers leave it as wall-clock time."""
        if now_raw is None:
            now_raw = time.time()

        cluster = self._recent_whales(symbol, whale_side, now_raw)
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

        min_momentum = self.config["min_momentum_pct"]
        if whale_side == "BUY":
            side = "LONG"
            momentum_ok = momentum >= min_momentum
            rsi_lo, rsi_hi = 38, 78
            macd_ok = hist > 0
            macd_need = "> 0"
        else:
            side = "SHORT"
            momentum_ok = momentum <= -min_momentum
            rsi_lo, rsi_hi = 22, 62
            macd_ok = hist < 0
            macd_need = "< 0"
        rsi_ok = rsi_lo <= rv <= rsi_hi

        wall_ok, wall_value = self._wall_confirmed(symbol, whale_side, now_raw)

        ai = self.ai.analyze_symbol(symbol, side, now_raw=now_raw)
        score = ai.get("score", 0)
        detail_scores = ai.get("scores", {})
        ai_reason = ai.get("reason", "")

        min_confidence = self.config["min_confidence"]
        confidence_ok = score >= min_confidence

        # optional confirmations (strategy-creator rules): trend direction
        # and above-average volume, computed from the AI metrics
        metrics = ai.get("metrics", {})
        trend_raw = metrics.get("trend_pct", 0)
        trend_ok = trend_raw > 0 if side == "LONG" else trend_raw < 0
        volume_ok = detail_scores.get("volume", 0) >= 55  # ratio >= ~1x avg
        require_trend = self.config.get("require_trend_confirmation", False)
        require_volume = self.config.get("require_volume_confirmation", False)

        checks = {
            "whale": cluster_ok,
            "cluster": cluster_ok,
            "wall": wall_ok,
            "momentum": momentum_ok,
            "rsi": rsi_ok,
            "macd": macd_ok
        }
        star_map = {k: stars(v) for k, v in checks.items()}

        # gate-by-gate record: this is what makes rejections debuggable
        gates = {
            "cluster": {"ok": cluster_ok, "actual": len(cluster), "required": self.config["cluster_count"]},
            "momentum": {"ok": momentum_ok, "actual": round(momentum, 3),
                         "required": f">= {min_momentum}" if side == "LONG" else f"<= -{min_momentum}"},
            "rsi": {"ok": rsi_ok, "actual": round(rv, 1), "required": f"{rsi_lo}-{rsi_hi}"},
            "macd": {"ok": macd_ok, "actual": round(hist, 4), "required": macd_need},
            "confidence": {"ok": confidence_ok, "actual": score, "required": min_confidence},
        }
        if require_trend:
            gates["trend"] = {"ok": trend_ok, "actual": round(trend_raw, 4),
                              "required": "> 0" if side == "LONG" else "< 0"}
        if require_volume:
            gates["volume"] = {"ok": volume_ok, "actual": detail_scores.get("volume", 0),
                               "required": ">= 55 (≈1x avg)"}
        hard_gates_ok = (cluster_ok and momentum_ok and rsi_ok and macd_ok
                         and (trend_ok or not require_trend)
                         and (volume_ok or not require_volume))
        passed = hard_gates_ok and confidence_ok
        failed = [k for k, g in gates.items() if not g["ok"]]

        evaluation = {
            "ts": now(),
            "time_raw": now_raw,
            "symbol": symbol,
            "side": side,
            "outcome": "SIGNAL" if passed else "REJECTED",
            "gates": gates,
            "wall_ok": wall_ok,
            "score": score,
            "cluster_value": cluster_value,
        }
        self._record_evaluation(evaluation, [] if passed else failed)

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

        if not hard_gates_ok:
            with LOCK:
                STATE["stats"]["ignored"] += 1
            return None

        if not confidence_ok:
            with LOCK:
                STATE["stats"]["blocked_confidence"] += 1
            timeline("Signal blocked", symbol, f"{score}% below min {min_confidence}%", "WARN")
            return None

        signal = {
            "ts": now(),
            "time_raw": now_raw,
            "symbol": symbol,
            "side": side,
            "price": price,
            "score": score,
            "risk": risk_label(score),
            "reason": f"{ai_reason} | RSI {rv:.1f} | MACD {hist:.4f}",
            "checks": checks,
            "stars": star_map,
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
            if wall_ok:
                STATE["stats"]["wall_confirmed"] += 1
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
        "detail_scores": {"whale": 95, "cluster": 96, "wall": 90, "momentum": 88, "trend": 92, "rsi": 84, "macd": 86, "volume": 78, "volatility": 80},
        "momentum": 0.22,
        "rsi": 58,
        "macd_hist": 1.25
    }
