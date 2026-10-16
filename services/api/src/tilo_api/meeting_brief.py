"""The owner's meeting brief (ADR-0047, MB-01 to MB-12, contracts/meeting_brief.rules.md).

`read_brief` serves the pinned brief (`GET`, never a model call). `brief_for_owner` makes one now (`POST`): code copies
the agenda and the carry-over from earlier confirmed minutes, one model call on role `meeting_analyst` writes only the
talk points' text, and code keeps a point only when its text is a clean line and every source it cites was offered.
The reply is untrusted data. Nothing here sends, asks, notifies or writes an outbox entry (MB-12): it stores a brief
artifact (`artifact.created`, then `artifact.versioned`) and pins it on the meeting.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request
from tilo_memory.artifacts import ArtifactError, ArtifactNotFound, ArtifactStore, NewVersion, Origin, Scope
from tilo_metering.flags import FlagStore
from tilo_people.access import _minutes_confirmed
from tilo_people.errors import NotFound, VersionConflict
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import GenerateRequest, SafetyProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.router import Router

from tilo_api import deps, spend
from tilo_api import events as event_parts
from tilo_api.assistant.metering import SpendLedger
from tilo_api.meeting_allowance import allowance_router
from tilo_api.meeting_analysis_mode import _Calls, _Router, _Safety
from tilo_api.people_meetings import _clean, _mine, set_world
from tilo_api.people_quotes import GONE, read_doc
from tilo_api.people_writes import Refusal, Writer, _unhide

SCHEMA = "meeting_brief.schema.json"
MAX_POINTS = 5  # talk points per agenda line (schema)
MAX_CARRY = 30
MAX_SOURCES = 10
_OPEN = ("done", "dropped")
_REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "talk_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "agenda": {"type": "integer"},
                    "text": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["agenda", "text", "sources"],
            },
        }
    },
    "required": ["talk_points"],
}


def _not_ready() -> Refusal:
    return Refusal(404, "not_ready")


def _try_again() -> Refusal:
    return Refusal(503, "try_again")


def _line(text: Any) -> bool:
    return isinstance(text, str) and conforms(f"{SCHEMA}#/$defs/line", text)


# --- the prior set (MB-06) and the carry-over (MB-07) ---------------------------------------------------------------


@dataclass(frozen=True)
class PriorItem:
    meeting_id: str
    item: str  # ai<n> or d<n>
    kind: str  # decision | open_action
    text: str
    work_item_id: str | None = None


def _prior_meeting(w: Writer, meeting: dict[str, Any]) -> dict[str, Any] | None:
    """The latest earlier meeting of the owner's same non-null series whose minutes the owner confirmed and that still
    has them."""
    series = meeting.get("series")
    if series is None:
        return None
    found = []
    for stored in w.stores.meetings.list(w.org, "owner", w.actor):
        r = stored.record
        until = r["delete_minutes_after"]
        if (
            r["id"] != meeting["id"]
            and r["owner"] == w.actor
            and r.get("series") == series
            and r["created_at"] < meeting["created_at"]
            and r["status"] == "minuted"
            and _minutes_confirmed(r, w.now)
            and r["minutes"] is not None
            and r.get("world_id") is not None
            and (until is None or w.now < until)
        ):
            found.append(r)
    return dict(max(found, key=lambda r: (r["created_at"], r["id"]))) if found else None


def prior_items(w: Writer, artifacts: ArtifactStore, meeting: dict[str, Any]) -> list[PriorItem]:
    """Every decision and action item of the prior minutes, read in the prior meeting's own Scope. An unreadable
    minutes document gives an empty set (the brief is made without it)."""
    prior = _prior_meeting(w, meeting)
    if prior is None:
        return []
    try:
        doc = read_doc(artifacts, Scope(prior["org_id"], prior["world_id"], prior["owner"]), prior["minutes"])
    except (ArtifactError, ValueError):
        return []
    minutes: dict[str, Any] = {} if doc is None else _clean(doc, w.redact)
    if not conforms("minutes.schema.json", minutes) or minutes["meeting_id"] != prior["id"]:
        return []
    # Hidden characters out of everything code copies or offers, as Writer.text does for a person's text (MB-11).
    out = [PriorItem(prior["id"], f"d{n}", "decision", _unhide(d["text"])) for n, d in enumerate(minutes["decisions"])]
    out += [
        PriorItem(prior["id"], a["id"], "open_action", _unhide(a["text"]), a["work_item_id"])
        for a in minutes["action_items"]
    ]
    return out


def _still_open(w: Writer, item: PriorItem) -> bool:
    if item.kind == "decision" or item.work_item_id is None:
        return True
    found = w.stores.work_items.get(w.org, item.work_item_id)
    return found is not None and found.record["status"] not in _OPEN


def carry_over(w: Writer, items: list[PriorItem]) -> list[dict[str, Any]]:
    """Copied by code, never written by a model: decisions first, then the action items still open, each in minutes
    order; an item whose text is not a clean line (a link, for example) is left out."""
    ordered = [i for i in items if i.kind == "decision"] + [i for i in items if i.kind == "open_action"]
    rows = [
        {"text": i.text, "kind": i.kind, "from_meeting": i.meeting_id, "item": i.item}
        for i in ordered
        if _line(i.text) and _still_open(w, i)
    ]
    return rows[:MAX_CARRY]


# --- the model call and its reply (MB-04, MB-05, MB-08) ------------------------------------------------------------


def _shown(items: list[PriorItem]) -> list[tuple[str, PriorItem]]:
    """The prior items offered to the model, each with its source id: only those whose text is a clean line."""
    return [(f"p{n}", i) for n, i in enumerate(items) if _line(i.text)]


def _sources(agenda: list[dict[str, Any]], items: list[PriorItem]) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {f"a{i}": {"kind": "agenda", "index": i} for i in range(len(agenda))}
    table.update({sid: {"kind": "prior", "meeting_id": i.meeting_id, "item": i.item} for sid, i in _shown(items)})
    return table


def _prompt_data(agenda: list[dict[str, Any]], items: list[PriorItem]) -> str:
    data = {
        "agenda": [{"id": f"a{i}", "title": a["title"], "minutes": a["minutes"]} for i, a in enumerate(agenda)],
        "prior": [{"id": sid, "kind": i.kind, "text": i.text} for sid, i in _shown(items)],
    }
    return "<<<DATA\n" + neutralise_marker(json.dumps(data), "DATA") + "\nDATA>>>"


def _points(
    w: Writer, reply: Any, agenda: list[dict[str, Any]], table: dict[str, dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    """Per agenda line, the model's points that survive: a clean line of text and only sources code offered. A point
    that fails is dropped, never repaired; at most five stay per line, in reply order."""
    kept: list[list[dict[str, Any]]] = [[] for _ in agenda]
    rows = reply.get("talk_points") if isinstance(reply, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        index, text, cited = row.get("agenda"), row.get("text"), row.get("sources")
        if type(index) is not int or not 0 <= index < len(agenda) or not isinstance(text, str):
            continue
        if not isinstance(cited, list) or not cited or not all(isinstance(c, str) and c in table for c in cited):
            continue
        evidence = [table[c] for c in dict.fromkeys(cited)]
        try:
            clean = w.text(text)  # hidden characters out (MB-11), then the secret redactor
        except Refusal:
            continue
        if _line(clean) and len(evidence) <= MAX_SOURCES and len(kept[index]) < MAX_POINTS:
            kept[index].append({"text": clean, "evidence": evidence})
    return kept


def _screened(safety: SafetyProvider, text: str) -> bool:
    """True when the SafetyProvider flags `text`. A spend cap is the owner's 429; any other failure is a retry."""
    try:
        verdict = safety.check(text)
    except Refusal as exc:
        if exc.status_code == 429:
            raise
        raise _try_again() from None
    except spend.SpendCapReached:
        raise Refusal(429, "allowance_capped", headers={"Cache-Control": "no-store"}) from None
    except deps.ReplayOnly:
        raise
    except Exception:
        raise _try_again() from None
    if not isinstance(verdict, dict) or not isinstance(verdict.get("flagged"), bool):
        raise _try_again()
    return verdict["flagged"]


def _ask(router: Router, data: str, budget: float) -> Any:
    system = load_prompt("meeting_analyst", "meeting_brief.md", {"max_points": MAX_POINTS, "max_chars": 240})
    try:
        result = router.generate(
            "meeting_analyst",
            GenerateRequest(system=system, prompt=data, json_mode=True, response_schema=_REPLY_SCHEMA),
            budget=budget,
        )
    except Refusal:
        raise
    except spend.SpendCapReached:
        raise Refusal(429, "allowance_capped", headers={"Cache-Control": "no-store"}) from None
    except deps.ReplayOnly:
        raise
    except Exception:
        raise _try_again() from None
    if getattr(result, "outcome", "ok") != "ok" or result.response is None:
        raise _try_again()
    return result


def build_brief(
    w: Writer, router: Router, safety: SafetyProvider, meeting: dict[str, Any], items: list[PriorItem], budget: float
) -> dict[str, Any]:
    """The brief document of `meeting`. Nothing is stored. The agenda is copied by code; with no agenda, or after a
    flag on the input, no model is called."""
    agenda = meeting["agenda"]
    table = _sources(agenda, items)
    kept: list[list[dict[str, Any]]] = [[] for _ in agenda]
    flagged = False
    if agenda:
        data = _prompt_data(agenda, items)
        flagged = _screened(safety, data)
        if not flagged:
            result = _ask(router, data, budget)
            text = result.response.text or ""
            try:
                reply = json.loads(text)
            except (ValueError, RecursionError):
                raise _try_again() from None
            flagged = _screened(safety, text)
            if not flagged:
                kept = _points(w, reply, agenda, table)
    doc = {
        "v": "1.0",
        "meeting_id": meeting["id"],
        "generated_at": w.now,
        "flagged": flagged,
        "agenda_points": [
            {"title": a["title"], "minutes": a["minutes"], "talk_points": kept[n]} for n, a in enumerate(agenda)
        ],
        "carry_over": carry_over(w, items),
    }
    if not conforms(SCHEMA, doc):
        raise _try_again()
    return doc


# --- storing and pinning (MB-03, MB-12) ------------------------------------------------------------------------------


def _delete_version(artifacts: ArtifactStore, scope: Scope, ref: dict[str, Any]) -> None:
    prefix = f"orgs/{scope.org_id}/worlds/{scope.world_id}/artifacts/{ref['artifact_id']}/versions"
    artifacts.retention().delete(f"{prefix}/{ref['version']:06d}")


def _announce(events: deps.EventWriter, world_id: str, w: Writer, kind: str, data: dict[str, Any]) -> None:
    part: dict[str, Any] = {
        "id": event_parts.new_part_id(),
        "type": kind,
        "actor": w.actor,
        "target": w.actor,
        "severity": "info",
        "summary": "A meeting brief is ready.",
        "vis": [],
        "authz": None,
        "data": data,
    }
    for attempt in range(3):  # the same part id on every retry: the single writer deduplicates it
        try:
            events.append(world_id, part)
            return
        except Exception:
            if attempt == 2:
                raise _try_again() from None


def store_brief(
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    worlds: deps.MeetingWorlds,
    events: deps.EventWriter,
    meeting: dict[str, Any],
    doc: dict[str, Any],
) -> dict[str, Any]:
    """A new version of the meeting's brief artifact in its world, announced, then pinned by a compare-and-set. A
    version that was not pinned is deleted, except a newer version of a pinned artifact that was already announced."""
    current, version, _ = _mine(w, meeting["id"], "read_full", GONE)
    if current["agenda"] != meeting["agenda"]:
        raise Refusal(409, "version_conflict")
    if current.get("world_id") is None:
        current = set_world(w, worlds, meeting["id"])
        version = _mine(w, meeting["id"], "read_full", GONE)[1]
    world_id = current["world_id"]
    world = store.load_world(world_id, settle=False)
    if world is None or world.owner != w.actor:
        raise Refusal(404, "not_found")
    scope = Scope(w.org, world_id, w.actor)
    parent = None
    if current.get("brief") is not None:
        try:
            parent = artifacts.versions(scope, current["brief"]["artifact_id"])[-1].ref
        except ArtifactNotFound:
            parent = None
    made = None
    try:
        for _ in range(2):
            new = NewVersion(
                "application/json",
                json.dumps(doc).encode(),
                world.run_id,
                Origin(kind="upload"),
                parent=parent,
                screening_hint="flagged" if doc["flagged"] else None,
            )
            made = artifacts.put(scope, new)
            if doc["flagged"] or made.doc["screening"] == "clean":
                break
            # The store's own screen flagged the stored bytes: keep only the code-copied parts, flagged (MB-08).
            _delete_version(artifacts, scope, made.ref)
            doc = {**doc, "flagged": True, "agenda_points": [{**p, "talk_points": []} for p in doc["agenda_points"]]}
        else:
            raise _try_again()
    except (ArtifactError, ValueError):
        raise _try_again() from None
    announced = False
    try:
        try:
            stored = json.loads(artifacts.read(scope, made.ref))
        except (ArtifactError, ValueError, RecursionError):
            raise _try_again() from None
        if parent is None:
            data = {"artifact": made.ref} | {k: made.doc[k] for k in ("content_sha256", "media_type", "size_bytes")}
            kind = "artifact.created"
        else:
            data, kind = {"artifact": made.ref, "previous_version": parent["version"]}, "artifact.versioned"
        _announce(events, world_id, w, kind, data)
        announced = True
        after = {**current, "brief": made.ref}
        if not conforms("meeting.schema.json", after):
            raise Refusal(422, "invalid_record")
        try:
            w.stores.meetings.replace(after, expected_version=version)
        except VersionConflict:
            raise Refusal(409, "version_conflict", code="version_conflict") from None
        except NotFound:
            raise Refusal(404, "not_found") from None
    except BaseException:
        # A version nobody pinned goes at once, so a lost pin leaves no brief behind (MB-09). One announced as a new
        # version of a pinned artifact stays: the chain EV-15 checks needs it, and a delete purges it by content.
        if parent is None or not announced:
            _delete_version(artifacts, scope, made.ref)
        raise
    return cast(dict[str, Any], stored)


def brief_for_owner(
    request: Request,
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    worlds: deps.MeetingWorlds,
    meeting_id: str,
    *,
    principal: deps.Principal,
    switches: FlagStore,
    budget: float,
    events: deps.EventWriter,
    allowance: SpendLedger,
    allowance_cap: float,
    clock: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """`POST /v1/meetings/{id}/brief`. The owner check comes first and is the only 404; a demo session may not make
    one (403). Metered on the owner's existing per-user allowance, like minutes. A model error stores nothing."""
    meeting, _, _ = _mine(w, meeting_id, "read_full", GONE)
    if w.actor != principal.user_id or getattr(request.state, "uid", None) != w.actor or w.org != deps.ORG_ID:
        raise Refusal(404, "not_found")
    if principal.demo_session or getattr(request.state, "demo_session", False) is True:
        raise Refusal(403, "demo_read_only")
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
        raise Refusal(429, "allowance_capped", headers={"Cache-Control": "no-store"})
    items = prior_items(w, artifacts, meeting)
    if not meeting["agenda"]:  # nothing for a model to write: copied parts only, nothing metered
        doc = build_brief(w, cast(Router, None), cast(SafetyProvider, None), meeting, items, budget)
    else:
        mode = deps.get_work_mode(request, switches)
        router, safety = deps.router_for_mode(mode), deps.get_safety(mode)
        held = store.load_world(meeting["world_id"], settle=False) if meeting.get("world_id") else None
        calls = _Calls(request, w, switches, mode, held.run_id if held is not None else f"r_brief_{meeting_id}")
        with allowance_router(
            _Router(router, calls),
            ledger=allowance,
            user=w.actor,
            clock=clock or (lambda: w.now),
            cap=allowance_cap,
            budget=budget,
        ) as metered:
            doc = build_brief(
                w, cast(Router, metered), cast(SafetyProvider, _Safety(safety, calls)), meeting, items, budget
            )
    return store_brief(w, store, artifacts, worlds, events, meeting, doc)


# --- reading (MB-02, MB-09) ------------------------------------------------------------------------------------------


def _cited(doc: dict[str, Any]) -> set[str]:
    cited = {c["from_meeting"] for c in doc["carry_over"]}
    for point in doc["agenda_points"]:
        for talk in point["talk_points"]:
            cited |= {e["meeting_id"] for e in talk["evidence"] if e["kind"] == "prior"}
    return cited


def read_brief(w: Writer, artifacts: ArtifactStore, redact: Callable[[str], str], meeting_id: str) -> dict[str, Any]:
    """The pinned brief of the owner's meeting, read through the artifact store in the meeting's own Scope. Anything
    short of a valid brief whose cited minutes still exist is 404 `not_ready`; this reads and never writes."""
    m = _mine(w, meeting_id, "read_full", ("deleted",))[0]
    ref, world = m.get("brief"), m.get("world_id")
    if m["status"] == "discarded" or ref is None or world is None:
        raise _not_ready()
    try:
        doc = read_doc(artifacts, Scope(m["org_id"], world, m["owner"]), ref)
    except (ArtifactError, ValueError):
        raise _not_ready() from None
    if doc is None:
        raise _not_ready()
    cleaned = _clean(doc, redact)
    if not conforms(SCHEMA, cleaned) or cleaned["meeting_id"] != m["id"]:
        raise _not_ready()
    for other_id in _cited(cleaned):
        other = w.stores.meetings.get(w.org, other_id)
        record = other.record if other is not None else None
        until = None if record is None else record["delete_minutes_after"]
        if (
            record is None
            or record["owner"] != w.actor
            or record["status"] in GONE
            or record["minutes"] is None
            or (until is not None and w.now >= until)
        ):
            raise _not_ready()
    return cast(dict[str, Any], cleaned)
