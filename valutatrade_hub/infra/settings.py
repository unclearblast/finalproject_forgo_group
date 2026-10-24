"""Application settings loaded once and shared as a singleton.

`SettingsLoader` provides:
- file paths for all ``data/`` storage;
- TTL for the local rates cache;
- a single place to override defaults via environment variables:
  ``VT_DATA_DIR``, ``VT_LOG_DIR``, ``VT_RATES_TTL``.
"""

from __future__ import annotations

import os
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"
_DEFAULT_LOG_DIR = _PROJECT_ROOT / "logs"


class SettingsLoader:
    """Singleton provider of runtime settings.

    Instantiate via :meth:`SettingsLoader.get`; the class is a singleton, so
    repeated construction returns the same object.
    """

    _instance: SettingsLoader | None = None

    def __new__(cls) -> SettingsLoader:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._load_from_env()
            cls._instance = instance
        return cls._instance

    def _load_from_env(self) -> None:
        self.data_dir: Path = Path(
            os.getenv("VT_DATA_DIR", str(_DEFAULT_DATA_DIR))
        ).resolve()
        self.log_dir: Path = Path(
            os.getenv("VT_LOG_DIR", str(_DEFAULT_LOG_DIR))
        ).resolve()
        self.rates_ttl_seconds: int = int(os.getenv("VT_RATES_TTL", "3600"))

    @classmethod
    def get(cls) -> SettingsLoader:
        """Return the process-wide instance."""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — used by tests."""
        cls._instance = None

    # ---- paths -------------------------------------------------------------
    @property
    def users_path(self) -> Path:
        """Path to ``data/users.json``."""
        return self.data_dir / "users.json"

    @property
    def portfolios_path(self) -> Path:
        """Path to ``data/portfolios.json``."""
        return self.data_dir / "portfolios.json"

    @property
    def rates_path(self) -> Path:
        """Path to ``data/rates.json`` (core cache)."""
        return self.data_dir / "rates.json"

    @property
    def history_path(self) -> Path:
        """Path to ``data/exchange_rates.json`` (parser history)."""
        return self.data_dir / "exchange_rates.json"

    @property
    def session_path(self) -> Path:
        """Path to ``data/session.json`` (current logged-in user)."""
        return self.data_dir / "session.json"

    @property
    def app_log_path(self) -> Path:
        """Path to ``logs/app.log``."""
        return self.log_dir / "app.log"

    @property
    def parser_log_path(self) -> Path:
        """Path to ``logs/parser.log``."""
        return self.log_dir / "parser.log"

    # ---- ttl ---------------------------------------------------------------
    def get_ttl_seconds(self) -> int:
        """Return TTL for the local rates cache, in seconds."""
        return self.rates_ttl_seconds
