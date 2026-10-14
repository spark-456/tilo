"""Shared helpers for ticket CC-PEOPLE (contracts for people, meetings, pinboards, calendar and the
assistant panel; rules in `contracts/people.rules.md`, requirement text in
`docs/prd-addendum-people-agents.md`).

Not a test module (leading underscore), same convention as `_lib.py` and `_events_lib.py`. It holds

- minimal VALID documents for every new contract, written here on purpose: the tests must not read
  the architect's fixtures to build their inputs, and a mutation named by a rule must fail the
  schema it targets;
- `permits(case)`, the crossref oracle for people.rules.md PE-01 to PE-07, PE-17 and PE-18 (the same shape
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
import hashlib
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
CHANNELS = ("web", "mobile_web", "email")
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
        "minutes_confirmed_by": None,
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
        "flagged": False,
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
        "flagged": False,
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
        "flagged": False,
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
# Crossref oracle (people.rules.md PE-01 to PE-07, PE-17, PE-18; PE-10 is ui_action's own tests).
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
    "read_directory",
    "read_membership",
    "create",
    "edit",
    "confirm",
    "mention",
    "untag",
    "mark_done",
    "assign_membership",
    "set_org_role",
    "start_capture",
)
RULES = (
    "PE-01",
    "PE-02",
    "PE-03",
    "PE-04",
    "PE-05",
    "PE-06",
    "PE-07",
    "PE-08",
    "PE-10",
    "PE-17",
    "PE-18",
    "PE-19",
    "PE-20",
)
READS = ("read_full", "read_status")


def request_kind(request: dict) -> str:
    action = request["action"]
    return f"read_{request.get('view')}" if action == "read" else action


def is_tilo(actor: str) -> bool:
    """Tilo acts as an agent id (A_...); a person is a user id (u_...)."""
    return actor.startswith("A_")


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


def teammates(persons: dict, a: str, b: str, now: str) -> bool:
    """Two people who are members of at least one team in common at `now`."""
    pa = persons.get(a)
    if pa is None or persons.get(b) is None:
        return False
    return any(
        is_member(persons, a, m["team"], now) and is_member(persons, b, m["team"], now) for m in pa["memberships"]
    )


def _confirmed(data: dict, confirmer: str | None, now: str) -> bool:
    """PE-07: a Tilo-made record counts as confirmed only by the person who owns the decision,
    dated between its creation (`created_by.at`) and the request."""
    c = data["confirmed_by"]
    return (
        c is not None and confirmer is not None and c["by"] == confirmer and data["created_by"]["at"] <= c["at"] <= now
    )


def _meeting_matches(ref: str | None, org_id: str, meeting: dict | None) -> bool:
    """PE-19: the source meeting is supplied, is the one `source.ref` names (before the #) and is of the org."""
    return (
        meeting is not None and ref is not None and ref.split("#")[0] == meeting["id"] and meeting["org_id"] == org_id
    )


def _minutes_confirmed(meeting: dict, now: str) -> bool:
    """PE-08, PE-19: the meeting Owner confirmed the minutes (by the owner, dated no later than the request)."""
    c = meeting.get("minutes_confirmed_by")
    return meeting["status"] == "minuted" and c is not None and c["by"] == meeting["owner"] and c["at"] <= now


def _released_item(data: dict, record: dict, meeting: dict, now: str) -> bool:
    """PE-08: a calendar proposal for an attendee cites an action item (`mt_x#aiN`) whose work item for
    that attendee the meeting Owner confirmed, on minutes the Owner confirmed."""
    ref, item = data["source"]["ref"], record.get("work_item")
    return (
        ref is not None
        and "#" in ref
        and item is not None
        and item["owner"] == data["owner"]
        and item["source"]["ref"] == ref
        and item["status"] in ("open", "done")
        and item["created_by"]["by"] == "tilo"
        and (item["assigned_by"] or {}).get("by") == meeting["owner"]
        and _confirmed(item, meeting["owner"], now)
        and _minutes_confirmed(meeting, now)
    )


def _tilo_made_ok(kind: str, data: dict, record: dict, now: str) -> bool:
    """PE-08, PE-19: a Tilo-made record's source and stamps hold, checked on every request about it.
    A meeting source needs its meeting in the case (fail closed); another source needs its owner."""
    meeting, source_owner = record.get("meeting"), record.get("source_owner")
    if data["created_by"]["by"] != "tilo":
        return True
    source = data["source"]
    if kind == "pinboard_item":
        if source is None or source["kind"] == "manual":
            return False
        if data["scope"]["kind"] == "personal" and data["set_up_by"] != data["scope"]["user"]:
            return False
        if source["kind"] == "meeting":
            return _meeting_matches(source["ref"], data["org_id"], meeting) and (data["set_up_by"] == meeting["owner"])
        return source_owner == data["set_up_by"]
    if kind == "work_item":  # Tilo makes work items from minutes only; the meeting Owner is the assigner
        return (
            source["kind"] == "meeting"
            and _meeting_matches(source["ref"], data["org_id"], meeting)
            and (data["assigned_by"] or {}).get("by") == meeting["owner"]
        )
    if kind == "calendar_entry":
        if source["kind"] == "manual":
            return False
        if source["kind"] == "google":  # a sync writes the connected person's own entries only
            return source_owner == data["owner"]
        if source["from"] in ("meeting", "transcript"):
            if not _meeting_matches(source["ref"], data["org_id"], meeting):
                return False
            if meeting["owner"] == data["owner"]:
                return True
            # for another attendee: one action item the meeting Owner released, never a bare transcript
            return source["from"] == "meeting" and _released_item(data, record, meeting, now)
        return source_owner == data["owner"]
    return True


def _pin_permits(persons: dict, now: str, actor: str, kind: str, data: dict, record: dict) -> bool:
    scope, tilo_made = data["scope"], data["created_by"]["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("pinboard_item", data, record, now):
        return False
    created = data["created_by"]
    if not tilo_made and data["set_up_by"] != created["ref"]:
        return False  # PE-19: a person-made pin is set up by its creator
    if scope["kind"] == "personal":  # PE-01, PE-08
        if kind == "create":
            return is_tilo(actor) if tilo_made else actor == scope["user"]
        return actor == scope["user"] and kind in (*READS, "edit")
    team = scope["team"]  # PE-02
    member_actor = is_member(persons, actor, team, now)
    owner_ok = data["owner"] is None or is_member(persons, data["owner"], team, now)
    if kind == "create":
        if tilo_made:
            return is_tilo(actor) and data["status"] == "proposed" and owner_ok
        return actor == data["set_up_by"] and member_actor and owner_ok
    if is_tilo(actor):  # PE-07: Tilo never reads or confirms
        return False
    if data["status"] == "active":
        if kind in READS:
            return member_actor and (not tilo_made or _confirmed(data, data["set_up_by"], now))
        return kind == "edit" and actor == data["set_up_by"] and member_actor
    if kind in (*READS, "edit"):  # proposed or removed
        return actor == data["set_up_by"] and member_actor
    return kind == "confirm" and data["status"] == "proposed" and actor == data["set_up_by"] and member_actor


def _work_item_permits(now: str, actor: str, kind: str, data: dict, record: dict) -> bool:
    owner, status = data["owner"], data["status"]
    assigner = (data["assigned_by"] or {}).get("by")
    created = data["created_by"]
    tilo_made = created["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("work_item", data, record, now):
        return False
    if kind == "create":  # PE-03: a person-made item is its creator's own; Tilo makes proposed ones
        if not tilo_made:
            return actor == owner == created["ref"] and status == "open" and assigner in (None, created["ref"])
        return is_tilo(actor) and status == "proposed" and assigner is not None
    if is_tilo(actor):
        return False
    if status == "proposed":  # nobody reads it; the meeting Owner confirms it
        return kind == "confirm" and assigner is not None and actor == assigner
    if tilo_made and not _confirmed(data, assigner, now):
        return False
    if kind in ("read_full", "edit"):
        return actor == owner
    if kind == "mark_done":
        return actor == owner and status == "open"
    if kind == "read_status":
        return actor == owner or (assigner is not None and actor == assigner)
    return False


def _calendar_permits(persons: dict, now: str, actor: str, kind: str, data: dict, record: dict) -> bool:
    owner, share, created = data["owner"], data["share"], data["created_by"]
    tilo_made = created["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("calendar_entry", data, record, now):
        return False
    if kind == "create":
        if not tilo_made:
            return actor == owner
        # PE-07, PE-08: Tilo proposes (or syncs) privately; it never accepts or shares
        return is_tilo(actor) and data["confirmed_by"] is None and share is None
    if is_tilo(actor):  # Tilo never reads or accepts
        return False
    needs_confirmation = data["source"]["kind"] == "tilo" or (tilo_made and data["source"]["kind"] == "manual")
    if data["state"] == "accepted" and needs_confirmation and not _confirmed(data, owner, now):
        return False
    if kind == "confirm":
        return actor == owner and data["state"] == "proposed"
    owner_in_team = share is not None and is_member(persons, owner, share["team"], now)
    if kind == "edit":
        return actor == owner and (share is None or owner_in_team)  # sharing needs the owner in the team
    if kind in READS:
        shared = share is not None and data["state"] == "accepted" and owner_in_team
        return actor == owner or (shared and is_member(persons, actor, share["team"], now))
    if kind == "read_busy":  # PE-04: the owner, or teammates; accepted entries; interval only
        return actor == owner or (data["state"] == "accepted" and teammates(persons, actor, owner, now))
    return False


def _meeting_permits(persons: dict, actor: str, kind: str, data: dict) -> bool:
    # PE-05: the meeting owner alone; attendees, assignees, teammates and org owners read nothing.
    # PE-18: capture starts only when the owner attested (attestation.by is the owner, a person of the org).
    if kind == "start_capture":
        attester = persons.get(data["attestation"]["by"])
        return actor == data["owner"] and data["attestation"]["by"] == data["owner"] and attester is not None
    return kind in (*READS, "edit", "confirm") and actor == data["owner"]


def _person_permits(persons: dict, now: str, actor: str, kind: str, data: dict) -> bool:
    me = persons.get(actor)
    if me is None:
        return False
    owner = me["org_id"] == data["org_id"] and me["org_role"] == "owner"
    if kind in ("assign_membership", "set_org_role"):  # PE-17: directory changes are an org owner's
        return owner
    if kind == "read_full":  # PE-20: your own record, in full
        return actor == data["id"]
    if kind == "read_membership":
        return actor == data["id"] or owner
    if kind == "read_directory":
        return actor == data["id"] or owner or teammates(persons, actor, data["id"], now)
    return False


def _mention_permits(case: dict, kind: str) -> bool:
    persons, now, record, actor = case["persons"], case["now"], case["record"], case["request"]["actor"]
    pin, tag, others = record.get("pin"), record["data"], record.get("mentions") or []
    if pin is None or pin["scope"]["kind"] != "team":  # PE-01/PE-06: a personal item takes no mention
        return False
    if tag["pin_id"] != pin["id"] or tag["team"] != pin["scope"]["team"] or tag["org_id"] != pin["org_id"]:
        return False
    if pin["created_by"]["by"] == "tilo" and not _tilo_made_ok("pinboard_item", pin, record, now):
        return False
    person = persons.get(actor)
    if kind == "mention":
        tagged = persons.get(tag["user"])
        if pin["status"] != "active" or tag["removed"] is not None:  # only active pins take a tag
            return False
        if tagged is None or tagged["org_id"] != pin["org_id"] or not is_member(persons, tag["user"], tag["team"], now):
            return False
        if any(o["user"] == tag["user"] and o["removed"] and o["removed"]["by"] == tag["user"] for o in others):
            return False  # whoever removed themselves is not tagged on that pin again
        if person is not None:
            return (
                actor == pin["set_up_by"]
                and person["org_id"] == pin["org_id"]
                and is_member(persons, actor, tag["team"], now)
            )
        return is_tilo(actor) and _confirmed(pin, pin["set_up_by"], now)  # Tilo, for an item the setter confirmed
    if kind == "untag":
        if tag["removed"] is not None:
            return False
        return person is not None and person["org_id"] == pin["org_id"] and actor in (tag["user"], pin["set_up_by"])
    return False


def permits(case: dict) -> bool:
    """True when people.rules.md PE-01 to PE-08, PE-10 and PE-17 to PE-20 grant the request in `case`."""
    request, record = case["request"], case["record"]
    kind = request_kind(request)
    if kind not in REQUEST_KINDS:
        return False
    if record["kind"] == "mention":
        return _mention_permits(case, kind)
    actor, persons, now, data = request["actor"], case["persons"], case["now"], record["data"]
    if is_tilo(actor):
        if kind != "create":
            return False
    else:
        me = persons.get(actor)
        if me is None or me["org_id"] != data["org_id"]:
            return False  # also PE-17: another org's owner changes nothing here
    if record["kind"] == "pinboard_item":
        return _pin_permits(persons, now, actor, kind, data, record)
    if record["kind"] == "work_item":
        return _work_item_permits(now, actor, kind, data, record)
    if record["kind"] == "calendar_entry":
        return _calendar_permits(persons, now, actor, kind, data, record)
    if record["kind"] == "meeting":
        return _meeting_permits(persons, actor, kind, data)
    if record["kind"] == "person":
        return _person_permits(persons, now, actor, kind, data)
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
    if (
        not isinstance(record, dict)
        or set(record) - {"kind", "data", "pin", "mentions", "meeting", "source_owner", "work_item"}
        or {"kind", "data"} - set(record)
    ):
        return [*found, "record holds kind, data (pin and mentions for a mention, meeting for a Tilo-made record)"]
    if record["kind"] not in RECORD_KINDS:
        return [*found, f"record.kind must be one of {sorted(RECORD_KINDS)}"]
    found += [f"record.data: {m}" for m in problems(repo_root, registry, RECORD_KINDS[record["kind"]], record["data"])]
    if (record["kind"] == "mention") != ("pin" in record):
        found.append("record.pin is present exactly for a mention")
    if "pin" in record:
        found += [f"record.pin: {m}" for m in problems(repo_root, registry, "pinboard_item", record["pin"])]
    if "mentions" in record and record["kind"] != "mention":
        found.append("record.mentions is for a mention only")
    for other in record.get("mentions", []):
        found += [f"record.mentions: {m}" for m in problems(repo_root, registry, "mention", other)]
    if "meeting" in record:
        found += [f"record.meeting: {m}" for m in problems(repo_root, registry, "meeting", record["meeting"])]
    if "work_item" in record:
        found += [f"record.work_item: {m}" for m in problems(repo_root, registry, "work_item", record["work_item"])]
    if "source_owner" in record:
        found += [
            f"record.source_owner: {m}"
            for m in problems(repo_root, registry, "common", record["source_owner"], "user_id")
        ]
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
    if request["action"] == "read" and request["view"] not in ("full", "status", "busy", "directory", "membership"):
        found.append("a read request names its view: full, status, busy, directory or membership")
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


def _assignee_reads_proposed_work_item(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _is(case, "work_item") and d["status"] == "proposed" and _reads(case) and case["request"]["actor"] == d["owner"]
    )


def _capture_with_foreign_attestation(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _is(case, "meeting")
        and request_kind(case["request"]) == "start_capture"
        and d["attestation"]["by"] != d["owner"]
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


def _kind(case: dict) -> str:
    return request_kind(case["request"])


def _actor(case: dict) -> str:
    return case["request"]["actor"]


def _data(case: dict) -> dict:
    return case["record"]["data"]


def _tilo_personal_pin_from_anothers_meeting(case: dict) -> bool:
    d, m = _data(case), case["record"].get("meeting")
    return (
        _is(case, "pinboard_item")
        and _kind(case) == "create"
        and is_tilo(_actor(case))
        and d["scope"]["kind"] == "personal"
        and m is not None
        and m["owner"] != d["scope"]["user"]
    )


def _tilo_calendar_proposal_before_confirmation(case: dict) -> bool:
    d, m = _data(case), case["record"].get("meeting")
    return (
        _is(case, "calendar_entry")
        and _kind(case) == "create"
        and is_tilo(_actor(case))
        and m is not None
        and m["owner"] != d["owner"]
        and m.get("minutes_confirmed_by") is None
    )


def _assignee_changes_proposed_work_item(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "work_item")
        and d["status"] == "proposed"
        and _actor(case) == d["owner"]
        and _kind(case) in ("read_full", "edit")
    )


def _person_assigns_item_to_another(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "work_item")
        and _kind(case) == "create"
        and d["created_by"]["by"] == "person"
        and _actor(case) != d["owner"]
    )


def _tilo_confirms_its_own_record(case: dict) -> bool:
    return _kind(case) == "confirm" and is_tilo(_actor(case)) and _data(case)["created_by"]["by"] == "tilo"


def _non_assigner_confirms_work_item(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "work_item")
        and _kind(case) == "confirm"
        and not is_tilo(_actor(case))
        and _actor(case) != (d["assigned_by"] or {}).get("by")
    )


def _non_owner_accepts_calendar_entry(case: dict) -> bool:
    return (
        _is(case, "calendar_entry")
        and _kind(case) == "confirm"
        and not is_tilo(_actor(case))
        and _actor(case) != _data(case)["owner"]
    )


def _non_teammate_reads_busy(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "calendar_entry")
        and _kind(case) == "read_busy"
        and not teammates(case["persons"], _actor(case), d["owner"], case["now"])
    )


def _busy_of_an_entry_not_accepted(case: dict) -> bool:
    d = _data(case)
    return _is(case, "calendar_entry") and _kind(case) == "read_busy" and d["state"] != "accepted"


def _non_member_creates_team_pin(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "pinboard_item")
        and _kind(case) == "create"
        and d["scope"]["kind"] == "team"
        and not is_tilo(_actor(case))
        and not is_member(case["persons"], _actor(case), d["scope"]["team"], case["now"])
    )


def _former_member_edits_team_pin(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "pinboard_item")
        and _kind(case) == "edit"
        and d["scope"]["kind"] == "team"
        and _actor(case) == d["set_up_by"]
        and not is_member(case["persons"], _actor(case), d["scope"]["team"], case["now"])
    )


def _share_to_a_team_the_owner_is_not_in(case: dict) -> bool:
    d = _data(case)
    share = d.get("share") if _is(case, "calendar_entry") else None
    return (
        share is not None
        and _kind(case) == "edit"
        and not is_member(case["persons"], d["owner"], share["team"], case["now"])
    )


def _responsible_person_not_a_member(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "pinboard_item")
        and _kind(case) == "create"
        and d["scope"]["kind"] == "team"
        and d["owner"] is not None
        and not is_member(case["persons"], d["owner"], d["scope"]["team"], case["now"])
    )


def _tag_on_a_pin_not_active(case: dict) -> bool:
    pin = case["record"].get("pin")
    return _is(case, "mention") and _kind(case) == "mention" and pin is not None and pin["status"] != "active"


def _retag_after_self_removal(case: dict) -> bool:
    tag = _data(case)
    return (
        _is(case, "mention")
        and _kind(case) == "mention"
        and any(
            o["user"] == tag["user"] and o["removed"] and o["removed"]["by"] == tag["user"]
            for o in case["record"].get("mentions") or []
        )
    )


def _untag_already_removed(case: dict) -> bool:
    return _is(case, "mention") and _kind(case) == "untag" and _data(case)["removed"] is not None


def _confirmation_names_another_person(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "pinboard_item")
        and _kind(case) in READS
        and d["created_by"]["by"] == "tilo"
        and d["status"] == "active"
        and d["confirmed_by"] is not None
        and d["confirmed_by"]["by"] != d["set_up_by"]
    )


def _confirmation_in_the_future(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "pinboard_item")
        and _kind(case) in READS
        and d["created_by"]["by"] == "tilo"
        and d["confirmed_by"] is not None
        and d["confirmed_by"]["at"] > case["now"]
    )


def _tilo_pin_set_up_by_not_the_meeting_owner(case: dict) -> bool:
    d, m = _data(case), case["record"].get("meeting")
    return (
        _is(case, "pinboard_item")
        and d["created_by"]["by"] == "tilo"
        and m is not None
        and m["owner"] != d["set_up_by"]
    )


def _person_made_pin_set_up_by_someone_else(case: dict) -> bool:
    d = _data(case)
    return _is(case, "pinboard_item") and d["created_by"]["by"] == "person" and d["created_by"]["ref"] != d["set_up_by"]


def _person_of_another_org_reads(case: dict) -> bool:
    p = case["persons"].get(_actor(case))
    return p is not None and _kind(case) in (*READS, "read_busy") and p["org_id"] != _data(case).get("org_id")


def _non_owner_marks_item_done(case: dict) -> bool:
    d = _data(case)
    return _is(case, "work_item") and _kind(case) == "mark_done" and _actor(case) != d["owner"]


def _owner_marks_proposed_item_done(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "work_item") and _kind(case) == "mark_done" and _actor(case) == d["owner"] and d["status"] != "open"
    )


def _teammate_reads_full_person_record(case: dict) -> bool:
    return _is(case, "person") and _kind(case) == "read_full" and _actor(case) != _data(case)["id"]


def _non_teammate_reads_directory(case: dict) -> bool:
    d = _data(case)
    p = case["persons"].get(_actor(case))
    return (
        _is(case, "person")
        and _kind(case) == "read_directory"
        and p is not None
        and p["org_role"] != "owner"
        and not teammates(case["persons"], _actor(case), d["id"], case["now"])
    )


def _tilo_creates_accepted_or_shared_entry(case: dict) -> bool:
    d = case["record"]["data"]
    return (
        _is(case, "calendar_entry")
        and _kind(case) == "create"
        and is_tilo(_actor(case))
        and (d["state"] == "accepted" or d["share"] is not None or d["confirmed_by"] is not None)
    )


def _tilo_writes_from_a_source_another_person_owns(case: dict) -> bool:
    d, owner = case["record"]["data"], case["record"].get("source_owner")
    if not (_kind(case) == "create" and is_tilo(_actor(case))) or owner is None:
        return False
    target = d["scope"].get("user") if _is(case, "pinboard_item") else d.get("owner")
    return target is not None and owner != target


def _meeting_sourced_tilo_record_without_its_meeting(case: dict) -> bool:
    d = case["record"]["data"]
    src = d.get("source")
    if not isinstance(src, dict) or case["record"]["kind"] not in ("pinboard_item", "work_item", "calendar_entry"):
        return False
    kind = src.get("kind")
    return (
        _kind(case) == "create"
        and is_tilo(_actor(case))
        and "meeting" not in case["record"]
        and (kind == "meeting" or (kind == "tilo" and src.get("from") in ("meeting", "transcript")))
    )


def _tilo_record_stamped_with_a_non_owner(case: dict) -> bool:
    d, m = case["record"]["data"], case["record"].get("meeting")
    if m is None or d.get("created_by", {}).get("by") != "tilo":
        return False
    if _is(case, "work_item"):
        return (d["assigned_by"] or {}).get("by") != m["owner"]
    return _is(case, "pinboard_item") and d["set_up_by"] != m["owner"]


def _minutes_confirmation_not_by_the_owner(case: dict) -> bool:
    m = case["record"].get("meeting")
    c = m.get("minutes_confirmed_by") if m else None
    return (
        _kind(case) == "create"
        and is_tilo(_actor(case))
        and m is not None
        and c is not None
        and (c["by"] != m["owner"] or c["at"] > case["now"])
    )


def _calendar_confirmation_dated_before_creation(case: dict) -> bool:
    d = case["record"]["data"]
    c = d.get("confirmed_by") if _is(case, "calendar_entry") else None
    return c is not None and c["at"] < d["created_by"]["at"]


def _tag_a_person_of_another_org(case: dict) -> bool:
    tagged = case["persons"].get(_data(case)["user"]) if _is(case, "mention") else None
    pin = case["record"].get("pin")
    return tagged is not None and pin is not None and tagged["org_id"] != pin["org_id"]


def _person_made_item_with_another_assigner(case: dict) -> bool:
    d = _data(case)
    return (
        _is(case, "work_item")
        and _kind(case) == "create"
        and d["created_by"]["by"] == "person"
        and d["assigned_by"] is not None
        and d["assigned_by"]["by"] != d["created_by"]["ref"]
    )


def _tilo_proposes_to_an_attendee_from_a_transcript(case: dict) -> bool:
    d, m = case["record"]["data"], case["record"].get("meeting")
    src = d.get("source") if _is(case, "calendar_entry") else None
    return (
        isinstance(src, dict)
        and _kind(case) == "create"
        and is_tilo(_actor(case))
        and src.get("from") == "transcript"
        and m is not None
        and m["owner"] != d["owner"]
    )


def _tilo_proposes_without_a_released_item(case: dict) -> bool:
    d, m = case["record"]["data"], case["record"].get("meeting")
    src = d.get("source") if _is(case, "calendar_entry") else None
    return (
        isinstance(src, dict)
        and _kind(case) == "create"
        and is_tilo(_actor(case))
        and src.get("from") == "meeting"
        and m is not None
        and m["owner"] != d["owner"]
        and m.get("minutes_confirmed_by") is not None
        and not _released_item(d, case["record"], m, case["now"])
    )


def _tilo_syncs_onto_another_persons_calendar(case: dict) -> bool:
    d, owner = case["record"]["data"], case["record"].get("source_owner")
    src = d.get("source") if _is(case, "calendar_entry") else None
    return (
        isinstance(src, dict)
        and src.get("kind") == "google"
        and owner is not None
        and owner != d["owner"]
        and is_tilo(_actor(case))
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
    "an assignee reads a proposed work item": _assignee_reads_proposed_work_item,
    "capture starts with an attestation by another person": _capture_with_foreign_attestation,
    "Tilo adds a personal pin from another person's meeting": _tilo_personal_pin_from_anothers_meeting,
    "Tilo proposes a calendar entry before the meeting Owner confirmed": _tilo_calendar_proposal_before_confirmation,
    "an assignee reads or edits a proposed work item": _assignee_changes_proposed_work_item,
    "a person assigns a work item to another person": _person_assigns_item_to_another,
    "Tilo confirms its own record": _tilo_confirms_its_own_record,
    "a non-assigner confirms a work item": _non_assigner_confirms_work_item,
    "a non-owner accepts a proposed calendar entry": _non_owner_accepts_calendar_entry,
    "a non-teammate reads busy intervals": _non_teammate_reads_busy,
    "busy intervals of an entry that is not accepted": _busy_of_an_entry_not_accepted,
    "a non-member creates a team pin": _non_member_creates_team_pin,
    "a former member edits a team pin": _former_member_edits_team_pin,
    "a calendar entry is shared with a team the owner is not in": _share_to_a_team_the_owner_is_not_in,
    "a responsible person who is not a member": _responsible_person_not_a_member,
    "a tag on a pin that is not active": _tag_on_a_pin_not_active,
    "a tag after the person removed themselves": _retag_after_self_removal,
    "an already removed mention is removed again": _untag_already_removed,
    "a confirmation that names another person": _confirmation_names_another_person,
    "a confirmation dated after the request": _confirmation_in_the_future,
    "a Tilo pin whose setter is not the meeting owner": _tilo_pin_set_up_by_not_the_meeting_owner,
    "a person-made pin set up by someone else": _person_made_pin_set_up_by_someone_else,
    "a person of another org reads": _person_of_another_org_reads,
    "a non-owner marks a work item done": _non_owner_marks_item_done,
    "an owner marks a proposed work item done": _owner_marks_proposed_item_done,
    "a teammate reads another person's full record": _teammate_reads_full_person_record,
    "a non-teammate reads the directory view": _non_teammate_reads_directory,
    "Tilo creates an accepted or shared calendar entry": _tilo_creates_accepted_or_shared_entry,
    "Tilo writes from a source another person owns": _tilo_writes_from_a_source_another_person_owns,
    "a meeting-sourced Tilo record without its meeting": _meeting_sourced_tilo_record_without_its_meeting,
    "a Tilo record stamped with someone who is not the meeting owner": _tilo_record_stamped_with_a_non_owner,
    "a minutes confirmation not made by the owner or dated later": _minutes_confirmation_not_by_the_owner,
    "a calendar confirmation dated before creation": _calendar_confirmation_dated_before_creation,
    "a tag on a person of another org": _tag_a_person_of_another_org,
    "a person-made item with another person as assigner": _person_made_item_with_another_assigner,
    "Tilo proposes to an attendee from a bare transcript": _tilo_proposes_to_an_attendee_from_a_transcript,
    "Tilo proposes to an attendee without a released action item": _tilo_proposes_without_a_released_item,
    "Tilo syncs a Google entry onto another person's calendar": _tilo_syncs_onto_another_persons_calendar,
}


def load_cases(repo_root: pathlib.Path, kind: str) -> list[tuple[pathlib.Path, dict]]:
    return [(p, load_json(p)) for p in fixture_files(repo_root, f"person/crossref/{kind}")]


# ---------------------------------------------------------------------------------------------
# World shares (ADR-0040, PE-31 to PE-35): `fixtures/world_share/crossref/{valid,invalid}/`.
# A case is the person crossref shape plus `world_owner` (the world's record owner) and `world_share`
# (the share of the item's world, or null). It has its own folder so the suites that run
# `person/crossref` (tilo_people PPL-10a, tilo-api) keep their counts until TSW-1 teaches `decide`
# the `read_team` action. `skip` switches single checks off: the mutant tests use it to show that
# each named case dies when its check is dropped.
# ---------------------------------------------------------------------------------------------
SHARE_CASE_KEYS = CASE_KEYS | {"world_owner", "world_share"}
SHARE_REQUEST_KINDS = (*REQUEST_KINDS, "read_team")  # the 14 actions plus the team view (PE-33)
SHARE_RULES = ("PE-03", "PE-31", "PE-33")
TEAM_VIEW_FIELDS = ("id", "title", "status", "due", "owner", "world_id")  # PE-33: the `read_team` view of a work item
SHARE_CHECKS = (
    "revoked",
    "granter_is_world_owner",
    "granted_not_in_future",
    "owner_in_team",
    "membership_predates_grant",
    "id_derived",
    "same_org",
    "item_in_the_share_world",
    "person_made",
    "open_or_done",
    "not_flagged",
    "actor_same_org",
    "actor_in_team",
    "item_owner_in_team",
    "creator_reads_world",
)


def share_id(world_id: str, team: str) -> str:
    """PE-31: `ws_` and the first 32 hex characters of the SHA-256 of `<world_id>/<team>`."""
    return "ws_" + hashlib.sha256(f"{world_id}/{team}".encode()).hexdigest()[:32]


def share_in_force(case: dict, skip: frozenset = frozenset()) -> bool:
    """PE-31: the share stands at `now` and still means what it said."""
    share, owner, persons, now = case["world_share"], case["world_owner"], case["persons"], case["now"]
    if share is None or owner not in persons:
        return False
    person = persons[owner]
    held = {
        "revoked": share["revoked"] is None,
        "granter_is_world_owner": share["granted_by"]["by"] == owner,
        "granted_not_in_future": share["granted_by"]["at"] <= now,
        "owner_in_team": is_member(persons, owner, share["team"], now),
        "membership_predates_grant": any(
            m["team"] == share["team"] and m["assigned_by"]["at"] <= share["granted_by"]["at"]
            for m in person["memberships"]
        ),
        "id_derived": share["id"] == share_id(share["world_id"], share["team"]),
        "same_org": share["org_id"] == person["org_id"],
    }
    return all(ok for name, ok in held.items() if name not in skip)


def world_share_permits(case: dict, skip: frozenset = frozenset()) -> bool:
    """PE-03 as amended, PE-31 and PE-33: the plain people oracle for every action but two. `read_team`
    answers only for a work item bound to the share's world; `create` of an item that names a world needs
    a creator who owns that world or belongs to a team it is shared with."""
    request, record, persons, now = case["request"], case["record"], case["persons"], case["now"]
    action, actor, data, share = request["action"], request["actor"], record["data"], case["world_share"]
    if action not in ("read_team", "create"):
        return permits({key: case[key] for key in CASE_KEYS})
    me = persons.get(actor)
    if action == "read_team":
        if record["kind"] != "work_item":  # the team view is for work items only (PE-33)
            return False
        created, owner = data["created_by"], data["owner"]
        held = {
            "item_in_the_share_world": share is not None
            and data.get("world_id") is not None
            and data["world_id"] == share["world_id"],
            "person_made": created["by"] == "person" and owner == created["ref"],
            "open_or_done": data["status"] in ("open", "done"),
            "not_flagged": data["flagged"] is False,
            "actor_same_org": me is not None and me["org_id"] == data["org_id"],
            "actor_in_team": share is not None and is_member(persons, actor, share["team"], now),
            "item_owner_in_team": share is not None and is_member(persons, owner, share["team"], now),
        }
        return all(ok for name, ok in held.items() if name not in skip) and share_in_force(case, skip)
    if not permits({key: case[key] for key in CASE_KEYS}):
        return False
    if record["kind"] != "work_item" or data.get("world_id") is None:
        return True
    owns = actor == case["world_owner"]
    reads = (
        share is not None
        and data["world_id"] == share["world_id"]
        and share_in_force(case, skip)
        and is_member(persons, actor, share["team"], now)
    )
    return owns or reads or "creator_reads_world" in skip


def share_case_shape_problems(repo_root: pathlib.Path, registry: Any, case: dict) -> list[str]:
    """Every part of a world-share crossref case is shape-valid against its schema."""
    if set(case) != SHARE_CASE_KEYS:
        return [f"keys must be {sorted(SHARE_CASE_KEYS)}, got {sorted(case)}"]
    if case["rule"] is not None and case["rule"] not in SHARE_RULES:
        return [f"rule must be null or one of {SHARE_RULES}"]
    plain = {key: case[key] for key in CASE_KEYS}
    plain["rule"] = None  # the person-case check knows the PE-01 to PE-20 rules only
    request = case["request"]
    if request.get("action") == "read_team":  # the person check, and tilo_people's 14 actions, stay as they are
        plain["request"] = {**request, "action": "read", "view": "full"}
        if request.get("view") != "team":
            return [f"a read_team request has view team, got {request.get('view')!r}"]
    found = case_shape_problems(repo_root, registry, plain)
    if case["world_share"] is not None:
        found += [f"world_share: {m}" for m in problems(repo_root, registry, "world_share", case["world_share"])]
    found += [f"world_owner: {m}" for m in problems(repo_root, registry, "common", case["world_owner"], "user_id")]
    return found


def load_share_cases(repo_root: pathlib.Path, kind: str) -> list[tuple[pathlib.Path, dict]]:
    return [(p, load_json(p)) for p in fixture_files(repo_root, f"world_share/crossref/{kind}")]
