"""Persistence layer for the Parser Service.

- ``rates.json``: current snapshot ``{"pairs": {PAIR: {...}}, "last_refresh": iso}``
- ``exchange_rates.json``: append-only journal, one record per (pair, timestamp).

Both files are written atomically via ``tmp → os.replace``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from valutatrade_hub.logging_config import get_parser_logger


class RatesStorage:
    """Read/write rates cache and history journal."""

    def __init__(self, rates_path: Path | str, history_path: Path | str) -> None:
        self.rates_path = Path(rates_path)
        self.history_path = Path(history_path)
        self.logger = get_parser_logger()

    # ---- atomic IO ---------------------------------------------------------
    def _atomic_write(self, path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ---- rates.json --------------------------------------------------------
    def load_rates(self) -> dict:
        """Load ``rates.json``; return empty structure if missing/corrupt."""
        default = {"pairs": {}, "last_refresh": None}
        if not self.rates_path.exists():
            return default
        try:
            text = self.rates_path.read_text(encoding="utf-8").strip()
        except OSError:
            return default
        if not text:
            return default
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return default
        if not isinstance(data, dict) or "pairs" not in data:
            return default
        data.setdefault("last_refresh", None)
        return data

    def save_rates(self, pairs: dict[str, dict], last_refresh: str) -> None:
        """Atomically write ``rates.json`` with the given pairs and last_refresh."""
        self._atomic_write(
            self.rates_path, {"pairs": pairs, "last_refresh": last_refresh}
        )
        self.logger.info("Wrote %d pairs to %s", len(pairs), self.rates_path)

    # ---- exchange_rates.json ----------------------------------------------
    def load_history(self) -> list[dict]:
        """Load the journal; return ``[]`` if missing/corrupt."""
        if not self.history_path.exists():
            return []
        try:
            text = self.history_path.read_text(encoding="utf-8").strip()
        except OSError:
            return []
        if not text:
            return []
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return []
        return data if isinstance(data, list) else []

    def append_history(self, records: list[dict]) -> None:
        """Append new records, deduplicating by ``id``."""
        if not records:
            return
        history = self.load_history()
        existing_ids = {rec.get("id") for rec in history}
        added = 0
        for rec in records:
            rid = rec.get("id")
            if rid and rid not in existing_ids:
                history.append(rec)
                existing_ids.add(rid)
                added += 1
        self._atomic_write(self.history_path, history)
        self.logger.info(
            "Journal: appended %d records (total=%d) to %s",
            added,
            len(history),
            self.history_path,
        )
