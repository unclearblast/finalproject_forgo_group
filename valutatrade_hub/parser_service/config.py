"""Parser Service configuration: URLs, currency lists, timeout, paths, key.

The ExchangeRate-API key is loaded from the ``EXCHANGERATE_API_KEY`` environment
variable. A local ``.env`` file (git-ignored) is auto-loaded on first import so
the CLI needs no manual ``export``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.core import currencies as core_currencies
from valutatrade_hub.infra.settings import SettingsLoader


def _load_dotenv(path: Path) -> None:
    """Load ``KEY=VALUE`` pairs from ``path`` into ``os.environ`` if not set."""
    if not path.exists():
        return
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(SettingsLoader.get().data_dir.parent / ".env")


@dataclass
class ParserConfig:
    """All parser-service constants in one place."""

    # ---- secrets -----------------------------------------------------------
    EXCHANGERATE_API_KEY: str | None = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY")
    )

    # ---- endpoints ---------------------------------------------------------
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"

    # ---- currencies --------------------------------------------------------
    BASE_CURRENCY: str = core_currencies.BASE_CURRENCY
    FIAT_CURRENCIES: tuple[str, ...] = core_currencies.FIAT_CURRENCIES
    CRYPTO_CURRENCIES: tuple[str, ...] = core_currencies.CRYPTO_CURRENCIES
    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: dict(core_currencies.CRYPTO_ID_MAP)
    )

    # ---- paths -------------------------------------------------------------
    RATES_FILE_PATH: str = field(
        default_factory=lambda: str(SettingsLoader.get().rates_path)
    )
    HISTORY_FILE_PATH: str = field(
        default_factory=lambda: str(SettingsLoader.get().history_path)
    )

    # ---- networking --------------------------------------------------------
    REQUEST_TIMEOUT: int = int(os.getenv("VT_REQUEST_TIMEOUT", "10"))
    SCHEDULER_INTERVAL_SECONDS: int = int(os.getenv("VT_SCHEDULER_INTERVAL", "300"))
