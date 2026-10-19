"""FR-PA-10 security round 1: a hostile ask costs no more than a plain one (NFKC amplification, many splits)."""

from __future__ import annotations

import time

from tilo_api.assistant import updates
from tilo_api.assistant.config import load_assistant_config
from tilo_api.assistant.core import Ask

ROWS = 200
FDFA = "ﷺ"  # NFKC expands it 18 times


def _rows() -> list[dict]:
    return [{"ref": {"kind": "work_item", "id": f"wi_{i}"}, "title": FDFA * 140, "reason": "open"} for i in range(ROWS)]


def _ask(question: str) -> Ask:
    return Ask("u_sam", "org_tilo", "2026-10-07T09:00:00.000Z", question, None, None)


def _count_keys(monkeypatch) -> list[int]:
    calls = [0]
    real = updates.question_key

    def spy(text: str) -> str:
        calls[0] += 1
        return real(text)

    monkeypatch.setattr(updates, "question_key", spy)
    return calls


def test_FR_PA_10_cost_many_prepositions_are_refused_before_any_title_is_read(monkeypatch):
    config, calls = load_assistant_config(), _count_keys(monkeypatch)
    key = ("snooze qqq " + "in " * 160)[:500]
    started = time.monotonic()
    assert updates.match_update(key, _rows(), _ask(key), None, config, "UTC") is None  # type: ignore[arg-type]
    assert calls[0] == 0
    assert time.monotonic() - started < 10


def test_FR_PA_10_cost_titles_are_normalised_once_per_row_however_many_splits(monkeypatch):
    config, calls = load_assistant_config(), _count_keys(monkeypatch)
    key = "snooze qqq in in in"  # the most prepositions a rule reads: four splits, none names a row
    started = time.monotonic()
    assert updates.match_update(key, _rows(), _ask(key), None, config, "UTC") is None  # type: ignore[arg-type]
    assert calls[0] <= ROWS
    assert time.monotonic() - started < 10
