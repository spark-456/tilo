"""Test doubles and builders for FR-CHN-03 (WhatsApp number binding) and FR-CHN-05 (interactive
WhatsApp cards that sync to every channel). The API they drive is pinned in API_FR_CHN_03_05.md.

Package-unique module name on purpose (same reason as `_channels_lib.py`): this directory has no
__init__.py and other test directories have their own conftest.py. Nothing here is production logic:
every class is a fake for an injected dependency (binding store, number cipher, card sender, the
tilo-api cards client, PIN verifier, raw archive, event writer) or a builder of a Meta webhook message.

No real numbers, tokens or secrets. Phone numbers are fictional North American 555-01xx numbers,
written as WhatsApp wa_ids (digits, no plus). Keys are assembled at runtime with `secrets`.
"""

from __future__ import annotations

import copy
import datetime as _dt
import functools
import itertools
import json
import pathlib
import secrets
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import yaml
from _channels_lib import T0, FakeClock
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
CONTRACTS = REPO_ROOT / "contracts"
CARD_FIXTURES = CONTRACTS / "fixtures" / "card" / "valid"

WEB_URL = "https://app.tilo.test"

# Users and their fictional numbers (wa_id form, as Meta sends `from`), plus the typed E.164 forms.
RIYA = "u_riya"
SAM = "u_sam"
KAI = "u_kai"
NUM_RIYA = "12025550101"
NUM_SAM = "12025550102"
NUM_KAI = "12025550103"
NUM_STRANGER = "12025550199"
TYPED_RIYA = "+1 202-555-0101"

CODE_TTL_S = 600  # BQ-89 default, pinned in API_FR_CHN_03_05.md
MAX_CODE_ATTEMPTS = 5
THIRTY_DAYS_S = 30 * 86400  # PRD 11.1 "Binding is re-confirmed every 30 days"
PIN_WINDOW_S = 300

# Fresh card ids (contract fixtures reuse ids across kinds); valid ULIDs.
GATE_T3 = "01JC0000000000000000000001"  # gate_send_reply: T3, irreversible send_email, approve/edit/hold
GATE_T1 = "01JC0000000000000000000002"  # gate_save_file_reversible: T1 save_file, approve/hold
QUESTION = "01JC0000000000000000000003"  # needs_you_compare_basis: per_kwh / per_pack
MEETING = "01JC0000000000000000000004"  # meeting_budget_split: research / even, web + whatsapp
CONSENT = "01JC0000000000000000000005"  # consent_drive_folder: web and mobile web only
WORLD = "w_chn05"
RUN = "r_chn05_1"


def fake_key() -> bytes:
    """A fresh 32-byte key for the lookup hash, assembled at runtime."""
    return secrets.token_bytes(32)


def rfc3339(unix_s: float) -> str:
    t = _dt.datetime.fromtimestamp(unix_s, _dt.UTC)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


_FIXTURE_FOR = {
    GATE_T3: "gate_send_reply",
    GATE_T1: "gate_save_file_reversible",
    QUESTION: "needs_you_compare_basis",
    MEETING: "meeting_budget_split",
    CONSENT: "consent_drive_folder",
}


def make_card(card_id: str, *, created_at: float = float(T0), timeout: int = 3600) -> dict[str, Any]:
    """A contract fixture card with its own id, world, run, creation time and timeout."""
    card = json.loads((CARD_FIXTURES / f"{_FIXTURE_FOR[card_id]}.json").read_text(encoding="utf-8"))
    card.update(id=card_id, world_id=WORLD, run_id=RUN, created_at=rfc3339(created_at), timeout=timeout)
    if card["kind"] != "consent":  # CH-RM PR 1 took whatsapp out of the fixtures (SD-01); PR 2 deletes these tests
        rest = [c for c in card["answer_channels"] if c != "email"]
        card["answer_channels"] = [*rest, "whatsapp", *(["email"] if "email" in card["answer_channels"] else [])]
    return card


# ---------------------------------------------------------------------------
# Contract helpers


@functools.cache
def _registry() -> Registry:
    resources = []
    for path in sorted(CONTRACTS.glob("**/*.schema.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data, default_specification=DRAFT202012)))
    return Registry().with_resources(resources)


@functools.cache
def registered_types() -> frozenset[str]:
    reg = yaml.safe_load((CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8"))
    types = reg.get("types", reg) if isinstance(reg, dict) else {}
    return frozenset(k for k in types if isinstance(k, str) and "." in k)


def data_errors(event_type: str, data: Any) -> list[str]:
    """Schema errors of an event part's `data` against contracts/events/data/<type>.schema.json."""
    schema = json.loads((CONTRACTS / "events" / "data" / f"{event_type}.schema.json").read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema, registry=_registry())
    return [e.message for e in validator.iter_errors(data)]


def card_errors(card: Any) -> list[str]:
    schema = json.loads((CONTRACTS / "card.schema.json").read_text(encoding="utf-8"))
    return [e.message for e in Draft202012Validator(schema, registry=_registry()).iter_errors(card)]


# ---------------------------------------------------------------------------
# FR-CHN-03 fakes


class FakeBindingStore:
    """The injected binding store (Firestore in production): get / put / delete and an atomic
    create-if-absent. Values are deep-copied in and out so the service cannot keep live references."""

    def __init__(self) -> None:
        self._data: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> dict | None:
        with self._lock:
            value = self._data.get(key)
            return copy.deepcopy(value) if value is not None else None

    def put(self, key: str, value: dict) -> None:
        with self._lock:
            self._data[key] = copy.deepcopy(value)

    def create(self, key: str, value: dict) -> bool:
        with self._lock:
            if key in self._data:
                return False
            self._data[key] = copy.deepcopy(value)
            return True

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def dump(self) -> str:
        """Every key and value as one JSON string, for plaintext checks."""
        with self._lock:
            return json.dumps(self._data, sort_keys=True, default=str)


class FakeCipher:
    """The injected number cipher (KMS in production). Ciphertexts are opaque counters, so they never
    contain a digit run of the plaintext; every call is recorded."""

    def __init__(self) -> None:
        self._plain: dict[str, str] = {}
        self._counter = itertools.count(1)
        self.encrypted: list[str] = []
        self.decrypted: list[str] = []

    def encrypt(self, plaintext: str) -> str:
        token = f"ct_{next(self._counter):x}_" + secrets.token_hex(4).replace("0", "g")
        self._plain[token] = plaintext
        self.encrypted.append(plaintext)
        return token

    def decrypt(self, ciphertext: str) -> str:
        self.decrypted.append(ciphertext)
        return self._plain[ciphertext]

    def ciphertexts(self) -> list[str]:
        return list(self._plain)


class RaisingSender:
    def send_text(self, to: str, body: str) -> None:
        raise RuntimeError("WhatsApp send unavailable")


# ---------------------------------------------------------------------------
# FR-CHN-05 fakes


class FakeCardSender:
    """Records WhatsApp sends; never touches the network. `send_buttons` returns a fresh wamid. Each call
    advances the injected clock by `latency_s` (a Graph API round trip)."""

    def __init__(self, clock: FakeClock, *, latency_s: float = 0.2) -> None:
        self._clock = clock
        self._latency_s = latency_s
        self._ids = itertools.count(1)
        self.texts: list[tuple[str, str, float]] = []  # (to, body, at)
        self.cards: list[dict[str, Any]] = []  # {to, body, buttons, message_id, at}

    def send_text(self, to: str, body: str) -> str:
        self._clock.advance(self._latency_s)
        self.texts.append((to, body, self._clock()))
        return f"wamid.OUTTXT{next(self._ids):06d}"

    def send_buttons(self, to: str, body: str, buttons: Sequence[tuple[str, str]]) -> str:
        self._clock.advance(self._latency_s)
        message_id = f"wamid.OUTCARD{next(self._ids):06d}"
        self.cards.append(
            {
                "to": to,
                "body": body,
                "buttons": [tuple(b) for b in buttons],
                "message_id": message_id,
                "at": self._clock(),
            }
        )
        return message_id

    def texts_to(self, number: str) -> list[str]:
        return [b for (to, b, _) in self.texts if to == number]

    def everything(self) -> str:
        return json.dumps({"texts": self.texts, "cards": self.cards}, default=str)


@dataclass(frozen=True)
class ApiAnswer:
    outcome: str  # "answered" | "rejected"
    reason: str | None = None


class FakeCardsApi:
    """The tilo-api cards client. Models the contract rules the API applies: first answer wins
    (compare-and-set), the option must be on the card, and approve on a T3 gate from WhatsApp without
    pin_verified is rejected. Every call is recorded with the clock time it reached the API."""

    def __init__(self, clock: FakeClock, cards: Mapping[str, Mapping[str, Any]], *, latency_s: float = 0.3) -> None:
        self._clock = clock
        self._cards = cards
        self._latency_s = latency_s
        self._lock = threading.Lock()
        self.closed: dict[str, tuple[str, str]] = {}  # card_id -> (option, channel)
        self.calls: list[dict[str, Any]] = []
        self.fail_next: Exception | None = None
        self.reject_with: str | None = None

    def close_elsewhere(self, card_id: str, option: str, channel: str = "web") -> None:
        with self._lock:
            self.closed[card_id] = (option, channel)

    def answer(
        self, world_id: str, card_id: str, *, option: str, user_id: str, channel: str, pin_verified: bool
    ) -> ApiAnswer:
        self._clock.advance(self._latency_s)
        with self._lock:
            call = dict(
                world_id=world_id,
                card_id=card_id,
                option=option,
                user_id=user_id,
                channel=channel,
                pin_verified=pin_verified,
                at=self._clock(),
            )
            self.calls.append(call)
            if self.fail_next is not None:
                exc, self.fail_next = self.fail_next, None
                raise exc
            if self.reject_with is not None:
                return ApiAnswer("rejected", self.reject_with)
            card = self._cards.get(card_id)
            if card is None:
                return ApiAnswer("rejected", "card_not_found")
            if card_id in self.closed:
                return ApiAnswer("rejected", "already_resolved")
            if option not in {o["id"] for o in card["options"]}:
                return ApiAnswer("rejected", "invalid_option")
            gate = card.get("gate")
            # approval.resolved / OB-01: a T3 gate answered on WhatsApp *opens* only with pin_verified;
            # only approve opens a gate (CR-07), so Hold and Edit first need no PIN.
            if (
                gate
                and gate["risk_tier"] == "T3"
                and channel == "whatsapp"
                and option == "approve"
                and not pin_verified
            ):
                return ApiAnswer("rejected", "pin_required")
            self.closed[card_id] = (option, channel)
            call["accepted"] = True
            return ApiAnswer("answered")

    def accepted(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if c.get("accepted")]


class FakePins:
    """The PIN verifier (SEC-06). Holds each user's PIN, assembled at runtime; records every check."""

    def __init__(self, pins: Mapping[str, str]) -> None:
        self._pins = dict(pins)
        self.checks: list[tuple[str, str, bool]] = []

    def verify(self, user_id: str, pin: str) -> bool:
        ok = self._pins.get(user_id) == pin
        self.checks.append((user_id, pin, ok))
        return ok


def fake_pin() -> str:
    """A 6-digit PIN assembled at runtime (no PIN literal in the repo)."""
    return "".join(secrets.choice("123456789") for _ in range(6))


class FakeArchive:
    """The redacted raw archive: `record(run_id, kind, payload) -> "<run_id>/<seq>"`."""

    def __init__(self) -> None:
        self.records: list[tuple[str, str, Any]] = []

    def record(self, run_id: str, kind: str, payload: Mapping[str, Any]) -> str:
        self.records.append((run_id, kind, copy.deepcopy(dict(payload))))
        return f"{run_id}/{len(self.records)}"

    def dump(self) -> str:
        return json.dumps(self.records, default=str)


class FakeEventWriter:
    """The event writer tilo-channels hands unstamped event parts to (the harness stamps id/seq/ts)."""

    def __init__(self) -> None:
        self.parts: list[dict[str, Any]] = []

    def write(self, part: dict) -> None:
        self.parts.append(copy.deepcopy(part))

    def of_type(self, event_type: str) -> list[dict[str, Any]]:
        return [p for p in self.parts if p.get("type") == event_type]

    def dump(self) -> str:
        return json.dumps(self.parts, default=str)


class DictCardBindings:
    """Number <-> user lookup for card tests that do not need the full binding flow."""

    def __init__(self, bound: Mapping[str, str] | None = None) -> None:
        self.by_number = dict(bound if bound is not None else {NUM_RIYA: RIYA, NUM_SAM: SAM})

    def user_for(self, number: str) -> str | None:
        return self.by_number.get(number)

    def number_for(self, user_id: str) -> str | None:
        for number, user in self.by_number.items():
            if user == user_id:
                return number
        return None


# ---------------------------------------------------------------------------
# A wired WhatsAppCards with fakes (the module under test is imported when a rig is built, so the
# FR-CHN-03 files that import this helper do not depend on tilo_channels.cards).


class CardRig:
    """`tilo_channels.cards.WhatsAppCards` wired to fakes. Riya and Sam are bound; Kai is not."""

    def __init__(self, *, card_ids: Sequence[str] = (GATE_T3, GATE_T1, QUESTION, MEETING, CONSENT)) -> None:
        import importlib

        cards_mod = importlib.import_module("tilo_channels.cards")
        whatsapp = importlib.import_module("tilo_channels.whatsapp")
        self._inbound = whatsapp.InboundMessage
        self.clock = FakeClock()
        self.cards = {cid: make_card(cid, created_at=self.clock()) for cid in card_ids}
        self.bindings = DictCardBindings()
        self.sender = FakeCardSender(self.clock)
        self.api = FakeCardsApi(self.clock, self.cards)
        self.events = FakeEventWriter()
        self.archive = FakeArchive()
        self.pin = fake_pin()
        self.sam_pin = fake_pin()
        while self.sam_pin == self.pin:
            self.sam_pin = fake_pin()
        self.pins = FakePins({RIYA: self.pin, SAM: self.sam_pin})
        self.svc = cards_mod.WhatsAppCards(
            bindings=self.bindings,
            api=self.api,
            sender=self.sender,
            events=self.events,
            archive=self.archive,
            pins=self.pins,
            clock=self.clock,
            web_url=WEB_URL,
        )
        self._n = 0

    def send(self, card_id: str, user: str = RIYA) -> dict[str, Any]:
        result = self.svc.send_card(self.cards[card_id], user_id=user)
        assert result.outcome == "sent", result
        sent = self.sender.cards[-1]
        assert result.message_id == sent["message_id"]
        return sent

    def message(self, sender: str, *, kind: str = "text", text: str | None = None, **extra: Any) -> Any:
        self._n += 1
        return self._inbound(f"wamid.IN{self._n:06d}", sender, int(self.clock()), kind, text, **extra)

    def tap(self, sent: Mapping[str, Any], option: str, *, sender: str = NUM_RIYA, card_id: str | None = None) -> Any:
        card = self.cards[card_id] if card_id else self.card_of(sent)
        index = [o["id"] for o in card["options"]].index(option)
        button_id, _title = sent["buttons"][index]
        return self.svc.handle(
            self.message(sender, kind="interactive", button_id=button_id, context_id=sent["message_id"])
        )

    def text(self, sender: str, body: str, context_id: str | None = None) -> Any:
        return self.svc.handle(self.message(sender, text=body, context_id=context_id))

    def card_of(self, sent: Mapping[str, Any]) -> Mapping[str, Any]:
        titles = [t for _, t in sent["buttons"]]
        for card in self.cards.values():
            if [o["label"] for o in card["options"]] == titles and card["what_happened"] in sent["body"]:
                return card
        raise AssertionError("sent message matches no card")


# ---------------------------------------------------------------------------
# Meta webhook message builders (shapes of the WhatsApp Cloud API `messages` webhook)


def button_reply(message_id: str, sender: str, ts: int, button_id: str, title: str, context_id: str | None) -> dict:
    """A tap on an interactive reply button."""
    msg: dict[str, Any] = {
        "from": sender,
        "id": message_id,
        "timestamp": str(ts),
        "type": "interactive",
        "interactive": {"type": "button_reply", "button_reply": {"id": button_id, "title": title}},
    }
    if context_id is not None:
        msg["context"] = {"from": "12025550100", "id": context_id}
    return msg


def template_button(message_id: str, sender: str, ts: int, payload: str, text: str, context_id: str) -> dict:
    """A tap on a template quick-reply button (the first message outside the 24-hour window, PRD 11.1)."""
    return {
        "from": sender,
        "id": message_id,
        "timestamp": str(ts),
        "type": "button",
        "button": {"payload": payload, "text": text},
        "context": {"from": "12025550100", "id": context_id},
    }


def text_reply(message_id: str, sender: str, ts: int, body: str, context_id: str | None = None) -> dict:
    msg: dict[str, Any] = {
        "from": sender,
        "id": message_id,
        "timestamp": str(ts),
        "type": "text",
        "text": {"body": body},
    }
    if context_id is not None:
        msg["context"] = {"from": "12025550100", "id": context_id}
    return msg
