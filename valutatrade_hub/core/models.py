"""Domain models: :class:`User`, :class:`Wallet`, :class:`Portfolio`.

Pure domain layer — no I/O, no logging, no CLI concerns. Persistence is handled
by the caller (see :mod:`valutatrade_hub.core.usecases` and
:mod:`valutatrade_hub.infra.database`).
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from valutatrade_hub.core.currencies import (
    BASE_CURRENCY,
    is_known_currency,
    normalize,
)
from valutatrade_hub.core.exceptions import (
    InsufficientFundsError,
    ValidationError,
    WalletNotFoundError,
)
from valutatrade_hub.core.utils import utcnow_iso

_USERNAME_MIN = 3
_USERNAME_MAX = 32
_PASSWORD_MIN = 6
_PASSWORD_MAX = 128


# --------------------------------------------------------------------------- #
# Validators                                                                  #
# --------------------------------------------------------------------------- #
def _validate_username(username: str) -> str:
    """Normalise and validate a username; raise :class:`ValidationError`."""
    if not isinstance(username, str) or not username.strip():
        raise ValidationError("Username must be a non-empty string")
    username = username.strip()
    if not (_USERNAME_MIN <= len(username) <= _USERNAME_MAX):
        raise ValidationError(
            f"Username must be {_USERNAME_MIN}-{_USERNAME_MAX} characters long"
        )
    if not all(ch.isalnum() or ch == "_" for ch in username):
        raise ValidationError("Username may contain only letters, digits, and '_'")
    return username


def _validate_password(password: str) -> None:
    """Validate password length; raise :class:`ValidationError`."""
    if not isinstance(password, str):
        raise ValidationError("Password must be a string")
    if not (_PASSWORD_MIN <= len(password) <= _PASSWORD_MAX):
        raise ValidationError(
            f"Password must be {_PASSWORD_MIN}-{_PASSWORD_MAX} characters long"
        )


def _hash_password(password: str, salt: str) -> str:
    """Salted SHA-256 (lowercase hex)."""
    return hashlib.sha256((salt + password).encode("utf-8")).hexdigest()


def _validate_amount(value: Any, *, field: str = "amount") -> float:
    """Return ``value`` as a positive float or raise :class:`ValidationError`."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field.capitalize()} must be a number")
    value = float(value)
    if value <= 0:
        raise ValidationError(f"{field.capitalize()} must be positive")
    return value


# --------------------------------------------------------------------------- #
# User                                                                        #
# --------------------------------------------------------------------------- #
class User:
    """A registered user with a salted SHA-256 password hash.

    Users are created via :meth:`create` (generates a salt) and rebuilt from
    JSON via :meth:`from_dict`. Password and salt never appear in
    :meth:`get_user_info`.
    """

    def __init__(
        self,
        username: str,
        password_hash: str,
        salt: str,
        registration_date: str,
    ) -> None:
        self._username = username
        self._password_hash = password_hash
        self._salt = salt
        self._registration_date = registration_date

    @classmethod
    def create(cls, username: str, password: str) -> User:
        """Create a new :class:`User` with fresh salt and hashed password."""
        clean_username = _validate_username(username)
        _validate_password(password)
        salt = secrets.token_hex(16)
        return cls(
            username=clean_username,
            password_hash=_hash_password(password, salt),
            salt=salt,
            registration_date=utcnow_iso(),
        )

    @classmethod
    def from_dict(cls, data: dict) -> User:
        """Rebuild a :class:`User` from its JSON representation."""
        try:
            return cls(
                username=data["username"],
                password_hash=data["password_hash"],
                salt=data["salt"],
                registration_date=data["registration_date"],
            )
        except KeyError as exc:
            raise ValidationError(
                f"Corrupted user record, missing field: {exc.args[0]}"
            ) from exc

    # ---- properties -------------------------------------------------------
    @property
    def username(self) -> str:
        """User's login name."""
        return self._username

    @property
    def registration_date(self) -> str:
        """ISO-8601 UTC timestamp of registration."""
        return self._registration_date

    # ---- public API -------------------------------------------------------
    def check_password(self, password: str) -> bool:
        """Return ``True`` if ``password`` matches the stored hash."""
        if not isinstance(password, str):
            return False
        return secrets.compare_digest(
            _hash_password(password, self._salt), self._password_hash
        )

    def get_user_info(self) -> dict:
        """Public info about the user (no password or salt)."""
        return {
            "username": self._username,
            "registration_date": self._registration_date,
        }

    def to_dict(self) -> dict:
        """Serialisable representation for ``users.json``."""
        return {
            "username": self._username,
            "password_hash": self._password_hash,
            "salt": self._salt,
            "registration_date": self._registration_date,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"User(username={self._username!r})"


# --------------------------------------------------------------------------- #
# Wallet                                                                      #
# --------------------------------------------------------------------------- #
class Wallet:
    """Single-currency balance with validation invariants."""

    def __init__(self, currency: str, balance: float = 0.0) -> None:
        if not is_known_currency(currency):
            raise ValidationError(f"Unknown currency: {currency}")
        self._currency = normalize(currency)
        self._balance = 0.0
        self._set_balance(balance)

    def _set_balance(self, value: Any) -> None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValidationError("Balance must be a number")
        value = float(value)
        if value < 0:
            raise ValidationError("Balance cannot be negative")
        self._balance = value

    # ---- properties -------------------------------------------------------
    @property
    def currency(self) -> str:
        """ISO currency code (upper-case)."""
        return self._currency

    @property
    def balance(self) -> float:
        """Current non-negative balance."""
        return self._balance

    # ---- public API -------------------------------------------------------
    def deposit(self, amount: float) -> float:
        """Increase balance; return new balance."""
        self._balance += _validate_amount(amount, field="deposit amount")
        return self._balance

    def withdraw(self, amount: float) -> float:
        """Decrease balance; return new balance.

        Raises
        ------
        ValidationError
            If ``amount`` is non-positive or non-numeric.
        InsufficientFundsError
            If ``amount`` exceeds the current balance.
        """
        value = _validate_amount(amount, field="withdraw amount")
        if value > self._balance:
            raise InsufficientFundsError(
                f"Insufficient funds in {self._currency}: "
                f"have {self._balance:.8g}, need {value:.8g}"
            )
        self._balance -= value
        return self._balance

    def get_balance_info(self) -> dict:
        """Dict with ``currency`` and ``balance``."""
        return {"currency": self._currency, "balance": self._balance}

    def to_dict(self) -> dict:
        """Serialisable representation (``{"balance": ...}``)."""
        return {"balance": self._balance}

    @classmethod
    def from_dict(cls, currency: str, data: dict) -> Wallet:
        """Rebuild a :class:`Wallet` from ``{currency, {"balance": ...}}``."""
        return cls(currency=currency, balance=data.get("balance", 0.0))

    def __repr__(self) -> str:  # pragma: no cover
        return f"Wallet({self._currency}={self._balance!r})"


# --------------------------------------------------------------------------- #
# Portfolio                                                                   #
# --------------------------------------------------------------------------- #
class Portfolio:
    """A user's collection of :class:`Wallet` objects, one per currency."""

    def __init__(self, user: User) -> None:
        self._user = user
        self._wallets: dict[str, Wallet] = {}

    # ---- properties -------------------------------------------------------
    @property
    def user(self) -> User:
        """Owner of this portfolio (read-only)."""
        return self._user

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Shallow copy of ``{currency: Wallet}``; mutating the result is safe."""
        return dict(self._wallets)

    # ---- public API -------------------------------------------------------
    def add_currency(self, currency: str) -> Wallet:
        """Return the wallet for ``currency``, creating it if absent."""
        cur = normalize(currency)
        if not is_known_currency(cur):
            raise ValidationError(f"Unknown currency: {cur}")
        if cur not in self._wallets:
            self._wallets[cur] = Wallet(currency=cur)
        return self._wallets[cur]

    def has_wallet(self, currency: str) -> bool:
        """Return ``True`` if a wallet for ``currency`` exists."""
        return normalize(currency) in self._wallets

    def get_wallet(self, currency: str) -> Wallet:
        """Return the wallet for ``currency`` or raise :class:`WalletNotFoundError`."""
        cur = normalize(currency)
        wallet = self._wallets.get(cur)
        if wallet is None:
            raise WalletNotFoundError(f"No wallet for currency '{cur}'")
        return wallet

    def get_total_value(
        self,
        base: str = BASE_CURRENCY,
        rates: dict[str, dict] | None = None,
    ) -> float:
        """Total portfolio value in ``base`` currency.

        ``rates`` is the ``pairs`` mapping from ``rates.json``::

            {"BTC_USD": {"rate": 59337.21, ...}, "EUR_USD": {"rate": 1.0786, ...}}

        Pairs not present in ``rates`` contribute 0 to the total (a warning is
        the caller's responsibility).
        """
        base = normalize(base)
        rates = rates or {}
        total = 0.0
        for currency, wallet in self._wallets.items():
            if currency == base:
                total += wallet.balance
                continue
            direct = rates.get(f"{currency}_{base}")
            if direct and isinstance(direct.get("rate"), (int, float)):
                total += wallet.balance * float(direct["rate"])
                continue
            inverse = rates.get(f"{base}_{currency}")
            if inverse and inverse.get("rate", 0) > 0:
                total += wallet.balance / float(inverse["rate"])
        return total

    def get_portfolio_info(self, rates: dict[str, dict] | None = None) -> dict:
        """Snapshot: username, list of wallets, total value in USD."""
        return {
            "username": self._user.username,
            "wallets": [w.get_balance_info() for w in self._wallets.values()],
            "total_usd": self.get_total_value(BASE_CURRENCY, rates),
        }

    def to_dict(self) -> dict:
        """Serialisable representation for ``portfolios.json``."""
        return {
            "username": self._user.username,
            "wallets": {cur: w.to_dict() for cur, w in self._wallets.items()},
        }

    @classmethod
    def from_dict(cls, user: User, data: dict) -> Portfolio:
        """Rebuild a :class:`Portfolio` from ``portfolios.json`` entry."""
        portfolio = cls(user)
        for cur, wdata in data.get("wallets", {}).items():
            try:
                portfolio._wallets[normalize(cur)] = Wallet.from_dict(cur, wdata)
            except ValidationError:
                continue  # skip unknown/corrupted wallets rather than abort
        return portfolio

    def __repr__(self) -> str:  # pragma: no cover
        return f"Portfolio(user={self._user.username!r}, wallets={list(self._wallets)})"
