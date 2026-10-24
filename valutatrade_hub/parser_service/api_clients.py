"""API clients for CoinGecko and ExchangeRate-API.

Every client exposes ``fetch_rates() -> dict[str, float]`` where the dict is
``{"<FROM>_<BASE>": rate, ...}``. Per-pair metadata needed for the
``exchange_rates.json`` journal lives in ``self.last_meta`` after a successful
fetch. Failures are wrapped in :class:`ApiRequestError` with ``status_code``
and ``source`` filled in.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import requests

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.logging_config import get_parser_logger
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Common interface for parser-service HTTP clients."""

    name: str = "base"

    def __init__(self, config: ParserConfig) -> None:
        self.config = config
        self.logger = get_parser_logger()
        self.last_meta: dict[str, dict] = {}

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Return ``{"<FROM>_<BASE>": rate}`` for tracked currencies."""

    # ---- shared HTTP -------------------------------------------------------
    def _get(
        self, url: str, params: dict | None = None
    ) -> tuple[requests.Response, int]:
        """GET ``url`` with a timeout; return ``(response, elapsed_ms)``.

        Raises
        ------
        ApiRequestError
            On timeout, network error, or any HTTP status >= 400. 429 and 401
            get their own human-readable messages.
        """
        started = time.perf_counter()
        try:
            response = requests.get(
                url, params=params, timeout=self.config.REQUEST_TIMEOUT
            )
        except requests.exceptions.Timeout as exc:
            raise ApiRequestError(
                f"{self.name}: request timed out after {self.config.REQUEST_TIMEOUT}s",
                source=self.name,
            ) from exc
        except requests.exceptions.RequestException as exc:
            raise ApiRequestError(
                f"{self.name}: network error: {exc}", source=self.name
            ) from exc
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        if response.status_code == 429:
            raise ApiRequestError(
                f"{self.name}: rate limit exceeded (HTTP 429). Try again later.",
                status_code=429,
                source=self.name,
            )
        if response.status_code == 401:
            raise ApiRequestError(
                f"{self.name}: unauthorized (HTTP 401). Check API key.",
                status_code=401,
                source=self.name,
            )
        if response.status_code >= 400:
            raise ApiRequestError(
                f"{self.name}: HTTP {response.status_code} {response.reason}",
                status_code=response.status_code,
                source=self.name,
            )
        return response, elapsed_ms


class CoinGeckoClient(BaseApiClient):
    """Crypto rates from the public CoinGecko ``simple/price`` endpoint."""

    name = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Fetch crypto rates; return ``{"<CODE>_USD": rate}``."""
        ids = ",".join(
            self.config.CRYPTO_ID_MAP[code]
            for code in self.config.CRYPTO_CURRENCIES
            if code in self.config.CRYPTO_ID_MAP
        )
        base_lower = self.config.BASE_CURRENCY.lower()
        self.logger.info("Fetching from %s: ids=%s", self.name, ids)
        response, elapsed_ms = self._get(
            self.config.COINGECKO_URL,
            params={"ids": ids, "vs_currencies": base_lower},
        )
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiRequestError(
                f"{self.name}: invalid JSON response",
                status_code=response.status_code,
                source=self.name,
            ) from exc

        rates: dict[str, float] = {}
        meta: dict[str, dict] = {}
        for code, raw_id in self.config.CRYPTO_ID_MAP.items():
            entry = data.get(raw_id) or {}
            rate = entry.get(base_lower)
            if not isinstance(rate, (int, float)) or rate <= 0:
                self.logger.warning("%s: no valid rate for %s", self.name, code)
                continue
            pair = f"{code}_{self.config.BASE_CURRENCY}"
            rates[pair] = float(rate)
            meta[pair] = {
                "raw_id": raw_id,
                "request_ms": elapsed_ms,
                "status_code": response.status_code,
                "etag": response.headers.get("ETag"),
            }
        self.last_meta = meta
        self.logger.info("%s: parsed %d rates", self.name, len(rates))
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Fiat rates from ExchangeRate-API (v6, key from env).

    The v6 endpoint returns rates under ``conversion_rates``. We fall back to
    ``rates`` for compatibility with the sample response in the assignment
    handout, which uses the older shape.
    """

    name = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Fetch fiat rates; return ``{"<CODE>_USD": rate}``."""
        key = self.config.EXCHANGERATE_API_KEY
        if not key:
            raise ApiRequestError(
                "ExchangeRate-API key is not configured "
                "(EXCHANGERATE_API_KEY env var / .env)",
                source=self.name,
            )
        url = (
            f"{self.config.EXCHANGERATE_API_URL}/{key}"
            f"/latest/{self.config.BASE_CURRENCY}"
        )
        self.logger.info(
            "Fetching from %s: base=%s", self.name, self.config.BASE_CURRENCY
        )
        response, elapsed_ms = self._get(url)
        try:
            data = response.json()
        except ValueError as exc:
            raise ApiRequestError(
                f"{self.name}: invalid JSON response",
                status_code=response.status_code,
                source=self.name,
            ) from exc
        if data.get("result") != "success":
            raise ApiRequestError(
                f"{self.name}: API returned result={data.get('result')!r}",
                status_code=response.status_code,
                source=self.name,
            )

        # v6 uses "conversion_rates"; the handout sample uses "rates".
        raw_rates = data.get("conversion_rates") or data.get("rates") or {}
        rates: dict[str, float] = {}
        meta: dict[str, dict] = {}
        for code in self.config.FIAT_CURRENCIES:
            if code == self.config.BASE_CURRENCY:
                continue
            raw = raw_rates.get(code)
            if not isinstance(raw, (int, float)) or raw <= 0:
                self.logger.warning("%s: no valid rate for %s", self.name, code)
                continue
            pair = f"{code}_{self.config.BASE_CURRENCY}"
            # API returns "1 BASE = X code"; we want "1 code = ? BASE".
            rates[pair] = float(1.0 / raw)
            meta[pair] = {
                "raw_id": code,
                "request_ms": elapsed_ms,
                "status_code": response.status_code,
                "etag": response.headers.get("ETag"),
            }
        self.last_meta = meta
        self.logger.info("%s: parsed %d rates", self.name, len(rates))
        return rates
