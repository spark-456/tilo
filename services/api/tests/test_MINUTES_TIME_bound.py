"""MINUTES-TIME (owner's live test, 21 Oct): "Analyze minutes" took 501 s. Each hung Gemini call waited out its 120 s
request timeout, then the router retried. The owner's minutes request now gives the real router a deadline (PL-03
`Deadline`): one model call (its retries and the role's configured fallback included) at most `ANALYSIS_CALL_SECONDS`,
the whole analysis at most `ANALYSIS_TOTAL_SECONDS`, so a hung primary hands over to the fallback in time. Running out
is one plain refusal, 503 `analysis_timed_out`, that the web says with Try again. Spend holds and screening are
unchanged. Offline doubles only."""

import json
import time
from types import SimpleNamespace

import pytest
from _ppl11a_lib import OWNER
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import live, owner_call, run  # noqa: F401
from tilo_api import deps
from tilo_api.meeting_allowance import AllowanceRouter
from tilo_api.meeting_analysis_mode import ANALYSIS_CALL_SECONDS, ANALYSIS_TOTAL_SECONDS, FIRST_SHARE
from tilo_api.people_writes import Refusal
from tilo_providers.router import RouterDeadlineError


class Bounded:
    """The real Router's shape for this call (it takes `deadline`), answering or running out of time per role."""

    def __init__(self, doc, late=(), verdict=None):
        self.doc, self.late, self.verdict, self.calls = doc, set(late), verdict, []

    def generate(self, role, request, *, budget, deadline=None):
        self.calls.append((role, deadline, time.monotonic()))
        if role in self.late:
            raise RouterDeadlineError(f"PL-03: role {role!r} ran out of time", [])
        text = json.dumps(self.doc if role == "meeting_analyst" else self.verdict)
        return SimpleNamespace(response=SimpleNamespace(text=text), outcome="ok", budget=0.5)


def bounded(c, monkeypatch, **kw):
    router = Bounded(c.router.doc, **kw)
    monkeypatch.setattr(deps, "router_for_mode", lambda mode: router)
    return router


def test_MINUTES_TIME_each_model_call_gets_a_bounded_deadline_with_a_fallback_share(owner_call, monkeypatch):  # noqa: F811
    c = owner_call
    live(c, monkeypatch)
    router = bounded(c, monkeypatch)
    started = time.monotonic()
    assert run(c)["status"] == "minuted"
    (role, deadline, at), *_ = router.calls
    assert role == "meeting_analyst" and deadline is not None and deadline.first_share == FIRST_SHARE
    assert 0 < deadline.at - at <= ANALYSIS_CALL_SECONDS
    assert deadline.at <= started + ANALYSIS_TOTAL_SECONDS + 1
    assert ANALYSIS_CALL_SECONDS < ANALYSIS_TOTAL_SECONDS <= 90


def test_MINUTES_TIME_an_analyst_that_runs_out_of_time_is_one_plain_retryable_refusal(owner_call, monkeypatch):  # noqa: F811
    c = owner_call
    live(c, monkeypatch)
    bounded(c, monkeypatch, late={"meeting_analyst"})
    with pytest.raises(Refusal) as refused:
        run(c)
    assert (refused.value.status_code, refused.value.detail) == (503, "analysis_timed_out")
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None
    assert c.ledger.spent_minor(OWNER) == 2 * c.caps.unit_reserve_minor  # the screen and the call stay charged


def test_MINUTES_TIME_a_late_verifier_leaves_decisions_unverified_and_still_makes_minutes(owner_call, monkeypatch):  # noqa: F811
    c = owner_call
    live(c, monkeypatch)
    c.router.doc["decisions"][0]["text"] = "The group chose to proceed."  # not a literal line: needs the verifier
    router = bounded(c, monkeypatch, late={"verifier"})
    result = run(c)
    assert result["status"] == "minuted" and [r[0] for r in router.calls] == ["meeting_analyst", "verifier"]


def test_MINUTES_TIME_a_late_verifier_that_the_summary_needs_is_the_timeout_refusal(owner_call, monkeypatch):  # noqa: F811
    c = owner_call
    live(c, monkeypatch)
    quote = c.router.doc["decisions"][0]["evidence"][0]
    c.router.doc["summary"] = [{"text": "The team agreed the plan.", "evidence": [quote]}]  # summary must be verified
    bounded(c, monkeypatch, late={"verifier"})
    with pytest.raises(Refusal) as refused:
        run(c)
    assert refused.value.detail == "analysis_timed_out"
    assert c.rig.stored("meetings", "mt_q4_plan")["minutes"] is None


def test_MINUTES_TIME_the_allowance_wrapper_lets_a_timeout_through_never_as_allowance_capped():
    class Late:
        def generate(self, role, request, *, budget):
            raise RouterDeadlineError("PL-03: role 'meeting_analyst' ran out of time", [])

    ledger = SimpleNamespace(reserve=lambda *a: "hold", release=lambda hold: None, commit=lambda hold, n: None)
    wrapper = AllowanceRouter(Late(), ledger=ledger, user=OWNER, clock=lambda: "2026-10-21T04:00:00.000Z", cap=10,
                              budget=5)  # fmt: skip
    with pytest.raises(RouterDeadlineError):
        wrapper.generate("meeting_analyst", object(), budget=2)
    assert wrapper.left == 3  # the sent budget stays consumed (conservative), as for any failed call
