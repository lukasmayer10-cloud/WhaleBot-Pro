import os

class BinanceTestnetExchange:
    """
    Safe placeholder for Binance Futures Testnet.

    This module is prepared for Version 3.0.
    It does NOT send live orders yet.
    """

    def __init__(self):
        self.api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        self.enabled = bool(self.api_key and self.api_secret)

    def status(self):
        return {
            "enabled": self.enabled,
            "mode": "testnet",
            "live_orders": False,
            "message": "Testnet placeholder ready. Order execution not activated yet."
        }

    def create_order(self, *args, **kwargs):
        raise RuntimeError("Testnet order execution is prepared but intentionally disabled in 3.0 READY.")

    def close_position(self, *args, **kwargs):
        raise RuntimeError("Testnet position closing is prepared but intentionally disabled in 3.0 READY.")
