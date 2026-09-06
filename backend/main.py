"""Executable bootstrap for the BoThesis HTTP application."""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)

from config import get_config

from api.app import app


if __name__ == "__main__":
    import uvicorn

    server = get_config().server
    logging.basicConfig(
        level=server.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(
        app,
        host=server.host,
        port=server.port,
        env_file=Path(__file__).with_name(".env"),
    )
