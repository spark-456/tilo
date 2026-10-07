"""A bot-hosted meeting, the tilo-api half (FR-MTG-09, ADR-0024; services/api/tests/API_MTG09_b.md, BQ-MTG09-20 to -24).
`host_meeting` is the owner's own request: it reads the stored meeting and the owner's and attendees' person records
(never a request body), asks the connector for the draft (MH-01 to MH-06), and starts one fixed run: a single unit that
stores the draft, a single T3 gate card, then the outbox sends exactly the approved invitation. No Director, no model.
`HostRun` is the generic `Run` with four differences: its plan is fixed, no question comes before the gate, the gate
card says the draft's own sentence to the draft's own recipients, and after the send it records the receipt, the draft's
`sent` revision and, when Google added no Meet link, a needs-you card. The Meet link, the title and the addresses are
in no event, log, receipt or card but where the pins allow. `on_connection_event` abandons what a revoked grant leaves
unsent. Deterministic code only.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, HTTPException
from tilo_archive import RunArchive
from tilo_connectors import Outbox
from tilo_connectors.adapters.meeting_host import MeetingHostAdapter
from tilo_connectors.errors import MeetingHostConfigError, MeetingHostRefused, SideEffectRefused
from tilo_connectors.meeting_host import (
    ACTION_TYPE,
    CONNECTOR_ID,
    HOST_CALENDAR,
    HostReceipt,
    MeetingEventDraft,
    draft_meeting_event,
    host_gate,
    load_meeting_host_config,
)
from tilo_connectors.provenance import build_manifest
from tilo_connectors.registry import ConnectorRegistry
from tilo_harness.executor import UnitOutcome
from tilo_harness.outputs import UnitOutput
from tilo_harness.skills import SkillRegistry
from tilo_memory.artifacts import ArtifactStore, NewVersion, Origin, Scope

from tilo_api import deps, events
from tilo_api.people_writes import Refusal, Writer
from tilo_api.runs import Run, Seams, _GateFailed

logger = logging.getLogger("tilo_api.meeting_host")
_UNSENT = ("queued", "scheduled", "sending")
_CAP = 1.0  # a hosted meeting uses no model: the plan needs a positive cap, the meter stays at 0
_NEEDS_YOU_TIMEOUT_S = 86_400


@dataclass(frozen=True)
class HostSeams:
    """Everything a host run reads, each from its own `deps` seam (unwired ones are 503 `not_configured`)."""

    store: deps.Store
    writer: deps.EventWriter
    outbox_store: Any
    registry: ConnectorRegistry
    artifacts: ArtifactStore
    redactor: Callable[[str], str]
    open_archive: Callable[..., RunArchive]
    layout_builder: Callable[..., dict]
    skills: SkillRegistry
    broker: Any
    transport: Any


def get_host_seams(
    store: Annotated[deps.Store, Depends(deps.get_store)],
    writer: Annotated[deps.EventWriter, Depends(deps.get_event_writer)],
    outbox_store: Annotated[Any, Depends(deps.get_outbox_store)],
    registry: Annotated[ConnectorRegistry, Depends(deps.get_connector_registry)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    redactor: Annotated[Callable[[str], str], Depends(deps.get_redactor)],
    open_archive: Annotated[Callable[..., RunArchive], Depends(deps.get_run_archive)],
    layout_builder: Annotated[Callable[..., dict], Depends(deps.get_layout_builder)],
    skills: Annotated[SkillRegistry, Depends(deps.get_skill_registry)],
    broker: Annotated[Any, Depends(deps.get_token_broker)],
    transport: Annotated[Any, Depends(deps.get_meeting_host_transport)],
) -> HostSeams:
    return HostSeams(
        store,
        writer,
        outbox_store,
        registry,
        artifacts,
        redactor,
        open_archive,
        layout_builder,
        skills,
        broker,
        transport,
    )


def _canonical(doc: Mapping[str, Any]) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


class _Drafts:
    """The adapter's `ArtifactSource`: the hash-checked read of the run's own store, parsed."""

    def __init__(self, artifacts: ArtifactStore, scope: Scope) -> None:
        self._artifacts, self._scope = artifacts, scope

    def get(self, artifact_id: str, version: int) -> Mapping[str, Any]:
        doc = json.loads(self._artifacts.read(self._scope, {"artifact_id": artifact_id, "version": version}))
        return doc if isinstance(doc, dict) else {}


class _Receipts:
    """The adapter's `ReceiptStore`: Google's event id and the draft ref, as an artifact of the run (origin unit)."""

    def __init__(self, artifacts: ArtifactStore, scope: Scope, run_id: str) -> None:
        self._artifacts, self._scope, self._run_id = artifacts, scope, run_id
        self.unit: str | None = None  # the host unit and its worker, set when the gate starts
        self.agent: str | None = None
        self.made: dict[tuple[str, str], tuple[HostReceipt, dict[str, Any]]] = {}

    def put(self, receipt: HostReceipt) -> dict[str, Any]:
        doc = {
            "v": "1.0", "kind": "meeting_event_receipt", "connector": CONNECTOR_ID, "calendar": HOST_CALENDAR,
            "event_ref": receipt.event_ref, "meeting_id": receipt.meeting_id, "draft": dict(receipt.draft),
            "outbox_id": receipt.outbox_id, "conference": receipt.conference,
        }  # fmt: skip
        data = _canonical(doc)
        origin = Origin(kind="unit", unit=self.unit, agent=self.agent)
        new = NewVersion(
            "application/json", data, self._run_id, origin, idempotency_key=f"{self._run_id}:{self.unit}:0:1"
        )
        stored = self._artifacts.put(self._scope, new)  # the same key returns the first version, whatever its bytes
        if self._artifacts.read(self._scope, stored.ref) != data:
            raise SideEffectRefused("a different receipt is already stored for this send")
        self.made[(receipt.world_id, receipt.outbox_id)] = (receipt, stored.ref)
        return stored.ref

    def get(self, world_id: str, meeting_id: str) -> HostReceipt | None:
        return next(
            (r for (w, _), (r, _ref) in self.made.items() if w == world_id and r.meeting_id == meeting_id), None
        )


class _DraftRunner:
    """The one unit's work: the draft the connector made, as it is. Never a model."""

    def __init__(self, draft: MeetingEventDraft) -> None:
        self._content = draft.content

    async def run(self, unit: Mapping[str, Any], context: Any) -> UnitOutcome:
        output = UnitOutput(media_type="application/json", content=self._content)
        return UnitOutcome(success=True, summary="Drafted the invitation.", outputs=(output,))


def _no_director(**_: Any) -> dict:
    raise NotImplementedError("a hosted meeting is a fixed plan: the Director is never asked")


def _plan() -> dict[str, Any]:
    """One unit, one T3 gate, the two approaches the schema wants (they differ on two dimensions, PG-08)."""
    dims = {"depth": "overview", "sources": 0, "parallelism": 1, "verification": "basic", "output_format": "in_app"}
    approach = {"time": {"min_s": 1, "max_s": 60}, "credits": {"min": 0, "max": 0}, "risks": [], "skips": []}
    return {
        "approaches": [
            {"id": "invite", "label": "Invite the people", "summary": "Ask first, then send the invitation.",
             "dimensions": dims, **approach},
            {"id": "wait", "label": "Hold the invitation", "summary": "Keep the draft and send nothing.",
             "dimensions": {**dims, "depth": "deep", "verification": "thorough"}, **approach},
        ],
        "chosen_approach": "invite",
        "units": [{
            "id": "U1", "unit_type": "meeting_invitation", "title": "Invite the meeting's people", "role": "specialist",
            "district": "D1", "skills": [], "connectors": [CONNECTOR_ID], "actions": [ACTION_TYPE], "depends_on": [],
        }],
        "gates": [{"id": "G1", "action_type": ACTION_TYPE, "risk_tier": "T3", "guards": ["U1"], "policy_ref": None}],
        "budget_cap": _CAP,
    }  # fmt: skip


class HostRun(Run):
    owner_started: frozenset[str] = frozenset()  # this is the owner's own request

    def __init__(
        self, seams: HostSeams, task: deps.TaskRecord, draft: MeetingEventDraft, still_hosted: Callable[[], bool]
    ) -> None:
        self.draft, self.still_hosted = draft, still_hosted
        scope = Scope(deps.ORG_ID, task.world_id, task.owner)
        self.receipts = _Receipts(seams.artifacts, scope, task.run_id)
        adapter = MeetingHostAdapter(  # built per run from the two Google seams and this run's own store
            declaration=seams.registry.get(CONNECTOR_ID), broker=seams.broker, transport=seams.transport,
            artifacts=_Drafts(seams.artifacts, scope), owner_of=lambda world_id: seams.store.worlds[world_id].owner,
            receipts=self.receipts, clock=events.now, emit=lambda part: None, sleep=lambda seconds: None,
        )  # fmt: skip

        def resolver(**_: Any) -> dict:  # step 5 of the gate: the draft's own list, never the address book
            return {"recipients": list(draft.recipients), "destination": HOST_CALENDAR, "known_recipients": []}

        run_seams = Seams(
            _no_director, seams.layout_builder, _DraftRunner(draft), resolver, seams.skills, seams.registry,
            {CONNECTOR_ID: adapter}, seams.outbox_store, seams.writer, {}, seams.artifacts, seams.redactor,
            seams.open_archive,
        )  # fmt: skip
        super().__init__(seams.store, task, {}, _CAP, run_seams)
        self.unit: dict[str, Any] = {}
        self.worker = ""

    def _compile(self, context: Any) -> dict:
        return _plan()

    def _must_ask(self, config: Any) -> None:
        return None  # the owner's own request replaces the "go ahead?" question; the gate card is the one authorisation

    def _exact(self, connector: str, action: str, destination: str, recipients: list[str]) -> str:
        return self.draft.exact if action == ACTION_TYPE else super()._exact(connector, action, destination, recipients)

    async def gate(self, unit: dict, worker: str, action: str, ref: dict, made: str) -> None:
        self.unit, self.worker = unit, worker
        self.receipts.unit, self.receipts.agent = unit["id"], worker
        try:  # MH-07: the stored draft is the one the connector made, and the declaration is the pinned one
            host_gate(self.draft, self._stored(ref), self.seams.connectors.get(CONNECTOR_ID))
        except Exception:
            raise _GateFailed("the stored draft is not the one that was made") from None
        await super().gate(unit, worker, action, ref, made)

    def _stored(self, ref: dict) -> dict[str, Any]:
        found = self.seams.artifacts.head(self.scope, ref)
        if found is None:
            raise LookupError("the item is not in the run's store")
        return dict(found.record)

    async def _send(self, entry: dict, evidence: dict[str, Any]) -> dict:
        authz = entry["authz"]  # only the owner's own approval sends, and only for a meeting that still stands
        try:
            ok = authz.get("by") == "person" and authz.get("ref") == self.owner and self.still_hosted()
        except Exception:
            ok = False  # fail closed
        if not ok:
            raise _GateFailed("the meeting changed or was deleted, so nothing was sent")
        transfer = await super()._send(entry, evidence)
        try:
            self._after_send(entry, transfer)
        except Exception as exc:  # the invitation went out; the run says so plainly
            logger.warning("run %s: the receipt was not recorded (%s)", self.run_id, type(exc).__name__)
            raise _GateFailed("the invitation went out but its receipt could not be recorded") from None
        return transfer

    def _after_send(self, entry: dict, transfer: dict) -> None:
        """Steps 8 and 9: the receipt (its manifest before its event, HR-1), the draft's `sent` revision caused by the
        data.transfer (AR-06, MF-04), and one needs-you card when Google reported `failure`."""
        receipt, ref = self.receipts.made[(self.world_id, entry["id"])]
        stored = self._stored(ref)
        self._manifest(ref, inputs=[entry["item"]], stage="created", cause=None)
        data = {"artifact": ref} | {k: stored[k] for k in ("content_sha256", "media_type", "size_bytes")}
        summary = "The agent made an item."
        self.put("artifact.created", self.worker, ref["artifact_id"], summary, data, district=self.unit["district"],
                 cause=transfer["id"], check_pause=False)  # fmt: skip
        self._manifest(entry["item"], inputs=[], stage="sent", cause=transfer["id"])
        if receipt.conference == "failure":
            self._store_card(self._no_meet_link_card())

    def _manifest(self, ref: dict, *, inputs: list[dict], stage: str, cause: str | None) -> None:
        artifacts, archive = self.seams.artifacts, self.seams.open_archive(org_id=self.org_id, run_id=self.run_id)
        trail = [e for e in self.store.events.get(self.world_id, []) if e.get("run_id") == self.run_id]
        manifest = build_manifest(
            run_id=self.run_id, artifact=ref, content=artifacts.read(self.scope, ref),
            parents=self._stored(ref)["parents"],
            agent={"agent_id": self.worker, "role": self.unit["role"], "model_role": None, "profile": None},
            inputs=inputs, sources=[], claims=[], events=trail, archive=archive.records(), redact=self.seams.redactor,
            archive_head=archive.head(),
        )  # fmt: skip
        artifacts.add_manifest(self.scope, ref, manifest, stage=stage, cause=cause)

    def _no_meet_link_card(self) -> dict:
        building = next(
            b["id"] for level in self.layout["semantic"]["levels"] for d in level["districts"]
            for b in d["buildings"] if self.unit["id"] in b["plan_units"]
        )  # fmt: skip
        return {
            "id": events.new_part_id(), "world_id": self.world_id, "run_id": self.run_id, "kind": "needs_you",
            "rung": "needs_you", "header": {"building": building, "agent": self.worker},
            "what_happened": "Google did not add a Meet link to the invitation.",
            "why_it_matters": "The invitations went out, but nobody can join until a link is added by hand.",
            "options": [
                {"id": "o1", "label": "I will add one", "suggested": True, "irreversible": False,
                 "reason": "Open the event on the meeting host's calendar and add a Google Meet link."},
                {"id": "o2", "label": "Leave it", "suggested": False, "irreversible": False},
            ],
            "add_context": False, "actions": ["show_me"], "answer_channels": ["web", "mobile_web"],
            "created_at": events.now(), "timeout": _NEEDS_YOU_TIMEOUT_S, "safe_default": "o1", "gate": None,
            "consent": None,
        }  # fmt: skip


def host_meeting(w: Writer, meeting_id: str, seams: HostSeams) -> dict[str, Any]:
    """404 for anyone but the owner (PE-05), 409 for a meeting that cannot be hosted or is hosted already, 422 with the
    MH rule for a draft the connector refuses; else the run starts and the owner gets the meeting's world id."""
    found, me = w.stores.meetings.get(w.org, meeting_id), w.stores.persons.get(w.org, w.actor)
    if found is None or me is None or found.record.get("owner") != w.actor or found.record.get("status") == "deleted":
        raise Refusal(404, "not_found")  # the record itself is the connector's to refuse (MH-01): no schema gate here
    meeting = dict(found.record)
    world_id = meeting.get("world_id")
    if (
        meeting["status"] != "scheduled"
        or meeting["source"] != "bot"
        or not isinstance(world_id, str)
        or (world := seams.store.worlds.get(world_id)) is None
        or world.owner != w.actor
    ):
        raise Refusal(409, "not_hostable")
    if world.paused or world_id in seams.store.runs:
        raise Refusal(409, "already_hosted")
    users = dict.fromkeys([meeting["owner"], *(a["user"] for a in meeting["attendees"] if a["user"] is not None)])
    persons = {u: dict(p.record) for u in users if (p := w.stores.persons.get(w.org, u)) is not None}
    try:
        config = load_meeting_host_config(registry=seams.registry)
    except MeetingHostConfigError:
        raise HTTPException(status_code=503, detail="not_configured") from None
    try:
        draft = draft_meeting_event(meeting=meeting, persons=persons, actor=w.actor, now=w.now, config=config)
    except MeetingHostRefused as exc:
        raise Refusal(422, str(exc), rule=exc.rule) from None
    task = deps.TaskRecord(
        owner=w.actor, world_id=world_id, run_id=world.run_id, draft={}, brief={}, questions=[], next_seq=1
    )

    def still_hosted() -> (
        bool
    ):  # at approval: the meeting is still the owner's, scheduled, and every invitee is a person
        now = w.stores.meetings.get(w.org, meeting_id)
        return (
            now is not None
            and (now.record.get("owner"), now.record.get("status")) == (w.actor, "scheduled")
            and all(w.stores.persons.get(w.org, u) is not None for u in draft.invited)
        )

    run = HostRun(seams, task, draft, still_hosted)
    with seams.store.runs_guard:  # two requests at once make one run
        if world_id in seams.store.runs:
            raise Refusal(409, "already_hosted")
        seams.store.runs[world_id] = run
    try:
        threading.Thread(target=run.main, name=f"host-{world_id}", daemon=True).start()
    except BaseException:
        with seams.store.runs_guard:  # a run that never started must not leave a permanent 409
            seams.store.runs.pop(world_id, None)
        raise
    return {"world_id": world_id}


def on_connection_event(part: Mapping[str, Any], *, outbox_store: Any) -> int:
    """The token broker's `emit` sink. A revoked `meeting_host` grant abandons every unsent entry of that person's
    (`authz.ref`), so a reconnect later sends nothing for it. Returns how many it abandoned; an entry a live lease holds
    stays for the next event; any other or malformed part does nothing."""
    try:
        if part["type"] != "connection.revoked" or part["data"]["connector"] != CONNECTOR_ID:
            return 0
        user = part["user_id"]
        unsent = [
            e for e in outbox_store.all_entries()
            if e["connector"] == CONNECTOR_ID and e["state"] in _UNSENT and (e.get("authz") or {}).get("ref") == user
        ]  # fmt: skip
    except Exception:  # a malformed part or a store that cannot be read: nothing is abandoned, nothing is raised
        return 0
    abandoned = 0
    for entry in unsent:
        try:
            if outbox_store.retry_state(entry["id"]).get("ambiguous"):
                continue  # it may have gone out: it stays for the alert path, never marked failed
            Outbox(outbox_store, {}, emit=lambda part: None, clock=events.now, world_id=entry["world_id"]).abandon(
                entry["id"]
            )
            abandoned += 1
        except Exception:  # a live lease (OutboxRefused) or a store error: the next event asks again
            continue
    return abandoned
