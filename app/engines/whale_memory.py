import json
from pathlib import Path

MEMORY_PATH = Path("data/whale_memory.json")

class WhaleMemory:
    """
    Stores recurring whale behavior for Version 3.0.
    """

    def __init__(self):
        MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not MEMORY_PATH.exists():
            MEMORY_PATH.write_text("{}", encoding="utf-8")

    def load(self):
        try:
            return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save(self, data):
        MEMORY_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def remember_whale(self, symbol, side, value, price):
        data = self.load()
        key = f"{symbol}:{side}"
        item = data.get(key, {"count": 0, "total_value": 0, "last_price": 0})
        item["count"] += 1
        item["total_value"] += float(value)
        item["last_price"] = float(price)
        data[key] = item
        self.save(data)
        return item
