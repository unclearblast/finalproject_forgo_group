"""Coordinator for parser-service updates.

``RatesUpdater.run_update()`` polls every client, merges the results, writes the
current snapshot to ``rates.json`` and appends new journal entries to
``exchange_rates.json``. A failure in one client never stops the others
(resilience is a rubric requirement).
"""

from __future__ import annotations

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.utils import parse_iso, utcnow_iso
from valutatrade_hub.logging_config import get_parser_logger
from valutatrade_hub.parser_service.api_clients import BaseApiClient
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Runs a single update cycle across all registered API clients."""

    def __init__(
        self, clients: list[BaseApiClient], storage: RatesStorage
    ) -> None:
        self.clients = clients
        self.storage = storage
        self.logger = get_parser_logger()

    # ---- helpers -----------------------------------------------------------
    @staticmethod
    def _matches_source(client: BaseApiClient, flt: str) -> bool:
        f = flt.strip().lower().replace("_", "-")
        name = client.name.lower().replace("-", "")
        if f in {"exchangerate", "exchangerate-api", "exchangerateapi"}:
            return "exchangerate" in name
        if f == "coingecko":
            return "coingecko" in name
        return f == name

    @staticmethod
    def _make_history_record(
        pair: str, rate: float, source: str, timestamp: str, meta: dict | None
    ) -> dict:
        from_cur, _, to_cur = pair.partition("_")
        return {
            "id": f"{from_cur}_{to_cur}_{timestamp}",
            "from_currency": from_cur,
            "to_currency": to_cur,
            "rate": float(rate),
            "timestamp": timestamp,
            "source": source,
            "meta": meta or {},
        }

    @staticmethod
    def _is_fresher(new_iso: str, existing_iso: str | None) -> bool:
        if not existing_iso:
            return True
        try:
            return parse_iso(new_iso) > parse_iso(existing_iso)
        except ValueError:
            return True

    # ---- public API --------------------------------------------------------
    def run_update(self, source_filter: str | None = None) -> dict:
        """Run one update cycle.

        Parameters
        ----------
        source_filter:
            Optional client-name filter (``coingecko`` / ``exchangerate`` /
            ``exchangerate-api``), case-insensitive.

        Returns
        -------
        dict
            ``{"total": int, "sources": [...], "errors": [...], "last_refresh": iso}``
        """
        self.logger.info(
            "Starting rates update (clients=%s, filter=%r)",
            [c.name for c in self.clients],
            source_filter,
        )

        current = self.storage.load_rates()
        pairs: dict[str, dict] = dict(current.get("pairs") or {})

        total_new = 0
        errors: list[dict] = []
        succeeded: list[str] = []
        new_history: list[dict] = []

        for client in self.clients:
            if source_filter and not self._matches_source(client, source_filter):
                self.logger.info("Skipping %s (filter)", client.name)
                continue
            self.logger.info("Fetching from %s...", client.name)
            try:
                fetched = client.fetch_rates()
            except ApiRequestError as exc:
                self.logger.error("Failed to fetch from %s: %s", client.name, exc)
                errors.append(
                    {
                        "source": client.name,
                        "error": str(exc),
                        "status_code": exc.status_code,
                    }
                )
                continue
            except Exception as exc:  # noqa: BLE001 — never abort the cycle
                self.logger.exception(
                    "Unexpected error from %s: %s", client.name, exc
                )
                errors.append({"source": client.name, "error": str(exc)})
                continue

            now = utcnow_iso()
            meta_map = getattr(client, "last_meta", {}) or {}
            accepted = 0
            for pair, rate in fetched.items():
                if not isinstance(rate, (int, float)) or rate <= 0:
                    continue
                existing = pairs.get(pair)
                if existing and not self._is_fresher(now, existing.get("updated_at")):
                    continue
                pairs[pair] = {
                    "rate": float(rate),
                    "updated_at": now,
                    "source": client.name,
                }
                new_history.append(
                    self._make_history_record(
                        pair, float(rate), client.name, now, meta_map.get(pair)
                    )
                )
                accepted += 1
            self.logger.info("%s: OK (%d rates)", client.name, accepted)
            if accepted:
                total_new += accepted
                succeeded.append(client.name)

        last_refresh = utcnow_iso()
        if new_history:
            self.storage.save_rates(pairs, last_refresh)
            self.storage.append_history(new_history)
        else:
            self.logger.info("No new rates to write")

        summary = {
            "total": total_new,
            "sources": succeeded,
            "errors": errors,
            "last_refresh": last_refresh,
        }
        if errors:
            self.logger.warning("Update completed with %d error(s)", len(errors))
        else:
            self.logger.info("Update successful: %d new rates", total_new)
        return summary
