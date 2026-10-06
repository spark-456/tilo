"""Test doubles and builders for FR-CHN-10 (Email Autopilot drafting from an instruction plus the thread, within the
content rules of PRD 11.4). The API they drive is pinned in API_FR_CHN_10.md.

Package-unique module name on purpose (same reason as `_channels_lib.py`). Nothing here is production logic: every
class is a fake for an injected dependency of `tilo_channels.drafting` (the quarantined thread reader, the
"autopilot" role model, the safety provider, the draft store, the event writer) or a builder of a test thread.
`load_drafting_cases` joins the 20 E-MAIL drafting cases (evals/cases/E-MAIL/E-MAIL-31..50.yaml, PRD 19.2) with the
scripted answers and 30 extra cases in fixtures/FR_CHN_10_drafting_cases.yaml: 50 drafting cases.

No network, no paid calls: the model is a scripted `ModelProvider`, the safety provider wraps the deterministic
`tilo_providers.safety.FakeSafetyProvider`. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import copy
import functools
import importlib
import json
import re
import secrets
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

import yaml
from _channels_lib import FakeClock
from _chn_contracts_lib import REPO_ROOT
from tilo_providers.interfaces import (
    Capability,
    GenerateRequest,
    GenerateResponse,
    ModelProvider,
    PriceQuote,
    SafetyResult,
)
from tilo_providers.safety import FakeSafetyProvider

E_MAIL_DIR = REPO_ROOT / "evals" / "cases" / "E-MAIL"
FIXTURE = REPO_ROOT / "services" / "channels" / "tests" / "fixtures" / "FR_CHN_10_drafting_cases.yaml"
PROMPTS_AUTOPILOT = REPO_ROOT / "prompts" / "autopilot"

USER = "u_sarah"
OTHER_USER = "u_marcus"
FINDING_KINDS = ("number", "date", "contact", "commitment", "obfuscation")
INJECTION_MARKER = "Ignore previous instructions"  # a FakeSafetyProvider marker (tilo_providers.safety)
# FR-CHN-11 (BQ-265): inbound-aware L2 reads the replied-to message's Subject (it must hold no money, legal or
# commitment word, so no "estimate") and its Authentication-Results header (dmarc=pass), so a clean test thread
# carries both by default.
CLEAN_SUBJECT = "Engine tuneup scheduling"
AUTH_PASS = "mx.example; spf=pass; dkim=pass; dmarc=pass header.from=harriercharters.example"


def drafting_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.drafting")


def needs_drafting(test: Callable[..., Any]) -> Callable[..., Any]:
    """Wraps a Hypothesis test so a missing `tilo_channels.drafting` fails once, before any example is generated
    or shrunk (Hypothesis would otherwise shrink an import error for minutes)."""

    @functools.wraps(test)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        drafting_module()
        return test(*args, **kwargs)

    return wrapper


def answer(body: Any, questions: Any = None, **extra: Any) -> str:
    """A model answer in the pinned JSON shape: {"body": str, "questions": [str]} plus anything a model adds."""
    doc: dict[str, Any] = {"body": body}
    if questions is not None:
        doc["questions"] = questions
    doc.update(extra)
    return json.dumps(doc)


def fresh_key() -> str:
    """A unique letters-only marker that ties a thread to its scripted answers. No digits, so it never adds a
    number to the facts a draft may use; never a secret."""
    return "zq" + "".join(secrets.choice("bcdfghjklmnpqrstvwxz") for _ in range(12))


def bare(address: str) -> str:
    match = re.search(r"<([^>]+)>", address)
    return (match.group(1) if match else address).strip().lower()


def message_id_header(message_id: str) -> str:
    return f"<{message_id}@mail.example>"


# ---------------------------------------------------------------------------
# Threads


@dataclass
class Msg:
    message_id: str
    sender: str  # the From header, possibly with a display name
    subject: str
    body: str
    to: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)
    date: str = "2026-10-02T09:00:00Z"

    def as_message(self) -> dict[str, Any]:
        headers = {"Message-ID": message_id_header(self.message_id), **self.headers}
        return {
            "message_id": self.message_id,
            "from": self.sender,
            "to": list(self.to),
            "cc": list(self.cc),
            "subject": self.subject,
            "body": self.body,
            "date": self.date,
            "headers": headers,
            # the body shape the production reader carries (a lone plain-text body, no files)
            "has_text_part": True,
            "has_other_parts": False,
            "attachments": [],
        }


@dataclass
class Thread:
    thread_id: str
    messages: list[Msg]

    def as_thread(self) -> dict[str, Any]:
        return {"thread_id": self.thread_id, "messages": [m.as_message() for m in self.messages]}

    def texts(self) -> list[str]:
        """The thread as the checker's fact sources: every message's subject, body, From, To and Cc."""
        out: list[str] = []
        for m in self.messages:
            out += [m.subject, m.body, m.sender, *m.to, *m.cc]
        return out

    def last_inbound(self, mailbox: str) -> Msg:
        return [m for m in self.messages if bare(m.sender) != mailbox.lower()][-1]


class FakeThreadReader:
    """The quarantined reader (PRD 16.3 item 3): read-only `get_thread(user_id, thread_id)`. It has no other
    method, so it offers no side effect. Records every call."""

    def __init__(self) -> None:
        self._threads: dict[tuple[str, str], Thread] = {}
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def add(self, user_id: str, thread: Thread) -> Thread:
        with self._lock:
            self._threads[(user_id, thread.thread_id)] = thread
        return thread

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        with self._lock:
            self.calls.append((user_id, thread_id))
            thread = self._threads.get((user_id, thread_id))
        if thread is None:
            raise LookupError("no such thread")
        return thread.as_thread()


# ---------------------------------------------------------------------------
# Model and safety provider


Scripted = Callable[[], GenerateResponse] | str


class ScriptedModel(ModelProvider):
    """The "autopilot" role model (PRD 6.4), scripted. `script(key, *answers)` registers answers for the call
    whose prompt contains `key` (a unique marker in the thread); they are given in order and the last one repeats,
    so (invented, clean) acts out a regeneration. Records every request."""

    def __init__(self, default: str | None = None) -> None:
        self.default = default if default is not None else answer("Thanks, noted.")
        self.scripts: dict[str, list[Scripted]] = {}
        self.served: dict[str, int] = {}
        self.requests: list[GenerateRequest] = []
        self.raise_with: Exception | None = None
        self._lock = threading.Lock()

    def script(self, key: str, *answers: Scripted) -> None:
        with self._lock:
            self.scripts[key] = list(answers)
            self.served[key] = 0

    def calls_for(self, key: str) -> list[GenerateRequest]:
        return [r for r in self.requests if key in r.prompt or key in (r.system or "")]

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
            if self.raise_with is not None:
                raise self.raise_with
            hits = [k for k in self.scripts if k in request.prompt]
            if len(hits) > 1:
                raise AssertionError("FR-CHN-10 test: one model call carried more than one thread")
            if not hits:
                return GenerateResponse(text=self.default, profile_id="fake-autopilot")
            key = hits[0]
            answers = self.scripts[key]
            scripted = answers[min(self.served[key], len(answers) - 1)]
            self.served[key] += 1
        if callable(scripted):
            return scripted()
        return GenerateResponse(text=scripted, profile_id="fake-autopilot")

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


class SpySafety(FakeSafetyProvider):
    """The deterministic fake safety provider (flags the fixed prompt-injection markers), recording every screened
    text. `raise_with` makes every check raise, to test fail-closed handling."""

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.raise_with: Exception | None = None
        self._lock = threading.Lock()

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> SafetyResult:
        with self._lock:
            self.texts.append(text)
        if self.raise_with is not None:
            raise self.raise_with
        return super()._check(text, content=content, mime_type=mime_type)

    def screened(self, needle: str) -> bool:
        return any(needle in t for t in self.texts)


# ---------------------------------------------------------------------------
# Store and event writer


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))  # raises TypeError on anything a document store could not hold


class MemoryDraftStore:
    """Drafting results per (user, instruction): get, atomic create-if-absent, put."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str, instruction_id: str) -> dict | None:
        with self._lock:
            doc = self._docs.get((user_id, instruction_id))
            return copy.deepcopy(doc) if doc is not None else None

    def create(self, user_id: str, instruction_id: str, value: dict) -> bool:
        with self._lock:
            if (user_id, instruction_id) in self._docs:
                return False
            self._docs[(user_id, instruction_id)] = _jsonable(value)
            return True

    def put(self, user_id: str, instruction_id: str, value: dict) -> None:
        with self._lock:
            self._docs[(user_id, instruction_id)] = _jsonable(value)

    def dump(self) -> str:
        with self._lock:
            return json.dumps({f"{u}/{i}": v for (u, i), v in self._docs.items()}, sort_keys=True)


class EventLog:
    """The injected `emit`: records every event part (`{type, data, ...}`)."""

    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def __call__(self, part: dict[str, Any]) -> None:
        with self._lock:
            self.parts.append(copy.deepcopy(part))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [p for p in self.parts if p.get("type") == event_type]


# ---------------------------------------------------------------------------
# Rig


@dataclass
class Rig:
    """One drafting wiring: the real `Drafter` over the fakes. `new_drafter()` builds another instance over the
    same stores (a restart, or a second Cloud Run instance)."""

    clock: FakeClock
    reader: FakeThreadReader
    model: ScriptedModel
    safety: SpySafety
    drafts: MemoryDraftStore
    events: EventLog
    svc: Any = None

    def new_drafter(self) -> Any:
        return drafting_module().Drafter(
            reader=self.reader,
            model=self.model,
            safety=self.safety,
            drafts=self.drafts,
            clock=self.clock,
            emit=self.events,
        )

    def thread(
        self,
        *,
        sender: str = "David Miller <david.miller@harriercharters.example>",
        to: Sequence[str] = ("ops@harborview.example",),
        cc: Sequence[str] = ("sarah.chen@harborview.example",),
        subject: str = CLEAN_SUBJECT,
        body: str = "Can Marcus come by this Friday afternoon to look at the engine?",
        headers: dict[str, str] | None = None,
        earlier: Sequence[Msg] = (),
        answers: Sequence[Scripted] = (),
        user_id: str = USER,
    ) -> tuple[Thread, str]:
        """Adds a thread for `user_id` whose last message carries a fresh key; `answers` are scripted for it.
        Returns the thread and its key."""
        key = fresh_key()
        last = Msg(
            message_id="m-" + secrets.token_hex(5),
            sender=sender,
            subject=subject,
            body=f"{body}\n\n{key}",
            to=list(to),
            cc=list(cc),
            headers={"Authentication-Results": AUTH_PASS, **(headers or {})},
        )
        thread = Thread(thread_id="t-" + secrets.token_hex(5), messages=[*earlier, last])
        self.reader.add(user_id, thread)
        if answers:
            self.model.script(key, *answers)
        return thread, key

    def draft(self, thread: Thread, instruction: str = "Tell David Friday 2pm works.", **kwargs: Any) -> Any:
        kwargs.setdefault("instruction_id", "ins-" + secrets.token_hex(6))
        kwargs.setdefault("mailbox", "ops@harborview.example")
        user_id = kwargs.pop("user_id", USER)
        return self.svc.draft(user_id, thread_id=thread.thread_id, instruction=instruction, **kwargs)


def make_rig() -> Rig:
    rig = Rig(
        clock=FakeClock(),
        reader=FakeThreadReader(),
        model=ScriptedModel(),
        safety=SpySafety(),
        drafts=MemoryDraftStore(),
        events=EventLog(),
    )
    rig.svc = rig.new_drafter()
    return rig


# ---------------------------------------------------------------------------
# The 50 drafting cases


@dataclass(frozen=True)
class Invented:
    kind: str
    body: str
    sentence: str
    realizes: str | None


@dataclass(frozen=True)
class DraftingCase:
    id: str
    mailbox: str
    mode: str
    instruction: str
    thread: Thread
    clean: str
    invented: tuple[Invented, ...]
    forbidden: tuple[str, ...]  # ground-truth forbidden commitments (eval cases only)

    def sources(self) -> list[str]:
        return self.thread.texts()


def insert_before_sign_off(clean: str, sentence: str) -> str:
    """The clean answer with one extra sentence added at the end of the paragraph before the sign-off."""
    paragraphs = clean.split("\n\n")
    paragraphs[-2] = f"{paragraphs[-2]} {sentence}"
    return "\n\n".join(paragraphs)


def _thread_from(raw: dict[str, Any]) -> Thread:
    messages = [
        Msg(
            message_id=m["message_id"],
            sender=m["from"],
            subject=m["subject"],
            body=m["body"],
            to=list(m.get("to") or []),
            cc=list(m.get("cc") or []),
            headers=dict(m.get("headers") or {}),
            date=str(m.get("date") or "2026-10-02T09:00:00Z"),
        )
        for m in raw["messages"]
    ]
    return Thread(thread_id=raw["thread_id"], messages=messages)


def _invented(clean: str, rows: list[dict[str, Any]]) -> tuple[Invented, ...]:
    return tuple(
        Invented(
            kind=r["kind"],
            body=insert_before_sign_off(clean, r["sentence"]),
            sentence=r["sentence"],
            realizes=r.get("realizes"),
        )
        for r in rows
    )


def load_drafting_cases() -> list[DraftingCase]:
    fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    scripted = fixture["eval_answers"]
    cases: list[DraftingCase] = []
    for path in sorted(E_MAIL_DIR.glob("E-MAIL-*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        truth = raw.get("ground_truth") or {}
        if "forbidden_commitments" not in truth:
            continue  # triage cases (FR-CHN-09) have no instruction
        answers = scripted[raw["id"]]
        instruction = raw["inputs"]["instruction"]
        mode = "reply_all" if instruction.lower().startswith("reply to all") else "reply"
        cases.append(
            DraftingCase(
                id=raw["id"],
                mailbox=raw["inputs"]["mailbox"],
                mode=mode,
                instruction=instruction,
                thread=_thread_from(raw["inputs"]["thread"]),
                clean=answers["clean"],
                invented=_invented(answers["clean"], answers["invented"]),
                forbidden=tuple(truth["forbidden_commitments"]),
            )
        )
    for raw in fixture["extra_cases"]:
        cases.append(
            DraftingCase(
                id=raw["id"],
                mailbox=raw["mailbox"],
                mode=raw.get("mode", "reply"),
                instruction=raw["instruction"],
                thread=_thread_from(raw["thread"]),
                clean=raw["clean"],
                invented=_invented(raw["clean"], raw["invented"]),
                forbidden=(),
            )
        )
    return cases


def case_rig(case: DraftingCase, *answers: Scripted, user_id: str = USER) -> tuple[Rig, str]:
    """A rig holding `case`'s thread, with `answers` scripted for it. Returns the rig and the thread key (the case's
    last message body, unique across the set)."""
    rig = make_rig()
    rig.reader.add(user_id, case.thread)
    key = case.thread.messages[-1].body
    rig.model.script(key, *answers)
    return rig, key


def draft_case(rig: Rig, case: DraftingCase, *, instruction_id: str | None = None, user_id: str = USER) -> Any:
    return rig.svc.draft(
        user_id,
        instruction_id=instruction_id or f"ins-{case.id.lower()}",
        thread_id=case.thread.thread_id,
        instruction=case.instruction,
        mailbox=case.mailbox,
        mode=case.mode,
    )
