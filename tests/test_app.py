"""End-to-end tests against the Flask app, offline (no Binance calls).

Ordered flow: the app holds global state, so these tests build on each other
the same way a live session would."""

import time

def test_01_boot_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    s = r.get_json()
    assert s["balance"] == 1000.0
    assert s["equity"] == 1000.0
    assert s["positions"] == []

def test_02_healthz_idle(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    h = r.get_json()
    assert h["healthy"] is True
    assert h["running"] is False
    assert h["open_positions"] == 0

def test_03_demo_market_opens_v2_position(client):
    r = client.post("/api/demo-market")
    assert r.status_code == 200
    s = client.get("/api/state").get_json()
    assert len(s["positions"]) == 1
    pos = s["positions"][0]
    assert pos["engine"] == "v2"
    assert pos["fee_open"] > 0
    assert s["signals"][0]["detail_scores"]  # the old NameError path

def test_04_state_candles_slimmed(client):
    s = client.get("/api/state?chart=BTCUSDT").get_json()
    assert list(s["candles"].keys()) == ["BTCUSDT"]

def test_05_pnl_and_equity_consistent(client):
    from app.web.server import paper_v2, paper_trader
    s = client.get("/api/state").get_json()
    entry = s["positions"][0]["entry"]
    prices = {"BTCUSDT": entry * 1.001}
    paper_trader.update_positions(prices)
    paper_v2.update(prices)
    s = client.get("/api/state").get_json()
    p = s["positions"][0]
    assert abs(s["equity"] - (s["balance"] + p["pnl"])) < 1e-9

def test_06_manual_close_books_once(client):
    s = client.get("/api/state").get_json()
    p = s["positions"][0]
    bal_before, pnl = s["balance"], p["pnl"]
    r = client.post(f"/api/close/{p['id']}")
    assert r.get_json()["ok"] is True
    s = client.get("/api/state").get_json()
    assert s["positions"] == []
    assert len(s["closed"]) == 1
    assert abs(s["balance"] - (bal_before + pnl)) < 1e-6
    assert abs(s["equity"] - s["balance"]) < 1e-9
    assert abs(s["daily_pnl"] - (s["equity"] - 1000.0)) < 1e-9
    assert s["performance"]["total_trades"] == 1
    assert s["wins"] + s["losses"] == 1

def test_07_auto_tp_close(client):
    from app.web.server import paper_v2
    paper_v2.last_open_by_symbol.clear()
    client.post("/api/demo-market")
    s = client.get("/api/state").get_json()
    assert len(s["positions"]) == 1
    p = s["positions"][0]
    bal_before = s["balance"]
    paper_v2.update({"BTCUSDT": p["tp"] * 1.0001})
    s = client.get("/api/state").get_json()
    assert s["positions"] == []
    assert s["closed"][0]["close_reason"] == "TP"
    assert s["closed"][0]["pnl"] > 0
    assert s["balance"] > bal_before
    assert s["performance"]["profit_factor"] > 0

def test_08_engine_ownership(client):
    """v2 must never close v1 positions and vice versa."""
    from app.web.server import paper_v2, paper_trader
    from app.engines.strategy_engine import demo_signal
    sig = demo_signal(paper_trader.config, 65000.0)
    paper_trader.open_position(sig)
    s = client.get("/api/state").get_json()
    v1 = [p for p in s["positions"] if p["engine"] == "v1"]
    assert len(v1) == 1
    n = len(s["positions"])
    paper_v2.update({"BTCUSDT": v1[0]["tp"] * 1.01})  # would be a TP for v1
    assert len(client.get("/api/state").get_json()["positions"]) == n
    bal_before = s["balance"]
    paper_trader.update_positions({"BTCUSDT": v1[0]["tp"] * 1.01})
    s = client.get("/api/state").get_json()
    assert not any(p["engine"] == "v1" for p in s["positions"])
    assert s["balance"] > bal_before

def test_09_settings_validation(client, original_config):
    r = client.post("/api/settings", json={
        "min_confidence": -5,
        "position_size_usd": 75,
        "whale_usd_min": "abc",
    })
    j = r.get_json()
    assert "min_confidence" in j["rejected"]
    assert "whale_usd_min" in j["rejected"]
    assert j["config"]["position_size_usd"] == 75.0
    assert j["config"]["min_confidence"] == original_config["min_confidence"]

def test_10_platform_and_core_endpoints(client):
    assert client.get("/api/platform").status_code == 200
    assert client.get("/api/core").status_code == 200

def test_11_persistence_survives_restart(client):
    """Simulate a process restart: wipe in-memory state, restore from SQLite."""
    from app.core import persistence
    from app.core.state import STATE, LOCK
    from collections import deque

    s = client.get("/api/state").get_json()
    balance, closed_count = s["balance"], len(s["closed"])
    assert closed_count >= 3

    persistence.save_account()
    with LOCK:
        STATE["balance"] = 1000.0
        STATE["wins"] = 0
        STATE["losses"] = 0
        STATE["closed"] = deque(maxlen=300)
    persistence.close_db()
    persistence.init_db()
    assert persistence.restore_state() is True

    s = client.get("/api/state").get_json()
    assert abs(s["balance"] - balance) < 1e-6
    assert len(s["closed"]) == closed_count
    assert s["wins"] + s["losses"] == closed_count

def test_12_position_ids_unique(client):
    from app.core.state import next_position_id
    ids = {next_position_id() for _ in range(1000)}
    assert len(ids) == 1000
    assert min(ids) > int(time.time() * 1000) - 60_000
