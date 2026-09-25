"""tilo_connectors._time — RFC 3339 (common.schema.json#/$defs/timestamp) helpers, millisecond
precision, always "...Z" (so plain string comparison already sorts chronologically; only OB-02's
created_at + undo_window_s == scheduled_at check needs real arithmetic)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def parse_ts(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"not an RFC 3339 UTC timestamp: {value!r}")
    return datetime.strptime(value[:-1], "%Y-%m-%dT%H:%M:%S.%f").replace(tzinfo=UTC)


def format_ts(dt: datetime) -> str:
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def add_seconds(value: str, seconds: float) -> str:
    return format_ts(parse_ts(value) + timedelta(seconds=seconds))
