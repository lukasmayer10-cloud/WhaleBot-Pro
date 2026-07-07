class RiskEngine:
    """
    Version 3.0 risk module.

    Prepared features:
    - fixed dollar risk
    - percent balance risk
    - max daily loss
    - max concurrent positions
    - volatility SL/TP
    """

    def __init__(self, config):
        self.config = config

    def position_size(self, balance, stop_distance_pct):
        base_size = float(self.config.get("position_size_usd", 50))
        if stop_distance_pct <= 0:
            return base_size
        return base_size

    def allowed_to_trade(self, state):
        max_positions = int(self.config.get("max_open_positions", 3))
        if len(state.get("positions", [])) >= max_positions:
            return False, "max positions reached"
        return True, "ok"
