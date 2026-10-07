"""tilo_logging: one JSON object per log line, with run, world and trace ids (NFR-26)."""

from __future__ import annotations

import json
import logging
import sys
from typing import IO

from tilo_logging.context import current

__all__ = ["configure_logging"]

TRACE_KEY = "logging.googleapis.com/trace"


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, str] = {"severity": record.levelname, "message": record.getMessage(), "logger": record.name}
        for key, value in current().items():
            line[TRACE_KEY if key == "trace" else key] = value
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        return json.dumps(line)  # ensure_ascii: newlines and any unicode stay inside one line


class _JsonHandler(logging.Handler):
    """Writes to `stream`, or to whatever `sys.stdout` is at the time (pytest swaps it per test)."""

    def __init__(self, stream: IO[str] | None) -> None:
        super().__init__()
        self._stream = stream
        self.setFormatter(_JsonFormatter())

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stream = self._stream or sys.stdout
            stream.write(self.format(record) + "\n")
            stream.flush()
        except Exception:
            self.handleError(record)


def configure_logging(stream: IO[str] | None = None, level: int = logging.INFO) -> None:
    """Leave exactly one Tilo JSON handler on the root logger. Idempotent: it replaces only its own handler, so
    handlers someone else installed (pytest's caplog, for one) stay."""
    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _JsonHandler)]:
        root.removeHandler(handler)
    root.addHandler(_JsonHandler(stream))
    root.setLevel(level)
