import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode

class ExchangeSafetyError(RuntimeError):
    pass

class BinanceFuturesTestnet:
    """
    Binance Futures Testnet exchange layer prepared for 4.1+.

    In 4.0 PLATFORM this is intentionally safe:
    - reading status is allowed
    - real order methods are disabled unless explicitly enabled in config/env
    """

    BASE = "https://testnet.binancefuture.com"

    def __init__(self, config):
        self.config = config
        self.api_key = os.getenv("BINANCE_TESTNET_API_KEY", "")
        self.api_secret = os.getenv("BINANCE_TESTNET_API_SECRET", "")
        self.enabled = bool(self.api_key and self.api_secret)
        self.allow_trading = bool(config.get("allow_testnet_trading", False)) and os.getenv("ALLOW_TESTNET_TRADING", "false").lower() == "true"

    def status(self):
        return {
            "exchange": "binance_futures_testnet",
            "enabled": self.enabled,
            "allow_trading": self.allow_trading,
            "mode": "testnet",
            "message": "Testnet layer prepared. Trading disabled in 4.0 unless explicitly enabled later."
        }

    def _signed_request(self, method, path, params=None):
        if not self.enabled:
            raise ExchangeSafetyError("Testnet API keys missing.")
        params = params or {}
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        sig = hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{self.BASE}{path}?{query}&signature={sig}"
        headers = {"X-MBX-APIKEY": self.api_key}
        r = requests.request(method, url, headers=headers, timeout=10)
        r.raise_for_status()
        return r.json()

    def account_status(self):
        if not self.enabled:
            return {"enabled": False, "message": "No testnet API keys configured."}
        return self._signed_request("GET", "/fapi/v2/account", {})

    def create_order(self, **kwargs):
        if not self.allow_trading:
            raise ExchangeSafetyError("Testnet order execution disabled in 4.0 PLATFORM.")
        return self._signed_request("POST", "/fapi/v1/order", kwargs)

    def close_position(self, **kwargs):
        if not self.allow_trading:
            raise ExchangeSafetyError("Testnet position closing disabled in 4.0 PLATFORM.")
        return self._signed_request("POST", "/fapi/v1/order", kwargs)
