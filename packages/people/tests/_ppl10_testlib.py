"""Shared helpers for the PPL-10 acceptance tests (people core, `tilo_people`; spec in
`packages/people/tests/API.md`, rules in `contracts/people.rules.md`).

Not a test module (leading underscore). The unique module name matters: pytest's prepend import mode
puts every test directory on one `sys.path`, so a second `_lib.py` here would shadow another suite's.

Rules this file follows (root CLAUDE.md, test-writer):

- No business logic. Every helper loads a file unchanged, builds a plain dict through the contract
  suite's own minimal-document builders (`tests/contracts/_people_lib.py`, imported as `pl`), or defers
  an import until a test runs (`access`, `names`, ... are lazy, so a module that does not exist yet
  fails ONE test with ModuleNotFoundError instead of breaking collection of the whole file).
- No unicode escape sequences in any test file (editors and writers unescape them): code points are
  built with `u(0x200B, ...)`.
- No secrets, no network, no clock: every time value is an argument.
"""

from __future__ import annotations

import copy
import importlib
import json
import pathlib
import sys
from typing import Any

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACT_TESTS = REPO_ROOT / "tests" / "contracts"
CROSSREF = REPO_ROOT / "contracts" / "fixtures" / "person" / "crossref"
SRC = REPO_ROOT / "packages" / "people" / "src" / "tilo_people"

if str(CONTRACT_TESTS) not in sys.path:
    sys.path.insert(0, str(CONTRACT_TESTS))

import _people_lib as pl  # noqa: E402  (the reference oracle and the minimal-document builders)


class _Lazy:
    """`access.decide` imports `tilo_people.access` on first use, at test time."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> Any:
        if attr.startswith("__"):
            raise AttributeError(attr)
        return getattr(importlib.import_module(self._name), attr)


errors = _Lazy("tilo_people.errors")
text = _Lazy("tilo_people.text")
directory = _Lazy("tilo_people.directory")
access = _Lazy("tilo_people.access")
crossref = _Lazy("tilo_people.crossref")
names = _Lazy("tilo_people.names")
dates = _Lazy("tilo_people.dates")
writes = _Lazy("tilo_people.writes")
stores = _Lazy("tilo_people.stores")

ORG = pl.ORG
OTHER_ORG = pl.OTHER_ORG
T0 = pl.T0  # 2026-10-01T09:00:00.000Z
T1 = pl.T1  # 2026-10-02T09:00:00.000Z
T2 = pl.T2  # 2026-10-02T09:30:00.000Z
NOW = "2026-10-03T09:00:00.000Z"  # after every stamp the builders use
LATER = "2026-10-04T09:00:00.000Z"
FUTURE = "2026-10-09T09:00:00.000Z"
ACTIONS = pl.REQUEST_KINDS  # the 14 actions of people.rules.md "Terms", in the API.md order
RECORD_KINDS = ("pinboard_item", "work_item", "calendar_entry", "meeting", "mention", "person")

SENTINEL = "SENTINEL-7c41f9e2-record-text"  # a title no repr, error or log may ever carry
READ_ACTIONS = ("read_full", "read_status", "read_busy", "read_directory", "read_membership")

# The view allowlists of API.md "Views and fields", written out here on purpose (the tests must not
# import the allowlist they are checking).
VIEW_KEYS = {
    "status": ("id", "title", "status", "due"),
    "busy": ("start", "end"),
    "directory": ("id", "display_name"),
    "membership": ("id", "display_name", "org_role", "memberships"),
}


def u(*code_points: int) -> str:
    """Build a string from code points (no escape sequences in the test files)."""
    return "".join(chr(c) for c in code_points)


def snap(obj: Any) -> Any:
    return copy.deepcopy(obj)


def dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=repr, ensure_ascii=False)


# ---------------------------------------------------------------------------------------------
# Crossref fixtures (contracts/fixtures/person/crossref/{valid,invalid}/*.json)
# ---------------------------------------------------------------------------------------------
def crossref_cases(kind: str) -> list[tuple[str, dict[str, Any]]]:
    folder = CROSSREF / kind
    return [(p.stem, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(folder.glob("*.json"))]


VALID_CASES = crossref_cases("valid")
INVALID_CASES = crossref_cases("invalid")
ALL_CASES = [*VALID_CASES, *INVALID_CASES]


def case_params(cases: list[tuple[str, dict[str, Any]]]) -> list[Any]:
    return [pytest.param(case, id=name) for name, case in cases]


def reference_permits(case: dict[str, Any], actor: str, action: str) -> bool:
    """The reference oracle of the crossref suite for `actor` doing `action` in `case`."""
    other = copy.deepcopy(case)
    other["request"] = {"actor": actor, "action": action, "view": None}
    try:
        return bool(pl.permits(other))
    except Exception:  # an oracle that crashes grants nothing
        return False


# ---------------------------------------------------------------------------------------------
# A small org (every record is schema-valid; checked by test_PPL_10a_testlib_builders_are_schema_valid)
# ---------------------------------------------------------------------------------------------
def member(team: str, by: str = "u_owner", at: str = T0) -> dict[str, Any]:
    return {"team": team, "assigned_by": {"by": by, "at": at}}


def make_person(
    uid: str,
    name: str,
    *,
    org: str = ORG,
    role: str = "member",
    teams: tuple[str, ...] = ("tm_sales",),
    by: str = "u_owner",
    at: str = T0,
    aliases: tuple[str, ...] = (),
    tz: str = "Asia/Kolkata",
    email: str | None = None,
) -> dict[str, Any]:
    return pl.person(
        id=uid,
        org_id=org,
        display_name=name,
        aliases=list(aliases),
        email=email or f"{uid[2:]}@example.com",
        time_zone=tz,
        org_role=role,
        memberships=[member(t, by, at) for t in teams],
        created_by={"by": by, "at": at},
    )


def world_persons() -> list[dict[str, Any]]:
    return [
        make_person("u_owner", "Owen Owner", role="owner", teams=("tm_sales",), aliases=("Owen",)),
        make_person("u_riya", "Riya Example", teams=("tm_sales",), aliases=("Riya",)),
        make_person("u_sam", "Sam Iyer", teams=("tm_ops",), aliases=("Sam",)),
        make_person("u_lee", "Lee Wong", teams=()),
        make_person("u_ext", "Eve Outsider", org=OTHER_ORG, role="owner", teams=("tm_sales",), by="u_ext"),
    ]


def world_directory(extra: list[dict[str, Any]] | None = None, drop: tuple[str, ...] = ()) -> Any:
    persons = [p for p in world_persons() if p["id"] not in drop]
    return directory.Directory.of([*persons, *(extra or [])])


def person_in(uid: str, persons: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return next(p for p in (persons or world_persons()) if p["id"] == uid)


def req(actor: Any, action: Any, kind: Any, record: Any, *, now: Any = NOW, **kw: Any) -> Any:
    return access.AccessRequest(actor=actor, action=action, record_kind=kind, record=record, now=now, **kw)


def verdict(actor: Any, action: Any, kind: Any, record: Any, d: Any = None, *, now: Any = NOW, **kw: Any) -> Any:
    return access.decide(req(actor, action, kind, record, now=now, **kw), d if d is not None else world_directory())


def allowed(actor: Any, action: Any, kind: Any, record: Any, d: Any = None, *, now: Any = NOW, **kw: Any) -> bool:
    return bool(verdict(actor, action, kind, record, d, now=now, **kw).allowed)


EXTRA_KEYS = ("meeting", "work_item", "source_owner", "pin", "mentions")


def ref_allows(
    actor: str,
    action: str,
    kind: str,
    record: dict[str, Any],
    persons: list[dict[str, Any]] | None = None,
    *,
    now: str = NOW,
    **extras: Any,
) -> bool:
    """What the reference oracle (`tests/contracts/_people_lib.permits`) says for the same request."""
    case = {
        "persons": {p["id"]: p for p in (persons if persons is not None else world_persons())},
        "now": now,
        "record": {
            "kind": kind,
            "data": record,
            **{k: v for k, v in extras.items() if k in EXTRA_KEYS and v is not None},
        },
        "request": {"actor": actor, "action": action, "view": None},
    }
    try:
        return bool(pl.permits(copy.deepcopy(case)))
    except Exception:
        return False


def both(actor: str, action: str, kind: str, record: dict[str, Any], **kw: Any) -> tuple[bool, bool]:
    """(reference oracle, tilo_people.decide) for the same request in the default org."""
    persons = kw.pop("persons", None)
    now = kw.pop("now", NOW)
    d = directory.Directory.of(persons) if persons is not None else world_directory()
    return (
        ref_allows(actor, action, kind, record, persons, now=now, **kw),
        allowed(actor, action, kind, record, d, now=now, **kw),
    )


# ---------------------------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------------------------
def meeting(**ov: Any) -> dict[str, Any]:
    return pl.meeting(**ov)


def minuted_meeting(by: str = "u_owner", at: str = T1, **ov: Any) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "status": "minuted",
        "transcript": copy.deepcopy(pl.ART),
        "minutes": copy.deepcopy(pl.ART_MINUTES),
        "minutes_confirmed_by": {"by": by, "at": at},
    }
    changes.update(ov)
    return pl.meeting(**changes)


def own_item(**ov: Any) -> dict[str, Any]:
    """A person-made, open work item on u_riya's own plate (no assigner)."""
    base = pl.work_item(
        id="wi_own1",
        owner="u_riya",
        title="Water the plants",
        due=None,
        due_text=None,
        source={"kind": "manual", "ref": None, "evidence": []},
        created_by=pl.maker_person("u_riya", T0),
        assigned_by=None,
        confirmed_by=None,
        history=[pl.history_entry("u_riya", "created", "open", T0)],
    )
    return pl.with_(base, **ov)


def tilo_item(**ov: Any) -> dict[str, Any]:
    """A Tilo-made work item from the minutes of mt_weekly1 for u_riya, assigned by the meeting owner."""
    base = pl.work_item(
        id="wi_tilo1",
        owner="u_riya",
        created_by=pl.maker_tilo("A_notes", T0),
        assigned_by={"by": "u_owner", "at": T0},
        confirmed_by={"by": "u_owner", "at": T1},
        status="open",
        history=[
            pl.history_entry("A_notes", "created", "proposed", T0),
            pl.history_entry("u_owner", "confirmed", "open", T1),
        ],
    )
    return pl.with_(base, **ov)


def proposed_tilo_item(**ov: Any) -> dict[str, Any]:
    changes: dict[str, Any] = {
        "status": "proposed",
        "confirmed_by": None,
        "history": [pl.history_entry("A_notes", "created", "proposed", T0)],
    }
    changes.update(ov)
    return tilo_item(**changes)


def team_pin(**ov: Any) -> dict[str, Any]:
    return pl.pin(**ov)


def personal_pin(**ov: Any) -> dict[str, Any]:
    return pl.personal_pin(**ov)


def tilo_team_pin(**ov: Any) -> dict[str, Any]:
    """A Tilo-made active team pin from mt_weekly1, confirmed by its setter (the meeting owner)."""
    base = pl.pin(
        id="pb_tilo1",
        created_by=pl.maker_tilo("A_notes", T0),
        set_up_by="u_owner",
        source={"kind": "meeting", "ref": "mt_weekly1", "evidence": []},
        confirmed_by={"by": "u_owner", "at": T1},
        history=[
            pl.history_entry("A_notes", "created", "proposed", T0),
            pl.history_entry("u_owner", "accepted", "active", T1),
        ],
    )
    return pl.with_(base, **ov)


def entry(**ov: Any) -> dict[str, Any]:
    """u_owner's own accepted, private, manual calendar entry."""
    return pl.calendar_entry(**ov)


def shared_entry(**ov: Any) -> dict[str, Any]:
    return pl.calendar_entry(share={"team": "tm_sales"}, **ov)


def tilo_proposal(**ov: Any) -> dict[str, Any]:
    """Tilo's calendar proposal for the owner of mt_weekly1, cited to that meeting."""
    base = pl.calendar_entry(
        id="ce_prop1",
        owner="u_owner",
        state="proposed",
        source={"kind": "tilo", "from": "meeting", "ref": "mt_weekly1"},
        created_by=pl.maker_tilo("A_notes", T1),
        confirmed_by=None,
        share=None,
    )
    return pl.with_(base, **ov)


def tag(**ov: Any) -> dict[str, Any]:
    return pl.mention(**ov)


# ---------------------------------------------------------------------------------------------
# Walking a document (for mutation tests)
# ---------------------------------------------------------------------------------------------
def put(doc: Any, path: tuple, value: Any) -> Any:
    return pl.put(doc, path, value)


def drop(doc: Any, path: tuple) -> Any:
    return pl.drop(doc, path)


def with_(doc: dict, **changes: Any) -> dict:
    return pl.with_(doc, **changes)
