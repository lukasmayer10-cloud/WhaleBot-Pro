import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

def setup_logging():
    log_dir = Path(os.getenv("WHALEBOT_LOG_DIR", Path(__file__).parent / "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(RotatingFileHandler(log_dir / "whalebot.log", maxBytes=5_000_000, backupCount=3))
    except OSError:
        pass  # read-only filesystem: console logging only
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        handlers=handlers,
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

setup_logging()

from app.web.server import create_app

app = create_app()

if __name__ == "__main__":
    # namespaced on purpose: zsh exports HOST=<hostname> on macOS
    host = os.getenv("WHALEBOT_HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8080"))
    print(f"WhaleBot Pro X 6.1 POSITION MANAGER läuft auf http://{host}:{port}")
    if "--dev" in sys.argv:
        app.run(host=host, port=port, threaded=True)
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)
