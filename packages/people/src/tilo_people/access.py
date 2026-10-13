"""The people visibility oracle (PPL-10a; people.rules.md PE-01 to PE-08, PE-11, PE-17 to PE-20).

`decide` ports `permits()` of `tests/contracts/_people_lib.py` (the reference oracle of the crossref suite)
with exactly the stricter clauses S1 to S5 and the grants G1 (an org owner creates a person) and G2 (a person
creates the meeting they own and attest); see packages/people/tests/API.md. Deterministic code only: no
model, store, clock or randomness. It fails closed: anything unknown, malformed or missing is a refusal,
never an exception, and no refusal says why (callers answer 404).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ._schema import is_agent_id, is_timestamp, is_user_id, valid
from .directory import Directory
from .world_share import in_force

ACTIONS = (
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
RECORD_KINDS = ("pinboard_item", "work_item", "calendar_entry", "meeting", "mention", "person")
READS = ("read_full", "read_status")
TEAM_ACTIONS = (*ACTIONS, "read_team")  # ADR-0040: the 14 stay as they are; "read_team" is the work item's team view
TEAM_VIEW = ("id", "title", "status", "due", "owner", "world_id")  # PE-33: six keys, nothing private
VIEW_FIELDS = {
    "status": ("id", "title", "status", "due"),
    "busy": ("start", "end"),
    "directory": ("id", "display_name"),
    "membership": ("id", "display_name", "org_role", "memberships"),
}


@dataclass(frozen=True, repr=False)
class AccessRequest:
    actor: str  # "u_..." the signed-in person (from the session), or "A_..." Tilo
    action: str  # one of ACTIONS
    record_kind: str  # one of RECORD_KINDS
    record: Mapping[str, Any]  # the stored record (a create: the record to be stored)
    now: str  # the server clock, read once per API request by the caller
    meeting: Mapping[str, Any] | None = None  # source meeting (or its tombstone) of a Tilo-made record or pin
    work_item: Mapping[str, Any] | None = None  # the released item a Tilo calendar proposal cites (PE-08)
    source_owner: str | None = None  # owner of a mail, request, call or Google source (PE-08)
    pin: Mapping[str, Any] | None = None  # record_kind "mention": the pin it tags
    mentions: tuple[Mapping[str, Any], ...] = ()  # action "mention": the pin's existing mentions
    world_share: Mapping[str, Any] | None = (
        None  # the share of the item's world (PE-31): read_team, create with world_id
    )
    world_owner: str | None = None  # the item's world's record owner, from the store, never from the request

    def __repr__(self) -> str:  # fixed words only: a record, an actor or a field may hold text
        action = self.action if self.action in TEAM_ACTIONS else "?"
        kind = self.record_kind if self.record_kind in RECORD_KINDS else "?"
        return f"AccessRequest(action={action!r}, record_kind={kind!r})"


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    view: str | None  # reads: "full" | "status" | "busy" | "directory" | "membership" | "team"; else None


_REFUSED = Verdict(False, None)


def decide(request: AccessRequest, directory: Directory) -> Verdict:
    """Never raises. A refusal is `Verdict(False, None)`; an allowed read carries the action's suffix as its
    view (`read_busy` -> "busy"), an allowed write has none."""
    try:
        if _allowed(request, directory) is not True:
            return _REFUSED
        action = request.action
        return Verdict(True, action[5:] if action.startswith("read_") else None)
    except Exception:
        return _REFUSED


# ---------------------------------------------------------------------------------------------
# Steps 0 and 1: the input gate and the stricter clauses
# ---------------------------------------------------------------------------------------------
def _gate(r: AccessRequest) -> bool:
    return bool(
        (is_user_id(r.actor) or is_agent_id(r.actor))
        and isinstance(r.action, str)
        and r.action in TEAM_ACTIONS
        and isinstance(r.record_kind, str)
        and r.record_kind in RECORD_KINDS
        and is_timestamp(r.now)
        and valid(f"{r.record_kind}.schema.json", r.record)
        and (r.meeting is None or valid("meeting.schema.json", r.meeting))
        and (r.work_item is None or valid("work_item.schema.json", r.work_item))
        and (r.pin is None or valid("pinboard_item.schema.json", r.pin))
        and isinstance(r.mentions, tuple | list)
        and all(valid("mention.schema.json", m) for m in r.mentions)
        and (r.source_owner is None or is_user_id(r.source_owner))
        and (r.world_share is None or valid("world_share.schema.json", r.world_share))
        and (r.world_owner is None or is_user_id(r.world_owner))
    )


def _history_ok(rec: Mapping[str, Any]) -> bool:  # S3
    confirmer = (rec["confirmed_by"] or {}).get("by")
    return all(h["by"] == confirmer for h in rec["history"] if h["change"] in ("confirmed", "accepted"))


def _link_ok(rec: Mapping[str, Any]) -> bool:  # S4
    return (rec["kind"] == "link") == (rec["url"] is not None)


def _stricter(r: AccessRequest) -> bool:
    rec, kind, meeting = r.record, r.record_kind, r.meeting
    if meeting is not None:  # S1
        c = meeting["minutes_confirmed_by"]
        if c is not None and not (c["by"] == meeting["owner"] and c["at"] <= r.now):
            return False
    if kind == "work_item" and rec["created_by"]["by"] == "person":  # S2
        assigner = rec["assigned_by"]
        if assigner is not None and assigner["by"] != rec["created_by"]["ref"]:
            return False
    history_records = [x for x in (r.pin, r.work_item) if x is not None]
    pins = [x for x in (r.pin,) if x is not None]
    if kind in ("work_item", "pinboard_item"):
        history_records.append(rec)
    if kind == "pinboard_item":
        pins.append(rec)
    if not all(_history_ok(x) for x in history_records) or not all(_link_ok(x) for x in pins):
        return False
    return kind != "calendar_entry" or rec["end"] is None or rec["end"] >= rec["start"]  # S5


# ---------------------------------------------------------------------------------------------
# Helpers of the reference oracle
# ---------------------------------------------------------------------------------------------
def _confirmed(rec: Mapping[str, Any], who: str | None, now: str) -> bool:
    c = rec["confirmed_by"]
    return c is not None and who is not None and c["by"] == who and rec["created_by"]["at"] <= c["at"] <= now


def _meeting_matches(ref: str | None, org_id: str, meeting: Mapping[str, Any] | None) -> bool:
    return (
        meeting is not None and ref is not None and ref.split("#")[0] == meeting["id"] and meeting["org_id"] == org_id
    )


def _minutes_confirmed(meeting: Mapping[str, Any], now: str) -> bool:
    c = meeting["minutes_confirmed_by"]
    return meeting["status"] == "minuted" and c is not None and c["by"] == meeting["owner"] and c["at"] <= now


def _released_item(entry: Mapping[str, Any], r: AccessRequest, meeting: Mapping[str, Any]) -> bool:
    ref, item = entry["source"]["ref"], r.work_item
    return (
        ref is not None
        and "#" in ref
        and item is not None
        and item["owner"] == entry["owner"]
        and item["source"]["ref"] == ref
        and item["status"] in ("open", "done")
        and item["created_by"]["by"] == "tilo"
        and (item["assigned_by"] or {}).get("by") == meeting["owner"]
        and _confirmed(item, meeting["owner"], r.now)
        and _minutes_confirmed(meeting, r.now)
    )


def _tilo_made_ok(kind: str, rec: Mapping[str, Any], r: AccessRequest) -> bool:
    """PE-08, PE-19: a Tilo-made record's source and stamps hold, checked on every request about it. A meeting
    source needs its meeting in the request, another source needs its owner (fail closed)."""
    meeting, source_owner = r.meeting, r.source_owner
    if rec["created_by"]["by"] != "tilo":
        return True
    source = rec["source"]
    if kind == "pinboard_item":
        if source is None or source["kind"] == "manual":
            return False
        if rec["scope"]["kind"] == "personal" and rec["set_up_by"] != rec["scope"]["user"]:
            return False
        if source["kind"] == "meeting":
            return (
                meeting is not None
                and _meeting_matches(source["ref"], rec["org_id"], meeting)
                and rec["set_up_by"] == meeting["owner"]
            )
        return source_owner == rec["set_up_by"]
    if kind == "work_item":
        return (
            source["kind"] == "meeting"
            and meeting is not None
            and _meeting_matches(source["ref"], rec["org_id"], meeting)
            and (rec["assigned_by"] or {}).get("by") == meeting["owner"]
        )
    if kind == "calendar_entry":
        if source["kind"] == "manual":
            return False
        if source["kind"] == "google":
            return source_owner == rec["owner"]
        if source["from"] in ("meeting", "transcript"):
            if meeting is None or not _meeting_matches(source["ref"], rec["org_id"], meeting):
                return False
            if meeting["owner"] == rec["owner"]:
                return True
            return source["from"] == "meeting" and _released_item(rec, r, meeting)
        return source_owner == rec["owner"]
    return True


# ---------------------------------------------------------------------------------------------
# Steps 2 to 4: mentions, the actor gate, one function per record kind
# ---------------------------------------------------------------------------------------------
def _allowed(r: AccessRequest, d: Directory) -> bool:
    if not isinstance(r, AccessRequest) or not isinstance(d, Directory) or not _gate(r) or not _stricter(r):
        return False
    tilo = is_agent_id(r.actor)
    if r.action == "read_team" and (r.record_kind != "work_item" or tilo):
        return False
    if r.record_kind == "mention":
        return _mention(r, d, tilo)
    if tilo:
        if r.action != "create":
            return False
    else:
        me = d.record(r.actor)
        if me is None or me["org_id"] != r.record["org_id"]:
            return False
    handler = {
        "pinboard_item": _pin,
        "work_item": _work_item,
        "calendar_entry": _calendar,
        "meeting": _meeting,
        "person": _person,
    }[r.record_kind]
    return handler(r, d, tilo)


def _mention(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, pin, now, actor = r.record, r.pin, r.now, r.actor
    if pin is None or pin["scope"]["kind"] != "team":
        return False
    if rec["pin_id"] != pin["id"] or rec["team"] != pin["scope"]["team"] or rec["org_id"] != pin["org_id"]:
        return False
    if pin["created_by"]["by"] == "tilo" and not _tilo_made_ok("pinboard_item", pin, r):
        return False
    person = None if tilo else d.record(actor)
    if r.action == "mention":
        if pin["status"] != "active" or rec["removed"] is not None:
            return False
        tagged = d.record(rec["user"])
        if tagged is None or tagged["org_id"] != pin["org_id"] or not d.is_member(rec["user"], rec["team"], now):
            return False
        if any(o["user"] == rec["user"] and o["removed"] and o["removed"]["by"] == rec["user"] for o in r.mentions):
            return False
        if person is not None:
            return (
                actor == pin["set_up_by"] and person["org_id"] == pin["org_id"] and d.is_member(actor, rec["team"], now)
            )
        return tilo and _confirmed(pin, pin["set_up_by"], now)
    if r.action == "untag":
        if rec["removed"] is not None:
            return False
        return person is not None and person["org_id"] == pin["org_id"] and actor in (rec["user"], pin["set_up_by"])
    return False  # nobody reads or changes a mention record directly (BQ-PPL10-12)


def _pin(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, now, actor, action = r.record, r.now, r.actor, r.action
    scope, created = rec["scope"], rec["created_by"]
    tilo_made = created["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("pinboard_item", rec, r):
        return False
    if not tilo_made and rec["set_up_by"] != created["ref"]:
        return False
    if scope["kind"] == "personal":
        if action == "create":
            return tilo if tilo_made else actor == scope["user"]
        return actor == scope["user"] and action in (*READS, "edit")
    team = scope["team"]
    member = d.is_member(actor, team, now)
    owner_ok = rec["owner"] is None or d.is_member(rec["owner"], team, now)
    if action == "create":
        if tilo_made:
            return tilo and rec["status"] == "proposed" and owner_ok
        return actor == rec["set_up_by"] and member and owner_ok
    if tilo:
        return False
    if rec["status"] == "active":
        if action in READS:
            return member and (not tilo_made or _confirmed(rec, rec["set_up_by"], now))
        return action == "edit" and actor == rec["set_up_by"] and member
    if action in (*READS, "edit"):
        return actor == rec["set_up_by"] and member
    return action == "confirm" and rec["status"] == "proposed" and actor == rec["set_up_by"] and member


def _work_item(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, now, actor, action = r.record, r.now, r.actor, r.action
    owner, status, created = rec["owner"], rec["status"], rec["created_by"]
    assigner = (rec["assigned_by"] or {}).get("by")
    tilo_made = created["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("work_item", rec, r):
        return False
    if action == "create":
        if not tilo_made:
            made = actor == owner == created["ref"] and status == "open" and assigner in (None, created["ref"])
            return made and _world_readable(r, d)
        return tilo and status == "proposed" and assigner is not None and "world_id" not in rec
    if tilo:
        return False
    if action == "read_team":
        return _team_view(r, d)
    if status == "proposed":
        return action == "confirm" and assigner is not None and actor == assigner
    if tilo_made and not _confirmed(rec, assigner, now):
        return False
    if action in ("read_full", "edit"):
        return actor == owner
    if action == "mark_done":
        return actor == owner and status == "open"
    if action == "read_status":
        return actor == owner or (assigner is not None and actor == assigner)
    return False


def _share_for(r: AccessRequest, d: Directory) -> Mapping[str, Any] | None:
    """The request's share when it is in force for the item's world and of the item's org (PE-31); else None. The
    org test is stricter than the reference oracle: a team id of another org is never the item's team."""
    share, wid = r.world_share, r.record.get("world_id")
    if share is None or wid is None or share["world_id"] != wid or share["org_id"] != r.record["org_id"]:
        return None
    return share if in_force(share, r.world_owner, d, r.now) else None


def _world_readable(r: AccessRequest, d: Directory) -> bool:
    """PE-33: an item that names a world is created by someone who owns that world or is a member of a team it is
    shared with (a share in force); an item with no world needs nothing."""
    if r.record.get("world_id") is None:
        return True
    if r.world_owner is not None and r.actor == r.world_owner:
        return True
    share = _share_for(r, d)
    return share is not None and d.is_member(r.actor, share["team"], r.now)


def _team_view(r: AccessRequest, d: Directory) -> bool:
    """PE-33: the team view of a person-made, open or done, unflagged item of a shared world, for a member of the
    share's team when the item's owner is one too."""
    rec = r.record
    share = _share_for(r, d)
    if share is None or rec["created_by"]["by"] != "person" or rec["owner"] != rec["created_by"]["ref"]:
        return False
    if rec["status"] not in ("open", "done") or rec["flagged"] is not False:
        return False
    return d.is_member(r.actor, share["team"], r.now) and d.is_member(rec["owner"], share["team"], r.now)


def _calendar(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, now, actor, action = r.record, r.now, r.actor, r.action
    owner, share, created = rec["owner"], rec["share"], rec["created_by"]
    tilo_made = created["by"] == "tilo"
    if tilo_made and not _tilo_made_ok("calendar_entry", rec, r):
        return False
    if action == "create":
        if not tilo_made:
            return actor == owner
        return tilo and rec["confirmed_by"] is None and share is None
    if tilo:
        return False
    needs_confirmation = rec["source"]["kind"] == "tilo" or (tilo_made and rec["source"]["kind"] == "manual")
    if rec["state"] == "accepted" and needs_confirmation and not _confirmed(rec, owner, now):
        return False
    if action == "confirm":
        return actor == owner and rec["state"] == "proposed"
    owner_in_team = share is not None and d.is_member(owner, share["team"], now)
    if action == "edit":
        return actor == owner and (share is None or owner_in_team)
    if action in READS:
        shared = share is not None and rec["state"] == "accepted" and owner_in_team
        return actor == owner or (shared and d.is_member(actor, share["team"], now))
    if action == "read_busy":
        return actor == owner or (rec["state"] == "accepted" and d.teammates(actor, owner, now))
    return False


def _meeting(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, actor, action = r.record, r.actor, r.action
    owner, attester = rec["owner"], rec["attestation"]["by"]
    if action == "start_capture":
        return actor == owner and attester == owner and d.record(attester) is not None
    if action == "create":  # G2 (BQ-PPL10-3): the person who owns and attests the meeting adds it
        return not tilo and actor == owner and attester == actor
    return action in (*READS, "edit", "confirm") and actor == owner


def _person(r: AccessRequest, d: Directory, tilo: bool) -> bool:
    rec, actor, action = r.record, r.actor, r.action
    me = d.record(actor)
    if me is None:
        return False
    org_owner = me["org_id"] == rec["org_id"] and me["org_role"] == "owner"
    if action in ("assign_membership", "set_org_role", "create"):  # create is G1 (PE-17, BQ-PPL10-3)
        return org_owner
    if action == "read_full":
        return actor == rec["id"]
    if action == "read_membership":
        return actor == rec["id"] or org_owner
    if action == "read_directory":
        return actor == rec["id"] or org_owner or d.teammates(actor, rec["id"], r.now)
    return False


# ---------------------------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------------------------
def project(record_kind: str, view: str, record: Mapping[str, Any]) -> dict[str, Any] | None:
    """View "full": a deep copy of the record. "team" (work items only, ADR-0040): the TEAM_VIEW keys. "status": the
    VIEW_FIELDS keys the record has. "busy" (calendar
    entries only): {"start", "end"}, or None when `end` is None (BQ-PPL10-9). "directory" and "membership"
    (persons only): those keys. Values are deep copies; no other key is ever copied. Unknown kind or view:
    None."""
    if not isinstance(record, Mapping) or not isinstance(record_kind, str) or not isinstance(view, str):
        return None
    if view == "team":  # ADR-0040: work items only; exactly the PE-33 keys the record has
        if record_kind != "work_item":
            return None
        return copy.deepcopy({k: record[k] for k in TEAM_VIEW if k in record})
    if record_kind not in RECORD_KINDS or (view != "full" and view not in VIEW_FIELDS):
        return None
    if view == "busy" and (record_kind != "calendar_entry" or record.get("end") is None):
        return None
    if view in ("directory", "membership") and record_kind != "person":
        return None
    keys = tuple(record) if view == "full" else tuple(k for k in VIEW_FIELDS[view] if k in record)
    return copy.deepcopy({k: record[k] for k in keys})


def read(request: AccessRequest, directory: Directory) -> dict[str, Any] | None:
    """`project(...)` of `request.record` when `decide` allows a read_* action, else None."""
    verdict = decide(request, directory)
    if not verdict.allowed or verdict.view is None:
        return None
    try:
        return project(request.record_kind, verdict.view, request.record)
    except Exception:
        return None
