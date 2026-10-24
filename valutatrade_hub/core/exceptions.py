"""Domain exceptions for ValutaTrade Hub.

All domain errors inherit from :class:`ValutaTradeError` so that the CLI
layer can catch them uniformly and render a friendly message.
"""

from __future__ import annotations


class ValutaTradeError(Exception):
    """Base class for all domain errors in ValutaTrade Hub."""


class ValidationError(ValutaTradeError):
    """Raised when user input fails domain validation."""


class CurrencyNotFoundError(ValutaTradeError):
    """Raised when a requested currency is not tracked or unknown."""


class UserNotFoundError(ValutaTradeError):
    """Raised when a user lookup fails."""


class UserAlreadyExistsError(ValutaTradeError):
    """Raised when trying to register a user whose email already exists."""


class AuthenticationError(ValutaTradeError):
    """Raised on a failed login attempt."""


class InsufficientFundsError(ValutaTradeError):
    """Raised when a wallet does not have enough balance for an operation."""


class WalletNotFoundError(ValutaTradeError):
    """Raised when a portfolio does not hold a given currency wallet."""


class RatesNotAvailableError(ValutaTradeError):
    """Raised when the rates cache is empty or stale beyond recovery."""


class ApiRequestError(ValutaTradeError):
    """Raised by parser-service API clients on network or HTTP failure.

    Parameters
    ----------
    message:
        Human-readable error description.
    status_code:
        HTTP status code if the failure was an HTTP error.
    source:
        Human-readable name of the upstream provider (e.g. "CoinGecko").
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.source = source
