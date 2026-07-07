import json
from pathlib import Path
from app.core.state import now

JOURNAL_PATH = Path("data/trade_journal.json")

class JournalEngine:
    """
    Trade journal prepared for Version 3.0.
    """

    def __init__(self):
        JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        if not JOURNAL_PATH.exists():
            JOURNAL_PATH.write_text("[]", encoding="utf-8")

    def load(self):
        try:
            return json.loads(JOURNAL_PATH.read_text(encoding="utf-8"))
        except Exception:
            return []

    def append(self, trade):
        rows = self.load()
        trade["journal_ts"] = now()
        rows.append(trade)
        JOURNAL_PATH.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        return trade
