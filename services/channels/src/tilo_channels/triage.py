"""tilo_channels.triage — Email Autopilot triage (FR-CHN-09; PRD 11.3, 11.4, 13.1, 16.3; BQ-130 to BQ-138).

Mail is untrusted data. The safety provider screens From, To, Cc, subject and body first; a flagged mail is
`suspicious` and never reaches the model. Otherwise the "autopilot" role model sees the mail only as delimited data
in the user prompt, with no tools, and answers `{"category", "priority"}`; anything else falls back to fyi/normal.
The user's corrections, mutes and VIPs (P7 preferences, keyed by the bare From address) override the model, but never
downgrade a model `suspicious` (BQ-132): a From header is not authenticated, so a rule must not hide a spoof. Triage
itself never writes preferences, never sends and never logs or stores a subject, body or display name.
"""

from __future__ import annotations

import json
import logging
import string
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, GenerateResponse, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt

CATEGORIES = ("needs_reply", "needs_action", "fyi", "newsletter_promo", "suspicious")
PRIORITIES = ("high", "normal", "low")
PILOT_AGREEMENT_TARGET = 0.85  # PRD 11.6, 19.2 E-MAIL
PILOT_WARMUP_S = 86_400  # "after day 1" (BQ-131)

ROLE = "autopilot"
FALLBACK = ("fyi", "normal")  # BQ-136: never needs_reply (no ask), never newsletter_promo (never buried)
FIELD_CAPS = {"sender": 500, "to": 1_000, "cc": 1_000, "subject": 500, "body": 8_000}  # EFF-03, chars
MAX_ANSWER_CHARS = 1_000
MAX_FROM_CHARS = 2_000  # a longer From header gets no rule key (parseaddr and NFKC never see more than this)
UNIT = {"unit_type": "mail_triaged", "unit_count": 1}  # BQ-03

_LOG = logging.getLogger(__name__)
_ANGLES = {ord("<"): "‹", ord(">"): "›"}
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


class MailReader(Protocol):  # the quarantined reader (PRD 16.3 item 3): read-only
    def get_message(self, user_id: str, message_id: str) -> dict: ...


class PreferenceStore(Protocol):  # P7 preferences (PRD 13.1), one JSON document per user
    def get(self, user_id: str) -> dict | None: ...
    def put(self, user_id: str, value: dict) -> None: ...


class TriageStore(Protocol):
    def get(self, user_id: str, message_id: str) -> dict | None: ...
    def create(self, user_id: str, message_id: str, value: dict) -> bool: ...  # atomic set-if-absent
    def put(self, user_id: str, message_id: str, value: dict) -> None: ...
    def items(self, user_id: str) -> list[tuple[str, dict]]: ...


@dataclass(frozen=True)
class TriageResult:
    message_id: str
    category: str
    priority: str
    source: str  # "model" | "rule" | "user" | "safety" | "fallback": where the category came from
    flagged: bool


@dataclass(frozen=True)
class AgreementReport:
    agreed: int
    labelled: int
    rate: float | None
    meets_target: bool


def bare_address(value: Any) -> str | None:
    """The address of a From header with ASCII letters lower-cased, never its display name; None when there is none.
    An address with a control or format (zero-width) character, or one NFKC would change (the Kelvin sign,
    full-width letters), gets no key, so no look-alike shares a rule with the real address."""
    try:  # parseaddr recurses on nested comments and colon runs: a hostile From gets no key, never a crash
        address = parseaddr(value if isinstance(value, str) and len(value) <= MAX_FROM_CHARS else "")[1].strip()
    except (RecursionError, ValueError):
        return None
    if any(unicodedata.category(c)[0] == "C" for c in address) or unicodedata.normalize("NFKC", address) != address:
        return None
    address = address.translate(_ASCII_LOWER)
    return address if "@" in address and not any(c.isspace() for c in address) else None


def _render(value: Any, *, header: bool, limit: int) -> tuple[str, str]:
    """(head, rest): the untrusted mail text as the model sees it, and the raw text beyond `limit` characters.
    Only the first `limit` raw characters are normalised: NFKC is quadratic on characters that expand (U+FDFA), so
    unbounded mail would pin a worker. NFKC first, so no full-width or small-form look-alike survives; then `<` and
    `>` become look-alikes, so no mail can open or close the MAIL block. A header folds control and line-separator
    characters to a space, so it cannot forge another header line. The model gets the head capped again to `limit`;
    the screen gets head and rest, so it covers at least everything the model sees.
    TODO(#206): share tilo_providers.prompts.neutralise_marker once PR #206 lands."""
    if isinstance(value, list):
        value = ", ".join(v for v in value if isinstance(v, str))
    text = value if isinstance(value, str) else ""
    head = unicodedata.normalize("NFKC", text[:limit])
    if header:
        head = "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in head)
    return head.translate(_ANGLES), text[limit:]


def _parse(text: str | None) -> tuple[str, str] | None:
    if not text or len(text) > MAX_ANSWER_CHARS:
        return None
    try:
        answer = json.loads(text)
    except ValueError:
        return None
    if not isinstance(answer, dict):
        return None
    category, priority = answer.get("category"), answer.get("priority")
    if isinstance(category, str) and isinstance(priority, str) and category in CATEGORIES and priority in PRIORITIES:
        return category, priority
    return None


def _pick(value: Any, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _result(message_id: str, doc: Mapping[str, Any]) -> TriageResult:
    label = None if doc["flagged"] else doc.get("label")  # a flag beats every label (PRD 16.2)
    return TriageResult(
        message_id=message_id,
        category=label or doc["category"],
        priority=(None if doc["flagged"] else doc.get("label_priority")) or doc["priority"],  # flagged stays high
        source="user" if label else doc["source"],
        flagged=doc["flagged"],
    )


class Triage:
    def __init__(
        self,
        *,
        reader: MailReader,
        model: ModelProvider,
        safety: SafetyProvider,
        preferences: PreferenceStore,
        results: TriageStore,
        clock: Callable[[], float],
        emit: Callable[[dict], None] = lambda part: None,
    ) -> None:
        self._reader, self._model, self._safety = reader, model, safety
        self._preferences, self._results, self._clock, self._emit = preferences, results, clock, emit
        self._system = load_prompt(ROLE, "triage_system.md")

    def __call__(self, user_id: str, message_id: str) -> TriageResult:
        return self.triage(user_id, message_id)

    def triage(self, user_id: str, message_id: str) -> TriageResult:
        doc = self._results.get(user_id, message_id)
        if doc is None:
            doc = self._decide(user_id, self._reader.get_message(user_id, message_id))
            if self._results.create(user_id, message_id, doc):
                if doc["source"] != "fallback":  # BQ-137: a fallback is not a finished unit (PRD 14.2)
                    self._emit({"type": "building.completed", "data": dict(UNIT)})
            else:  # another call or instance stored it first: theirs is the result
                doc = self._results.get(user_id, message_id) or doc
        return _result(message_id, doc)

    def _decide(self, user_id: str, mail: Mapping[str, Any]) -> dict[str, Any]:
        sender = bare_address(mail.get("from"))
        parts = {
            name: _render(mail.get("from" if name == "sender" else name), header=name != "body", limit=cap)
            for name, cap in FIELD_CAPS.items()
        }
        fields = {name: head for name, (head, _rest) in parts.items()}
        doc: dict[str, Any] = {"sender": sender, "triaged_at": self._clock(), "flagged": False}
        flagged = {"category": "suspicious", "priority": "high", "source": "safety", "flagged": True}
        if self._safety.check("\n".join(head + rest for head, rest in parts.values()))[
            "flagged"
        ]:  # raises: nothing stored or emitted
            return {**doc, **flagged}
        category, priority, source = self._ask(fields)  # always asked, even for a ruled sender (BQ-132)
        if source == "safety":
            return {**doc, **flagged}
        prefs = self._preferences.get(user_id) or {}
        rule = ((prefs.get("senders") or {}).get(sender) or {}) if sender else {}
        if category != "suspicious":  # no rule or mute downgrades the model's suspicious (BQ-132)
            rule_category = _pick(rule.get("category"), CATEGORIES)
            category, source = (rule_category, "rule") if rule_category else (category, source)
            priority = _pick(rule.get("priority"), PRIORITIES) or priority
            if rule.get("muted") is True and category == "needs_reply":  # "don't ask me about these" (BQ-133)
                category, source = "fyi", "rule"
        if sender is not None and sender in (prefs.get("vips") or ()):  # BQ-134: a VIP only raises priority
            priority = "high"
        return {**doc, "category": category, "priority": priority, "source": source}

    def _ask(self, fields: Mapping[str, str]) -> tuple[str, str, str]:
        capped = {name: text[: FIELD_CAPS[name]] for name, text in fields.items()}
        request = GenerateRequest(
            system=self._system,
            prompt=load_prompt(ROLE, "triage_task.md", capped),
            json_mode=True,
            max_output_tokens=64,
        )
        response: GenerateResponse | None = self._model.generate(request)  # raises: nothing stored or emitted
        if response is None:  # the Router's own screen blocked the call (safety_blocked): a flag (BQ-135)
            _LOG.info("triage flagged: safety_blocked")
            return "suspicious", "high", "safety"
        answer = None if response.tool_calls else _parse(response.text)
        if answer is None:
            _LOG.info("triage fallback: %s", "tool_call" if response.tool_calls else "unusable_answer")
            return (*FALLBACK, "fallback")
        return (*answer, "model")

    # --- the user's own corrections: the only writers of preferences (PRD 11.3 Learning) ---

    def _stored(self, user_id: str, message_id: str) -> dict[str, Any]:
        doc = self._results.get(user_id, message_id)
        if doc is None:
            raise LookupError("message not triaged")
        return doc

    def _update_rule(self, user_id: str, sender: str, change: Mapping[str, Any], drop: str | None = None) -> None:
        prefs = self._preferences.get(user_id) or {}
        rule = prefs.setdefault("senders", {}).setdefault(sender, {})
        rule.update(change)
        if drop:
            rule.pop(drop, None)
        self._preferences.put(user_id, prefs)

    def correct(
        self, user_id: str, message_id: str, *, category: str | None = None, priority: str | None = None
    ) -> None:
        if (category is None and priority is None) or (category is not None and category not in CATEGORIES):
            raise ValueError("a correction needs a known category or priority")
        if priority is not None and priority not in PRIORITIES:
            raise ValueError("unknown priority")
        doc = self._stored(user_id, message_id)
        change = {k: v for k, v in (("category", category), ("priority", priority)) if v is not None}
        if category:
            doc["label"] = category
        if priority:
            doc["label_priority"] = priority
        self._results.put(user_id, message_id, doc)  # the label first: a failed put leaves no rule without it
        if doc.get("sender"):  # the latest correction for an address wins; a relabel ends a mute
            self._update_rule(user_id, doc["sender"], change, drop="muted" if category else None)

    def mute(self, user_id: str, message_id: str) -> None:
        sender = self._stored(user_id, message_id).get("sender")
        if not sender:
            raise ValueError("the message has no sender address")
        self._update_rule(user_id, sender, {"muted": True})

    def add_vip(self, user_id: str, address: str) -> None:
        bare = bare_address(address)
        if not bare:
            raise ValueError("not an email address")
        prefs = self._preferences.get(user_id) or {}
        prefs["vips"] = sorted({*(prefs.get("vips") or ()), bare})
        self._preferences.put(user_id, prefs)

    def agreement_records(self, user_id: str) -> list[dict]:
        return [
            {"message_id": m, "triaged_at": d["triaged_at"], "predicted": d["category"], "label": d.get("label")}
            for m, d in self._results.items(user_id)
        ]


def pilot_agreement(records: Iterable[Mapping], *, started_at: float) -> AgreementReport:
    """BQ-131: labelled messages first triaged after day one; agreement is the first category equal to the label."""
    counted = [r for r in records if r.get("label") is not None and r["triaged_at"] >= started_at + PILOT_WARMUP_S]
    agreed = sum(r["predicted"] == r["label"] for r in counted)
    rate = agreed / len(counted) if counted else None
    return AgreementReport(agreed, len(counted), rate, rate is not None and rate >= PILOT_AGREEMENT_TARGET)
