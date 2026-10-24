"""Small helpers shared across core modules."""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow_iso() -> str:
    """Return the current UTC time as ISO-8601 with a ``Z`` suffix."""
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(timestamp: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware UTC datetime.

    Accepts both the ``Z`` suffix and ``+00:00`` style offsets.
    """
    normalized = timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_stale(updated_at: str | None, ttl_seconds: int) -> bool:
    """Return ``True`` if ``updated_at`` is missing, malformed, or older than ``ttl_seconds``."""
    if not updated_at:
        return True
    try:
        delta = datetime.now(tz=UTC) - parse_iso(updated_at)
    except ValueError:
        return True
    return delta.total_seconds() > ttl_seconds
