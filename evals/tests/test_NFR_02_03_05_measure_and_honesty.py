"""NFR-02, NFR-03, NFR-05 (PRD 17.1): the latency measurement harness, `tilo_evals.latency.measure(n)`.

PRD targets (17.1): NFR-02 intake to first brief chips <= 4 s p50; NFR-03 intake to approaches (EV-02) <= 12 s p50 and
<= 25 s p95; NFR-05 event emitted to rendered <= 1 s p95. FR-INT-01: "a task appears with brief chips in <= 4 s p50".

What this measures, and no more: Tilo's OWN overhead, in process, on the real tilo-api app with the dev models file (a
deterministic fake Director) and the in-memory store. It is never a model, network or cloud figure: the report says
`scope: local_overhead_fake_providers`, `live: None`, and claims nothing live (the user's later, switched live run on
tilo-dev is out of scope and would be a different report).

The seams (see _latency_lib.py for the full pin):
- NFR-02: `POST /intake` (text and 3 files, FR-INT-01) until its response; the brief chips are the response's `brief`.
- NFR-03: that intake, then `POST /tasks/{id}/answers` (every question skipped), then `GET /tasks/{id}/approaches`
  until approaches come back.
- NFR-05: an event appended through the dev event writer until a `GET /worlds/{id}/events` response holds it.

NFR-05 render half: NOT measured here. The report stops at client receipt (the server half of "emitted -> rendered").
The render half needs a Playwright run against a live tilo-api (its address is fixed at 127.0.0.1:8080 and its own
Vite, as the cp2 project does), a new Playwright project and config entry, and a DOM marker for "this event is
drawn"; the existing e2e flows replay fixtures at their own speed, which is not event-to-pixel latency. Also worth
the builder's attention: `apps/web/src/api/http.ts` polls events every 1000 ms by default, so the client alone can
spend the whole 1 s p95 budget before it renders. That is a client finding for a later ticket, not a harness defect.

Ambiguities resolved (PRD gives no more): the NFR-05 timer starts just before `append` (the append is part of
"emitted", the conservative reading); NFR-03 includes skipping every question (no human think time, which no
fake can measure); "the report says it stops at client receipt" is a `note` on the NFR-05 entry, because `scope` is
always the one exact label.
"""

import functools
import os
import re

import pytest
from _latency_lib import (
    BUDGETS,
    ENTRY_KEYS,
    IDS,
    REFUSING_ENV,
    SCOPE,
    Clock,
    RequestSpy,
    _offline_env,  # noqa: F401  (autouse: no live switch, no network)
    is_finite_number,
    latency,
    slow,
    walk,
)

N = 20  # "about 20": enough for a p95 that is not just the maximum, fast enough for every run


@functools.cache
def _report20() -> dict:
    """One real 20-sample run shared by the budget and honesty tests (the env is clean: the autouse fixture runs
    first, and `measure` is told to refuse otherwise)."""
    return latency().measure(N)


# ---- report shape ---------------------------------------------------------------------------------------------


def test_NFR_02_report_has_one_entry_per_measure_with_the_agreed_keys():
    report = latency().measure(3)

    assert set(report) >= set(IDS)
    for nfr in IDS:
        entry = report[nfr]
        assert set(entry) >= ENTRY_KEYS, f"{nfr}: {sorted(entry)}"
        assert entry["n"] == 3, f"{nfr}: one sample per requested run"
        assert is_finite_number(entry["p50_ms"]) and is_finite_number(entry["p95_ms"])
        assert 0 < entry["p50_ms"] <= entry["p95_ms"], f"{nfr}: a real duration, never 0 and p50 <= p95"


def test_NFR_03_report_budgets_are_the_prd_numbers():
    report = _report20()

    for nfr, budget in BUDGETS.items():
        assert report[nfr]["budget"] == budget, f"{nfr} budget is PRD 17.1: {budget}"


def test_NFR_05_report_n_is_the_requested_sample_count():
    assert all(_report20()[nfr]["n"] == N for nfr in IDS)


@pytest.mark.parametrize("bad", [0, -1])
def test_NFR_02_measure_needs_at_least_one_sample(bad):
    with pytest.raises(ValueError):
        latency().measure(bad)


# ---- acceptance: local overhead fits inside each budget (n about 20) -----------------------------------------


def test_NFR_02_intake_to_first_brief_chips_p50_within_4_s():
    entry = _report20()["NFR-02"]

    assert entry["n"] == N
    assert entry["p50_ms"] <= 4000, f"NFR-02: p50 {entry['p50_ms']:.0f} ms must be <= 4000 ms"


def test_NFR_03_intake_to_approaches_p50_within_12_s_and_p95_within_25_s():
    entry = _report20()["NFR-03"]

    assert entry["n"] == N
    assert entry["p50_ms"] <= 12000, f"NFR-03: p50 {entry['p50_ms']:.0f} ms must be <= 12000 ms"
    assert entry["p95_ms"] <= 25000, f"NFR-03: p95 {entry['p95_ms']:.0f} ms must be <= 25000 ms"


def test_NFR_05_event_emitted_to_client_receipt_p95_within_1_s():
    entry = _report20()["NFR-05"]

    assert entry["n"] == N
    assert entry["p95_ms"] <= 1000, f"NFR-05: p95 {entry['p95_ms']:.0f} ms must be <= 1000 ms"


# ---- the timings sit at the real seams (a moved clock shows up exactly where the work is) -------------------


def test_NFR_02_timing_covers_the_intake_request_including_the_directors_brief(monkeypatch):
    from tilo_api import intake

    clock = Clock(monkeypatch)
    slow(monkeypatch, clock, intake, "extract_brief", 1500)  # the Director drafting the brief takes 1.5 s

    report = latency().measure(3)

    nfr02, nfr03 = report["NFR-02"], report["NFR-03"]
    assert 1500 <= nfr02["p50_ms"] <= 3500, "NFR-02 includes the 1.5 s the brief took, and little more"
    assert 1500 <= nfr02["p95_ms"] <= 3500
    assert nfr03["p50_ms"] >= 1500, "NFR-03 starts at intake too, so it includes the brief"


def test_NFR_03_timing_runs_to_the_approaches_and_nfr_02_stops_before_them(monkeypatch):
    from tilo_api import tasks

    clock = Clock(monkeypatch)
    slow(monkeypatch, clock, tasks, "propose_approaches", 6000)  # the Director proposing approaches takes 6 s

    report = latency().measure(3)

    nfr02, nfr03 = report["NFR-02"], report["NFR-03"]
    assert 6000 <= nfr03["p50_ms"] <= 9000, "NFR-03 includes the 6 s the approaches took, and little more"
    assert 6000 <= nfr03["p95_ms"] <= 9000
    assert nfr02["p50_ms"] < 3000, "chips are shown before approaches are proposed: NFR-02 must not include them"


def test_NFR_05_timing_includes_the_append_and_ends_at_client_receipt(monkeypatch):
    from tilo_api import dev

    clock = Clock(monkeypatch)
    slow(monkeypatch, clock, dev.DevEventWriter, "append", 300)  # the store write takes 300 ms (timer starts before it)

    report = latency().measure(3)

    nfr05 = report["NFR-05"]
    assert 300 <= nfr05["p95_ms"] <= 2300, "the 300 ms append is inside the sample, and nothing like seconds more"
    assert nfr05["p50_ms"] <= nfr05["p95_ms"]


def test_NFR_02_03_05_the_harness_drives_the_real_routes(monkeypatch):
    spy = RequestSpy(monkeypatch)

    latency().measure(3)

    assert spy.count("POST", "/intake") >= 3, f"intake is posted for every sample: {spy.requests[:6]}"
    assert spy.count("POST", "/tasks/", "/answers") >= 3, "the questions are answered (skipped) before approaches"
    assert spy.count("GET", "/tasks/", "/approaches") >= 3, "approaches are fetched the way the web client does"
    assert spy.count("GET", "/worlds/", "/events") >= 3, "events are read from GET /worlds/{id}/events"


def test_NFR_02_a_sample_that_gets_no_brief_is_never_timed_as_success(monkeypatch):
    from tilo_api import intake
    from tilo_planning.brief import BriefExtractionError

    def failing(*_args, **_kwargs):
        raise BriefExtractionError("no brief")

    monkeypatch.setattr(intake, "extract_brief", failing)  # intake answers 502 and shows no chips

    with pytest.raises(latency().LatencyError):
        latency().measure(2)


def test_NFR_03_a_sample_that_gets_no_approaches_is_never_timed_as_success(monkeypatch):
    from tilo_api import tasks
    from tilo_planning.approaches import ApproachProposalError

    def failing(*_args, **_kwargs):
        raise ApproachProposalError("none usable")

    monkeypatch.setattr(tasks, "propose_approaches", failing)  # the approaches route answers 502

    with pytest.raises(latency().LatencyError):
        latency().measure(2)


# ---- EFF-01: no live switch, no network, nothing left behind --------------------------------------------------


@pytest.mark.parametrize("variable", REFUSING_ENV)
def test_NFR_02_measure_refuses_when_live_or_deployed(monkeypatch, variable):
    monkeypatch.setenv(variable, "1")
    spy = RequestSpy(monkeypatch)

    with pytest.raises(latency().LatencyRefused):
        latency().measure(2)

    assert spy.requests == [], "refused before any request is made"


def test_NFR_02_measure_restores_the_environment_it_touched(monkeypatch):
    monkeypatch.setenv("TILO_DEV_UNIT_DELAY_S", "7")  # a value the harness may override while it runs

    latency().measure(2)

    assert "TILO_MODELS_FILE" not in os.environ, "the dev models file is selected for the run only"
    assert os.environ.get("TILO_DEV_UNIT_DELAY_S") == "7"
    assert not any(name in os.environ for name in REFUSING_ENV)


# ---- honesty: local overhead only, never a live number --------------------------------------------------------


def test_NFR_02_03_05_scope_is_always_the_local_overhead_label():
    report = _report20()

    assert [report[nfr]["scope"] for nfr in IDS] == [SCOPE] * 3
    assert SCOPE == "local_overhead_fake_providers"


def test_NFR_02_03_05_live_is_always_none():
    report = _report20()

    for nfr in IDS:
        assert "live" in report[nfr] and report[nfr]["live"] is None, f"{nfr}: no live figure exists"


def test_NFR_02_03_05_report_makes_no_live_or_cloud_claim_anywhere():
    """No key but the literal `live` mentions live, cloud, production or a real model, and no text says a number
    was measured on one. Every number in the report is a local, in-process figure."""
    forbidden_key = ("live", "cloud", "tilo-dev", "tilo_dev", "prod", "real", "model", "extrapolat", "estimate")
    claim = ("measured on", "observed on", "measured against", "from the live", "on tilo-dev", "in production")
    for path, value in walk(_report20()):
        last = path.rsplit(".", 1)[-1].lower() if path else ""
        if last and last != "live" and not last.startswith("["):
            assert not any(word in last for word in forbidden_key), f"key {path!r} suggests a live or invented figure"
        if isinstance(value, str):
            lowered = value.lower()
            assert not any(phrase in lowered for phrase in claim), f"{path!r} claims a live measurement: {value!r}"
            says_live = re.search(r"\blive\b", lowered) is not None
            assert not says_live or any(w in lowered for w in ("not", "no ", "never", "without")), (
                f"{path!r} mentions live without denying it: {value!r}"
            )


def test_NFR_05_note_says_the_figure_stops_at_client_receipt():
    entry = _report20()["NFR-05"]

    note = entry.get("note", "")
    assert "client receipt" in note.lower(), "NFR-05 here is the server half: emitted to received by a client"
    assert "render" in note.lower(), "and it says the render half is not measured"


def test_NFR_02_03_05_the_report_invents_nothing_from_a_constant_delay(monkeypatch):
    """If every NFR-02 sample takes the same extra time, p50 and p95 both land on it: no extrapolated tail."""
    from tilo_api import intake

    clock = Clock(monkeypatch)
    slow(monkeypatch, clock, intake, "extract_brief", 2000)

    entry = latency().measure(5)["NFR-02"]

    assert entry["n"] == 5
    assert 2000 <= entry["p50_ms"] <= entry["p95_ms"] <= 4000, "both within the measured range, none above the data"


def test_NFR_02_03_05_numbers_are_in_milliseconds_not_seconds():
    """A local in-process intake takes tens of milliseconds, not microseconds and not minutes: seconds mislabelled as
    ms would give values below 1."""
    entry = _report20()["NFR-02"]

    assert entry["p50_ms"] >= 1, "milliseconds, not seconds"
    assert entry["p95_ms"] < 60_000
