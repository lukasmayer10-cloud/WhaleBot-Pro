import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# isolate the database BEFORE any app import
os.environ["WHALEBOT_DATA_DIR"] = tempfile.mkdtemp(prefix="whalebot-test-")

_original_settings = (ROOT / "config" / "settings.json").read_text(encoding="utf-8")

@pytest.fixture(scope="session", autouse=True)
def restore_settings_file():
    """Tests exercise /api/settings which writes config/settings.json; put it back."""
    yield
    (ROOT / "config" / "settings.json").write_text(_original_settings, encoding="utf-8")

@pytest.fixture(scope="session")
def client():
    from main import app
    return app.test_client()

@pytest.fixture(scope="session")
def original_config():
    return json.loads(_original_settings)
