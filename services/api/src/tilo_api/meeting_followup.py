"""Internal FR-MTG-08 owner adapter: retained confirmed minutes to draft approval cards, never send."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from datetime import datetime
from types import SimpleNamespace
from typing import Any, cast

from fastapi import Request
from tilo_channels.autopilot import Autopilot, Preview
from tilo_channels.drafting import DraftStore
from tilo_channels.meeting_followup import MeetingFollowUp
from tilo_contracts import Minutes
from tilo_memory.artifacts import ArtifactError, ArtifactStore, Scope
from tilo_metering.flags import FlagStore
from tilo_people.access import AccessRequest, read
from tilo_policy.schemas import conforms
from tilo_providers.interfaces import SafetyProvider

from tilo_api import deps
from tilo_api import events as parts
from tilo_api.meeting_analysis_mode import _Calls, _Safety
from tilo_api.people_limits import limits_of
from tilo_api.people_meetings import _mine
from tilo_api.people_quotes import GONE, read_doc
from tilo_api.people_writes import Refusal, Writer


class _Guarded:
    def __init__(self, port: Any, check: Callable[[], None]) -> None:
        self.port, self.check = port, check

    def __getattr__(self, name: str) -> Any:
        def invoke(*args: Any, **kwargs: Any) -> Any:
            self.check()
            return getattr(self.port, name)(*args, **kwargs)

        return invoke


def draft_owner_followup(
    request: Request,
    w: Writer,
    store: deps.Store,
    artifacts: ArtifactStore,
    meeting_id: str,
    *,
    principal: deps.Principal,
    switches: FlagStore,
    budget: float,
    events: deps.EventWriter,
    drafts: DraftStore,
    autopilot_factory: Callable[[str, str, str, Callable[[dict], None]], Autopilot],
    recipients: Sequence[str] | None = None,
) -> Preview | None | list[Preview]:
    """Server-only wiring: None picks means nudges; person-id picks mean one minutes email.
    Factory supplies scoped cards/outbox; scope check rejects another world/run or bench evidence.
    Source rechecks guard each call, not a transaction across stores. Confirmation has no pin field:
    the current minutes pointer and meeting version are authoritative. No route/job invokes this seam.
    """
    meeting, version, _ = _mine(w, meeting_id, "read_full", GONE)
    world_id = meeting.get("world_id")
    world = store.load_world(world_id, settle=False) if world_id else None
    if (
        principal.user_id != w.actor
        or getattr(request.state, "uid", None) != w.actor
        or w.org != deps.ORG_ID
        or world is None
        or world.owner != w.actor
        or (principal.world_id is not None and principal.world_id != world_id)
    ):
        raise Refusal(404, "not_found")
    world_id = cast(str, world_id)
    now = datetime.fromisoformat(w.now.replace("Z", "+00:00")).timestamp()
    limits_of(w.stores).attempt(w.actor, now)
    if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
        raise Refusal(409, "followup_unavailable")
    if recipients is not None and (
        not isinstance(recipients, (list, tuple))
        or not 1 <= len(recipients) <= 50
        or any(not isinstance(p, str) for p in recipients)
    ):
        raise Refusal(422, "invalid_recipients")
    picks = sorted(set(recipients or []))
    scope = Scope(w.org, world_id, w.actor)

    def snapshot() -> tuple[dict, dict, dict, dict, list]:
        m, v, _ = _mine(w, meeting_id, "read_full", GONE)
        current = store.load_world(world_id, settle=False)
        stamp, ref, until = m.get("minutes_confirmed_by"), m.get("minutes"), m.get("delete_minutes_after")
        if (
            v != version
            or m.get("world_id") != world_id
            or current is None
            or current.owner != w.actor
            or current.run_id != world.run_id
            or m["status"] != "minuted"
            or not stamp
            or stamp["by"] != w.actor
            or stamp["at"] > w.now
            or ref is None
            or (until is not None and w.now >= until)
        ):
            raise Refusal(409, "followup_unavailable")
        try:
            head = artifacts.head(scope, ref)
            doc = read_doc(artifacts, scope, ref)
            if head is None or head.doc["screening"] != "clean" or doc is None or doc.get("meeting_id") != meeting_id:
                raise ValueError
            Minutes.model_validate(doc)
            if not conforms("minutes.schema.json", doc):
                raise ValueError
        except (ArtifactError, ValueError):
            raise Refusal(409, "minutes_unavailable") from None
        directory, items, addresses = w.org_directory(), {}, {}
        item_versions, people_versions = [], []
        audience = set(picks) | {w.actor}
        if not set(picks) <= {a["user"] for a in m["attendees"]}:
            raise Refusal(422, "invalid_recipients")
        for action in doc["action_items"]:
            key = action.get("work_item_id")
            if not key:
                continue
            stored = w.stores.work_items.get(w.org, key)
            item_versions.append([key, stored.version if stored else None])
            if stored is None:
                continue
            record = stored.record
            status = read(AccessRequest(w.actor, "read_status", "work_item", record, w.now, meeting=m), directory)
            confirmed = record.get("confirmed_by")
            if (
                status is None
                or not confirmed
                or confirmed["at"] > w.now
                or not MeetingFollowUp._is_open(w.actor, meeting_id, action, record)
            ):
                continue
            # Only eligibility metadata is copied; prompts get the confirmed minutes entry, never item text.
            items[key] = {k: record[k] for k in ("id", "owner", "status", "confirmed_by", "source", "flagged")}
            audience.add(record["owner"])
        for person_id in sorted(audience):
            person = w.stores.persons.get(w.org, person_id)
            if (
                person is None
                or read(AccessRequest(w.actor, "read_directory", "person", person.record, w.now), directory) is None
            ):
                raise Refusal(404, "not_found")
            addresses[person_id] = person.record["email"]
            people_versions.append([person_id, person.version, person.record["email"]])
        identity = [w.org, w.actor, world_id, world.run_id, meeting_id, v, ref, stamp]
        identity += [item_versions, people_versions, picks]
        return m, doc, items, addresses, identity

    original = snapshot()

    def check() -> None:
        if snapshot() != original:
            raise Refusal(409, "version_conflict")

    identity = hashlib.sha256(json.dumps(original[4], sort_keys=True).encode()).hexdigest()

    def emit(part: dict) -> None:
        check()
        if part["type"] not in ("artifact.created", "approval.requested"):
            raise Refusal(409, "unexpected_followup_event")
        event = {
            **part,
            "id": parts.stable_part_id(identity, part["type"], json.dumps(part["data"], sort_keys=True)),
            "actor": w.actor,
            "target": w.actor,
            "severity": "needs_you",
            "summary": "Meeting follow-up draft.",
            "vis": [],
            "authz": None,
        }
        events.append(world_id, event)

    ap = autopilot_factory(world_id, world.run_id, w.actor, emit)
    if not ap.matches_scope(world_id=world_id, run_id=world.run_id, owner=w.actor):
        raise Refusal(404, "not_found")
    check()
    mode = deps.get_work_mode(request, switches)
    if principal.demo_session or getattr(request.state, "demo_session", False) is True:
        mode = "replay"
    router, safety = deps.router_for_mode(mode), deps.get_safety(mode)
    calls = _Calls(request, w, switches, mode, world.run_id)
    left = budget

    def generate(prompt: Any) -> Any:
        nonlocal left
        check()
        if left <= 0:
            raise Refusal(409, "followup_budget_exhausted")
        result = calls.invoke(lambda: router.generate("autopilot", prompt, budget=left))
        if type(result.budget) not in (int, float) or not math.isfinite(result.budget):
            raise Refusal(502, "followup_failed")
        left = max(0.0, min(left, result.budget))
        check()
        return result.response if result.outcome == "ok" else None

    m, doc, items, addresses, _ = original
    followup = MeetingFollowUp(
        meetings=SimpleNamespace(get=lambda uid, key: m if uid == w.actor and key == meeting_id else None),
        minutes=SimpleNamespace(
            get=lambda uid, key, v: (
                doc if uid == w.actor and {"artifact_id": key, "version": v} == m["minutes"] else None
            )
        ),
        work_items=SimpleNamespace(get=lambda uid, key: items.get(key) if uid == w.actor else None),
        directory=SimpleNamespace(address=addresses.get),
        model=SimpleNamespace(generate=generate),
        safety=cast(SafetyProvider, _Safety(safety, calls)),
        drafts=cast(DraftStore, _Guarded(drafts, check)),
        autopilot=cast(Autopilot, _Guarded(ap, check)),
        mailbox=lambda uid: addresses.get(uid),
        clock=lambda: now,
        emit=emit,
    )
    result = (
        followup.draft_minutes_email(w.actor, meeting_id, recipients=picks, request_id=identity)
        if recipients is not None else followup.draft_nudges(w.actor, meeting_id, request_id=identity)
    )  # fmt: skip
    check()
    cards = result if isinstance(result, list) else [result] if result is not None else []
    for card in cards:
        if (gate := ap.approval_requested(w.actor, card.card_id)) is not None:
            emit(gate)  # repairs partial publication; registered writer dedupes the stable id
    return result
