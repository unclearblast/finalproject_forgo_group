"""Application-wide logging configuration.

Two loggers are wired:

- ``valutatrade``        — main application log (``logs/app.log``)
- ``valutatrade.parser`` — parser-service log  (``logs/parser.log``)

Both write rotating files (1 MB × 3 backups) with a concise line format.
Configuration is idempotent and triggered on first :func:`get_logger` call.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.infra.settings import SettingsLoader

_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_MAX_BYTES = 1_000_000
_BACKUP_COUNT = 3

_CONFIGURED = False


def configure_logging(level: int = logging.INFO) -> None:
    """Configure rotating file handlers for app and parser loggers.

    Safe to call multiple times; only the first call has effect.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = SettingsLoader.get()
    settings.log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    app_logger = logging.getLogger("valutatrade")
    app_logger.setLevel(level)
    app_logger.propagate = False
    app_handler = RotatingFileHandler(
        settings.app_log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    app_handler.setFormatter(formatter)
    app_logger.addHandler(app_handler)

    parser_logger = logging.getLogger("valutatrade.parser")
    parser_logger.setLevel(level)
    parser_logger.propagate = False
    parser_handler = RotatingFileHandler(
        settings.parser_log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    parser_handler.setFormatter(formatter)
    parser_logger.addHandler(parser_handler)

    _CONFIGURED = True


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an app logger (optionally nested under ``valutatrade``)."""
    configure_logging()
    return logging.getLogger(f"valutatrade.{name}" if name else "valutatrade")


def get_parser_logger() -> logging.Logger:
    """Return the dedicated parser-service logger."""
    configure_logging()
    return logging.getLogger("valutatrade.parser")
