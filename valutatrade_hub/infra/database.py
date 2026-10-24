"""JSON-backed storage manager (singleton).

`DatabaseManager` handles read/write of every ``data/*.json`` file atomically:
data is serialised to a temporary file in the same directory and then
``os.replace()``-d onto the target — same-filesystem rename is atomic on POSIX.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from valutatrade_hub.infra.settings import SettingsLoader


class DatabaseManager:
    """Singleton for reading and writing JSON storage files."""

    _instance: DatabaseManager | None = None

    def __new__(cls) -> DatabaseManager:
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._settings = SettingsLoader.get()
            cls._instance = instance
        return cls._instance

    @classmethod
    def get(cls) -> DatabaseManager:
        """Return the process-wide instance."""
        return cls()

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton — used by tests."""
        cls._instance = None

    # ---- atomic JSON io ----------------------------------------------------
    def read_json(self, path: Path, default: Any = None) -> Any:
        """Read JSON from ``path``; return ``default`` if missing or empty."""
        if not path.exists():
            return default
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return default
        if not text:
            return default
        return json.loads(text)

    def write_json(self, path: Path, data: Any) -> None:
        """Atomically write ``data`` as pretty JSON to ``path``."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    # ---- domain shortcuts --------------------------------------------------
    def load_users(self) -> dict[str, dict]:
        """Load ``users.json`` as ``{username: user_data}``."""
        return self.read_json(self._settings.users_path, default={})

    def save_users(self, users: dict[str, dict]) -> None:
        """Persist ``users.json``."""
        self.write_json(self._settings.users_path, users)

    def load_portfolios(self) -> dict[str, dict]:
        """Load ``portfolios.json`` as ``{username: portfolio_data}``."""
        return self.read_json(self._settings.portfolios_path, default={})

    def save_portfolios(self, portfolios: dict[str, dict]) -> None:
        """Persist ``portfolios.json``."""
        self.write_json(self._settings.portfolios_path, portfolios)

    def load_rates(self) -> dict:
        """Load ``rates.json`` (empty structure if missing)."""
        return self.read_json(
            self._settings.rates_path,
            default={"pairs": {}, "last_refresh": None},
        )

    def save_rates(self, rates: dict) -> None:
        """Persist ``rates.json``."""
        self.write_json(self._settings.rates_path, rates)

    def load_history(self) -> list[dict]:
        """Load ``exchange_rates.json`` as a list of history records."""
        return self.read_json(self._settings.history_path, default=[])

    def save_history(self, history: list[dict]) -> None:
        """Persist ``exchange_rates.json``."""
        self.write_json(self._settings.history_path, history)

    def load_session(self) -> dict:
        """Load ``session.json`` (empty dict if not logged in)."""
        return self.read_json(self._settings.session_path, default={})

    def save_session(self, session: dict) -> None:
        """Persist ``session.json``."""
        self.write_json(self._settings.session_path, session)

    def clear_session(self) -> None:
        """Remove ``session.json`` if it exists."""
        path = self._settings.session_path
        if path.exists():
            path.unlink()
