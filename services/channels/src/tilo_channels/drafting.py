"""tilo_channels.drafting — Email Autopilot drafting (FR-CHN-10; PRD 11.4, 11.6, 13.1, 16.3; BQ-139 to BQ-151).

A reply is drafted from the user's instruction (trusted) plus the thread (untrusted, raw-capped before any NFKC or
regex). The safety provider screens exactly the prompt the "autopilot" model gets (thread only as delimited data, no
tools) plus the raw rest past each cap. Recipients, subject and reply headers come from the thread and the user, never
from the model. `find_invented` holds the body to PRD 11.4 Content. Drafting never sends, saves a Gmail draft or
writes the outbox, and never logs, emits or stores mail text beyond the draft itself.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from email.utils import getaddresses
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt

MODES = ("reply", "reply_all")  # forward and new email add recipients: FR-CHN-12's T3 path (BQ-145)
PRESETS = ("confirm", "decline", "follow_up", "reschedule", "formal_letter")
STYLE_KEYS = ("greeting", "sign_off", "formality", "language", "signature")

ROLE = "autopilot"
MAX_ATTEMPTS = 2  # one draft plus at most one regeneration (BQ-141)
MAX_OUTPUT_TOKENS = 1_200
# Raw caps, applied before any NFKC, fold or regex: NFKC is quadratic on expanding characters (U+FDFA), so untrusted
# text is always cut first (EFF-03). An over-long address or reply header is dropped, never truncated.
FIELD_CAPS = {"from": 500, "to": 2_000, "cc": 2_000, "subject": 500, "body": 8_000}
ADDRESS_CAP, MAX_ADDRESSES, HEADER_CAP, MAX_MESSAGES = 500, 50, 4_000, 50
MAX_INSTRUCTION, MAX_STYLE_VALUE, CHECK_CAP = 4_000, 2_000, 20_000

_LOG = logging.getLogger(__name__)
_ANGLES = {ord("<"): "‹", ord(">"): "›"}

# The content checker (PRD 11.4 Content; BQ-140). Every quantifier that can fail after a long scan is bounded.
_CONTACT = re.compile(r"(?:https?://|www\.)[^\s‹›<>\"']+|[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:[.:]\d+)*")
_NUMBER_WORDS = dict(
    pair.split(":")
    for pair in "two:2 three:3 four:4 five:5 six:6 seven:7 eight:8 nine:9 ten:10 eleven:11 twelve:12 twenty:20 "
    "thirty:30 forty:40 fifty:50 sixty:60 seventy:70 eighty:80 ninety:90 hundred:100 thousand:1000 dozen:12 "
    "half:0.5".split()
)
_NUMBER_WORD = re.compile(r"\b(?:" + "|".join(_NUMBER_WORDS) + r")\b")
_DATE = re.compile(
    r"\b(?:(mon|tues|wednes|thurs|fri|satur|sun)days?|(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|today|tonight|tomorrow|weekends?"
    r"|this week|next week|next month|end of (?:the )?day|eod|same[- ]day|overnight|asap)\b"
)
_COMMITMENTS = [  # one family per pattern; a family in the draft must also be in the instruction
    re.compile(p)
    for p in r"\bfree\b;\bdiscount\w*;\bwaive\w*;\bwaiving\b;\brefund\w*;\breimburs\w*;\bcompensat\w*;\bguarantee\w*;"
    r"\bpromise\w*;\bpromising\b;\bcomplimentary\b;\bwarrant(?:y|ies)\b;\bno (?:extra |additional )?(?:charge|cost)s?\b"
    r";\bprepa(?:y\w*|id)\b;\bpay\w*;\bpaid\b".split(";")
]


@dataclass(frozen=True)
class Finding:
    kind: str  # "number" | "date" | "contact" | "commitment"
    text: str  # the draft span no source supports; shown to the user, never logged or emitted


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", text).lower()


def _number(text: str) -> str:
    text = text.replace(",", "")
    return re.sub(r"^0+(?=\d)", "", text[:-3] if text.endswith((".00", ":00")) else text)


def _date(match: re.Match[str]) -> str:
    if match.group(1) or match.group(2):
        return match.group(1) + "day" if match.group(1) else match.group(2)[:3]
    word = match.group(0).replace("-", " ").removesuffix("s")
    return "eod" if word.startswith("end of") else word


def _facts(text: str) -> tuple[list[tuple[str, str, str]], str]:
    """(kind, normalised value, span) for every contact, number and date in folded `text`, and the commitment text."""
    facts = [("contact", c, c) for m in _CONTACT.finditer(text) if (c := m.group(0).rstrip(".,;:!?)"))]
    rest = _CONTACT.sub(" ", text)
    facts += [("number", _number(m.group(0)), m.group(0)) for m in _NUMBER.finditer(rest)]
    facts += [("number", _NUMBER_WORDS[m.group(0)], m.group(0)) for m in _NUMBER_WORD.finditer(rest)]
    facts += [("date", _date(m), m.group(0)) for m in _DATE.finditer(rest)]
    return facts, re.sub(r"\bfeel free\b", "feel", rest)


def find_invented(body: str, *, instruction: str, thread: Sequence[str], trusted: Sequence[str] = ()) -> list[Finding]:
    """Every number, date, address or link in `body` that no fact source holds, and every commitment word the
    instruction does not hold (the thread and `trusted` never authorise a commitment). Deterministic. A body over
    CHECK_CAP raises ValueError; a source is read only up to CHECK_CAP (a cut fact is reported, never assumed)."""
    if len(body) > CHECK_CAP:
        raise ValueError("draft too long to check")
    sources = (instruction, *thread, *trusted)
    known = {(kind, value) for text in sources for kind, value, _ in _facts(_fold(text[:CHECK_CAP]))[0]}
    facts, words = _facts(_fold(body))
    allowed = _facts(_fold(instruction[:CHECK_CAP]))[1]
    findings = [Finding(kind, span) for kind, value, span in facts if (kind, value) not in known]
    for family in _COMMITMENTS:
        if not family.search(allowed):
            findings += [Finding("commitment", m.group(0)) for m in family.finditer(words)]
    return list(dict.fromkeys(findings))


class ThreadReader(Protocol):  # the quarantined reader (PRD 16.3 item 3): read-only
    def get_thread(self, user_id: str, thread_id: str) -> dict: ...


class DraftStore(Protocol):  # JSON-able results keyed (user_id, instruction_id)
    def get(self, user_id: str, instruction_id: str) -> dict | None: ...
    def create(self, user_id: str, instruction_id: str, value: dict) -> bool: ...  # atomic set-if-absent
    def put(self, user_id: str, instruction_id: str, value: dict) -> None: ...


@dataclass(frozen=True)
class Draft:
    artifact_id: str
    version: int
    thread_id: str
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
    """A bare, lower-case ASCII address; None for anything with a space, control or non-ASCII character."""
    value = value.strip()
    ok = value.isascii() and value.isprintable() and " " not in value and value.count("@") == 1
    return value.lower() if ok else None


def _addresses(value: Any) -> list[str]:
    """Bare addresses of an untrusted header: at most MAX_ADDRESSES entries, an entry over ADDRESS_CAP is dropped,
    and a header the parser chokes on (nested comments) has none."""
    raw = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    try:
        pairs = getaddresses([v for v in raw[:MAX_ADDRESSES] if isinstance(v, str) and len(v) <= ADDRESS_CAP])
    except (RecursionError, ValueError):
        return []
    return [a for _, addr in pairs if (a := _address(addr))]


def _raw(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(v for v in value if isinstance(v, str))
    return value if isinstance(value, str) else ""


def _header(value: Any, cap: int) -> str:
    """A header value cut to `cap` raw characters, then NFKC, with control and line-separator characters folded to
    spaces: it cannot forge another line."""
    text = unicodedata.normalize("NFKC", (value if isinstance(value, str) else "")[:cap])[:cap]
    return " ".join("".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text).split())


def _render(value: str, field: str) -> str:
    """Untrusted text exactly as the safety screen and the model see it: cut to its raw cap, NFKC, format characters
    dropped, controls folded, then `<` and `>` as look-alikes so no mail can open or close the THREAD block."""
    cap = FIELD_CAPS[field]
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


def _envelope(message: Mapping[str, Any], own: str, mode: str) -> dict[str, Any]:
    """Recipients and reply headers, from the message replied to only (BQ-144, BQ-146)."""
    to = _addresses(message.get("from"))[:1]
    cc: list[str] = []
    if mode == "reply_all":
        for field, out in (("to", to), ("cc", cc)):
            out += [a for a in dict.fromkeys(_addresses(message.get(field))) if a != own and a not in to + cc]
    raw = message.get("headers")
    headers = {str(k).lower(): v for k, v in raw.items()} if isinstance(raw, dict) else {}
    message_id = _reply_header(headers.get("message-id"))
    references = _reply_header(headers.get("references")).split()
    references += [message_id] if message_id and message_id not in references else []
    subject = _header(message.get("subject"), FIELD_CAPS["subject"])
    subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    envelope = {"to": to, "cc": cc, "bcc": [], "attachments": [], "subject": subject, "in_reply_to": message_id}
    return envelope | {"references": " ".join(references)}


def _parse(text: str | None) -> tuple[str, list[str]] | None:
    if text is not None and len(text) > CHECK_CAP:  # also bounds the body find_invented reads
        return None
    try:
        answer = json.loads(text or "")
    except ValueError:
        return None
    body, questions = (answer.get("body"), answer.get("questions") or []) if isinstance(answer, dict) else (None, [])
    if not isinstance(questions, list) or not all(isinstance(q, str) for q in questions):
        return None
    if questions := [q.strip() for q in questions if q.strip()]:
        return "", questions
    return (body.strip(), []) if isinstance(body, str) and body.strip() else None


def _result(instruction_id: str, doc: Mapping[str, Any]) -> DraftResult:
    fields: dict[str, Any] = {k: tuple(v) if isinstance(v, list) else v for k, v in (doc.get("draft") or {}).items()}
    findings = tuple(Finding(**f) for f in doc["findings"])
    draft = Draft(**fields) if fields else None
    return DraftResult(instruction_id, doc["status"], draft, findings, tuple(doc["questions"]), doc["flagged"])


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
        thread_id: str,
        instruction: str,
        mailbox: str,
        mode: str = "reply",
        preset: str | None = None,
        style: Mapping[str, Any] | None = None,
    ) -> DraftResult:
        if mode not in MODES or (preset is not None and preset not in PRESETS):
            raise ValueError("unknown drafting mode or preset")
        if len(instruction) > MAX_INSTRUCTION:
            raise ValueError("instruction too long")
        doc = self._drafts.get(user_id, instruction_id)
        if doc is None:
            request = {"thread_id": thread_id, "instruction": instruction, "mode": mode, "preset": preset or "none"}
            doc = self._make(user_id, mailbox, style or {}, request)
            if self._drafts.create(user_id, instruction_id, doc):  # BQ-150: keyed by the instruction
                if doc["draft"]:
                    artifact = {"artifact_id": doc["draft"]["artifact_id"], "version": 1}
                    self._emit({"type": "artifact.created", "data": {"artifact": artifact}})
                _LOG.info("drafting %s: %s", instruction_id, doc["status"])
            else:  # another call or instance stored it first: theirs is the result
                doc = self._drafts.get(user_id, instruction_id) or doc
        return _result(instruction_id, doc)

    def _make(self, user_id: str, mailbox: str, style: Mapping[str, Any], ask: dict[str, str]) -> dict[str, Any]:
        listed = self._reader.get_thread(user_id, ask["thread_id"]).get("messages")
        messages = [m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if isinstance(m, dict)]
        raws = [{k: _raw(m.get(k)) for k in FIELD_CAPS} for m in messages]
        fields = [{k: _render(text, k) for k, text in r.items()} for r in raws]
        thread = "\n\n".join(
            "[message {n}]\nFrom: {from}\nTo: {to}\nCc: {cc}\nSubject: {subject}\n\n{body}".format(n=n, **f)
            for n, f in enumerate(fields, 1)
        )
        settings = {
            k: v for k, v in style.items() if k in STYLE_KEYS and isinstance(v, str) and len(v) <= MAX_STYLE_VALUE
        }
        variables = {**ask, "style": json.dumps(settings, ensure_ascii=False, sort_keys=True), "problems": "none"}
        # The screen gets exactly the prompt the model gets, plus the raw rest of every capped field (never seen by
        # the model, still screened). It runs before anything parses a header. Raises: nothing stored or emitted.
        prompt = load_prompt(ROLE, "draft_task.md", variables | {"thread": thread})
        rests = [text[FIELD_CAPS[k] :] for r in raws for k, text in r.items() if len(text) > FIELD_CAPS[k]]
        flagged = self._safety.check("\n".join([prompt, *rests]))["flagged"]
        doc: dict[str, Any] = {"drafted_at": self._clock(), "flagged": flagged, "draft": None, "findings": []}
        own = _address(mailbox) or mailbox.lower()
        replied = next((m for m in reversed(messages) if _addresses(m.get("from"))[:1] != [own]), None)
        if replied is None or not _addresses(replied.get("from")):  # no one to reply to: fail closed
            return {**doc, "status": "failed", "questions": []}
        envelope, sources = _envelope(replied, own, ask["mode"]), [v for f in fields for v in f.values()]
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
            if questions:  # "unclear points are asked, not guessed"
                return {**doc, "status": "needs_you", "questions": questions}
            findings = find_invented(
                body, instruction=ask["instruction"], thread=sources, trusted=list(settings.values())
            )
            if not findings:
                draft = {"artifact_id": "art_" + secrets.token_hex(12), "version": 1, "thread_id": ask["thread_id"]}
                draft |= {"mode": ask["mode"], **envelope, "body": body, "safety_flag": flagged}
                return {**doc, "status": "ready", "draft": draft, "questions": []}
            variables["problems"] = ", ".join(sorted({f.kind for f in findings}))
            prompt = load_prompt(ROLE, "draft_task.md", variables | {"thread": thread})
        findings_doc = [{"kind": f.kind, "text": f.text} for f in findings]
        return {**doc, "status": "needs_you", "findings": findings_doc, "questions": []}
