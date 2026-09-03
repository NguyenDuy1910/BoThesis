"""Executable bootstrap for the BoThesis HTTP application."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)

from api.app import _environment_boolean, app


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=os.getenv("BOTHESIS_LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    uvicorn.run(
        app,
        host=os.getenv("BOTHESIS_HOST", "127.0.0.1"),
        port=int(os.getenv("BOTHESIS_PORT", "8000")),
        env_file=Path(__file__).with_name(".env"),
    )
