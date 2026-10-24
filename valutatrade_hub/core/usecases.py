"""Core usecases: register, login, buy, sell, get_rate, show_portfolio.

This module is the boundary between the domain layer (models + exceptions) and
the outside world (JSON storage, CLI). It raises only :class:`ValutaTradeError`
subclasses; the CLI layer renders friendly messages.

``register`` and ``login`` are intentionally **not** decorated with
``@log_action`` — arguments contain passwords and would be logged verbatim.
"""

from __future__ import annotations

from valutatrade_hub.core.currencies import (
    BASE_CURRENCY,
    INITIAL_USD_BALANCE,
    is_known_currency,
    normalize,
)
from valutatrade_hub.core.exceptions import (
    AuthenticationError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    RatesNotAvailableError,
    UserAlreadyExistsError,
    ValidationError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.utils import is_stale, utcnow_iso
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


# --------------------------------------------------------------------------- #
# Auth                                                                        #
# --------------------------------------------------------------------------- #
def register(username: str, password: str) -> dict:
    """Register a new user and create a portfolio with initial USD balance.

    Raises
    ------
    UserAlreadyExistsError
        If the normalised username is already taken.
    ValidationError
        If username or password fail validation.
    """
    db = DatabaseManager.get()
    users = db.load_users()

    user = User.create(username, password)  # validates + normalises
    if user.username in users:
        raise UserAlreadyExistsError(f"User '{user.username}' already exists")

    users[user.username] = user.to_dict()
    db.save_users(users)

    portfolio = Portfolio(user)
    portfolio.add_currency(BASE_CURRENCY).deposit(INITIAL_USD_BALANCE)
    portfolios = db.load_portfolios()
    portfolios[user.username] = portfolio.to_dict()
    db.save_portfolios(portfolios)

    return user.get_user_info()


def login(username: str, password: str) -> dict:
    """Authenticate a user and persist a session token.

    The session is stored in ``data/session.json`` and read by every
    subsequent command that needs the current user.
    """
    db = DatabaseManager.get()
    users = db.load_users()

    record = users.get(username.strip())
    if record is None:
        raise AuthenticationError("Invalid username or password")
    user = User.from_dict(record)
    if not user.check_password(password):
        raise AuthenticationError("Invalid username or password")

    db.save_session({"username": user.username, "logged_in_at": utcnow_iso()})
    return user.get_user_info()


def logout() -> dict:
    """Clear the current session (no-op if not logged in)."""
    DatabaseManager.get().clear_session()
    return {"logged_out": True}


def current_user() -> User | None:
    """Return the logged-in :class:`User`, or ``None`` if no session."""
    db = DatabaseManager.get()
    session = db.load_session()
    username = (session or {}).get("username")
    if not username:
        return None
    record = db.load_users().get(username)
    if record is None:
        return None
    return User.from_dict(record)


# --------------------------------------------------------------------------- #
# Portfolio helpers                                                           #
# --------------------------------------------------------------------------- #
def _require_current_user() -> User:
    user = current_user()
    if user is None:
        raise AuthenticationError("You must log in first (run 'login')")
    return user


def _load_portfolio(user: User) -> Portfolio:
    db = DatabaseManager.get()
    data = db.load_portfolios().get(user.username)
    if data is None:
        portfolio = Portfolio(user)
        portfolio.add_currency(BASE_CURRENCY).deposit(INITIAL_USD_BALANCE)
        return portfolio
    return Portfolio.from_dict(user, data)


def _save_portfolio(portfolio: Portfolio) -> None:
    db = DatabaseManager.get()
    portfolios = db.load_portfolios()
    portfolios[portfolio.user.username] = portfolio.to_dict()
    db.save_portfolios(portfolios)


# --------------------------------------------------------------------------- #
# Rates (cache-aware)                                                         #
# --------------------------------------------------------------------------- #
def _resolve_rate(currency: str, base: str) -> dict:
    """Look up ``currency→base`` in rates.json; return a rate descriptor.

    Returned dict::

        {
          "from_currency": "BTC",
          "to_currency":   "USD",
          "rate":          59337.21,
          "updated_at":    "2025-10-10T12:00:00Z",
          "source":        "CoinGecko",
          "stale":         False,
        }

    Raises
    ------
    CurrencyNotFoundError
        If either code is unknown or no pair is present in the cache.
    """
    settings = SettingsLoader.get()
    cache = DatabaseManager.get().load_rates()
    pairs = cache.get("pairs", {})

    cur = normalize(currency)
    b = normalize(base)

    if not is_known_currency(b):
        raise CurrencyNotFoundError(f"Unknown base currency: {b}")
    if not is_known_currency(cur):
        raise CurrencyNotFoundError(f"Unknown currency: {cur}")

    if cur == b:
        return {
            "from_currency": cur,
            "to_currency": b,
            "rate": 1.0,
            "updated_at": utcnow_iso(),
            "source": "internal",
            "stale": False,
        }

    ttl = settings.get_ttl_seconds()

    direct = pairs.get(f"{cur}_{b}")
    if direct and direct.get("rate", 0) > 0:
        return {
            "from_currency": cur,
            "to_currency": b,
            "rate": float(direct["rate"]),
            "updated_at": direct["updated_at"],
            "source": direct["source"],
            "stale": is_stale(direct["updated_at"], ttl),
        }

    inverse = pairs.get(f"{b}_{cur}")
    if inverse and inverse.get("rate", 0) > 0:
        return {
            "from_currency": cur,
            "to_currency": b,
            "rate": 1.0 / float(inverse["rate"]),
            "updated_at": inverse["updated_at"],
            "source": inverse["source"],
            "stale": is_stale(inverse["updated_at"], ttl),
        }

    raise CurrencyNotFoundError(
        f"Rate for {cur}/{b} not found in cache — run 'update-rates'"
    )


@log_action
def get_rate(currency: str, base: str = BASE_CURRENCY) -> dict:
    """Return the current rate for ``currency→base``, with staleness flag."""
    return _resolve_rate(currency, base)


# --------------------------------------------------------------------------- #
# Trading                                                                     #
# --------------------------------------------------------------------------- #
def _require_fresh_rate(currency: str, base: str) -> dict:
    """Resolve rate and raise :class:`RatesNotAvailableError` if stale."""
    info = _resolve_rate(currency, base)
    if info["stale"]:
        raise RatesNotAvailableError(
            f"Rates for {info['from_currency']}/{info['to_currency']} are stale "
            f"(updated {info['updated_at']}). Run 'update-rates' to refresh."
        )
    return info


@log_action
def buy(currency: str, amount: float) -> dict:
    """Buy ``amount`` of ``currency`` for USD at the cached rate.

    Returns
    -------
    dict
        ``{action, currency, amount, rate, cost_usd, new_balance, usd_balance}``
    """
    user = _require_current_user()
    cur = normalize(currency)
    if not is_known_currency(cur):
        raise CurrencyNotFoundError(f"Unknown currency: {cur}")
    if cur == BASE_CURRENCY:
        raise ValidationError(f"Cannot buy {BASE_CURRENCY} with {BASE_CURRENCY}")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValidationError("Amount must be a number")
    amt = float(amount)
    if amt <= 0:
        raise ValidationError("Amount must be positive")

    rate_info = _require_fresh_rate(cur, BASE_CURRENCY)
    rate = rate_info["rate"]
    cost = amt * rate

    portfolio = _load_portfolio(user)
    usd = portfolio.get_wallet(BASE_CURRENCY)
    usd.withdraw(cost)  # raises InsufficientFundsError if balance too low

    wallet = portfolio.add_currency(cur)
    wallet.deposit(amt)
    _save_portfolio(portfolio)

    return {
        "action": "buy",
        "currency": cur,
        "amount": amt,
        "rate": rate,
        "cost_usd": cost,
        "new_balance": wallet.balance,
        "usd_balance": usd.balance,
    }


@log_action
def sell(currency: str, amount: float) -> dict:
    """Sell ``amount`` of ``currency`` for USD at the cached rate.

    Returns
    -------
    dict
        ``{action, currency, amount, rate, proceeds_usd, new_balance, usd_balance}``
    """
    user = _require_current_user()
    cur = normalize(currency)
    if not is_known_currency(cur):
        raise CurrencyNotFoundError(f"Unknown currency: {cur}")
    if cur == BASE_CURRENCY:
        raise ValidationError(f"Cannot sell {BASE_CURRENCY} for {BASE_CURRENCY}")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        raise ValidationError("Amount must be a number")
    amt = float(amount)
    if amt <= 0:
        raise ValidationError("Amount must be positive")

    rate_info = _require_fresh_rate(cur, BASE_CURRENCY)
    rate = rate_info["rate"]
    proceeds = amt * rate

    portfolio = _load_portfolio(user)
    if not portfolio.has_wallet(cur):
        raise InsufficientFundsError(f"No {cur} wallet to sell from")
    wallet = portfolio.get_wallet(cur)
    wallet.withdraw(amt)  # raises InsufficientFundsError if too little

    usd = portfolio.add_currency(BASE_CURRENCY)
    usd.deposit(proceeds)
    _save_portfolio(portfolio)

    return {
        "action": "sell",
        "currency": cur,
        "amount": amt,
        "rate": rate,
        "proceeds_usd": proceeds,
        "new_balance": wallet.balance,
        "usd_balance": usd.balance,
    }


@log_action
def show_portfolio() -> dict:
    """Snapshot of the current user's portfolio with USD valuation."""
    user = _require_current_user()
    portfolio = _load_portfolio(user)
    rates = DatabaseManager.get().load_rates().get("pairs", {})
    info = portfolio.get_portfolio_info(rates)
    info["user"] = user.get_user_info()
    return info
