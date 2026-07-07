from app.core.state import STATE, LOCK

class OrderflowEngine:
    """
    Prepared for 4.x:
    - CVD
    - orderbook imbalance
    - liquidity zones
    - absorption
    """

    def __init__(self, config):
        self.config = config

    def snapshot(self, symbol):
        with LOCK:
            whales = [w for w in list(STATE["whales"]) if w.get("symbol") == symbol]
            walls = [w for w in list(STATE["walls"]) if w.get("symbol") == symbol]
            ob = STATE["orderbook"].get(symbol, {})

        buy_whales = sum(w.get("value", 0) for w in whales if w.get("side") == "BUY")
        sell_whales = sum(w.get("value", 0) for w in whales if w.get("side") == "SELL")
        buy_walls = sum(w.get("value", 0) for w in walls if w.get("side") == "BUY_WALL")
        sell_walls = sum(w.get("value", 0) for w in walls if w.get("side") == "SELL_WALL")

        total = buy_whales + sell_whales + buy_walls + sell_walls
        imbalance = ((buy_whales + buy_walls) - (sell_whales + sell_walls)) / total * 100 if total else 0

        return {
            "symbol": symbol,
            "buy_whales": buy_whales,
            "sell_whales": sell_whales,
            "buy_walls": buy_walls,
            "sell_walls": sell_walls,
            "imbalance": round(imbalance, 2),
            "status": "prepared"
        }
