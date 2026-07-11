import time
from app.core.state import STATE, LOCK
from app.engines.indicators import rsi, macd, ema

def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, float(v)))

class AnalysisEngine:
    def __init__(self, config):
        self.config = config
        self.weights = {
            "whale": 0.18,
            "cluster": 0.16,
            "wall": 0.13,
            "momentum": 0.12,
            "trend": 0.12,
            "rsi": 0.10,
            "macd": 0.10,
            "volume": 0.05,
            "volatility": 0.04
        }
        self.weights.update(config.get("ai_weights", {}))

    def _recent(self, rows, seconds, now_raw):
        cutoff = now_raw - seconds
        return [x for x in rows if x.get("time_raw", 0) >= cutoff]

    def analyze_symbol(self, symbol, desired_side=None, now_raw=None):
        if now_raw is None:
            now_raw = time.time()
        with LOCK:
            candles = list(STATE.get("candles", {}).get(symbol, []))
            price = STATE.get("prices", {}).get(symbol)
            whales = [w for w in list(STATE.get("whales", [])) if w.get("symbol") == symbol]
            walls = [w for w in list(STATE.get("walls", [])) if w.get("symbol") == symbol]
            radar = STATE.get("radar", {}).get(symbol, {})

        if not candles or len(candles) < 35 or not price:
            return {
                "symbol": symbol,
                "side": desired_side or radar.get("side", "WATCH"),
                "score": int(radar.get("score", 0)),
                "status": "WARMING_UP",
                "scores": {
                    "whale": 0, "cluster": 0, "wall": 0, "momentum": 0,
                    "trend": 0, "rsi": 0, "macd": 0, "volume": 0, "volatility": 0
                },
                "reason": "AI warming up"
            }

        closes = [c["c"] for c in candles]
        volumes = [c.get("v", 1) for c in candles]

        recent_whales = self._recent(whales, self.config.get("cluster_window_sec", 120), now_raw)
        buy_whales = [w for w in recent_whales if w.get("side") == "BUY"]
        sell_whales = [w for w in recent_whales if w.get("side") == "SELL"]

        if desired_side == "LONG":
            side = "LONG"
            same_whales = buy_whales
            whale_dir = "BUY"
        elif desired_side == "SHORT":
            side = "SHORT"
            same_whales = sell_whales
            whale_dir = "SELL"
        else:
            if len(buy_whales) >= len(sell_whales):
                side = "LONG" if buy_whales else "WATCH"
                same_whales = buy_whales
                whale_dir = "BUY"
            else:
                side = "SHORT"
                same_whales = sell_whales
                whale_dir = "SELL"

        whale_value = sum(w.get("value", 0) for w in same_whales)
        whale_min = max(1, self.config.get("whale_usd_min", 50000))
        whale_score = clamp((whale_value / whale_min) * 18)
        cluster_score = clamp((len(same_whales) / max(1, self.config.get("cluster_count", 3))) * 100)

        want_wall = "BUY_WALL" if side == "LONG" else "SELL_WALL"
        recent_walls = self._recent(walls, 180, now_raw)
        same_walls = [w for w in recent_walls if w.get("side") == want_wall]
        wall_value = sum(w.get("value", 0) for w in same_walls)
        wall_min = max(1, self.config.get("orderbook_wall_usd_min", 200000))
        wall_score = clamp((wall_value / wall_min) * 45)

        momentum = ((closes[-1] - closes[-6]) / closes[-6]) * 100 if len(closes) >= 6 else 0
        if side == "SHORT":
            momentum_score = clamp(50 - momentum * 900)
        else:
            momentum_score = clamp(50 + momentum * 900)

        e20 = ema(closes, 20)
        e50 = ema(closes, 50) if len(closes) >= 50 else ema(closes, 26)
        trend_raw = ((e20 - e50) / e50) * 100 if e20 and e50 else 0
        trend_score = clamp(50 + trend_raw * 1200) if side != "SHORT" else clamp(50 - trend_raw * 1200)

        rv = rsi(closes) or 50
        if side == "SHORT":
            rsi_score = 85 if 32 <= rv <= 58 else clamp(100 - abs(rv - 45) / 35 * 100)
        else:
            rsi_score = 85 if 42 <= rv <= 68 else clamp(100 - abs(rv - 55) / 35 * 100)

        _, _, hist = macd(closes)
        hist = hist or 0
        macd_score = clamp(50 + hist * 250) if side != "SHORT" else clamp(50 - hist * 250)

        avg_vol = sum(volumes[-30:]) / max(1, len(volumes[-30:]))
        volume_score = clamp((volumes[-1] / avg_vol) * 55) if avg_vol else 40

        returns = []
        for i in range(1, min(len(closes) - 1, 20)):
            if closes[-i-1]:
                returns.append(abs((closes[-i] - closes[-i-1]) / closes[-i-1]) * 100)
        volat = sum(returns) / max(1, len(returns))
        volatility_score = clamp(100 - abs(volat - 0.12) * 320)

        scores = {
            "whale": round(whale_score),
            "cluster": round(cluster_score),
            "wall": round(wall_score),
            "momentum": round(momentum_score),
            "trend": round(trend_score),
            "rsi": round(rsi_score),
            "macd": round(macd_score),
            "volume": round(volume_score),
            "volatility": round(volatility_score)
        }

        final = round(clamp(sum(scores[k] * self.weights.get(k, 0) for k in scores)))
        if same_whales and final < 60:
            final = 60
        status = "TRADE_READY" if final >= self.config.get("min_confidence", 84) else "WATCH"

        return {
            "symbol": symbol,
            "side": side,
            "score": final,
            "status": status,
            "scores": scores,
            "metrics": {
                "whale_value": whale_value,
                "whale_count": len(same_whales),
                "wall_value": wall_value,
                "momentum_pct": momentum,
                "trend_pct": trend_raw,
                "rsi": rv,
                "macd_hist": hist,
                "volatility": volat
            },
            "reason": f"AI {final}% | whales {len(same_whales)} | wall ${wall_value:,.0f}"
        }
