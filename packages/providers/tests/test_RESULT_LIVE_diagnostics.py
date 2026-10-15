"""RESULT-LIVE: Cloud Run prints a caught error without its logger name, so a live `FileNotFoundError` could not be
traced to its code. The line now names the catching module and the raising file and line, never the error text."""

from __future__ import annotations

import inspect
import logging

from tilo_providers.diagnostics import log_caught


def _open_missing() -> None:
    raise FileNotFoundError("/private/owner/path.json")


def test_RESULT_LIVE_a_caught_error_names_where_it_was_raised_and_never_its_text(caplog):
    line = inspect.getsourcelines(_open_missing)[1] + 1
    try:
        _open_missing()
    except FileNotFoundError as error:
        with caplog.at_level(logging.ERROR):
            log_caught(error, "tilo_api.web_tools", {"unit": {"id": "U4"}})

    (record,) = caplog.records
    assert record.getMessage() == (
        "caught error run=- unit=U4 world=- exception=FileNotFoundError"
        f" in=tilo_api.web_tools raised=test_RESULT_LIVE_diagnostics.py:{line}"
    )
    assert "private" not in caplog.text
