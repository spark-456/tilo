"""FR-MEM-05 (PRD 16.1 rule 4: secrets never enter logs): a log line carries no secret.

NFR-26's JSON log formatter (`packages/logging`, `tilo_logging`) is not on this base (it is on unmerged
feat/NFR-26-structured-logs), so these tests pin the part FR-MEM-05 owns: `tilo_redact.RedactingFilter`, a plain
`logging.Filter` with no arguments, attached to a handler. It rewrites the message (after %-args are applied), the
traceback text and never drops or raises. A JSON formatter built on `logging.Formatter.format` then emits no secret;
the test's own formatter below stands in for it. When NFR-26 lands its ticket must attach this filter (follow-up).
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from _redact_samples_lib import FIXED_TAIL, build, leaks
from tilo_redact import REDACTED, RedactingFilter


class _JsonLine(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({"severity": record.levelname, "message": super().format(record)})


@pytest.fixture
def log():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_JsonLine("%(message)s"))
    handler.addFilter(RedactingFilter())
    logger = logging.Logger("fr_mem_05", logging.DEBUG)
    logger.addHandler(handler)
    return logger, stream


def _line(stream: io.StringIO) -> dict:
    return json.loads(stream.getvalue().strip().split("\n")[-1])


def test_FR_MEM_05_filter_is_a_standard_logging_filter():
    assert isinstance(RedactingFilter(), logging.Filter)


@pytest.mark.parametrize(
    "kind", ["google_oauth_access", "bearer_bare", "password_equals", "jwt", "pem_private_key", "card_spaced"]
)
def test_FR_MEM_05_a_secret_in_a_log_message_is_redacted_in_the_json_line(log, kind):
    logger, stream = log
    sample = build(kind, FIXED_TAIL)
    logger.warning("call failed for run r_abcdef: " + sample.text)
    raw = stream.getvalue()
    assert leaks(raw, sample) == [] and leaks(_line(stream)["message"], sample) == []
    assert _line(stream)["severity"] == "WARNING" and "call failed for run r_abcdef:" in _line(stream)["message"]


def test_FR_MEM_05_a_secret_in_a_percent_argument_or_a_non_string_message_is_redacted(log):
    logger, stream = log
    sample = build("api_secret_key", FIXED_TAIL)
    logger.info("key was %s for %d calls", sample.text, 3)
    assert leaks(stream.getvalue(), sample) == [] and "for 3 calls" in _line(stream)["message"]
    logger.info({"password": "Zq" + FIXED_TAIL[:12], "n": 1})
    assert "Zq" + FIXED_TAIL[:12] not in stream.getvalue()


def test_FR_MEM_05_a_secret_in_an_exception_message_is_redacted_from_the_traceback(log):
    logger, stream = log
    sample = build("google_oauth_access", FIXED_TAIL)
    try:
        raise RuntimeError("refresh refused for " + sample.text)
    except RuntimeError:
        logger.exception("token refresh failed")
    assert leaks(stream.getvalue(), sample) == []
    assert "RuntimeError" in _line(stream)["message"] and "token refresh failed" in _line(stream)["message"]


def test_FR_MEM_05_a_clean_message_passes_through_unchanged_and_is_never_dropped(log):
    logger, stream = log
    logger.info("run %s finished in %d ms, %s", "r_abcdef", 12, REDACTED)
    assert _line(stream)["message"] == f"run r_abcdef finished in 12 ms, {REDACTED}"
    assert RedactingFilter().filter(logging.LogRecord("x", logging.INFO, "f", 1, "m %s", ("a",), None)) is True
