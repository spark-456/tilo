"""Shared helpers for ticket CC-PEOPLE (contracts for people, meetings, pinboards, calendar and the
assistant panel; rules in `contracts/people.rules.md`, requirement text in
`docs/prd-addendum-people-agents.md`).

Not a test module (leading underscore), same convention as `_lib.py` and `_events_lib.py`. It holds

- minimal VALID documents for every new contract, written here on purpose: the tests must not read
  the architect's fixtures to build their inputs, and a mutation named by a rule must fail the
  schema it targets;
- `permits(case)`, the crossref oracle for people.rules.md PE-01 to PE-07 and PE-10 (the same shape
  `tilo-api` (CL-PEOPLE) tests run over `contracts/fixtures/person/crossref/`);
- the list of refusals the crossref fixtures must at least contain.

Ambiguities this file resolves (each is also in the ticket report; PRD/rules reference in brackets):

- A request is `{actor, action, view}`. people.rules.md lists `read_full`, `read_status`,
  `read_busy`, `edit`, `confirm`, `mention`, `untag` as the kinds of request. `request_kind()` accepts
  both spellings of a read: `action: "read_full"` or `action: "read"` with `view: "full"`.
  [people.rules.md "Terms"]
- A `mention` or `untag` request is made on a record of kind `mention` with the tagged pin in
  `record.pin`; every other request is made on the record itself. Tilo (for a tag) is an actor
  that is not in `persons` and has an agent id (`A_...`). [PE-06]
- A work item's `edit` is its owner's alone, and `confirm` is its `assigned_by.by` (the meeting Owner)
  on a `proposed` item: PE-03 gives nobody else a right and PE-07 names the meeting Owner. [PE-03, PE-07]
- `confirm` applies to a `proposed` team pin (set_up_by), `proposed` work item (assigned_by.by) and
  `proposed` calendar entry (owner); a meeting is confirmed by its owner (the minutes card). [PE-07]
- `read_busy` is open to every person of the record's org; `read_status` is allowed wherever
  `read_full` is, plus the assigner's status view of a work item. [PE-03, PE-04]
- calendar_entry follows the coordinator's later shape change: `share` is null (private) or `{team}`
  and "team-visible" in PE-04 means `share` is not null; `source` is one of three closed objects
  (google with ref and synced_at, manual, tilo with `from` and ref); visibility, team and
  synced_at fields are gone.
- Timestamps compare as strings: `common.schema.json#/$defs/timestamp` is fixed-width UTC.
"""

from __future__ import annotations

import copy
import json
import pathlib
from collections.abc import Callable
from typing import Any

from _lib import contracts_dir, errors_for, find_schema_path, load_json

BASE = "https://contracts.tilo.example/"
ORG = "org_acme"
OTHER_ORG = "org_other"
T0 = "2026-10-01T09:00:00.000Z"
T1 = "2026-10-02T09:00:00.000Z"
T2 = "2026-10-02T09:30:00.000Z"
ULID = "01J8Z3K4M5N6P7Q8R9S0T1V2W3"
ART = {"artifact_id": "art_transcript1", "version": 1}
ART_MINUTES = {"artifact_id": "art_minutes1", "version": 1}

ROUTES = (
    "plate",
    "calendar",
    "meetings",
    "meeting",
    "pinboard_team",
    "pinboard_personal",
    "worlds",
    "world",
    "cards",
    "connections",
    "channels",
    "autonomy",
    "settings",
)
CHANNELS = ("web", "mobile_web", "whatsapp", "email")
BAD_LINES = ("a\nb", "a\rb", "a\n", "\n", "a\r\n", "a\tb", "a\x00b", "a\x1bb")
VALID_ACTORS = ("u_riya", "A_notes", "tl_sales", "pol_autoreply", "system")
INVALID_ACTORS = ("riya", "org_acme", "w_1", "https://evil.example/x", "", "System", "u_")


# ---------------------------------------------------------------------------------------------
# Document editing helpers (always copy: a builder's result is never shared between cases).
# ---------------------------------------------------------------------------------------------
def put(doc: Any, path: tuple, value: Any) -> Any:
    out = copy.deepcopy(doc)
    cur = out
    for key in path[:-1]:
        cur = cur[key]
    cur[path[-1]] = value
    return out


def drop(doc: Any, path: tuple) -> Any:
    out = copy.deepcopy(doc)
    cur = out
    for key in path[:-1]:
        cur = cur[key]
    del cur[path[-1]]
    return out


def get(doc: Any, path: tuple) -> Any:
    cur = doc
    for key in path:
        cur = cur[key]
    return cur


def with_(doc: dict, **changes: Any) -> dict:
    out = copy.deepcopy(doc)
    out.update(copy.deepcopy(changes))
    return out


# ---------------------------------------------------------------------------------------------
# Schema access. Every validation goes through `problems`, which first asserts the file exists, so
# a missing contract fails with one clear message rather than a reference-resolution error.
# ---------------------------------------------------------------------------------------------
def schema_path(repo_root: pathlib.Path, rel: str) -> pathlib.Path:
    """`rel` is `person` (a top-level contract) or `events/data/meeting.minuted`."""
    if "/" not in rel:
        return find_schema_path(repo_root, rel)
    return contracts_dir(repo_root) / f"{rel}.schema.json"


def load_contract(repo_root: pathlib.Path, rel: str) -> dict[str, Any]:
    path = schema_path(repo_root, rel)
    assert path.is_file(), f"contracts/{rel}.schema.json does not exist (ticket CC-PEOPLE adds it)"
    return json.loads(path.read_text(encoding="utf-8"))


def problems(repo_root: pathlib.Path, registry: Any, rel: str, instance: Any, def_: str | None = None) -> list[str]:
    schema = load_contract(repo_root, rel)
    if def_ is not None:
        assert def_ in schema.get("$defs", {}), f"contracts/{rel}.schema.json has no $defs/{def_}"
    target = {"$ref": f"{BASE}{rel}.schema.json" + (f"#/$defs/{def_}" if def_ else "")}
    return [e.message for e in errors_for(target, instance, registry)]


def assert_valid(repo_root, registry, rel, instance, def_=None, why="") -> None:
    found = problems(repo_root, registry, rel, instance, def_)
    assert not found, f"{why or rel}: expected valid, got {found[:3]}"


def assert_invalid(repo_root, registry, rel, instance, def_=None, why="") -> None:
    found = problems(repo_root, registry, rel, instance, def_)
    assert found, f"{why or rel}: expected invalid, but the schema accepted {json.dumps(instance)[:200]}"


def fixture_files(repo_root: pathlib.Path, rel_dir: str) -> list[pathlib.Path]:
    d = contracts_dir(repo_root) / "fixtures" / rel_dir
    return sorted(d.glob("*.json")) if d.is_dir() else []


# ---------------------------------------------------------------------------------------------
# Minimal valid documents.
# ---------------------------------------------------------------------------------------------
def assignment(by: str = "u_owner", at: str = T0) -> dict:
    return {"by": by, "at": at}


def maker_person(ref: str = "u_owner", at: str = T0) -> dict:
    return {"by": "person", "ref": ref, "at": at}


def maker_tilo(ref: str = "A_notes", at: str = T0) -> dict:
    return {"by": "tilo", "ref": ref, "at": at}


def person(**ov: Any) -> dict:
    base = {
        "id": "u_riya",
        "org_id": ORG,
        "display_name": "Riya Example",
        "aliases": ["Riya"],
        "email": "riya@example.com",
        "time_zone": "Asia/Kolkata",
        "preferred_channel": "web",
        "org_role": "member",
        "memberships": [{"team": "tm_sales", "assigned_by": assignment()}],
        "created_by": assignment(),
    }
    return with_(base, **ov)


def meeting(**ov: Any) -> dict:
    base = {
        "id": "mt_weekly1",
        "org_id": ORG,
        "owner": "u_owner",
        "title": "Weekly sync",
        "series": "weekly-sync",
        "scheduled": {"start": T1, "end": T2},
        "agenda": [{"title": "Budget", "minutes": 10}],
        "attendees": [{"name": "Riya", "user": "u_riya"}, {"name": "Guest", "user": None}],
        "attestation": {"by": "u_owner", "at": T0, "notice_version": "1.0.0"},
        "source": "bot",
        "status": "scheduled",
        "ended_reason": None,
        "transcript": None,
        "minutes": None,
        "delete_transcript_after": None,
        "delete_minutes_after": None,
        "created_at": T0,
    }
    return with_(base, **ov)


def claim(text: str = "Ship the budget on Friday.", state: str = "verified", evidence: tuple = ("u0001",)) -> dict:
    return {"text": text, "state": state, "evidence": list(evidence)}


def action_item(id: str = "ai1", **ov: Any) -> dict:
    base = {
        **claim("Riya sends the budget."),
        "id": id,
        "owner_text": "Riya",
        "owner": "u_riya",
        "due_text": "by Friday",
        "due": "2026-10-09",
        "work_item_id": None,
    }
    return with_(base, **ov)


def minutes(**ov: Any) -> dict:
    base = {
        "meeting_id": "mt_weekly1",
        "transcript": copy.deepcopy(ART),
        "generated_at": T1,
        "flagged": False,
        "summary": [{"text": "The team agreed the budget split.", "evidence": ["u0001", "u0002"]}],
        "decisions": [claim()],
        "action_items": [action_item()],
        "agenda": [{"title": "Budget", "coverage": "covered", "evidence": ["u0002"]}],
    }
    return with_(base, **ov)


def history_entry(by: str = "u_owner", change: str = "created", status: str = "open", at: str = T0) -> dict:
    return {"at": at, "by": by, "change": change, "status": status}


def work_item(**ov: Any) -> dict:
    base = {
        "id": "wi_budget1",
        "org_id": ORG,
        "owner": "u_riya",
        "title": "Send the budget",
        "due": "2026-10-09",
        "due_text": "by Friday",
        "status": "open",
        "source": {"kind": "meeting", "ref": "mt_weekly1", "evidence": ["u0004"]},
        "created_by": maker_person(),
        "assigned_by": assignment(),
        "confirmed_by": assignment(),
        "snoozed_until": None,
        "history": [history_entry()],
        "created_at": T0,
        "updated_at": T0,
    }
    return with_(base, **ov)


def pin(**ov: Any) -> dict:
    """A team pinboard item made by a person (active)."""
    base = {
        "id": "pb_deadline1",
        "org_id": ORG,
        "scope": {"kind": "team", "team": "tm_sales"},
        "title": "Q4 deadline",
        "body": None,
        "kind": "deadline",
        "url": None,
        "owner": None,
        "due": "2026-10-31",
        "status": "active",
        "created_by": maker_person(),
        "set_up_by": "u_owner",
        "source": None,
        "confirmed_by": None,
        "history": [history_entry(change="created", status="active")],
        "created_at": T0,
        "updated_at": T0,
    }
    return with_(base, **ov)


def personal_pin(**ov: Any) -> dict:
    base = pin(
        id="pb_mine1",
        scope={"kind": "personal", "user": "u_riya"},
        set_up_by="u_riya",
        created_by=maker_person("u_riya"),
        history=[history_entry("u_riya", "created", "active")],
    )
    return with_(base, **ov)


def mention(**ov: Any) -> dict:
    base = {
        "id": "mn_tag1",
        "org_id": ORG,
        "pin_id": "pb_deadline1",
        "team": "tm_sales",
        "user": "u_riya",
        "added_by": maker_person(),
        "removed": None,
    }
    return with_(base, **ov)


def calendar_entry(**ov: Any) -> dict:
    base = {
        "id": "ce_plan1",
        "org_id": ORG,
        "owner": "u_owner",
        "title": "Planning",
        "start": T1,
        "end": T2,
        "all_day": False,
        "attendee_count": 0,
        "source": {"kind": "manual"},
        "state": "accepted",
        "share": None,
        "created_by": maker_person(),
        "confirmed_by": None,
        "updated_at": T0,
    }
    return with_(base, **ov)


GOOGLE_SOURCE = {"kind": "google", "ref": "evt_abc123", "synced_at": T0}
TILO_SOURCE = {"kind": "tilo", "from": "meeting", "ref": "mt_weekly1"}


def agenda_item(**ov: Any) -> dict:
    base = {
        "start": T1,
        "end": T2,
        "all_day": False,
        "title": "Planning",
        "kind": "event",
        "source": {"kind": "calendar_entry", "id": "ce_plan1"},
        "state": "confirmed",
        "shared": False,
    }
    return with_(base, **ov)


def free_busy(**ov: Any) -> dict:
    base = {"user": "u_riya", "from": T1, "to": "2026-10-03T09:00:00.000Z", "busy": [{"start": T1, "end": T2}]}
    return with_(base, **ov)


UI_ACTIONS: dict[str, dict] = {
    "navigate": {"kind": "navigate", "route": "plate", "target": None},
    "mark_done": {"kind": "mark_done", "work_item_id": "wi_budget1"},
    "snooze": {"kind": "snooze", "work_item_id": "wi_budget1", "until": T1},
    "draft_reply": {"kind": "draft_reply", "thread": "thread-supplier-1"},
    "tag": {"kind": "tag", "pin_id": "pb_deadline1", "user": "u_riya"},
    "untag": {"kind": "untag", "pin_id": "pb_deadline1", "user": "u_riya"},
}
TARGETS: tuple[dict, ...] = (
    {"kind": "world", "id": "w_village1"},
    {"kind": "meeting", "id": "mt_weekly1"},
    {"kind": "card", "id": ULID},
    {"kind": "pin", "id": "pb_deadline1"},
    {"kind": "work_item", "id": "wi_budget1"},
    {"kind": "calendar_entry", "id": "ce_plan1"},
)


def ui_action(kind: str = "navigate", **ov: Any) -> dict:
    return with_(UI_ACTIONS[kind], **ov)


# ---------------------------------------------------------------------------------------------
# Event data: type -> (pillar, valid data). All fields below are required by the ticket.
# ---------------------------------------------------------------------------------------------
EVENT_SPECS: dict[str, tuple[str, dict[str, Any]]] = {
    "meeting.minuted": (
        "P2",
        {
            "meeting_id": "mt_weekly1",
            "minutes": copy.deepcopy(ART_MINUTES),
            "decisions": 2,
            "action_items": 5,
            "unverified": 1,
            "flagged": False,
        },
    ),
    "work_item.created": (
        "P2",
        {"work_item_id": "wi_budget1", "owner": "u_riya", "status": "proposed", "source_kind": "meeting"},
    ),
    "work_item.changed": ("P2", {"work_item_id": "wi_budget1", "change": "done", "status": "done"}),
    "pinboard.item_added": (
        "P2",
        {
            "pin_id": "pb_deadline1",
            "scope_kind": "team",
            "team": "tm_sales",
            "status": "proposed",
            "made_by": "tilo",
            "source_kind": "meeting",
        },
    ),
    "pinboard.item_changed": ("P2", {"pin_id": "pb_deadline1", "change": "accepted", "status": "active"}),
    "mention.added": (
        "P2",
        {"mention_id": "mn_tag1", "pin_id": "pb_deadline1", "team": "tm_sales", "user": "u_riya"},
    ),
    "mention.removed": ("P2", {"mention_id": "mn_tag1", "pin_id": "pb_deadline1", "removed_by": "u_riya"}),
    "calendar.synced": ("P6", {"kind": "incremental", "changed": 3}),
    "calendar.entry_proposed": ("P6", {"entry_id": "ce_plan1", "source_kind": "meeting"}),
    "calendar.entry_changed": ("P6", {"entry_id": "ce_plan1", "change": "accepted", "state": "accepted"}),
    "assistant.asked": (
        "P5",
        {"conversation_id": ULID, "message_ref": "r_01J8Z3K4M5/12", "screen": "plate"},
    ),
    "assistant.replied": (
        "P5",
        {
            "conversation_id": ULID,
            "message_ref": "r_01J8Z3K4M5/13",
            "outcome": "answered",
            "decided_by": "rules",
            "sources": [{"kind": "work_item", "id": "wi_budget1"}],
            "ui_action": None,
            "cached": False,
        },
    ),
}
NEW_EVENT_TYPES = tuple(EVENT_SPECS)
NEW_FAMILIES = ("work_item", "pinboard", "mention", "calendar", "assistant")


def event_data(type_: str, **ov: Any) -> dict:
    return with_(EVENT_SPECS[type_][1], **ov)


def data_model_name(type_: str) -> str:
    family, verb = type_.split(".")
    return "".join(p[:1].upper() + p[1:] for p in (family + "_" + verb).split("_")) + "Data"


# ---------------------------------------------------------------------------------------------
# Crossref oracle (people.rules.md PE-01 to PE-07, PE-10).
# ---------------------------------------------------------------------------------------------
CASE_KEYS = {"rule", "note", "now", "persons", "record", "request"}
RECORD_KINDS = {
    "pinboard_item": "pinboard_item",
    "work_item": "work_item",
    "calendar_entry": "calendar_entry",
    "meeting": "meeting",
    "mention": "mention",
    "person": "person",
}
REQUEST_KINDS = (
    "read_full",
    "read_status",
    "read_busy",
    "edit",
    "confirm",
    "mention",
    "untag",
    "assign_membership",
    "set_org_role",
)
RULES = ("PE-01", "PE-02", "PE-03", "PE-04", "PE-05", "PE-06", "PE-07", "PE-17")


def request_kind(request: dict) -> str:
    action = request["action"]
    return f"read_{request.get('view')}" if action == "read" else action


def is_member(persons: dict, user: str, team: str, now: str) -> bool:
    """A member of team T at `now` (people.rules.md "Terms"): a `memberships` entry for T whose
    `assigned_by.by` is a person of the same org with `org_role: owner`, `assigned_by.at <= now`."""
    p = persons.get(user)
    if p is None:
        return False
    for m in p["memberships"]:
        if m["team"] != team:
            continue
        assigner = persons.get(m["assigned_by"]["by"])
        if (
            assigner is not None
            and assigner["org_id"] == p["org_id"]
            and assigner["org_role"] == "owner"
            and m["assigned_by"]["at"] <= now
        ):
            return True
    return False


def _pin_permits(persons: dict, now: str, actor: str, kind: str, data: dict) -> bool:
    scope = data["scope"]
    if scope["kind"] == "personal":  # PE-01: the person alone; no confirm, mention or busy view
        return actor == scope["user"] and kind in ("read_full", "read_status", "edit")
    if data["status"] == "active":  # PE-02: members read, set_up_by edits
        if kind in ("read_full", "read_status"):
            return is_member(persons, actor, scope["team"], now)
        return kind == "edit" and actor == data["set_up_by"]
    if kind in ("read_full", "read_status", "edit"):  # proposed or removed: set_up_by only
        return actor == data["set_up_by"]
    return kind == "confirm" and data["status"] == "proposed" and actor == data["set_up_by"]


def _work_item_permits(actor: str, kind: str, data: dict) -> bool:
    owner = data["owner"]
    assigner = (data["assigned_by"] or {}).get("by")
    if kind in ("read_full", "edit"):  # PE-03: the owner reads in full; nobody else
        return actor == owner
    if kind == "read_status":
        return actor == owner or (assigner is not None and actor == assigner and data["status"] != "proposed")
    return kind == "confirm" and assigner is not None and actor == assigner and data["status"] == "proposed"


def _calendar_permits(persons: dict, now: str, actor: str, kind: str, data: dict) -> bool:
    share = data["share"]  # null = private; {team} = shared with that team (brief change)
    full = actor == data["owner"] or (share is not None and is_member(persons, actor, share["team"], now))
    if kind in ("read_full", "read_status"):
        return full
    if kind == "read_busy":  # PE-04: everyone else sees the interval only (org owners no more)
        return True
    if kind == "edit":
        return actor == data["owner"]
    return kind == "confirm" and actor == data["owner"] and data["state"] == "proposed"


def _person_permits(persons: dict, actor: str, kind: str, data: dict) -> bool:
    # PE-17: directory changes (a membership, an org role) are an org owner's, of the same org
    assigner = persons.get(actor)
    owner = assigner is not None and assigner["org_id"] == data["org_id"] and assigner["org_role"] == "owner"
    return kind in ("assign_membership", "set_org_role") and owner


def _meeting_permits(actor: str, kind: str, data: dict) -> bool:
    # PE-05: the meeting owner alone; attendees, assignees, teammates and org owners read nothing.
    return kind in ("read_full", "read_status", "edit", "confirm") and actor == data["owner"]


def _mention_permits(case: dict, kind: str) -> bool:
    persons, now, record, actor = case["persons"], case["now"], case["record"], case["request"]["actor"]
    pin, mention_ = record.get("pin"), record["data"]
    if pin is None or pin["scope"]["kind"] != "team":  # PE-01/PE-06: a personal item takes no mention
        return False
    if (
        mention_["pin_id"] != pin["id"]
        or mention_["team"] != pin["scope"]["team"]
        or mention_["org_id"] != pin["org_id"]
    ):
        return False
    actor_person = persons.get(actor)
    if kind == "mention":
        tagged = persons.get(mention_["user"])
        if mention_["removed"] is not None or tagged is None or tagged["org_id"] != pin["org_id"]:
            return False  # a removed mention is never re-added
        if not is_member(persons, mention_["user"], mention_["team"], now):
            return False
        if actor_person is not None:
            return actor == pin["set_up_by"] and actor_person["org_id"] == pin["org_id"]
        confirmed = pin["confirmed_by"]  # Tilo, for an item the set_up_by person confirmed
        return actor.startswith("A_") and confirmed is not None and confirmed["by"] == pin["set_up_by"]
    if kind == "untag":
        return (
            actor_person is not None
            and actor_person["org_id"] == pin["org_id"]
            and actor in (mention_["user"], pin["set_up_by"])
        )
    return False


def permits(case: dict) -> bool:
    """True when people.rules.md PE-01 to PE-07 grant the request in `case`."""
    request, record = case["request"], case["record"]
    kind = request_kind(request)
    if kind not in REQUEST_KINDS:
        return False
    if record["kind"] == "mention":
        return _mention_permits(case, kind)
    actor, persons, now, data = request["actor"], case["persons"], case["now"], record["data"]
    actor_person = persons.get(actor)
    if actor_person is None or actor_person["org_id"] != data["org_id"]:
        return False  # also PE-17: another org's owner changes nothing here
    if record["kind"] == "pinboard_item":
        return _pin_permits(persons, now, actor, kind, data)
    if record["kind"] == "work_item":
        return _work_item_permits(actor, kind, data)
    if record["kind"] == "calendar_entry":
        return _calendar_permits(persons, now, actor, kind, data)
    if record["kind"] == "meeting":
        return _meeting_permits(actor, kind, data)
    if record["kind"] == "person":
        return _person_permits(persons, actor, kind, data)
    return False


def case_shape_problems(repo_root: pathlib.Path, registry: Any, case: dict) -> list[str]:
    """Every part of a crossref case is shape-valid against its schema."""
    found: list[str] = []
    if set(case) != CASE_KEYS:
        return [f"keys must be {sorted(CASE_KEYS)}, got {sorted(case)}"]
    if case["rule"] is not None and case["rule"] not in RULES:
        found.append(f"rule must be null or one of {RULES}")
    if not isinstance(case["note"], str) or not case["note"]:
        found.append("note must be a non-empty string")
    found += [f"now: {m}" for m in problems(repo_root, registry, "common", case["now"], "timestamp")]
    persons = case["persons"]
    if not isinstance(persons, dict) or not persons:
        return [*found, "persons must be a non-empty map of user id to person"]
    for key, p in persons.items():
        found += [f"persons.{key}: {m}" for m in problems(repo_root, registry, "person", p)]
        if isinstance(p, dict) and p.get("id") != key:
            found.append(f"persons.{key}: the key must equal the person's id")
    record = case["record"]
    if not isinstance(record, dict) or set(record) - {"kind", "data", "pin"} or {"kind", "data"} - set(record):
        return [*found, "record holds kind, data (and pin for a mention)"]
    if record["kind"] not in RECORD_KINDS:
        return [*found, f"record.kind must be one of {sorted(RECORD_KINDS)}"]
    found += [f"record.data: {m}" for m in problems(repo_root, registry, RECORD_KINDS[record["kind"]], record["data"])]
    if (record["kind"] == "mention") != ("pin" in record):
        found.append("record.pin is present exactly for a mention")
    if "pin" in record:
        found += [f"record.pin: {m}" for m in problems(repo_root, registry, "pinboard_item", record["pin"])]
    request = case["request"]
    if not isinstance(request, dict) or set(request) != {"actor", "action", "view"}:
        return [*found, "request holds actor, action and view"]
    actor_ok = not problems(repo_root, registry, "common", request["actor"], "user_id") or not problems(
        repo_root, registry, "common", request["actor"], "agent_id"
    )
    if not actor_ok:
        found.append("request.actor must be a user id or an agent id (Tilo)")
    if request["action"] not in (*REQUEST_KINDS, "read"):
        found.append(f"request.action must be one of {REQUEST_KINDS} (or read with a view)")
    if request["action"] == "read" and request["view"] not in ("full", "status", "busy"):
        found.append("a read request names its view: full, status or busy")
    return found


# ---------------------------------------------------------------------------------------------
# Refusals the invalid crossref fixtures must at least contain (brief, "Crossref oracle").
# Each predicate looks at the case content, not at the file name.
# ---------------------------------------------------------------------------------------------
def _reads(case: dict) -> bool:
    return request_kind(case["request"]).startswith("read_") and request_kind(case["request"]) != "read_busy"


def _is(case: dict, kind: str) -> bool:
    return case["record"]["kind"] == kind


def _team_pin_read(case: dict, status: str) -> bool:
    d = case["record"]["data"]
    return _is(case, "pinboard_item") and _reads(case) and d["scope"]["kind"] == "team" and d["status"] == status


def _entry_for(case: dict) -> dict | None:
    d, p = case["record"]["data"], case["persons"].get(case["request"]["actor"])
    if p is None or d.get("scope", {}).get("kind") != "team":
        return None
    return next((m for m in p["memberships"] if m["team"] == d["scope"]["team"]), None)


def _teammate_reads_personal_pin(case: dict) -> bool:
    d, p = case["record"]["data"], case["persons"].get(case["request"]["actor"])
    return (
        _is(case, "pinboard_item")
        and _reads(case)
        and d["scope"]["kind"] == "personal"
        and p is not None
        and case["request"]["actor"] != d["scope"]["user"]
        and p["org_role"] == "member"
    )


def _owner_reads_personal_pin(case: dict) -> bool:
    d, p = case["record"]["data"], case["persons"].get(case["request"]["actor"])
    return (
        _is(case, "pinboard_item")
        and _reads(case)
        and d["scope"]["kind"] == "personal"
        and p is not None
        and case["request"]["actor"] != d["scope"]["user"]
        and p["org_role"] == "owner"
    )


def _member_reads_proposed_team_pin(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _team_pin_read(case, "proposed")
        and case["request"]["actor"] != d["set_up_by"]
        and is_member(case["persons"], case["request"]["actor"], d["scope"]["team"], case["now"])
    )


def _non_member_reads_active_team_pin(case: dict) -> bool:
    d = case["record"]["data"]
    return _team_pin_read(case, "active") and not is_member(
        case["persons"], case["request"]["actor"], d["scope"]["team"], case["now"]
    )


def _membership_assigned_by_non_owner(case: dict) -> bool:
    entry = _entry_for(case)
    if entry is None or not _team_pin_read(case, "active"):
        return False
    assigner = case["persons"].get(entry["assigned_by"]["by"])
    return assigner is not None and assigner["org_role"] != "owner"


def _membership_dated_after_now(case: dict) -> bool:
    entry = _entry_for(case)
    if entry is None or not _team_pin_read(case, "active"):
        return False
    assigner = case["persons"].get(entry["assigned_by"]["by"])
    return assigner is not None and assigner["org_role"] == "owner" and entry["assigned_by"]["at"] > case["now"]


def _member_changes_the_directory(case: dict) -> bool:
    p = case["persons"].get(case["request"]["actor"])
    return (
        _is(case, "person")
        and request_kind(case["request"]) in ("assign_membership", "set_org_role")
        and p is not None
        and p["org_role"] != "owner"
    )


def _assigner_reads_proposed_work_item(case: dict) -> bool:
    d = case["record"]["data"]
    assigner = (d.get("assigned_by") or {}).get("by") if _is(case, "work_item") else None
    return (
        _is(case, "work_item")
        and request_kind(case["request"]) == "read_status"
        and d["status"] == "proposed"
        and assigner is not None
        and case["request"]["actor"] == assigner
        and assigner != d["owner"]
    )


def _teammate_reads_private_entry_in_full(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _is(case, "calendar_entry")
        and request_kind(case["request"]) == "read_full"
        and d["share"] is None
        and case["request"]["actor"] != d["owner"]
    )


def _attendee_reads_minutes(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _is(case, "meeting")
        and request_kind(case["request"]) in ("read_full", "read_status")
        and case["request"]["actor"] != d["owner"]
        and case["request"]["actor"] in {a["user"] for a in d["attendees"] if a["user"]}
    )


def _tag_on_non_member(case: dict) -> bool:
    m = case["record"]["data"]
    return (
        _is(case, "mention")
        and request_kind(case["request"]) == "mention"
        and not is_member(case["persons"], m["user"], m["team"], case["now"])
    )


def _untag_by_third_party(case: dict) -> bool:
    m, pin_ = case["record"]["data"], case["record"].get("pin") or {}
    actor = case["request"]["actor"]
    return (
        _is(case, "mention")
        and request_kind(case["request"]) == "untag"
        and actor != m["user"]
        and actor != pin_.get("set_up_by")
    )


REQUIRED_REFUSALS: dict[str, Callable[[dict], bool]] = {
    "a teammate reads a personal pin": _teammate_reads_personal_pin,
    "an org owner reads a personal pin": _owner_reads_personal_pin,
    "a member reads a proposed team pin": _member_reads_proposed_team_pin,
    "a non-member reads an active team pin": _non_member_reads_active_team_pin,
    "a membership assigned by a non-owner": _membership_assigned_by_non_owner,
    "a membership dated after now": _membership_dated_after_now,
    "an assigner reads a proposed work item": _assigner_reads_proposed_work_item,
    "a teammate reads a private calendar entry in full": _teammate_reads_private_entry_in_full,
    "an attendee reads minutes": _attendee_reads_minutes,
    "a tag on a non-member": _tag_on_non_member,
    "a person other than the tagged or set-up person removes a tag": _untag_by_third_party,
    "a member assigns a membership or sets an org role": _member_changes_the_directory,
}


def load_cases(repo_root: pathlib.Path, kind: str) -> list[tuple[pathlib.Path, dict]]:
    return [(p, load_json(p)) for p in fixture_files(repo_root, f"person/crossref/{kind}")]
