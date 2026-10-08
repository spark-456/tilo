"""Builders for the FR-PA-20 effort-tracker API tests (services/api; the interface is pinned in `API_FR_PA_20.md`).

One real `Treasury` (the FR-MTR-10 fake price sheets of `_mtr10_lib`) holds the ledger of five fixture runs of one
owner and one run of a second owner; the same worlds, their recorded events and the people records of both owners are
seeded behind the real `tilo_api.app` through the PPL-11a `Rig` (every people seam faked, the model router a spy that
fails the test when anything builds one). Credits and minutes are chosen so every sum is exact in binary floating
point, so the tests assert equality, not closeness. Named `_fr_pa_20_lib` for the global-bare-module-name reason of
`_sec15_lib.py`. Fake data only: no network, no provider, no secret.

    run    world  owner    meeting             ledger commits (credits)          building.completed (unit_type x n)
    r_e1   w_e1   u_owner  mt_e1               U1 flash-38 40 (v1), U2 lite 40   reply_handled 2 + 1, mail_triaged 10
    r_e2   w_e2   u_owner  mt_e2               U1 flash-38 120 (v2) + a reserve  reply_handled 4 (delivered twice)
    r_e3   w_e3   u_owner  mt_gone (deleted)   U1 lite 40, U9 plain 2            research 2 (no baseline), mail 4
    r_e4   w_e4   u_owner  (none)              U1 flash-38 40 (v1), U2 120 (v2)  reply_handled 0 (not completed)
    r_e5   w_e5   u_owner  (none)              nothing                           nothing (not completed)
    r_p1   w_p1   u_priya  mt_p1               U1 flash-38 120 (v2)              reply_handled 3
    mt_none (u_owner, no world), mt_foreign (u_owner, its world_id is u_priya's w_p1: must add nothing)
"""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Callable, Iterable
from typing import Any

from _api_lib import REPO_ROOT, validate_event
from _clint1_lib import seam
from _mtr10_lib import CREDIT_USD, FLASH, LITE, _reserve, _spend, at, treasury
from _ppl11a_lib import ORG, OWNER, PRIYA, Rig, pl
from _ppl11c_lib import gone_meeting
from tilo_api import deps
from tilo_metering import Treasury

R_EFFORT = ("GET", "/v1/effort")
PATH = R_EFFORT[1]
OWNER_RUNS = {"w_e1": "r_e1", "w_e2": "r_e2", "w_e3": "r_e3", "w_e4": "r_e4", "w_e5": "r_e5"}
PRIYA_RUNS = {"w_p1": "r_p1"}
RUN_OF = {**OWNER_RUNS, **PRIYA_RUNS}
OWNER_OF = {**dict.fromkeys(OWNER_RUNS, OWNER), **dict.fromkeys(PRIYA_RUNS, PRIYA)}
METHOD_URL = "https://tilo.example.com/method/time-saved"  # example.com: a fake host (contracts/CLAUDE.md)
SENTINEL = "Quarterly layoffs plan"  # a meeting title and a plan title that must never reach the numbers
GUEST = "Dana Whitfield"  # an attendee name that must never reach the numbers

# EV-G2 baselines as the time-saved method (PRD 14.2) reads them: minutes per unit, 25th / median / 75th percentile.
BASELINES: dict[str, Any] = {
    "method_url": METHOD_URL,
    "units": {
        "reply_handled": {"p25": 2.0, "median": 3.5, "p75": 5.0},
        "mail_triaged": {"p25": 0.25, "median": 0.5, "p75": 1.0},
    },
}
# (unit_type, unit_count, event number within the world); a world's list is its building.completed events in order
COMPLETED: dict[str, list[tuple[str, int]]] = {
    "w_e1": [("reply_handled", 2), ("reply_handled", 1), ("mail_triaged", 10)],
    "w_e2": [("reply_handled", 4)],
    "w_e3": [("research", 2), ("mail_triaged", 4)],
    "w_e4": [("reply_handled", 0)],
    "w_e5": [],
    "w_p1": [("reply_handled", 3)],
}
DONE = {"w_e1", "w_e2", "w_e3", "w_p1"}  # worlds with a world.completed
# Hand-worked time saved (minutes, low, high) per world: units x the baseline's median, 25th and 75th percentile.
TIME_SAVED = {
    "w_e1": (15.5, 8.5, 25.0),  # 3 x 3.5 + 10 x 0.5 ; 3 x 2 + 10 x .25 ; 3 x 5 + 10 x 1
    "w_e2": (14.0, 8.0, 20.0),  # 4 x 3.5 once, the redelivery is the same event
    "w_e3": (2.0, 1.0, 4.0),  # research has no baseline (counts zero); 4 x 0.5
    "w_e4": (0.0, 0.0, 0.0),
    "w_e5": (0.0, 0.0, 0.0),
    "w_p1": (10.5, 6.0, 15.0),
}
MEETING_WORLD = {"mt_e1": "w_e1", "mt_e2": "w_e2", "mt_none": None, "mt_foreign": "w_p1"}  # u_owner's listed meetings
ID_BASE = {w: 1000 * (i + 1) for i, w in enumerate(RUN_OF)}

ALLOWED_KEYS = {
    "top": {"credit_usd", "totals", "meetings", "tasks"},
    "totals": {"tasks", "completed_tasks", "credits", "usd", "time_saved"},
    "meeting": {"meeting_id", "world_id", "tasks", "credits", "usd", "time_saved"},
    "task": {"world_id", "run_id", "meeting_id", "completed", "credits", "usd", "time_saved"},
    "time_saved": {"minutes", "low", "high", "steering_measured", "method_url"},
}


# --- ledger ---------------------------------------------------------------------------------------


def build_ledger(tmp_path: Any) -> Treasury:
    t = treasury(tmp_path)
    for world, run in RUN_OF.items():
        t.open_run(run, user_id=OWNER_OF[world], org_id="org_test", approved=300)
    _spend(t, "r_e1", "U1", FLASH, 100_000, 50_000, at("2026-05-31", "23:59:00"))  # sheet v1: 40
    _spend(t, "r_e1", "U2", LITE, 200_000, 100_000, at("2026-06-02"))  # 40
    _spend(t, "r_e2", "U1", FLASH, 100_000, 50_000, at("2026-06-01", "00:00:00"), 120.0)  # sheet v2: 120
    _reserve(t, "r_e2", "U2", 30.0, at("2026-06-02"))  # reserved, never committed: not spend
    _spend(t, "r_e3", "U1", LITE, 200_000, 100_000, at("2026-06-03"))  # 40
    t.commit(_reserve(t, "r_e3", "U9", 10.0, at("2026-06-03")), 2.0, at=at("2026-06-03"))  # plain commit, 2
    _spend(t, "r_e4", "U1", FLASH, 100_000, 50_000, at("2026-05-30"))  # v1: 40
    _spend(t, "r_e4", "U2", FLASH, 100_000, 50_000, at("2026-06-04"), 120.0)  # v2: 120
    _spend(t, "r_p1", "U1", FLASH, 100_000, 50_000, at("2026-06-02"), 120.0)  # v2: 120
    return t


def commits(ledger: Iterable[Any], runs: Iterable[str]) -> list[Any]:
    wanted = set(runs)
    return [e for e in ledger if e.kind == "commit" and e.run in wanted]


def ledger_credits(ledger: Iterable[Any], runs: Iterable[str]) -> float:
    return math.fsum(e.credits or 0.0 for e in commits(ledger, runs))


# --- events and worlds ----------------------------------------------------------------------------


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((REPO_ROOT / "contracts" / "fixtures" / "events" / "valid" / f"{name}.json").read_text("utf-8"))


def event(
    type_: str, world: str, seq: int, data: dict[str, Any] | None = None, *, check: bool = True, **overrides: Any
) -> dict[str, Any]:
    """A valid event (event.schema.json and its data schema) copied from the registry fixture, in `world`'s run.
    `check=False` skips the schema check (slow); the property test uses it for events built from the same template."""
    ev = copy.deepcopy(_fixture(type_))
    ev.update(
        id=f"01JB5VQ{ID_BASE[world] + seq:019d}", seq=seq, world_id=world, run_id=RUN_OF[world], target=world, vis="all"
    )
    ev.update(district=None, level=None, summary=f"{SENTINEL} progressed")
    if data is not None:
        ev["data"] = data
    ev.update(overrides)
    if check:
        validate_event(ev)
    return ev


def world_events(world: str) -> list[dict[str, Any]]:
    planned = {"tier": "village", "approach": "standard", "unit_count": 3, "credits": {"min": 20, "max": 35}}
    events = [event("world.planned", world, 1, planned)]
    for number, (unit_type, count) in enumerate(COMPLETED[world], start=2):
        events.append(event("building.completed", world, number, {"unit_type": unit_type, "unit_count": count}))
    if world == "w_e2":  # the same building.completed delivered twice
        events.append(copy.deepcopy(events[-1]))
    if world in DONE:
        events.append(
            event("world.completed", world, 20, {"credits_used": 1.0, "deliverable_count": 1}, cause=events[-1]["id"])
        )
    return events


def meetings() -> list[dict[str, Any]]:
    def mt(mid: str, owner: str, world: str | None, **ov: Any) -> dict[str, Any]:
        base = pl.meeting(
            id=mid,
            org_id=ORG,
            owner=owner,
            title=SENTINEL,
            series=None,
            attendees=[{"name": GUEST, "user": None}],
            attestation={"by": owner, "at": "2026-10-05T09:00:00.000Z", "notice_version": "1.0.0"},
        )
        base.pop("world_id", None)
        if world is not None:
            base["world_id"] = world
        return pl.with_(base, **ov)

    return [
        mt("mt_e1", OWNER, "w_e1"),
        mt("mt_e2", OWNER, "w_e2"),
        mt("mt_none", OWNER, None),
        mt("mt_foreign", OWNER, "w_p1"),  # points at u_priya's world: not the owner's to count
        gone_meeting(mt("mt_gone", OWNER, "w_e3"), "deleted"),  # gone for everyone (FR-MTG-10); its world's spend stays
        mt("mt_p1", PRIYA, "w_p1"),
    ]


# --- the rig --------------------------------------------------------------------------------------


class Effort:
    """The PPL-11a `Rig` with the three effort seams: `deps.get_store` (worlds, events), `deps.get_ledger` and
    `deps.get_time_baselines` (EV-G2 baselines and the method page, an unmeasured study is 503 until wired)."""

    def __init__(self, rig: Rig, tmp_path: Any) -> None:
        self.rig = rig
        self.treasury = build_ledger(tmp_path)
        self.ledger = self.treasury.ledger
        self.store = deps.Store()
        self.baselines = copy.deepcopy(BASELINES)
        for world, owner in OWNER_OF.items():
            self.store.worlds[world] = deps.WorldRecord(
                owner=owner, owner_channels=("web",), districts={}, run_id=RUN_OF[world], paused=False
            )
            self.store.events[world] = world_events(world)
        rig.add_people()
        for record in meetings():
            rig.add("meetings", record)
        rig.app.dependency_overrides[deps.get_store] = lambda: self.store
        rig.app.dependency_overrides[deps.get_ledger] = lambda: self.ledger
        rig.app.dependency_overrides[seam(deps, "get_time_baselines")] = lambda: self.baselines
        rig.as_user(OWNER)

    def get(self, **kwargs: Any) -> Any:
        self.rig.require_route(R_EFFORT)
        return self.rig.client.get(PATH, **kwargs)

    def body(self, who: str = OWNER) -> dict[str, Any]:
        self.rig.as_user(who)
        response = self.get()
        assert response.status_code == 200, (response.status_code, response.text[:300])
        return response.json()  # type: ignore[no-any-return]

    def set_ledger(self, ledger: Any) -> None:
        self.rig.app.dependency_overrides[deps.get_ledger] = lambda: ledger

    def wire(self, name: str, provider: Callable[[], Any] | None) -> None:
        """Override (or, with None, remove the override of) a `tilo_api.deps` seam; a seam that does not exist yet fails
        the test with a message saying so, not with an AttributeError."""
        key = getattr(deps, name, None)
        assert key is not None, f"tilo_api.deps.{name} does not exist yet (API_FR_PA_20.md section 2)"
        if provider is None:
            self.rig.app.dependency_overrides.pop(key, None)
        else:
            self.rig.app.dependency_overrides[key] = provider


def make(people_rig: Callable[..., Rig], tmp_path: Any) -> Effort:
    return Effort(people_rig(), tmp_path)


# --- reading a body -------------------------------------------------------------------------------


def task(body: dict[str, Any], world: str) -> dict[str, Any]:
    found = [t for t in body["tasks"] if t["world_id"] == world]
    assert len(found) == 1, f"expected one task row for {world}, found {len(found)}"
    return found[0]


def meeting_row(body: dict[str, Any], meeting_id: str) -> dict[str, Any]:
    found = [m for m in body["meetings"] if m["meeting_id"] == meeting_id]
    assert len(found) == 1, f"expected one meeting row for {meeting_id}, found {len(found)}"
    return found[0]


def minutes_of(rows: Iterable[dict[str, Any]]) -> tuple[float, float, float]:
    rows = list(rows)
    return (
        math.fsum(r["time_saved"]["minutes"] for r in rows),
        math.fsum(r["time_saved"]["low"] for r in rows),
        math.fsum(r["time_saved"]["high"] for r in rows),
    )


def triple(time_saved: dict[str, Any]) -> tuple[float, float, float]:
    return (time_saved["minutes"], time_saved["low"], time_saved["high"])


def expected_time_saved(events: Iterable[dict[str, Any]], baselines: dict[str, Any]) -> tuple[float, float, float]:
    """The PRD 14.2 method, written out again from the events and the baselines (each event id once; a unit type
    without a baseline counts zero): the oracle the property test compares the route to."""
    seen: set[str] = set()
    parts: list[tuple[float, float, float]] = []
    for ev in events:
        if ev.get("type") != "building.completed" or ev["id"] in seen:
            continue
        seen.add(ev["id"])
        base = baselines["units"].get(ev["data"]["unit_type"])
        if base is not None:
            n = ev["data"]["unit_count"]
            parts.append((n * base["median"], n * base["p25"], n * base["p75"]))
    return (
        math.fsum(p[0] for p in parts),
        math.fsum(p[1] for p in parts),
        math.fsum(p[2] for p in parts),
    )


def walk_keys(node: Any, path: str = "") -> Iterable[tuple[str, str]]:
    """(path, key) of every object key at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield (path, key)
            yield from walk_keys(value, f"{path}/{key}")
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item, path + "[]")


def walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from walk_strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_strings(item)


# A key that names tracked human time, or a person, anywhere in the numbers payload (FR-PA-20, D-4).
HUMAN_TIME_KEY = re.compile(
    r"(^|_)(hours?|man_?hours?|man_?days?|timesheets?|billable|worked|time_?spent|spent_?time|human|attention"
    r"|review_?minutes|effort_?minutes|duration|person|persons|people|user|users|owner|assignee|attendees?|by)(_|$)"
    r"|per_?(person|user|human)",  # `steering_measured`: the meter's flag, allowed
    re.IGNORECASE,
)

assert CREDIT_USD == 0.005  # PRD 14.1: 1 credit = US$0.005 (the prices sheet of _mtr10_lib says the same)
