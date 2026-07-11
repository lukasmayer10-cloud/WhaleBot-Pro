import json
from pathlib import Path

# anchor on the repo root so the app works from any working directory
ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "settings.json"

def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_config(config):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    tmp.replace(CONFIG_PATH)
