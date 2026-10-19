"""Test doubles for FR-MTG-08 (minutes email and a nudge per open item: drafted, never sent; the send is T3, a card,
the Owner's approval, the outbox). The API they drive is pinned in API_FR_MTG_08.md.

Nothing here is production logic. The send line under test is the real one end to end (the CHN-WIRE-1 line of
`_chn_wire1_lib`): the real FR-CHN-11 `Autopilot` in production mode, the real `tilo_connectors.Outbox` and
`GmailAdapter` over `FakeGmailApi`, the REAL `tilo_policy.check_entry`. The only thing these tests need from the
ticket is `tilo_channels.meeting_followup.MeetingFollowUp`, imported at call time so a missing module fails the test
that uses it, not the collection of the file.

The records the follow-up reads are the contract shapes (`meeting`, `minutes`, `work_item`), built here from a small
spec and checked against the schemas by `test_FR_MTG_08_the_fixtures_are_contract_valid`. Every text that must reach
(or must stay out of) a model prompt carries its own letters-only key (no digits), so a test finds it by substring.

No network, no paid call, no real mail. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import copy
import functools
import importlib
import json
import secrets
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from _chn10_lib import INJECTION_MARKER, USER, EventLog, MemoryDraftStore, answer, fresh_key
from _chn11_lib import MAILBOX
from _chn13_lib import Line
from _chn_wire1_lib import make_wire_line, requested_part, resolved, try_send
from tilo_providers.interfaces import (
    Capability,
    GenerateRequest,
    GenerateResponse,
    ModelProvider,
    PriceQuote,
)

__all__ = ["INJECTION_MARKER", "MAILBOX", "OWNER", "USER", "World", "make_world"]

OWNER = USER  # "u_sarah": the meeting Owner, the world's owner, the signed-in person who approves
MEETING_ID = "mt_launch_sync"
OTHER_MEETING_ID = "mt_other_sync"
MINUTES_ARTIFACT = {"artifact_id": "art_minutes_launch_sync", "version": 1}
TRANSCRIPT_ARTIFACT = {"artifact_id": "art_transcript_launch_sync", "version": 1}
ORG = "org_example"
CONFIRMED_AT = "2026-10-01T10:30:00.000Z"  # before the fake clock's start (2026-10-02T09:00Z): "no later than now"

PEOPLE: dict[str, str] = {  # person id -> the address tilo-api resolves for them (PE-09, PE-20)
    "u_sarah": "sarah.chen@harborview.example",
    "u_priya": "priya.rao@harborview.example",
    "u_sam": "sam.ito@harborview.example",
    "u_lena": "lena.okafor@harborview.example",
    "u_mallory": "mallory.ng@harborview.example",  # a person of the org who was not at the meeting
}
STRANGER = "u_mallory"  # a person of the org who was not at the meeting
STRANGER_ADDRESS = "mallory@attacker.example"
ATTENDEES = [
    {"name": "Sarah Chen", "user": "u_sarah"},
    {"name": "Priya", "user": "u_priya"},
    {"name": "Sam", "user": "u_sam"},
    {"name": "Lena", "user": "u_lena"},
    {"name": "Dev from Acme", "user": None},  # an outsider: no person, no address Tilo may use
]


def followup_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.meeting_followup")


def needs_followup(test: Callable[..., Any]) -> Callable[..., Any]:
    """A missing `tilo_channels.meeting_followup` fails once, before Hypothesis generates or shrinks anything."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        followup_module()
        return test(*args, **kwargs)

    return wrapper


# ---------------------------------------------------------------------------
# The records: one spec per action item, one build per meeting


@dataclass
class Item:
    """One action item of the minutes and, when `work` is set, the work item the Owner's answer made of it.
    `work`: None (no work item yet), "proposed", "open", "done" or "dropped". `confirmed`: who confirmed an open item
    ("owner", "other", None). `source`: "this" meeting or "other" (PE-19 coupling)."""

    n: int
    text: str
    state: str = "verified"
    owner: str | None = "u_priya"
    work: str | None = "open"
    confirmed: str | None = "owner"
    source: str = "this"
    flagged: bool = False
    key: str = field(default_factory=fresh_key)

    @property
    def id(self) -> str:
        return f"ai{self.n}"

    @property
    def work_item_id(self) -> str | None:
        return f"wi_{self.id}" if self.work is not None else None

    @property
    def eligible(self) -> bool:
        """The oracle: a nudge exists for this item, and only for such items (PE-03, PE-07, PE-19, FR-MTG-06)."""
        return (
            self.state == "verified"
            and self.work == "open"
            and self.confirmed == "owner"
            and self.source == "this"
            and self.owner is not None
        )


def item(n: int, what: str, **kw: Any) -> Item:
    spec = Item(n=n, text="", **kw)
    spec.text = f"{what} {spec.key}"
    return spec


def minutes_doc(world: World) -> dict[str, Any]:
    return {
        "meeting_id": world.meeting_id,
        "transcript": copy.deepcopy(TRANSCRIPT_ARTIFACT),
        "generated_at": "2026-10-01T10:00:00.000Z",
        "flagged": world.minutes_flagged,
        "summary": [{"text": world.summary, "evidence": ["u0012"]}],
        "decisions": [
            {"text": text, "state": state, "evidence": ["u0012"] if state == "verified" else []}
            for text, state in world.decisions
        ],
        "action_items": [
            {
                "id": it.id,
                "text": it.text,
                "state": it.state,
                "evidence": ["u0021"] if it.state == "verified" else [],
                "owner_text": "Someone" if it.owner else None,
                "owner": it.owner,
                "due_text": None,
                "due": None,
                "work_item_id": it.work_item_id,
            }
            for it in world.items
        ],
        "agenda": [],
    }


def meeting_doc(world: World) -> dict[str, Any]:
    return {
        "id": world.meeting_id,
        "org_id": ORG,
        "owner": world.meeting_owner,
        "title": "Launch plan sync",
        "series": None,
        "scheduled": None,
        "agenda": [],
        "attendees": copy.deepcopy(ATTENDEES),
        "attestation": {"by": world.meeting_owner, "at": "2026-10-01T09:00:00.000Z", "notice_version": "1.0.0"},
        "source": "upload",
        "status": world.status,
        "ended_reason": "completed",
        "minutes_confirmed_by": world.confirmed_by,
        "transcript": copy.deepcopy(TRANSCRIPT_ARTIFACT),
        "minutes": None if world.status in ("discarded", "deleted") else copy.deepcopy(MINUTES_ARTIFACT),
        "delete_transcript_after": "2026-11-01T10:00:00.000Z",
        "delete_minutes_after": "2027-01-01T10:00:00.000Z",
        "created_at": "2026-10-01T09:00:00.000Z",
    }


def work_item_doc(world: World, it: Item) -> dict[str, Any]:
    assert it.work is not None
    confirmer = {"owner": world.meeting_owner, "other": STRANGER, None: None}[it.confirmed]
    confirmed = it.work in ("open", "done", "dropped") and confirmer is not None
    history = [{"at": "2026-10-01T10:00:00.000Z", "by": "A_analyst", "change": "created", "status": "proposed"}]
    if confirmed:
        history.append({"at": CONFIRMED_AT, "by": confirmer, "change": "confirmed", "status": it.work})
    ref = f"{world.meeting_id if it.source == 'this' else OTHER_MEETING_ID}#{it.id}"
    return {
        "id": it.work_item_id,
        "org_id": ORG,
        "owner": it.owner or "u_priya",
        "title": it.text[:140],
        "due": None,
        "due_text": None,
        "status": it.work,
        "source": {"kind": "meeting", "ref": ref, "evidence": ["u0021"]},
        "created_by": {"by": "tilo", "ref": "A_analyst", "at": "2026-10-01T10:00:00.000Z"},
        "assigned_by": {"by": world.meeting_owner, "at": "2026-10-01T10:00:00.000Z"},
        "confirmed_by": {"by": confirmer, "at": CONFIRMED_AT} if confirmed else None,
        "snoozed_until": None,
        "flagged": it.flagged,
        "history": history,
        "created_at": "2026-10-01T10:00:00.000Z",
        "updated_at": CONFIRMED_AT if confirmed else "2026-10-01T10:00:00.000Z",
    }


# ---------------------------------------------------------------------------
# Ports the follow-up reads through (read only; scoped to the meeting Owner, PE-05)


class FakeMeetings:
    def __init__(self, world: World) -> None:
        self._w = world
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def get(self, user_id: str, meeting_id: str) -> dict[str, Any] | None:
        with self._lock:
            self.calls.append((user_id, meeting_id))
        if meeting_id != self._w.meeting_id or (self._w.scoped_reads and user_id != self._w.meeting_owner):
            return None  # an attendee, an assignee and anyone else read nothing of a meeting (PE-05)
        return meeting_doc(self._w)


class FakeMinutes:
    def __init__(self, world: World) -> None:
        self._w = world
        self.calls: list[tuple[str, str, int]] = []
        self._lock = threading.Lock()

    def get(self, user_id: str, artifact_id: str, version: int) -> dict[str, Any] | None:
        with self._lock:
            self.calls.append((user_id, artifact_id, version))
        if (artifact_id, version) != (MINUTES_ARTIFACT["artifact_id"], MINUTES_ARTIFACT["version"]):
            return None
        if self._w.scoped_reads and user_id != self._w.meeting_owner:
            return None
        doc = minutes_doc(self._w)
        if self._w.minutes_of_meeting is not None:
            doc["meeting_id"] = self._w.minutes_of_meeting
        return doc


class FakeWorkItems:
    def __init__(self, world: World) -> None:
        self._w = world
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def get(self, user_id: str, work_item_id: str) -> dict[str, Any] | None:
        with self._lock:
            self.calls.append((user_id, work_item_id))
        if self._w.scoped_reads and user_id != self._w.meeting_owner:
            return None
        found = next((i for i in self._w.items if i.work_item_id == work_item_id and i.work is not None), None)
        return work_item_doc(self._w, found) if found else None


class FakeDirectory:
    """`address(person_id)`: the address `tilo-api` resolves for a person server side (PE-09, PE-20); None when it has
    none. A model, the minutes and the meeting never name an address Tilo sends to."""

    def __init__(self, known: dict[str, str]) -> None:
        self.known = dict(known)
        self.calls: list[str] = []
        self._lock = threading.Lock()

    def address(self, person_id: str) -> str | None:
        with self._lock:
            self.calls.append(person_id)
        return self.known.get(person_id)


# ---------------------------------------------------------------------------
# The "autopilot" role model: a faithful scripted writer (what the prompt gives, nothing else) unless a test overrides


class FollowUpModel(ModelProvider):
    """Answers in the FR-CHN-10 pinned JSON shape {"body": str, "questions": [str]}. A call whose prompt holds the
    summary's key is the minutes email; one that holds exactly one item key is that item's nudge. By default the answer
    is faithful: it repeats only what the Owner confirmed (the oracle of the World), so a test can tell what a leak or
    an invention is. `minutes_body` / `nudge_body` override the answer. Records every request."""

    def __init__(self, world: World) -> None:
        self._w = world
        self.requests: list[GenerateRequest] = []
        self.minutes_body: str | Callable[[], str] | None = None
        self.nudge_body: Callable[[Item], str] | None = None
        self.raise_with: Exception | None = None
        self._lock = threading.Lock()

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
            if self.raise_with is not None:
                raise self.raise_with
        text = request.prompt
        if self._w.summary_key in text:
            body = self.minutes_body() if callable(self.minutes_body) else self.minutes_body
            body = body if body is not None else self._w.faithful_minutes_body()
            return GenerateResponse(text=answer(body), profile_id="fake-autopilot")
        hit = [i for i in self._w.items if i.key in text]
        if len(hit) == 1:
            body = self.nudge_body(hit[0]) if self.nudge_body else self._w.faithful_nudge_body(hit[0])
            return GenerateResponse(text=answer(body), profile_id="fake-autopilot")
        return GenerateResponse(text=answer("Thanks, noted."), profile_id="fake-autopilot")

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        return {"vectors": [[0.0] * 8], "profile_id": "fake-autopilot"}

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON}

    def price(self) -> PriceQuote:
        return PriceQuote(input=0.0, output=0.0)

    def prompts(self) -> list[str]:
        """Everything each call was given: system text and prompt."""
        return [(r.system or "") + "\n" + r.prompt for r in self.requests]

    def minutes_prompts(self) -> list[str]:
        return [p for p in self.prompts() if self._w.summary_key in p]

    def nudge_prompts(self) -> list[str]:
        return [p for p in self.prompts() if self._w.summary_key not in p]


# ---------------------------------------------------------------------------
# The world under test


@dataclass
class World:
    """One meeting the Owner confirmed, its minutes and work items, the person directory, the model and the real send
    line. `followup` is the `MeetingFollowUp` under test; `new_instance()` another one over the same stores (a
    restart or a second Cloud Run instance)."""

    line: Line
    items: list[Item]
    decisions: list[tuple[str, str]]  # (text, "verified" | "unverified")
    summary: str
    summary_key: str
    status: str = "minuted"
    confirmed_by: dict[str, str] | None = None
    minutes_flagged: bool = False
    minutes_of_meeting: str | None = None  # the minutes document names another meeting (a broken coupling)
    meeting_id: str = MEETING_ID
    meeting_owner: str = OWNER
    scoped_reads: bool = True  # False: the readers hand back the record to anyone (the module must still refuse)
    _followup: Any = None
    meetings: FakeMeetings = None  # type: ignore[assignment]
    minutes: FakeMinutes = None  # type: ignore[assignment]
    work_items: FakeWorkItems = None  # type: ignore[assignment]
    directory: FakeDirectory = None  # type: ignore[assignment]
    model: FollowUpModel = None  # type: ignore[assignment]
    drafts: MemoryDraftStore = None  # type: ignore[assignment]
    events: Any = None

    # --- the oracle: what the Owner confirmed, computed here and nowhere in the code under test ------------------

    def confirmed_items(self) -> list[Item]:
        return [i for i in self.items if i.eligible]

    def confirmed_decisions(self) -> list[str]:
        return [t for t, s in self.decisions if s == "verified"]

    def unconfirmed_texts(self) -> list[str]:
        """The text of everything the Owner did not confirm: it must never reach a prompt or an email."""
        out = [t for t, s in self.decisions if s != "verified"]
        return out + [i.text for i in self.items if not i.eligible]

    def faithful_minutes_body(self) -> str:
        lines = ["Hi all,", "", "Here are the notes from the meeting.", "", self.summary, ""]
        if decisions := self.confirmed_decisions():
            lines += ["Decisions:", *[f"- {t}" for t in decisions], ""]
        if items := self.confirmed_items():
            lines += ["Action items:", *[f"- {i.text}" for i in items], ""]
        return "\n".join([*lines, "Best,", "Sarah"])

    @staticmethod
    def faithful_nudge_body(it: Item) -> str:
        return f"Hi,\n\nA reminder about this item: {it.text}\n\nThanks,\nSarah"

    @property
    def followup(self) -> Any:
        """The `MeetingFollowUp` under test, built on first use (so the fixtures can be checked without it)."""
        if self._followup is None:
            self._followup = self.build()
        return self._followup

    # --- wiring -----------------------------------------------------------------------------------------------

    def build(self, *, autopilot: Any = None) -> Any:
        return followup_module().MeetingFollowUp(
            meetings=self.meetings,
            minutes=self.minutes,
            work_items=self.work_items,
            directory=self.directory,
            model=self.model,
            safety=self.line.bench.rig.safety,
            drafts=self.drafts,
            autopilot=autopilot or self.line.ap,
            mailbox=lambda user_id: MAILBOX,
            clock=self.line.clock,
            emit=self.events,
        )

    def new_instance(self) -> Any:
        return self.build(autopilot=self.line.bench.new_autopilot())

    def minutes_email(self, *picks: str, request_id: str = "req-1", user_id: str = OWNER) -> Any:
        return self.followup.draft_minutes_email(
            user_id, self.meeting_id, recipients=list(picks), request_id=request_id
        )

    def nudges(self, *, request_id: str = "req-1", user_id: str = OWNER) -> list[Any]:
        return self.followup.draft_nudges(user_id, self.meeting_id, request_id=request_id)

    # --- what happened ------------------------------------------------------------------------------------------

    def all_events(self) -> list[dict[str, Any]]:
        return [*self.events.parts, *self.line.bench.events.parts]

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [p for p in self.all_events() if p.get("type") == event_type]

    def untouched(self) -> bool:
        """Nothing was drafted, screened, stored, emitted or queued."""
        return (
            self.model.requests == []
            and self.line.bench.rig.safety.texts == []
            and self.drafts.dump() == "{}"
            and self.line.bench.cards.dump() == "{}"
            and self.all_events() == []
            and self.line.entries() == []
            and self.line.api.sent == []
        )

    def approve(self, card: Any, *, line: Line | None = None, **kw: Any) -> dict:
        """The `approval.resolved` part `tilo-api` records for the Owner's Send tap on this card."""
        line = line or self.line
        requested = requested_part(line, card)
        line.advance(4)
        return resolved(requested, line, **kw)

    def approve_and_send(self, card: Any) -> Any:
        return try_send(self.line.ap, card.card_id, self.approve(card))


def make_world(
    items: Sequence[Item] | None = None,
    *,
    level: str = "L1",
    decisions: Sequence[tuple[str, str]] | None = None,
    summary: str | None = None,
    directory: dict[str, str] | None = None,
    **kw: Any,
) -> World:
    """The default meeting: two open, confirmed items (Priya, Sam), plus one of every kind the Owner did not confirm."""
    summary_key = fresh_key()
    if items is None:
        items = [
            item(1, "Send the rate sheet to Acme", owner="u_priya"),
            item(2, "Book the venue for the team", owner="u_sam"),
            item(3, "Draft the press note", owner="u_lena", work="proposed", confirmed=None),  # Owner skipped it
            item(4, "Call the printer", owner=None, state="unverified", work=None, confirmed=None),
            item(5, "Order the banners", owner="u_priya", work="dropped"),
            item(6, "Update the website", owner="u_sam", work="done"),
            item(7, "Brief the partners", owner="u_lena", confirmed="other"),
            item(8, "Plan the launch event", owner="u_lena", source="other"),
        ]
    line = make_wire_line(level)
    if decisions is None:
        decisions = [
            (f"Launch with the plan as agreed {fresh_key()}", "verified"),
            (f"Move the launch to the other site {fresh_key()}", "unverified"),
        ]
    summary_text = f"{summary} {summary_key}" if summary is not None else f"The launch plan is settled {summary_key}"
    is_confirmed = kw.pop("confirmed", True)
    confirmer = kw.pop("confirmer", OWNER)
    world = World(
        line=line,
        items=list(items),
        decisions=list(decisions),
        summary=summary_text,
        summary_key=summary_key,
        confirmed_by={"by": confirmer, "at": CONFIRMED_AT} if is_confirmed else None,
        **kw,
    )
    world.meetings, world.minutes, world.work_items = FakeMeetings(world), FakeMinutes(world), FakeWorkItems(world)
    world.directory = FakeDirectory(PEOPLE if directory is None else directory)
    world.model = FollowUpModel(world)
    world.drafts = MemoryDraftStore()
    world.events = EventLog()
    return world


def addresses(card: Any) -> tuple[str, ...]:
    return tuple(card.to) + tuple(card.cc)


def person_address(person_id: str) -> str:
    return PEOPLE[person_id]


def dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def token() -> str:
    return secrets.token_hex(4)
