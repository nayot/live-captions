"""Run: uv run python -m app   (serves on http://localhost:PORT, default 8765)"""
import logging

import uvicorn

from .config import Settings
from .server import create_app, lan_ip


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = Settings.from_env()
    # Default localhost only. HOST=0.0.0.0 lets other machines open /display (control stays local;
    # the microphone also needs localhost or HTTPS).
    if s.host not in ("127.0.0.1", "localhost"):
        ip = lan_ip() or "<this-machine-ip>"
        print(f"Control: http://localhost:{s.port}   Display for other machines: http://{ip}:{s.port}/display")
    uvicorn.run(create_app(s), host=s.host, port=s.port, log_level="warning")


if __name__ == "__main__":
    main()
