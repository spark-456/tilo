"""SEC-16 beta caps (user approved, 8 Oct 2026; docs/open-questions.md BQ-SEC16-3): the shipped numbers of
`config/spend_caps.yaml` become

    run_minor              12000 ->  50000   (INR 500 per run)
    uid_lifetime_minor    100000 -> 300000   (INR 3,000 per uid, lifetime)
    global_day_hard_minor 200000 -> 500000   (INR 5,000 per UTC day; the daily replay-only fallback is unchanged)

Everything else in the file is unchanged (org_day_minor null, unit_reserve_minor 1000, 240 requests per 60 s). What is
pinned: the config values and their comments, that no cap number is written anywhere but the config (API source and
web source), and that the behaviour built on them follows the config (the ledger, the guard and the HTTP refusal are
exercised with the SHIPPED caps, not small test ones). Also the reason code the lifetime cap answers with, and that
the per-run and daily limits do not answer with it.

Old tests that pin the previous numbers (the builder updates them; this file does not edit them):
`test_SEC_16_config.py::test_SEC_16_the_shipped_config_gives_each_uid_a_lifetime_cap_of_1000_inr_in_minor_units`
(asserts 100_000) and the `100_000` literal scan of `test_SEC_16_no_cap_number_is_written_in_code`.
"""

from __future__ import annotations

import io
import pathlib
import re
import tokenize
import uuid
from dataclasses import asdict
from datetime import UTC, datetime

from _sec16_lib import AT, JUDGE_A, JUDGE_B, ORG, SpyLedger

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = REPO_ROOT / "config" / "spend_caps.yaml"
API_SRC = REPO_ROOT / "services" / "api" / "src" / "tilo_api"
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"

RUN, LIFETIME, GLOBAL_DAY = 50_000, 300_000, 500_000
OLD = (12_000, 100_000, 200_000)
BIG_LIMIT = {"rate_limit_requests": 100_000}


def shipped():
    from tilo_api.spend import load_spend_caps  # noqa: PLC0415

    return load_spend_caps(None)


def declared():
    return {JUDGE_A: "judge", JUDGE_B: "judge"}


# --- the config ---------------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_the_shipped_caps_are_inr_500_per_run_3000_lifetime_and_5000_a_day():
    caps = shipped()

    assert (caps.run_minor, caps.uid_lifetime_minor, caps.global_day_hard_minor) == (RUN, LIFETIME, GLOBAL_DAY)
    assert caps.org_day_minor is None
    assert (caps.unit_reserve_minor, caps.rate_limit_requests, caps.rate_limit_window_s) == (1_000, 240, 60)
    assert caps.unit_reserve_minor <= caps.run_minor <= caps.uid_lifetime_minor <= caps.global_day_hard_minor


def test_SEC_16_FEEDBACK_the_config_comments_name_the_new_amounts_and_not_the_old_ones():
    lines = {line.split(":", 1)[0]: line for line in CONFIG.read_text(encoding="utf-8").splitlines() if ":" in line}

    assert "3,000 INR" in lines["uid_lifetime_minor"] and "1,000 INR" not in lines["uid_lifetime_minor"]
    assert "500 INR" in lines["run_minor"] and "120 INR" not in lines["run_minor"]
    assert "5,000 INR" in lines["global_day_hard_minor"] and "2,000 INR" not in lines["global_day_hard_minor"]
    assert "user" in lines["run_minor"].lower() or "8 Oct" in lines["run_minor"], "who approved it is on the line"
    assert "replay-only" in lines["global_day_hard_minor"] and "NFR-24" in lines["global_day_hard_minor"]


def test_SEC_16_FEEDBACK_no_cap_number_is_written_in_tilo_api_code():
    """FR-MTR-04 / SEC-16: the caps are config. None of the old or new cap values is a literal in tilo-api."""
    offenders = []
    for path in sorted(API_SRC.rglob("*.py")):
        for token in tokenize.generate_tokens(io.StringIO(path.read_text(encoding="utf-8")).readline):
            if token.type != tokenize.NUMBER:
                continue
            try:
                value = float(token.string.replace("_", ""))
            except ValueError:
                continue
            if value in {RUN, LIFETIME, GLOBAL_DAY, *OLD}:
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{token.start[0]}: {token.string}")
    assert offenders == [], f"a cap literal in code: {offenders}"


def test_SEC_16_FEEDBACK_the_web_source_never_states_a_cap_amount():
    """The pop-up says the allowance is used up; it carries no amount, so a config edit never leaves it wrong."""
    pattern = re.compile(
        r"uid_lifetime|spend_caps|\b300[_,]?000\b|\b500[_,]?000\b|3,000\s*(?:INR|rupees)|(?:INR|₹|Rs\.?)\s*3,?000|"
        r"5,000\s*(?:INR|rupees)|500\s*INR|(?:INR|₹)\s*500\b",
        re.IGNORECASE,
    )
    offenders = []
    for path in sorted(WEB_SRC.rglob("*")):
        if path.suffix not in {".ts", ".tsx"} or ".test." in path.name or "fixtures" in path.parts:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()[:100]}")
    assert offenders == [], offenders


def test_SEC_16_FEEDBACK_the_api_doc_names_the_new_lifetime_cap():
    doc = (REPO_ROOT / "services" / "api" / "tests" / "API_SEC_16.md").read_text(encoding="utf-8")

    assert "300000" in doc and "3,000 INR" in doc
    assert "shipped: 100000" not in doc and "uid_lifetime_minor: 100000" not in doc
    assert "1,000 INR cap is" not in doc, "the section on money still describes the 1,000 INR cap"


# --- behaviour at the SHIPPED numbers (the ledger, the guard) -------------------------------------------------


def ledger():
    from tilo_api.spend import InMemorySpendLedger  # noqa: PLC0415

    return InMemorySpendLedger(shipped())


def settle(ledger_, uid, run_id, minor, *, org=ORG, at=AT):
    held = ledger_.reserve(uid=uid, run_id=run_id, org_id=org, amount_minor=minor, at=at)
    assert not hasattr(held, "reason"), f"setup: refused {minor} for {uid}/{run_id}: {held}"
    ledger_.settle(held, minor)


def test_SEC_16_FEEDBACK_one_run_may_spend_exactly_50000_and_not_one_paisa_more():
    book = ledger()
    settle(book, JUDGE_A, "r_one", RUN)

    refused = book.reserve(uid=JUDGE_A, run_id="r_one", org_id=ORG, amount_minor=1, at=AT)

    assert getattr(refused, "reason", None) == "run"
    assert book.spent_minor(JUDGE_A) == RUN


def test_SEC_16_FEEDBACK_a_uid_may_spend_exactly_300000_over_its_lifetime_and_not_one_paisa_more():
    book = ledger()
    for n in range(LIFETIME // RUN):  # six runs of 50,000
        settle(book, JUDGE_A, f"r_{n}", RUN)

    refused = book.reserve(uid=JUDGE_A, run_id="r_next", org_id=ORG, amount_minor=1, at=AT)

    assert book.spent_minor(JUDGE_A) == LIFETIME
    assert getattr(refused, "reason", None) == "uid_lifetime"


def test_SEC_16_FEEDBACK_the_guard_calls_a_uid_capped_at_exactly_300000_and_not_at_299999():
    from tilo_api.spend import SpendGuard  # noqa: PLC0415
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    book = ledger()
    guard = SpendGuard(book, InMemoryFlagStore(), shipped())
    for n in range(5):
        settle(book, JUDGE_A, f"r_{n}", RUN)
    settle(book, JUDGE_A, "r_5", RUN - 1)  # 299,999

    assert guard.uid_capped(JUDGE_A) is False and guard.live_allowed(JUDGE_A) is True

    settle(book, JUDGE_A, "r_6", 1)  # 300,000

    assert guard.uid_capped(JUDGE_A) is True and guard.live_allowed(JUDGE_A) is False


def test_SEC_16_FEEDBACK_the_day_hard_cap_is_500000_and_reaching_it_turns_replay_only_as_before():
    from tilo_api.spend import SpendGuard  # noqa: PLC0415
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    book = ledger()
    guard = SpendGuard(book, InMemoryFlagStore(), shipped())
    for n in range(9):  # nine uids, one run each: 450,000 on the day
        settle(book, f"u_day_{n}", f"r_day_{n}", RUN)
    assert book.replay_only() is False

    settle(book, "u_day_9", "r_day_9", RUN)  # the tenth reaches 500,000 exactly

    assert book.replay_only() is True, "settling the day to the hard cap flips the durable switch (NFR-24, FR-MTR-04)"
    plan = guard.begin_unit("live", uid="u_day_10", run_id="r_day_10", org_id=ORG, estimate_minor=1_000, at=AT)
    assert (plan.mode, plan.reservation, plan.reason) == ("replay", None, "replay_only")


def test_SEC_16_FEEDBACK_a_reservation_that_would_cross_500000_is_refused_and_flips_the_switch():
    book = ledger()
    for n in range(9):
        settle(book, f"u_day_{n}", f"r_day_{n}", RUN)
    held = book.reserve(uid="u_day_9", run_id="r_day_9", org_id=ORG, amount_minor=RUN, at=AT)
    assert not hasattr(held, "reason"), "exactly 500,000 held passes"

    refused = book.reserve(uid="u_day_10", run_id="r_day_10", org_id=ORG, amount_minor=1, at=AT)

    assert getattr(refused, "reason", None) == "global_hard"
    assert book.replay_only() is True


def test_SEC_16_FEEDBACK_the_500000_day_cap_is_per_utc_day():
    book = ledger()
    next_day = datetime(2026, 10, 7, 0, 30, tzinfo=UTC)
    for n in range(9):
        settle(book, f"u_d1_{n}", f"r_d1_{n}", RUN, at=AT)
    for n in range(9):
        settle(book, f"u_d2_{n}", f"r_d2_{n}", RUN, at=next_day)

    assert book.replay_only() is False, "450,000 on each of two UTC days is under the daily hard cap"


# --- behaviour at the SHIPPED numbers (HTTP) ------------------------------------------------------------------


def fill(h, uid, total):
    """Puts `total` on the uid's lifetime through public ledger calls, in runs no bigger than the run cap."""
    run_cap = h.caps.run_minor
    left = total
    while left > 0:
        chunk = min(run_cap, left)
        held = h.ledger.reserve(uid=uid, run_id=f"r_fill_{uuid.uuid4().hex}", org_id=ORG, amount_minor=chunk, at=AT)
        assert not hasattr(held, "reason"), f"setup: {held}"
        h.ledger.settle(held, chunk)
        left -= chunk
    h.ledger.calls.clear()


def shipped_harness(sec16_factory, **overrides):
    h = sec16_factory(declarations=declared(), **{**asdict(shipped()), **BIG_LIMIT, **overrides})
    assert (h.caps.run_minor, h.caps.uid_lifetime_minor) == (RUN, LIFETIME), "the harness runs on the shipped numbers"
    return h


def test_SEC_16_FEEDBACK_http_a_judge_at_299999_still_gets_live_work_and_at_300000_is_refused(sec16_factory):
    h = shipped_harness(sec16_factory)
    fill(h, JUDGE_A, LIFETIME - 1)

    assert h.intake().status_code == 201
    assert set(h.router_modes) == {"live"}

    fill(h, JUDGE_A, 1)
    response = h.intake()

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "spend_cap_reached"


def test_SEC_16_FEEDBACK_http_another_judge_is_not_refused_by_the_first_ones_cap(sec16_factory):
    h = shipped_harness(sec16_factory)
    fill(h, JUDGE_A, LIFETIME)

    h.as_user(JUDGE_B)

    assert h.intake().status_code == 201


# --- the reason code ----------------------------------------------------------------------------------------


def test_SEC_16_FEEDBACK_the_lifetime_cap_refusal_is_403_with_the_stable_code_spend_cap_reached(sec16_factory):
    """The code the web keys the pop-up on. It already exists (SEC-16, tests/API_SEC_16.md); this pins the contract
    with the web: status 403, JSON, `code` exactly `spend_cap_reached`, and a `detail` sentence."""
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    held = h.ledger.reserve(uid=JUDGE_A, run_id="r_x", org_id=ORG, amount_minor=h.caps.uid_lifetime_minor, at=AT)
    h.ledger.settle(held, h.caps.uid_lifetime_minor)

    response = h.intake()

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["code"] == "spend_cap_reached"
    assert isinstance(body["detail"], str) and 20 < len(body["detail"]) <= 200
    assert str(h.caps.uid_lifetime_minor) not in body["detail"], "no amount in the sentence"
    assert JUDGE_A not in response.text


def test_SEC_16_FEEDBACK_the_daily_limit_has_its_own_answer_and_never_the_lifetime_code(sec16_factory):
    """The deployment's daily hard cap turns the link replay-only: 503 {"replay_only": true}, no lifetime code."""
    h = sec16_factory(declarations=declared(), **BIG_LIMIT)
    h.ledger.trip_replay_only("the daily hard cap would be exceeded")

    response = h.intake()

    assert response.status_code == 503, response.text
    body = response.json()
    assert body.get("replay_only") is True
    assert body.get("code") != "spend_cap_reached"


def test_SEC_16_FEEDBACK_a_run_at_its_cap_is_a_replay_unit_not_the_lifetime_refusal():
    """The per-run cap never produces the lifetime reason: the unit falls back to replay with reason `run`."""
    from tilo_api.spend import SpendGuard  # noqa: PLC0415
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    book = SpyLedger(ledger())
    guard = SpendGuard(book, InMemoryFlagStore(), shipped())
    settle(book, JUDGE_A, "r_full", RUN)

    plan = guard.begin_unit("live", uid=JUDGE_A, run_id="r_full", org_id=ORG, estimate_minor=1_000, at=AT)

    assert (plan.mode, plan.reason) == ("replay", "run")
    assert guard.uid_capped(JUDGE_A) is False, "50,000 of 300,000: the person is not at their lifetime cap"
