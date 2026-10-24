"""Periodic scheduler for :class:`RatesUpdater`.

Optional — the rubric mentions "по расписанию или по запросу". The CLI runs it
on demand; this module provides the periodic variant.
"""

from __future__ import annotations

import time

from valutatrade_hub.logging_config import get_parser_logger
from valutatrade_hub.parser_service.updater import RatesUpdater


def run_scheduler(updater: RatesUpdater, interval_seconds: int) -> None:
    """Run ``updater.run_update()`` every ``interval_seconds`` until Ctrl+C."""
    logger = get_parser_logger()
    logger.info("Scheduler started: interval=%ss", interval_seconds)
    try:
        while True:
            try:
                summary = updater.run_update()
                logger.info(
                    "Scheduled update: %d rates, errors=%d",
                    summary["total"],
                    len(summary["errors"]),
                )
            except Exception as exc:  # noqa: BLE001 — keep the loop alive
                logger.exception("Scheduled update crashed: %s", exc)
            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
