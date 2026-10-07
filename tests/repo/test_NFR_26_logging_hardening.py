"""NFR-26 hardening: `configure_logging` keeps libraries that log outbound URLs at INFO quiet, and is idempotent."""

from __future__ import annotations

import io
import logging

from tilo_logging import configure_logging


def test_NFR_26_httpx_and_httpcore_do_not_log_below_warning_and_a_second_call_adds_no_handler() -> None:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    levels = {name: logging.getLogger(name).level for name in ("httpx", "httpcore")}
    try:
        stream = io.StringIO()
        configure_logging(stream=stream)
        configure_logging(stream=stream)
        logging.getLogger("httpx").info("HTTP Request: GET https://example.test/?q=secret")
        logging.getLogger("httpcore.http11").info("connect")
        assert stream.getvalue() == ""
        logging.getLogger("httpx").warning("kept")
        assert stream.getvalue().count("\n") == 1
        ours = [h for h in root.handlers if type(h).__name__ == "_JsonHandler"]
        assert len(ours) == 1 and all(
            h in root.handlers for h in handlers if h not in ours and type(h).__name__ != "_JsonHandler"
        )
    finally:
        root.handlers[:], root.level = handlers, level
        for name, lvl in levels.items():
            logging.getLogger(name).setLevel(lvl)
