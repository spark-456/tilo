"""Test doubles and builders for FR-CHN-09 (Email Autopilot triage: five categories, priority, learning from
corrections). The API they drive is pinned in API_FR_CHN_09.md.

Package-unique module name on purpose (same reason as `_channels_lib.py`). Nothing here is production logic:
every class is a fake for an injected dependency of `tilo_channels.triage` (the quarantined mail reader, the
"autopilot" role model, the safety provider, the P7 preference store, the triage result store, the event
writer) or a builder of a test mail. `load_triage_cases` reads the 30 E-MAIL triage cases (PRD 19.2) straight
from `evals/cases/E-MAIL/*.yaml`; their ground truth fixes the five category slugs and the three priorities.

No network, no paid calls: the model is a scripted `ModelProvider`, the safety provider wraps the
deterministic `tilo_providers.safety.FakeSafetyProvider`. Addresses are fictional `.example` domains.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
import secrets
import threading
from collections.abc import Callable, Iterator
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
PROMPTS_AUTOPILOT = REPO_ROOT / "prompts" / "autopilot"

# PRD 11.3 categories, spelled as the E-MAIL eval ground truth spells them (evals/tests/test_PRD_19_2_e_mail_cases.py).
CATEGORIES = ("needs_reply", "needs_action", "fyi", "newsletter_promo", "suspicious")
# PRD 11.3 says priority is "a score"; the E-MAIL ground truth uses these three levels.
PRIORITIES = ("high", "normal", "low")
PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2}

DAY_S = 86_400
USER = "u_riya"
OTHER_USER = "u_sam"


def triage_module() -> Any:
    """Imported at call time so a missing module fails the test, not collection."""
    return importlib.import_module("tilo_channels.triage")


def answer(category: Any, priority: Any = "normal", **extra: Any) -> str:
    """A model answer in the pinned JSON shape."""
    return json.dumps({"category": category, "priority": priority, **extra})


def fresh_token() -> str:
    """A unique marker that ties a mail to its scripted model answer; never a secret."""
    return "ref-" + secrets.token_hex(6)


# ---------------------------------------------------------------------------
# Mail


@dataclass
class Mail:
    message_id: str
    sender: str  # the From header, possibly with a display name
    subject: str
    body: str
    to: list[str] = field(default_factory=lambda: ["riya@harborview.example"])
    cc: list[str] = field(default_factory=list)
    thread_id: str | None = None
    headers: dict[str, str] = field(default_factory=dict)

    def as_message(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "thread_id": self.thread_id or f"t-{self.message_id}",
            "from": self.sender,
            "to": list(self.to),
            "cc": list(self.cc),
            "subject": self.subject,
            "body": self.body,
            "headers": dict(self.headers),
        }


class FakeMailReader:
    """The quarantined reader (PRD 16.3 item 3): read-only `get_message(user_id, message_id)`. It has no other
    method, so it offers no side effect. Records every call."""

    def __init__(self) -> None:
        self._mail: dict[tuple[str, str], Mail] = {}
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def add(self, user_id: str, mail: Mail) -> Mail:
        with self._lock:
            self._mail[(user_id, mail.message_id)] = mail
        return mail

    def get_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        with self._lock:
            self.calls.append((user_id, message_id))
            mail = self._mail.get((user_id, message_id))
        if mail is None:
            raise LookupError("no such message")
        return mail.as_message()


# ---------------------------------------------------------------------------
# Model and safety provider


class ScriptedModel(ModelProvider):
    """The "autopilot" role model (PRD 6.4), scripted: each mail carries a unique token in its subject and
    body; the answer registered for the token found in the prompt is returned. Records every request. A
    request whose prompt carries two registered tokens means one mail's text leaked into another's call."""

    def __init__(self, default: str | None = None) -> None:
        self.default = default if default is not None else answer("fyi", "low")
        self.scripts: dict[str, Callable[[], GenerateResponse] | str | None] = {}
        self.requests: list[GenerateRequest] = []
        self.raise_with: Exception | None = None
        self._lock = threading.Lock()

    def script(self, token: str, text: str | None) -> None:
        self.scripts[token] = text

    def script_response(self, token: str, make: Callable[[], GenerateResponse]) -> None:
        self.scripts[token] = make

    def calls_for(self, token: str) -> list[GenerateRequest]:
        return [r for r in self.requests if token in r.prompt or token in (r.system or "")]

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        with self._lock:
            self.requests.append(request.model_copy(deep=True))
        if self.raise_with is not None:
            raise self.raise_with
        hits = [t for t in self.scripts if t in request.prompt]
        if len(hits) > 1:
            raise AssertionError("FR-CHN-09 test: one model call carried the text of more than one mail")
        if not hits:
            return GenerateResponse(text=self.default, profile_id="fake-autopilot")
        scripted = self.scripts[hits[0]]
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
    """The deterministic fake safety provider (flags the fixed prompt-injection markers), recording every
    screened text. `raise_with` makes every check raise, to test fail-closed handling."""

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
# Stores and event writer


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value))  # raises TypeError on anything a document store could not hold


class MemoryPreferenceStore:
    """The P7 preferences layer (PRD 13.1: "triage corrections"), per user, JSON-able documents."""

    def __init__(self) -> None:
        self._docs: dict[str, dict] = {}
        self.writes = 0
        self._lock = threading.Lock()

    def get(self, user_id: str) -> dict | None:
        with self._lock:
            doc = self._docs.get(user_id)
            return copy.deepcopy(doc) if doc is not None else None

    def put(self, user_id: str, value: dict) -> None:
        with self._lock:
            self._docs[user_id] = _jsonable(value)
            self.writes += 1

    def dump(self) -> str:
        with self._lock:
            return json.dumps(self._docs, sort_keys=True)


class MemoryTriageStore:
    """Triage results per (user, message): get, atomic create-if-absent, put, and a per-user listing."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str, message_id: str) -> dict | None:
        with self._lock:
            doc = self._docs.get((user_id, message_id))
            return copy.deepcopy(doc) if doc is not None else None

    def create(self, user_id: str, message_id: str, value: dict) -> bool:
        with self._lock:
            if (user_id, message_id) in self._docs:
                return False
            self._docs[(user_id, message_id)] = _jsonable(value)
            return True

    def put(self, user_id: str, message_id: str, value: dict) -> None:
        with self._lock:
            self._docs[(user_id, message_id)] = _jsonable(value)

    def items(self, user_id: str) -> list[tuple[str, dict]]:
        with self._lock:
            return [(m, copy.deepcopy(v)) for (u, m), v in sorted(self._docs.items()) if u == user_id]

    def dump(self) -> str:
        with self._lock:
            return json.dumps({f"{u}/{m}": v for (u, m), v in self._docs.items()}, sort_keys=True)


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

    def mail_triaged(self) -> list[dict[str, Any]]:
        return [
            p for p in self.of_type("building.completed") if (p.get("data") or {}).get("unit_type") == "mail_triaged"
        ]


@dataclass
class Rig:
    """One user's triage wiring: the real `Triage` over the fakes. `new_triage()` builds another instance over
    the same stores (a restart, or a second Cloud Run instance)."""

    clock: FakeClock
    reader: FakeMailReader
    model: ScriptedModel
    safety: SpySafety
    preferences: MemoryPreferenceStore
    results: MemoryTriageStore
    events: EventLog
    svc: Any = None

    def new_triage(self) -> Any:
        return triage_module().Triage(
            reader=self.reader,
            model=self.model,
            safety=self.safety,
            preferences=self.preferences,
            results=self.results,
            clock=self.clock,
            emit=self.events,
        )

    def mail(
        self,
        *,
        sender: str = "David Miller <david.miller@harriercharters.example>",
        subject: str = "Engine inspection next Tuesday",
        body: str = "Could you send an estimate and confirm Tuesday 10 AM?",
        reply: str | None = None,
        user_id: str = USER,
        message_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[Mail, str]:
        """Adds a mail for `user_id` whose prompt token maps to `reply` (a model answer text); returns the mail
        and its token."""
        token = fresh_token()
        mail = Mail(
            message_id=message_id or "m-" + secrets.token_hex(6),
            sender=sender,
            subject=f"{subject} [{token}]",
            body=f"{body}\n\n{token}",
            headers=dict(headers or {}),
        )
        self.reader.add(user_id, mail)
        self.model.script(token, reply if reply is not None else answer("needs_reply", "normal"))
        return mail, token


def make_rig() -> Rig:
    clock = FakeClock()
    rig = Rig(
        clock=clock,
        reader=FakeMailReader(),
        model=ScriptedModel(),
        safety=SpySafety(),
        preferences=MemoryPreferenceStore(),
        results=MemoryTriageStore(),
        events=EventLog(),
    )
    rig.svc = rig.new_triage()
    return rig


# ---------------------------------------------------------------------------
# The E-MAIL triage cases (PRD 19.2: "Triage agreement with ground truth", threshold >= 85%)


@dataclass(frozen=True)
class TriageCase:
    id: str
    sender: str
    subject: str
    body: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    category: str
    priority: str


def load_triage_cases() -> list[TriageCase]:
    cases = []
    for path in sorted(E_MAIL_DIR.glob("E-MAIL-*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        truth = raw.get("ground_truth") or {}
        if "category" not in truth:
            continue  # drafting cases (FR-CHN-10, -12) carry no triage label
        first = raw["inputs"]["thread"]["messages"][0]
        cases.append(
            TriageCase(
                id=raw["id"],
                sender=first["from"],
                subject=first["subject"],
                body=first["body"],
                to=tuple(first.get("to") or ()),
                cc=tuple(first.get("cc") or ()),
                category=truth["category"],
                priority=truth["priority"],
            )
        )
    return cases


def case_mail(rig: Rig, case: TriageCase, *, reply: str, suffix: str = "", user_id: str = USER) -> tuple[Mail, str]:
    """Adds an E-MAIL case as a mail for `user_id`, with the scripted model answer `reply`."""
    token = fresh_token()
    mail = Mail(
        message_id=f"{case.id.lower()}{suffix}-{secrets.token_hex(3)}",
        sender=case.sender,
        subject=f"{case.subject} [{token}]",
        body=f"{case.body}\n\n{token}",
        to=list(case.to),
        cc=list(case.cc),
    )
    rig.reader.add(user_id, mail)
    rig.model.script(token, reply)
    return mail, token


def bare_address(sender: str) -> str:
    match = re.search(r"<([^>]+)>", sender)
    return (match.group(1) if match else sender).strip().lower()


def wrong_category(category: str) -> str:
    """A deterministic wrong label: the next category in PRD order."""
    return CATEGORIES[(CATEGORIES.index(category) + 1) % len(CATEGORIES)]
