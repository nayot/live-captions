"""Run: uv run python -m app   (serves on http://localhost:PORT, default 8765)"""
import logging

import uvicorn

from .config import Settings
from .server import create_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    # localhost only: the browser needs localhost (or HTTPS) to use the microphone
    uvicorn.run(create_app(s), host="127.0.0.1", port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
