"""Command-line interface for ValutaTrade Hub.

The CLI layer only parses arguments, calls a usecase, and renders output. It
catches :class:`ValutaTradeError` at the top level and prints a friendly
message — never a raw traceback.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from collections.abc import Iterable
from pathlib import Path

from prettytable import PrettyTable

from valutatrade_hub.core import usecases
from valutatrade_hub.core.currencies import BASE_CURRENCY
from valutatrade_hub.core.exceptions import ValutaTradeError
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater


# --------------------------------------------------------------------------- #
# Output helpers                                                              #
# --------------------------------------------------------------------------- #
def _table(columns: list[str], rows: Iterable[Iterable]) -> None:
    """Render a PrettyTable with the given columns and rows."""
    table = PrettyTable()
    table.field_names = columns
    for row in rows:
        table.add_row(list(row))
    print(table)


def _read_password(args: argparse.Namespace) -> str | None:
    """Return ``--password`` or prompt interactively; ``None`` on Ctrl+C."""
    if args.password:
        return args.password
    try:
        return getpass.getpass("Password: ")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# Commands                                                                    #
# --------------------------------------------------------------------------- #
def cmd_register(args: argparse.Namespace) -> int:
    """Register a new user."""
    password = _read_password(args)
    if password is None:
        return 130
    if not args.password:
        try:
            confirm = getpass.getpass("Confirm password: ")
        except (KeyboardInterrupt, EOFError):
            print("\nAborted.", file=sys.stderr)
            return 130
        if password != confirm:
            print("Error: passwords do not match", file=sys.stderr)
            return 1
    info = usecases.register(args.username, password)
    print(f"Registered '{info['username']}' at {info['registration_date']}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    """Log in as an existing user."""
    password = _read_password(args)
    if password is None:
        return 130
    info = usecases.login(args.username, password)
    print(f"Logged in as {info['username']}")
    return 0


def cmd_logout(_args: argparse.Namespace) -> int:
    """Clear the current session."""
    usecases.logout()
    print("Logged out")
    return 0


def cmd_show_portfolio(_args: argparse.Namespace) -> int:
    """Show the current user's portfolio."""
    info = usecases.show_portfolio()
    print(f"Portfolio of {info['user']['username']}")
    rows = [(w["currency"], f"{w['balance']:.8g}") for w in info["wallets"]]
    if not rows:
        print("(empty)")
    else:
        _table(["Currency", "Balance"], rows)
    print(f"Total value in USD: {info['total_usd']:.2f}")
    return 0


def cmd_buy(args: argparse.Namespace) -> int:
    """Buy ``amount`` of ``currency`` for USD."""
    r = usecases.buy(args.currency, args.amount)
    print(
        f"Bought {r['amount']:g} {r['currency']} "
        f"@ {r['rate']:.6g} USD = {r['cost_usd']:.2f} USD"
    )
    print(f"New {r['currency']} balance: {r['new_balance']:.8g}")
    print(f"USD balance: {r['usd_balance']:.2f}")
    return 0


def cmd_sell(args: argparse.Namespace) -> int:
    """Sell ``amount`` of ``currency`` for USD."""
    r = usecases.sell(args.currency, args.amount)
    print(
        f"Sold {r['amount']:g} {r['currency']} "
        f"@ {r['rate']:.6g} USD = {r['proceeds_usd']:.2f} USD"
    )
    print(f"New {r['currency']} balance: {r['new_balance']:.8g}")
    print(f"USD balance: {r['usd_balance']:.2f}")
    return 0


def cmd_get_rate(args: argparse.Namespace) -> int:
    """Show the current rate for ``currency`` relative to ``base``."""
    info = usecases.get_rate(args.currency, base=args.base)
    suffix = "  [STALE — run 'update-rates']" if info["stale"] else ""
    print(
        f"{info['from_currency']}_{info['to_currency']}: {info['rate']:.8g}  "
        f"[source={info['source']}, updated_at={info['updated_at']}]{suffix}"
    )
    return 0


def cmd_update_rates(args: argparse.Namespace) -> int:
    """Run the Parser Service (optionally scoped to one source)."""
    settings = SettingsLoader.get()
    cfg = ParserConfig()
    clients = [CoinGeckoClient(cfg), ExchangeRateApiClient(cfg)]
    storage = RatesStorage(settings.rates_path, settings.history_path)
    updater = RatesUpdater(clients, storage)

    summary = updater.run_update(source_filter=args.source)
    if summary["errors"]:
        print(
            f"Update completed with errors. "
            f"Total rates updated: {summary['total']}. "
            f"Last refresh: {summary['last_refresh']}",
            file=sys.stderr,
        )
        for err in summary["errors"]:
            print(f"  - {err['source']}: {err['error']}", file=sys.stderr)
        return 2
    print(
        f"Update successful. Total rates updated: {summary['total']}. "
        f"Last refresh: {summary['last_refresh']}"
    )
    return 0


def cmd_show_rates(args: argparse.Namespace) -> int:
    """Show cached rates from ``rates.json`` with optional filters."""
    settings = SettingsLoader.get()
    path: Path = settings.rates_path
    if not path.exists():
        print(
            "Local rates cache is empty. Run 'update-rates' to fetch data.",
            file=sys.stderr,
        )
        return 1
    storage = RatesStorage(settings.rates_path, settings.history_path)
    snapshot = storage.load_rates()
    pairs = snapshot.get("pairs") or {}
    last_refresh = snapshot.get("last_refresh") or "unknown"

    base = (args.base or BASE_CURRENCY).upper()
    items: list[tuple[str, float, dict]] = []

    if args.currency:
        cur = args.currency.upper()
        if cur == base:
            items.append(
                (
                    f"{cur}_{base}",
                    1.0,
                    {
                        "source": "internal",
                        "updated_at": last_refresh,
                    },
                )
            )
        else:
            key = f"{cur}_{base}"
            if key in pairs and pairs[key].get("rate"):
                items.append((key, float(pairs[key]["rate"]), pairs[key]))
            else:
                inv = f"{base}_{cur}"
                if inv in pairs and pairs[inv].get("rate"):
                    items.append((key, 1.0 / float(pairs[inv]["rate"]), pairs[inv]))
                else:
                    print(f"Rate for '{cur}' not found in cache.", file=sys.stderr)
                    return 1
    else:
        for pair, info in pairs.items():
            from_cur, _, to_cur = pair.partition("_")
            if to_cur == base and info.get("rate"):
                items.append((pair, float(info["rate"]), info))
            elif from_cur == base and info.get("rate"):
                items.append((f"{to_cur}_{base}", 1.0 / float(info["rate"]), info))
        if not items:
            print(f"No rates found relative to base {base}.", file=sys.stderr)
            return 1

    if args.top is not None:
        crypto = {"BTC", "ETH", "SOL"}
        crypto_items = [it for it in items if it[0].split("_")[0] in crypto]
        crypto_items.sort(key=lambda x: x[1], reverse=True)
        items = crypto_items[: args.top]
        if not items:
            print("No crypto rates in cache to rank.", file=sys.stderr)
            return 1

    print(f"Rates from cache (updated at {last_refresh}):")
    _table(
        ["Pair", "Rate", "Source", "Updated at"],
        [
            (pair, f"{rate:.8g}", info.get("source", "?"), info.get("updated_at", "?"))
            for pair, rate, info in items
        ],
    )
    return 0


# --------------------------------------------------------------------------- #
# Parser                                                                      #
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="valutatrade",
        description="ValutaTrade Hub — currency trading simulator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("register", help="Register a new user")
    p.add_argument("username")
    p.add_argument("--password", default=None, help="Skip interactive prompt")
    p.set_defaults(func=cmd_register)

    p = sub.add_parser("login", help="Log in as a user")
    p.add_argument("username")
    p.add_argument("--password", default=None, help="Skip interactive prompt")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("logout", help="Clear the current session")
    p.set_defaults(func=cmd_logout)

    p = sub.add_parser("show-portfolio", help="Show the current user's portfolio")
    p.set_defaults(func=cmd_show_portfolio)

    p = sub.add_parser("buy", help="Buy a currency for USD")
    p.add_argument("currency")
    p.add_argument("amount", type=float)
    p.set_defaults(func=cmd_buy)

    p = sub.add_parser("sell", help="Sell a currency for USD")
    p.add_argument("currency")
    p.add_argument("amount", type=float)
    p.set_defaults(func=cmd_sell)

    p = sub.add_parser("get-rate", help="Show the current rate for a currency")
    p.add_argument("currency")
    p.add_argument("--base", default=BASE_CURRENCY)
    p.set_defaults(func=cmd_get_rate)

    p = sub.add_parser("update-rates", help="Run the Parser Service update")
    p.add_argument(
        "--source",
        default=None,
        help="Only refresh one source (coingecko | exchangerate)",
    )
    p.set_defaults(func=cmd_update_rates)

    p = sub.add_parser("show-rates", help="Show cached rates from rates.json")
    p.add_argument("--currency", default=None, help="Filter by currency code")
    p.add_argument(
        "--top", type=int, default=None, help="Show N most expensive cryptos"
    )
    p.add_argument("--base", default=BASE_CURRENCY, help="Quote base (default USD)")
    p.set_defaults(func=cmd_show_rates)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns a process exit code."""
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ValutaTradeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
