"""SEC-10 (SEC-SWEEP-1, #570 follow-up): a caller with no App Check token costs one log line a minute, not one per
request. The line names how many were left out since the previous one; the token itself is never logged."""

from __future__ import annotations

import logging

from tilo_api import appcheck


def _reset() -> None:
    appcheck._missing_log.update(at=float("-inf"), skipped=0)


def test_SEC_10_a_flood_of_missing_tokens_is_one_line_a_minute_with_a_count(caplog):
    _reset()
    clock = {"t": 1000.0}
    with caplog.at_level(logging.WARNING, logger="tilo_api.appcheck"):
        for _ in range(500):
            appcheck._warn_missing(lambda: clock["t"])
        assert len(caplog.records) == 1
        clock["t"] += appcheck._MISSING_LOG_EVERY_S + 1
        appcheck._warn_missing(lambda: clock["t"])
    assert len(caplog.records) == 2
    assert "499 more since the last line" in caplog.records[1].getMessage()
    assert "reason=missing" in caplog.records[0].getMessage()


def test_SEC_10_the_first_missing_token_is_always_logged(caplog):
    _reset()
    with caplog.at_level(logging.WARNING, logger="tilo_api.appcheck"):
        appcheck._warn_missing(lambda: 0.0)
    assert len(caplog.records) == 1
