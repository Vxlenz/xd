"""User-owned runtime paths; no credentials are embedded here."""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def data_directory() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "NovaDeck"
    # Allows development and tests on non-Windows hosts.
    return Path.home() / ".local" / "share" / "NovaDeck"


def configure_logging(directory: Path | None = None) -> None:
    directory = (directory or data_directory()) / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("novadeck")
    if not logger.handlers:
        handler = RotatingFileHandler(directory / "novadeck.log", maxBytes=1_000_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
