"""FR-PA-15 (PRD addendum; FR-PA-05, PE-12, PRD 10.2): proactive panel messages are `alert.raised` nudges the sweeper
offers, shown only inside 09:00 to 18:00 Asia/Kolkata, at most 5 a person a day, with a snooze of 1 hour or until
tomorrow. A model never decides to interrupt: the gate is code and templates. Fake clock throughout (`now` is passed);
nothing is sent and no model, provider or network is imported.
"""

from __future__ import annotations

import ast
import datetime as dt
import pathlib
import subprocess
import sys
from typing import Any

import pytest
from tilo_channels.nudges import MemoryNudgeStore, Nudge, NudgeGate, NudgeRules
from tilo_policy.schemas import conforms

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_channels"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
USER = "u_owner"


def _at(day: int, hh: int, mm: int = 0, ss: int = 0) -> dt.datetime:
    """A wall-clock time in Asia/Kolkata on 2026-10-<day>, as the aware datetime the gate is handed."""
    return dt.datetime(2026, 10, day, hh, mm, ss, tzinfo=IST)


class _Rig:
    def __init__(self, cap: int | None = None) -> None:
        self.parts: list[tuple[str, dict[str, Any]]] = []
        rules = NudgeRules() if cap is None else NudgeRules(daily_cap=cap)
        self.store = MemoryNudgeStore()
        self.gate = NudgeGate(rules=rules, store=self.store, emit=lambda u, p: self.parts.append((u, p)))

    def offer(self, item: str, now: dt.datetime, rule: str = "due_24h", user: str = USER) -> Any:
        return self.gate.offer(Nudge(user, item, rule), now=now)


def test_FR_PA_15_nothing_is_raised_outside_09_00_to_18_00_kolkata() -> None:
    rig = _Rig()

    assert rig.offer("wi_a", _at(12, 8, 59, 59)).status == "deferred"
    assert rig.offer("wi_a", _at(12, 18, 0, 0)).reason == "outside_window"  # end is exclusive
    assert rig.offer("wi_a", _at(12, 23, 30)).reason == "outside_window"
    assert rig.parts == []

    assert rig.offer("wi_a", _at(12, 9, 0, 0)).status == "raised"  # start is inclusive
    assert rig.offer("wi_b", _at(12, 17, 59, 59)).status == "raised"
    assert len(rig.parts) == 2
    # the same instant written in UTC is judged in the person's zone, never the server's
    utc = dt.datetime(2026, 10, 12, 3, 29, 59, tzinfo=dt.UTC)  # 08:59:59 IST
    assert rig.offer("wi_c", utc).reason == "outside_window"


def test_FR_PA_15_a_person_gets_at_most_five_a_day_and_the_count_resets_on_their_local_day() -> None:
    rig = _Rig()
    results = [rig.offer(f"wi_{n}", _at(12, 9, n)) for n in range(7)]

    assert [r.status for r in results] == ["raised"] * 5 + ["deferred"] * 2
    assert {r.reason for r in results[5:]} == {"cap"}
    assert len(rig.parts) == 5

    other = rig.offer("wi_other", _at(12, 10), user="u_second")  # the cap is per person
    assert other.status == "raised"
    next_day = rig.offer("wi_5", _at(13, 9, 0))  # a refused offer is still offerable the next local day
    assert next_day.status == "raised"


def test_FR_PA_15_the_cap_is_a_setting_not_a_constant() -> None:
    rig = _Rig(cap=2)
    statuses = [rig.offer(f"wi_{n}", _at(12, 10, n)).status for n in range(3)]
    assert statuses == ["raised", "raised", "deferred"]
    with pytest.raises(ValueError):
        NudgeRules(daily_cap=0)


def test_FR_PA_15_the_same_item_rule_and_day_raises_once_and_a_refusal_does_not_spend_it() -> None:
    rig = _Rig()
    assert rig.offer("wi_a", _at(12, 8, 0)).reason == "outside_window"  # not recorded as raised
    assert rig.offer("wi_a", _at(12, 9, 30)).status == "raised"
    again = rig.offer("wi_a", _at(12, 9, 31))
    assert (again.status, again.reason) == ("deferred", "duplicate")
    assert len(rig.parts) == 1
    assert rig.offer("wi_a", _at(12, 9, 32), rule="overdue").status == "raised"  # another rule is another nudge
    assert rig.offer("wi_a", _at(13, 9, 30)).status == "raised"  # another day is another nudge


def test_FR_PA_15_a_snoozed_nudge_returns_once_after_an_hour() -> None:
    rig = _Rig()
    first = rig.offer("wi_a", _at(12, 10, 0))
    assert first.alert_id is not None

    snoozed = rig.gate.snooze(USER, first.alert_id, "hour", now=_at(12, 10, 5))
    assert snoozed.status == "snoozed" and snoozed.until == "2026-10-12T05:35:00.000Z"  # 11:05 IST

    assert rig.gate.release(USER, now=_at(12, 11, 4, 59)) == []  # not yet
    back = rig.gate.release(USER, now=_at(12, 11, 5, 0))
    assert [r.status for r in back] == ["raised"] and back[0].alert_id == first.alert_id
    assert rig.gate.release(USER, now=_at(12, 11, 6)) == []  # once
    assert rig.gate.release(USER, now=_at(12, 15, 0)) == []
    assert len(rig.parts) == 2 and rig.parts[0][1]["id"] != rig.parts[1][1]["id"]  # a new event, not a rewrite


def test_FR_PA_15_snooze_until_tomorrow_returns_at_the_start_of_the_next_window_and_only_inside_it() -> None:
    rig = _Rig()
    first = rig.offer("wi_a", _at(12, 17, 30))
    assert first.alert_id is not None
    rig.gate.snooze(USER, first.alert_id, "hour", now=_at(12, 17, 40))  # due 18:40: outside the window

    assert rig.gate.release(USER, now=_at(12, 18, 45)) == []  # held, not dropped
    assert rig.gate.release(USER, now=_at(13, 8, 59)) == []
    back = rig.gate.release(USER, now=_at(13, 9, 0))
    assert [r.status for r in back] == ["raised"]
    assert rig.gate.release(USER, now=_at(13, 9, 1)) == []

    again = rig.gate.snooze(USER, first.alert_id, "tomorrow", now=_at(13, 9, 30))
    assert again.status == "snoozed" and again.until == "2026-10-14T03:30:00.000Z"  # 09:00 IST on the 14th
    assert rig.gate.release(USER, now=_at(13, 23, 0)) == []
    assert len(rig.gate.release(USER, now=_at(14, 9, 0))) == 1


def test_FR_PA_15_a_returning_nudge_counts_against_the_cap_and_waits_when_the_cap_is_spent() -> None:
    rig = _Rig(cap=2)
    first = rig.offer("wi_a", _at(12, 9, 0))
    assert first.alert_id is not None
    rig.gate.snooze(USER, first.alert_id, "hour", now=_at(12, 9, 1))
    assert rig.offer("wi_b", _at(12, 9, 30)).status == "raised"  # the second of two

    assert rig.gate.release(USER, now=_at(12, 11, 0)) == []  # cap spent today: held
    assert len(rig.gate.release(USER, now=_at(13, 9, 0))) == 1  # tomorrow: returns, once
    assert rig.gate.release(USER, now=_at(13, 9, 5)) == []


def test_FR_PA_15_snooze_refuses_an_unknown_other_persons_or_bad_choice() -> None:
    rig = _Rig()
    first = rig.offer("wi_a", _at(12, 10, 0))
    assert first.alert_id is not None

    assert rig.gate.snooze("u_second", first.alert_id, "hour", now=_at(12, 10, 1)).status == "refused"
    assert rig.gate.snooze(USER, "01JB5VQ0000000000000000000", "hour", now=_at(12, 10, 1)).status == "refused"
    with pytest.raises(ValueError):
        rig.gate.snooze(USER, first.alert_id, "next week", now=_at(12, 10, 1))
    assert rig.gate.release(USER, now=_at(12, 23, 0)) == []  # nothing was snoozed


def test_FR_PA_15_the_event_is_a_registered_alert_raised_nudge_with_template_text_only() -> None:
    rig = _Rig()
    result = rig.offer("wi_a", _at(12, 10, 0))
    assert result.status == "raised"

    ((user, part),) = rig.parts
    assert user == USER and part["type"] == "alert.raised" and part["severity"] == "nudge"
    assert part["actor"] == "system" and part["target"] == USER and part["authz"] is None
    assert part["vis"] == [] and part["data"] == {"alert_id": result.alert_id, "card_id": None}
    assert conforms("events/data/alert.raised.schema.json", part["data"])
    assert conforms("common.schema.json#/$defs/ulid", part["id"])
    assert part["summary"] == "A work item is due within 24 hours." and "wi_a" not in part["summary"]
    assert rig.gate.item_of(USER, result.alert_id) == "wi_a"  # the panel finds the item server-side
    assert rig.gate.item_of("u_second", result.alert_id) is None


def test_FR_PA_15_a_failed_emit_leaves_nothing_recorded_and_the_retry_has_the_same_event_id() -> None:
    seen: list[str] = []
    fail = [True]

    def emit(user: str, part: dict[str, Any]) -> None:
        seen.append(part["id"])
        if fail[0]:
            raise RuntimeError("event log down")

    gate = NudgeGate(rules=NudgeRules(), store=MemoryNudgeStore(), emit=emit)
    with pytest.raises(RuntimeError):
        gate.offer(Nudge(USER, "wi_a", "due_24h"), now=_at(12, 10, 0))
    fail[0] = False
    assert gate.offer(Nudge(USER, "wi_a", "due_24h"), now=_at(12, 10, 1)).status == "raised"
    assert len(seen) == 2 and seen[0] == seen[1]  # one id: the writer dedupes a commit-then-raise (EV-10)


def test_FR_PA_15_only_a_closed_set_of_templated_rules_and_plain_ids_are_accepted() -> None:
    rig = _Rig()
    for bad in (
        Nudge(USER, "wi_a", "ask the model"),
        Nudge(USER, "wi a\n", "due_24h"),
        Nudge("not a user", "wi_a", "due_24h"),
    ):
        with pytest.raises(ValueError):
            rig.gate.offer(bad, now=_at(12, 10, 0))
    with pytest.raises(ValueError):
        rig.gate.offer(Nudge(USER, "wi_a", "due_24h"), now=dt.datetime(2026, 10, 12, 10, 0))  # naive clock
    assert rig.parts == []


def test_FR_PA_15_the_nudge_path_imports_no_provider_model_or_network_client() -> None:
    source = (SRC / "nudges.py").read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0] if node.level == 0 else "tilo_channels")
    banned = {"tilo_providers", "anthropic", "openai", "google", "httpx", "requests", "urllib", "socket"}
    assert imported & banned == set()

    # the whole import closure of the module, in a fresh interpreter
    code = (
        "import sys, tilo_channels.nudges;"
        "print(sorted(m for m in sys.modules if m.split('.')[0] in "
        "('tilo_providers','anthropic','openai','google','httpx','requests')))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
    # and the sibling modules that would reach a model are not among its tilo_channels imports
    siblings = {n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom) and n.level == 1}
    assert not siblings & {"triage", "drafting", "autopilot", "meeting_followup"}


def test_FR_PA_15_the_defaults_are_the_prd_window_and_cap_and_come_from_config_personal_yaml() -> None:
    rules = NudgeRules.load()
    assert (rules.window_start, rules.window_end, rules.zone, rules.daily_cap) == ("09:00", "18:00", "Asia/Kolkata", 5)
    assert rules == NudgeRules()
