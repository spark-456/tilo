"""tilo_channels.drafting — Email Autopilot drafting (FR-CHN-10; PRD 11.4, 11.6, 13.1, 16.3; BQ-139 to BQ-151).

A reply is drafted from the user's instruction (trusted) plus the thread (untrusted, raw-capped per field and in total
before any NFKC or regex). The safety provider screens exactly the prompt the "autopilot" model gets (thread only as
delimited data, no tools) plus the raw rest past the caps, up to SCREEN_CAP (more is flagged, not sent). Recipients,
subject and reply headers come from the thread and the user, never from the model. `find_invented` (drafting_check)
holds the body and the model's questions to PRD 11.4 Content. Drafting never sends, saves a Gmail draft or writes the
outbox, and never logs, emits or stores mail text beyond the draft itself.
"""

from __future__ import annotations

import json
import logging
import secrets
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt

from tilo_channels.drafting_check import CHECK_CAP, Checker, Finding, find_invented

__all__ = ["Checker", "Drafter", "Finding", "find_invented"]

MODES = ("reply", "reply_all")  # forward and new email add recipients: FR-CHN-12's T3 path (BQ-145)
PRESETS = ("confirm", "decline", "follow_up", "reschedule", "formal_letter")
STYLE_KEYS = ("greeting", "sign_off", "formality", "language", "signature")

ROLE = "autopilot"
MAX_ATTEMPTS = 2  # one draft plus at most one regeneration (BQ-141)
MAX_OUTPUT_TOKENS = 1_200
# Raw caps, applied before any NFKC, fold or regex: NFKC is quadratic on expanding characters (U+FDFA), so untrusted
# text is always cut first (EFF-03). THREAD_CAP is shared newest message first. An over-long address or reply header
# is dropped, never truncated.
FIELD_CAPS = {"from": 500, "to": 2_000, "cc": 2_000, "subject": 500, "body": 8_000}
ADDRESS_CAP, MAX_ADDRESSES, HEADER_CAP, MAX_MESSAGES = 500, 50, 4_000, 50
THREAD_CAP, SCREEN_CAP, MAX_RECIPIENTS = 30_000, 100_000, 20
MAX_INSTRUCTION, MAX_STYLE_VALUE, MAX_QUESTIONS, QUESTION_CAP = 4_000, 2_000, 5, 300
EMIT_LEASE = 60.0  # seconds before an unconfirmed artifact.created is emitted again

_LOG = logging.getLogger(__name__)
_ANGLES = {ord("<"): "‹", ord(">"): "›"}


class ThreadReader(Protocol):  # the quarantined reader (PRD 16.3 item 3): read-only
    def get_thread(self, user_id: str, thread_id: str) -> dict: ...


class DraftStore(Protocol):  # JSON-able results keyed (user_id, instruction_id)
    def get(self, user_id: str, instruction_id: str) -> dict | None: ...
    def create(self, user_id: str, instruction_id: str, value: dict) -> bool: ...  # atomic set-if-absent


class ReplyTargetMoved(Exception):
    """The message a reply would answer is not the one the caller named (`Drafter.draft(answers=...)`)."""


@dataclass(frozen=True)
class Draft:
    artifact_id: str
    version: int
    thread_id: str | None
    mode: str
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    in_reply_to: str
    references: str
    body: str
    attachments: tuple[str, ...]
    safety_flag: bool


@dataclass(frozen=True)
class DraftResult:
    instruction_id: str
    status: str  # "ready" | "needs_you" | "failed"
    draft: Draft | None
    findings: tuple[Finding, ...]
    questions: tuple[str, ...]
    flagged: bool


def _address(value: str) -> str | None:
    """A bare, lower-case ASCII address; None for anything with a space, control or non-ASCII character, or an
    empty local part or domain."""
    value = value.strip()
    local, _, domain = value.partition("@")
    ok = value.isascii() and value.isprintable() and " " not in value and value.count("@") == 1 and local and domain
    return value.lower() if ok else None


def _base(address: str) -> str:
    """The mailbox an address delivers to: a plus tag (ops+x@...) is the same mailbox."""
    local, _, domain = address.partition("@")
    return f"{local.split('+', 1)[0]}@{domain}"


def _pairs(value: Any) -> list[tuple[str, str]]:
    """(display name, raw address) pairs of an untrusted header, bounded as `_addresses` says."""
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    try:
        return getaddresses([v for v in raw[:MAX_ADDRESSES] if isinstance(v, str) and len(v) <= ADDRESS_CAP])
    except (RecursionError, ValueError):
        return []


def _addresses(value: Any) -> list[str]:
    """Bare addresses of an untrusted header: at most MAX_ADDRESSES entries, an entry over ADDRESS_CAP is dropped,
    and a header the parser chokes on (nested comments) has none."""
    return [a for _, addr in _pairs(value) if (a := _address(addr))]


def _raw(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(v for v in value if isinstance(v, str))
    return value if isinstance(value, str) else ""


def _header(value: Any, cap: int) -> str:
    """A header value cut to `cap` raw characters, then NFKC, with control and line-separator characters folded to
    spaces: it cannot forge another line."""
    text = unicodedata.normalize("NFKC", (value if isinstance(value, str) else "")[:cap])[:cap]
    return " ".join("".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text).split())


def _render(value: str, field: str, cap: int) -> str:
    """Untrusted text exactly as the safety screen and the model see it: cut to `cap` raw characters, NFKC (cut to
    `cap` again), format characters dropped, controls folded, then `<` and `>` as look-alikes so no mail can open or
    close the THREAD block."""
    if field != "body":
        return _header(value, cap).translate(_ANGLES)
    text = unicodedata.normalize("NFKC", value[:cap])[:cap]
    kinds = [(c, unicodedata.category(c)) for c in text]
    text = "".join(
        c if c in "\n\t" or k not in ("Cc", "Cf", "Zl", "Zp") else "" if k == "Cf" else " " for c, k in kinds
    )
    return text.translate(_ANGLES)


def _reply_header(value: Any) -> str:
    return _header(value, HEADER_CAP) if isinstance(value, str) and len(value) <= HEADER_CAP else ""


def headers_of(message: Mapping[str, Any]) -> dict[str, Any]:
    """The message's headers by lower-cased name (the Gmail adapter lower-cases them; a fake may not). A name that
    occurs twice differing only by case is ambiguous: neither is kept, so it reads as absent and fails closed."""
    raw = message.get("headers") if isinstance(message, Mapping) else None
    if not isinstance(raw, dict):
        return {}
    names = [str(k).lower() for k in raw]
    seen = Counter(names)
    return {name: v for name, v in zip(names, raw.values(), strict=True) if seen[name] == 1}


def message_id_of(message: Mapping[str, Any]) -> str:
    """The Message-ID header of a message as the draft's `in_reply_to` carries it ("" when it has none)."""
    return _reply_header(headers_of(message).get("message-id"))


def gmail_id_of(message: Mapping[str, Any]) -> str | None:
    """The reader's id of a message (`message_id`: the Gmail message id, which no sender writes), None when it is
    not a non-empty text. Never the Message-ID header, which a later message can copy."""
    value = message.get("message_id")
    return value if isinstance(value, str) and value else None


def _replied(messages: list[dict[str, Any]], own: str) -> dict[str, Any] | None:
    """The message a reply answers: the newest one not from the person's own mailbox."""
    return next((m for m in reversed(messages) if [_base(a) for a in _addresses(m.get("from"))[:1]] != [own]), None)


def _envelope(message: Mapping[str, Any], own: str, mode: str) -> dict[str, Any]:
    """Recipients (at most MAX_RECIPIENTS) and reply headers, from the message replied to only (BQ-144, BQ-146)."""
    to = _addresses(message.get("from"))[:1]
    cc: list[str] = []
    if mode == "reply_all":
        for field, out in (("to", to), ("cc", cc)):
            out += [a for a in dict.fromkeys(_addresses(message.get(field))) if _base(a) != own and a not in to + cc]
    to, cc = to[:MAX_RECIPIENTS], cc[: max(0, MAX_RECIPIENTS - len(to))]
    headers = headers_of(message)
    message_id = message_id_of(message)
    references = _reply_header(headers.get("references")).split()
    references += [message_id] if message_id and message_id not in references else []
    subject = _header(message.get("subject"), FIELD_CAPS["subject"])
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    envelope = {"to": to, "cc": cc, "bcc": [], "attachments": [], "subject": subject, "in_reply_to": message_id}
    return envelope | {"references": " ".join(references)}


def _parse(text: str | None, cap: int = CHECK_CAP) -> tuple[str, list[str]] | None:
    if text is not None and len(text) > cap:  # also bounds the body and questions find_invented reads
        return None
    try:
        answer = json.loads(text or "")
    except (RecursionError, ValueError):  # deeply nested JSON is an unusable answer
        return None
    body, questions = (answer.get("body"), answer.get("questions") or []) if isinstance(answer, dict) else (None, [])
    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
        return None
    if questions := [q.strip() for q in questions if q.strip()]:  # at most 5 kept; one over 300 characters dropped
        kept = [q for q in questions if len(q) <= QUESTION_CAP][:MAX_QUESTIONS]
        return ("", kept) if kept else None
    return (body.strip(), []) if isinstance(body, str) and body.strip() else None


def _result(instruction_id: str, doc: Mapping[str, Any]) -> DraftResult:
    fields: dict[str, Any] = {k: tuple(v) if isinstance(v, list) else v for k, v in (doc.get("draft") or {}).items()}
    findings = tuple(Finding(**f) for f in doc["findings"])
    draft = Draft(**fields) if fields else None
    return DraftResult(instruction_id, doc["status"], draft, findings, tuple(doc["questions"]), doc["flagged"])


def _thread(raws: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[str]]:
    """Each message's fields rendered within THREAD_CAP (newest message first), and the raw rest past every cap."""
    budget, fields, rests = THREAD_CAP, list[dict[str, str]](), list[str]()
    for raw in reversed(raws):
        caps = {}
        for k, text in raw.items():
            caps[k] = min(FIELD_CAPS[k], budget)
            budget -= min(len(text), caps[k])
        fields.insert(0, {k: _render(text, k, caps[k]) for k, text in raw.items()})
        rests += [text[caps[k] :] for k, text in raw.items() if len(text) > caps[k]]
    return fields, rests


class Drafter:
    def __init__(
        self,
        *,
        reader: ThreadReader,
        model: ModelProvider,
        safety: SafetyProvider,
        drafts: DraftStore,
        clock: Callable[[], float],
        emit: Callable[[dict], None] = lambda part: None,
    ) -> None:
        self._reader, self._model, self._safety = reader, model, safety
        self._drafts, self._clock, self._emit = drafts, clock, emit
        self._system = load_prompt(ROLE, "draft_system.md")

    def draft(
        self,
        user_id: str,
        *,
        instruction_id: str,
        thread_id: str | None,
        instruction: str,
        mailbox: str,
        mode: str = "reply",
        preset: str | None = None,
        style: Mapping[str, Any] | None = None,
        answers: str | None = None,
    ) -> DraftResult:
        """`answers` (optional) is the reader id of the message the draft must answer (FR-PA-07). If the thread no
        longer gives a reply to that message, `ReplyTargetMoved` is raised before anything is stored or emitted and
        before the model is called; a draft already stored for `instruction_id` is returned as it is."""
        if not isinstance(thread_id, str) or not thread_id:  # a thread-less (new email) context has nothing to reply to
            raise ValueError("a reply is drafted from a thread")
        if mode not in MODES or (preset is not None and preset not in PRESETS) or "#" in instruction_id:
            raise ValueError("unknown drafting mode, preset or instruction id")
        if len(instruction) > MAX_INSTRUCTION:
            raise ValueError("instruction too long")
        doc = self._drafts.get(user_id, instruction_id)
        if doc is None:
            request = {"thread_id": thread_id, "instruction": instruction, "mode": mode, "preset": preset or "none"}
            doc = self._make(user_id, mailbox, style or {}, request, answers)
            if self._drafts.create(user_id, instruction_id, doc):  # BQ-150: keyed by the instruction
                _LOG.info("drafting %s: %s", instruction_id, doc["status"])
            else:  # another call or instance stored it first: theirs is the result
                doc = self._drafts.get(user_id, instruction_id) or doc
        self._announce(user_id, instruction_id, doc)
        return _result(instruction_id, doc)

    def reply_target(self, user_id: str, thread_id: str, mailbox: str) -> str | None:
        """The reader's id (the Gmail message id) of the message a reply in this thread would answer, read only:
        nothing is screened, drafted, stored or emitted. Never the Message-ID header, which a later message can copy.
        None when there is no one to reply to or the message has no id."""
        replied = self._target(self._reader.get_thread(user_id, thread_id), mailbox)
        return gmail_id_of(replied) if replied is not None else None

    @staticmethod
    def _target(thread: Mapping[str, Any], mailbox: str) -> dict[str, Any] | None:
        listed = thread.get("messages")
        messages = [m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if isinstance(m, dict)]
        replied = _replied(messages, _base(_address(mailbox) or mailbox.lower()))
        return replied if replied is not None and _addresses(replied.get("from")) else None

    def stored(self, user_id: str, instruction_id: str) -> DraftResult | None:
        """The result stored for the instruction, read only (BQ-183); None when nothing is stored."""
        doc = None if "#" in instruction_id else self._drafts.get(user_id, instruction_id)
        return _result(instruction_id, doc) if doc is not None else None

    def _announce(self, user_id: str, instruction_id: str, doc: Mapping[str, Any]) -> None:
        """One artifact.created per stored ready draft. An `#emitted` marker confirms it; while it is missing, one
        caller per EMIT_LEASE window (an atomic claim) emits, so an emit that failed after the store is not lost."""
        if not doc.get("draft") or self._drafts.get(user_id, f"{instruction_id}#emitted") is not None:
            return
        window = int(max(0.0, self._clock() - doc["drafted_at"]) // EMIT_LEASE)
        if self._drafts.create(user_id, f"{instruction_id}#emit{window}", {}):
            artifact = {"artifact_id": doc["draft"]["artifact_id"], "version": 1}
            self._emit({"type": "artifact.created", "data": {"artifact": artifact}})
            self._drafts.create(user_id, f"{instruction_id}#emitted", {})

    def _make(
        self, user_id: str, mailbox: str, style: Mapping[str, Any], ask: dict[str, str], answers: str | None = None
    ) -> dict[str, Any]:
        listed = self._reader.get_thread(user_id, ask["thread_id"]).get("messages")
        messages = [m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if isinstance(m, dict)]
        fields, rests = _thread([{k: _raw(m.get(k)) for k in FIELD_CAPS} for m in messages])
        thread = "\n\n".join(
            "[message {n}]\nFrom: {from}\nTo: {to}\nCc: {cc}\nSubject: {subject}\n\n{body}".format(n=n, **f)
            for n, f in enumerate(fields, 1)
        )
        settings = {
            k: v for k, v in style.items() if k in STYLE_KEYS and isinstance(v, str) and len(v) <= MAX_STYLE_VALUE
        }
        variables = {**ask, "style": json.dumps(settings, ensure_ascii=False, sort_keys=True), "problems": "none"}
        # The screen gets exactly the prompt the model gets, plus the raw rest of every capped field (never seen by
        # the model, still screened) up to SCREEN_CAP. It runs before anything parses a header. Raises: nothing
        # stored or emitted.
        prompt = load_prompt(ROLE, "draft_task.md", variables | {"thread": thread})
        screened, room = [prompt], SCREEN_CAP
        for rest in rests:
            screened.append(rest[: max(0, room)])
            room -= len(rest)
        flagged = self._safety.check("\n".join(screened))["flagged"] or room < 0
        doc: dict[str, Any] = {"drafted_at": self._clock(), "flagged": flagged, "draft": None, "findings": []}
        own = _base(_address(mailbox) or mailbox.lower())
        replied = _replied(messages, own)
        if answers is not None and (
            replied is None or not _addresses(replied.get("from")) or gmail_id_of(replied) != answers
        ):
            raise ReplyTargetMoved  # the thread changed since the caller looked: nothing stored, emitted or called
        if replied is None or not _addresses(replied.get("from")):  # no one to reply to: fail closed
            return {**doc, "status": "failed", "questions": []}
        envelope = _envelope(replied, own, ask["mode"])
        thread_facts = [v for f in reversed(fields) for v in f.values()]  # newest first: read first
        checker = Checker(instruction=ask["instruction"], thread=thread_facts, trusted=[*settings.values()])
        check = checker.find  # sources are read once per draft, for every attempt and question
        for _ in range(MAX_ATTEMPTS):
            request = GenerateRequest(
                system=self._system, prompt=prompt, json_mode=True, max_output_tokens=MAX_OUTPUT_TOKENS
            )
            response = self._model.generate(request)  # raises: nothing stored or emitted
            if response is None:  # the Router's own screen blocked the call (safety_blocked): fail closed
                return {**doc, "status": "failed", "flagged": True, "questions": []}
            parsed = None if response.tool_calls else _parse(response.text)
            if parsed is None or self._safety.check(parsed[0] or "\n".join(parsed[1]))["flagged"]:
                return {**doc, "status": "failed", "questions": []}
            body, questions = parsed
            if questions:  # "unclear points are asked, not guessed"; one holding an unsupported fact is never shown
                checked = [(q, [f for f in check(q) if f.kind != "commitment"]) for q in questions]
                findings_doc = [{"kind": f.kind, "text": f.text} for _, found in checked for f in found]
                return {
                    **doc,
                    "status": "needs_you",
                    "findings": findings_doc,
                    "questions": [q for q, f in checked if not f],
                }
            findings = check(body)
            if not findings:
                draft = {"artifact_id": "art_" + secrets.token_hex(12), "version": 1, "thread_id": ask["thread_id"]}
                draft |= {"mode": ask["mode"], **envelope, "body": body, "safety_flag": flagged}
                return {**doc, "status": "ready", "draft": draft, "questions": []}
            variables["problems"] = ", ".join(sorted({f.kind for f in findings}))
            prompt = load_prompt(ROLE, "draft_task.md", variables | {"thread": thread})
        findings_doc = [{"kind": f.kind, "text": f.text} for f in findings]
        return {**doc, "status": "needs_you", "findings": findings_doc, "questions": []}
