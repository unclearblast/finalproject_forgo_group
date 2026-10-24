"""Cross-cutting decorators for ValutaTrade Hub."""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from valutatrade_hub.logging_config import get_logger

F = TypeVar("F", bound=Callable[..., Any])

_REPR_MAX = 80


def _short(value: Any, max_len: int = _REPR_MAX) -> str:
    try:
        text = repr(value)
    except Exception:  # noqa: BLE001 — defensive against broken __repr__
        text = f"<unreprable {type(value).__name__}>"
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _render_call(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    pieces = [_short(a) for a in args]
    pieces.extend(f"{k}={_short(v)}" for k, v in kwargs.items())
    return "(" + ", ".join(pieces) + ")"


def log_action(func: F) -> F:
    """Log entry, exit, duration, and exceptions of the wrapped callable."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        logger = get_logger(func.__module__.rsplit(".", 1)[-1])
        rendered = _render_call(args, kwargs)
        logger.info("ENTER %s%s", func.__qualname__, rendered)
        started = time.perf_counter()
        try:
            result = func(*args, **kwargs)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger.exception(
                "FAIL  %s in %.1f ms: %s: %s",
                func.__qualname__,
                elapsed_ms,
                type(exc).__name__,
                exc,
            )
            raise
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logger.info(
            "EXIT  %s in %.1f ms -> %s",
            func.__qualname__,
            elapsed_ms,
            _short(result),
        )
        return result

    return wrapper  # type: ignore[return-value]
