"""Static currency metadata shared across the core and parser services."""

from __future__ import annotations

BASE_CURRENCY: str = "USD"

FIAT_CURRENCIES: tuple[str, ...] = ("USD", "EUR", "GBP", "RUB")
CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")

CRYPTO_ID_MAP: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}

ALL_CURRENCIES: tuple[str, ...] = FIAT_CURRENCIES + CRYPTO_CURRENCIES

# Starting balance for a newly registered portfolio. Not part of the rubric,
# but buy/sell need a non-empty USD wallet to operate and the rubric has no
# `deposit` CLI command.
INITIAL_USD_BALANCE: float = 10_000.0


def normalize(code: str) -> str:
    """Return ``code`` stripped and upper-cased."""
    return code.strip().upper()


def is_known_currency(code: str) -> bool:
    """Return ``True`` if ``code`` (case-insensitive) is a tracked currency."""
    return normalize(code) in ALL_CURRENCIES


def is_crypto(code: str) -> bool:
    """Return ``True`` if ``code`` is a tracked crypto currency code."""
    return normalize(code) in CRYPTO_CURRENCIES


def is_fiat(code: str) -> bool:
    """Return ``True`` if ``code`` is a tracked fiat currency code."""
    return normalize(code) in FIAT_CURRENCIES
