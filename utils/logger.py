"""Application file logging for PCleaner."""

from __future__ import annotations

import logging
from utils.config import DATA_DIR, ensure_data_dir

_LOGGER: logging.Logger | None = None


def get_logger() -> logging.Logger:
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER

    ensure_data_dir()
    logger = logging.getLogger("pcleaner")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        fh = logging.FileHandler(DATA_DIR / "pcleaner.log", encoding="utf-8")
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    _LOGGER = logger
    return logger
