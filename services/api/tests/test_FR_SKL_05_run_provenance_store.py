"""FR-SKL-05, FR-SKL-06 (ADR-0037; taught_skill.rules.md TS-08, TS-09, TS-13 to TS-15): the taught-skill store keeps
real runs, ratings and fixes durably, on both adapters (memory, and Firestore over an optimistic fake with
transactions).
A run is recorded by code at its start from the stored skill, never from a request; a rating is accepted only for a
finished run of the rater's own pinned version, once; a fix is atomic and rejects a stale version; trust counts
verified, deduplicated up-ratings. The crossref fixtures are the same files the contract lane checks (TS-15).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from _adr35_l2_fake import OccFirestore, OccTransaction
from _ppl11a_lib import ORG, OTHER_ORG, PRIYA, SAM
from test_FR_SKL_04_SKILLS_2_skill_store import record
from tilo_api.skill_firestore import FirestoreSkillStore
from tilo_api.skill_ledger import SkillRefused
from tilo_api.skill_store import MemorySkillStore

SKILL = "tsk_01JB6Z0000000000000000AAA"
T0, T1, T2 = "2026-10-12T09:00:00.000Z", "2026-10-12T09:05:00.000Z", "2026-10-12T09:10:00.000Z"
CROSSREF = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "taught_skill" / "crossref"
STEPS = [
    {"text": "Read it", "tool": "gmail", "action": "read_email", "verb": "read", "ask_first": False, "must_ask": False},
    {
        "text": "Save it",
        "tool": "google_drive",
        "action": "save_file",
        "verb": "write",
        "ask_first": True,
        "must_ask": False,
    },
    {"text": "Send it", "tool": "gmail", "action": "send_email", "verb": "send", "ask_first": True, "must_ask": True},
]


@pytest.fixture(params=["memory", "firestore"])
def store(request):
    return MemorySkillStore() if request.param == "memory" else FirestoreSkillStore(OccFirestore())


def skill(**over: Any) -> dict[str, Any]:
    return {**record(SKILL, PRIYA), "plan": copy.deepcopy(STEPS), **over}


def started(store, run_id="r_one", by=PRIYA, **kw):
    kw = {"org": ORG, "skill_id": SKILL, "teams": (), "world_id": "w_desk_priya", "now": T0, **kw}
    return store.start_real_run(
        kw["org"], kw["skill_id"], by=by, teams=kw["teams"], world_id=kw["world_id"], run_id=run_id, now=kw["now"]
    )


def finished(store, run_id="r_one", outcome="completed", at=T1):
    return store.finish_real_run(ORG, SKILL, run_id, outcome=outcome, at=at)


def rating(run_id="r_one", thumb="up", version=1, by=PRIYA, wrong_step=None, rid="01JB6Z00000000000000RAT001"):
    return {
        "id": rid,
        "skill": SKILL,
        "version": version,
        "run_id": run_id,
        "by": by,
        "thumb": thumb,
        "wrong_step": wrong_step,
        "note": None,
        "at": T2,
    }


def refused(call) -> str:
    with pytest.raises(SkillRefused) as caught:
        call()
    return caught.value.reason


# -- TS-13: a run is recorded when it starts, from the stored skill -------------------------------------------------


def test_FR_SKL_05_a_started_run_is_the_stored_skills_pinned_version_and_plan(store):
    store.put(skill())
    run = started(store)
    assert run == {
        "org_id": ORG,
        "skill": SKILL,
        "version": 1,
        "run_id": "r_one",
        "world_id": "w_desk_priya",
        "by": PRIYA,
        "plan": STEPS,
        "started_at": T0,
        "finished_at": None,
        "outcome": None,
    }
    assert store.get_real_run(ORG, SKILL, "r_one") == run


def test_FR_SKL_05_a_run_id_is_recorded_once_and_a_second_start_writes_nothing(store):
    store.put(skill())
    first = started(store)
    assert started(store, now=T2, world_id="w_other") == first
    assert store.list_real_runs(ORG, SKILL) == [first]


@pytest.mark.parametrize("over", [{"status": "draft"}, {"paused": True}])
def test_FR_SKL_06_the_start_guard_refuses_a_draft_or_paused_skill(store, over):
    store.put(skill(**over))
    assert refused(lambda: started(store)) in {"draft", "paused"}
    assert store.list_real_runs(ORG, SKILL) == []


def test_FR_SKL_05_only_the_owner_or_a_current_team_member_starts_a_run(store):
    store.put(skill(scope={"kind": "team", "team": "tm_ops"}))
    assert refused(lambda: started(store, by=SAM)) == "forbidden"
    assert started(store, by=SAM, teams=("tm_ops",))["by"] == SAM
    assert refused(lambda: started(store, by=PRIYA)) == "forbidden"  # r_one is Sam's: not handed to another person
    assert refused(lambda: started(store, org=OTHER_ORG, run_id="r_two")) == "not_found"


# -- TS-14: a run finishes once -------------------------------------------------------------------------------------


def test_FR_SKL_05_a_run_finishes_once_and_never_before_it_started(store):
    store.put(skill())
    started(store)
    assert refused(lambda: finished(store, at="2026-10-12T08:00:00.000Z")) == "finished_before_start"
    assert finished(store)["outcome"] == "completed"
    assert finished(store, outcome="failed", at=T2)["outcome"] == "completed"
    assert store.get_real_run(ORG, SKILL, "r_one")["finished_at"] == T1
    assert refused(lambda: finished(store, run_id="r_unknown")) == "not_found"


# -- TS-15: who may rate which run (the contract lane's crossref files) ------------------------------------------


def _case_files():
    return sorted(p for kind in ("valid", "invalid") for p in (CROSSREF / kind).glob("*.json"))


@pytest.mark.parametrize(
    "path", [p for p in _case_files() if "rating" in json.loads(p.read_text())], ids=lambda p: p.stem
)
def test_FR_SKL_05_the_crossref_cases_reach_the_contract_verdict(store, path):
    case = json.loads(path.read_text())
    run, given, org = case["run"], case["rating"], case["org_id"]
    base = record(given["skill"], run["by"] if run else given["by"], org=run["org_id"] if run else org)
    store.put(
        {**base, "plan": run["plan"] if run else base["plan"], "version": run["version"] if run else given["version"]}
    )
    if run:
        s = (run["org_id"], run["skill"])
        store.start_real_run(
            s[0], s[1], by=run["by"], teams=(), world_id=run["world_id"], run_id=run["run_id"], now=run["started_at"]
        )
        if run["outcome"]:
            store.finish_real_run(*s, run["run_id"], outcome=run["outcome"], at=run["finished_at"])
    for n, earlier in enumerate(case["earlier"]):  # seeded raw: the files reuse one rating id for both records
        store._atomic(lambda tx, e=earlier, n=n: tx.create(f"orgs/{org}/taught_skills/{e['skill']}/ratings/E{n}", e))
    call = lambda: store.record_rating(org, given["skill"], given)  # noqa: E731
    if case["rule"] == "TS-15":
        assert refused(call) in {"not_found", "already_rated", "not_rateable"}
    else:
        assert call()["id"] == given["id"]


def test_FR_SKL_05_the_pinned_version_survives_a_later_fix_and_a_rating_names_it(store):
    store.put(skill())
    started(store)
    finished(store)
    store.apply_fix(
        ORG,
        SKILL,
        {
            "id": "01JB6Z00000000000000FXA001",
            "from_version": 1,
            "step": 1,
            "text": "Read it twice",
            "ask_first": False,
            "by": PRIYA,
            "rating": None,
            "at": T2,
        },
    )
    assert store.get(ORG, SKILL)["version"] == 2
    assert store.get_real_run(ORG, SKILL, "r_one")["version"] == 1
    assert store.get_real_run(ORG, SKILL, "r_one")["plan"] == STEPS
    assert refused(lambda: store.record_rating(ORG, SKILL, rating(version=2))) == "not_found"
    assert store.record_rating(ORG, SKILL, rating(version=1))["version"] == 1


def test_FR_SKL_06_each_finished_run_counts_at_most_once_toward_good_runs(store):
    store.put(skill())
    for n in ("r_one", "r_two", "r_three"):
        started(store, run_id=n)
        finished(store, run_id=n, outcome="failed" if n == "r_three" else "completed")
    assert store.record_rating(ORG, SKILL, rating("r_one"))
    assert (
        refused(lambda: store.record_rating(ORG, SKILL, rating("r_one", rid="01JB6Z00000000000000RAT002")))
        == "already_rated"
    )
    assert (
        refused(lambda: store.record_rating(ORG, SKILL, rating("r_one", "down", rid="01JB6Z00000000000000RAT003")))
        == "already_rated"
    )
    assert store.get(ORG, SKILL)["good_runs"] == 1
    store.record_rating(ORG, SKILL, rating("r_two", "down", wrong_step=2, rid="01JB6Z00000000000000RAT004"))
    assert (
        refused(lambda: store.record_rating(ORG, SKILL, rating("r_three", rid="01JB6Z00000000000000RAT005")))
        == "not_rateable"
    )
    assert store.get(ORG, SKILL)["good_runs"] == 1
    assert [r["run_id"] for r in store.list_ratings(ORG, SKILL)] == ["r_one", "r_two"]


def test_FR_SKL_05_a_wrong_step_beyond_the_pinned_plan_is_refused(store):
    store.put(skill())
    started(store)
    finished(store)
    assert refused(lambda: store.record_rating(ORG, SKILL, rating(thumb="down", wrong_step=4))) == "invalid_step"


# -- TS-09: fixes are atomic and reject a stale version ---------------------------------------------------------


def _fix(**over):
    return {
        "id": "01JB6Z00000000000000FXA001",
        "from_version": 1,
        "step": 3,
        "text": "Send it to me only",
        "ask_first": True,
        "by": PRIYA,
        "rating": None,
        "at": T2,
        **over,
    }


def test_FR_SKL_05_a_fix_sets_text_and_ask_first_and_makes_the_next_version(store):
    store.put(skill())
    after = store.apply_fix(ORG, SKILL, _fix())
    assert after["version"] == 2
    assert after["plan"][2] == {**STEPS[2], "text": "Send it to me only"}
    assert after["plan"][:2] == STEPS[:2]
    assert store.list_fixes(ORG, SKILL) == [{**_fix(), "skill": SKILL, "to_version": 2}]


def test_FR_SKL_05_a_stale_or_unowned_or_unsafe_fix_writes_nothing(store):
    store.put(skill())
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix(from_version=3))) == "stale_version"
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix(by=SAM))) == "forbidden"
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix(ask_first=False))) == "ask_first_required"
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix(step=4))) == "invalid_step"
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix(rating="01JB6Z00000000000000RATXXX"))) == "unknown_rating"
    assert store.get(ORG, SKILL)["version"] == 1 and store.list_fixes(ORG, SKILL) == []


def test_FR_SKL_05_a_concurrent_fix_that_read_the_old_version_is_rejected():
    class Racing(OccFirestore):
        rival: tuple[str, dict] | None = None

        def transaction(self, **_: Any) -> OccTransaction:
            db = self

            class Late(OccTransaction):
                def _commit(self) -> list:  # another instance fixed the skill between our read and our commit
                    if db.rival is not None:
                        (path, doc), db.rival = db.rival, None
                        db.commit([("set", path, doc)])
                    return super()._commit()

            return Late(self)

    db = Racing()
    store = FirestoreSkillStore(db)
    store.put(skill())
    path = f"orgs/{ORG}/taught_skills/{SKILL}"
    db.rival = (path, {**skill(), "version": 2, "updated_at": T1})
    assert refused(lambda: store.apply_fix(ORG, SKILL, _fix())) == "stale_version"
    assert store.get(ORG, SKILL)["version"] == 2 and store.list_fixes(ORG, SKILL) == []


# -- TS-08 and FR-SKL-06: trust and pause ---------------------------------------------------------------------------


def test_FR_SKL_06_trusted_needs_the_threshold_of_verified_up_ratings(store):
    store.put(skill())
    for i, n in enumerate(("r_one", "r_two")):
        started(store, run_id=n)
        finished(store, run_id=n)
        assert (
            refused(lambda: store.set_state(ORG, SKILL, "trusted", by=PRIYA, threshold=2, now=T2))
            == "not_enough_good_runs"
        )
        store.record_rating(ORG, SKILL, rating(n, rid=f"01JB6Z00000000000000RAT00{i}"))
    after, changed = store.set_state(ORG, SKILL, "trusted", by=PRIYA, threshold=2, now=T2)
    assert (after["status"], changed, after["good_runs"], after["version"]) == ("trusted", True, 2, 1)
    assert store.set_state(ORG, SKILL, "trusted", by=PRIYA, threshold=2, now=T2)[1] is False
    assert store.set_state(ORG, SKILL, "learning", by=PRIYA, threshold=2, now=T2)[0]["status"] == "learning"


def test_FR_SKL_06_pause_and_resume_keep_the_status_and_only_the_owner_changes_it(store):
    store.put(skill(status="trusted"))
    paused, changed = store.set_state(ORG, SKILL, "paused", by=PRIYA, threshold=5, now=T1)
    assert (paused["status"], paused["paused"], changed) == ("trusted", True, True)
    assert refused(lambda: started(store)) == "paused"
    resumed, _ = store.set_state(ORG, SKILL, "resumed", by=PRIYA, threshold=5, now=T2)
    assert (resumed["status"], resumed["paused"], resumed["updated_at"]) == ("trusted", False, T2)
    assert refused(lambda: store.set_state(ORG, SKILL, "paused", by=SAM, threshold=5, now=T2)) == "forbidden"
    store.put({**skill(), "id": "tsk_draft", "status": "draft"})
    assert refused(lambda: store.set_state(ORG, "tsk_draft", "paused", by=PRIYA, threshold=5, now=T2)) == "not_found"
