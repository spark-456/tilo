"""tilo_channels.triage — Email Autopilot triage (FR-CHN-09; PRD 11.3, 11.4, 13.1, 16.3; BQ-130 to BQ-138).

Mail is untrusted data. The safety provider screens From, To, Cc, subject and body first; a flagged mail is
`suspicious` and never reaches the model. Otherwise the "autopilot" role model sees the mail only as delimited data
in the user prompt, with no tools, and answers `{"category", "priority"}`; anything else falls back to fyi/normal.
The user's corrections, mutes and VIPs (P7 preferences, keyed by the bare From address) override the model. Triage
itself never writes preferences, never sends and never logs or stores a subject, body or display name.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Protocol

from tilo_providers.interfaces import GenerateRequest, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt

CATEGORIES = ("needs_reply", "needs_action", "fyi", "newsletter_promo", "suspicious")
PRIORITIES = ("high", "normal", "low")
PILOT_AGREEMENT_TARGET = 0.85  # PRD 11.6, 19.2 E-MAIL
PILOT_WARMUP_S = 86_400  # "after day 1" (BQ-131)

ROLE = "autopilot"
FALLBACK = ("fyi", "normal")  # BQ-136: never needs_reply (no ask), never newsletter_promo (never buried)
FIELD_CAPS = {"sender": 500, "to": 1_000, "cc": 1_000, "subject": 500, "body": 8_000}  # EFF-03, chars
MAX_ANSWER_CHARS = 1_000
UNIT = {"unit_type": "mail_triaged", "unit_count": 1}  # BQ-03

_LOG = logging.getLogger(__name__)


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
    """The lower-cased address of a From header, never its display name; None when there is none."""
    address = parseaddr(value if isinstance(value, str) else "")[1].strip().lower()
    return address if "@" in address and not any(c.isspace() for c in address) else None


def _data(value: Any, cap: int) -> str:
    """Untrusted text for the MAIL block, capped. Angle brackets become look-alikes so no mail can close the block.
    TODO(#206): use tilo_providers.prompts.neutralise_marker once PR #206 lands."""
    text = ", ".join(map(str, value)) if isinstance(value, list) else str(value or "")
    return text[:cap].translate({ord("<"): "‹", ord(">"): "›"})


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
        priority=doc.get("label_priority") or doc["priority"],
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
        screened = "\n".join(str(mail.get(k) or "") for k in ("from", "to", "cc", "subject", "body"))
        doc: dict[str, Any] = {"sender": sender, "triaged_at": self._clock(), "flagged": False}
        if self._safety.check(screened)["flagged"]:  # raises: nothing stored, nothing emitted (fail closed)
            return {**doc, "category": "suspicious", "priority": "high", "source": "safety", "flagged": True}
        prefs = self._preferences.get(user_id) or {}
        rule = ((prefs.get("senders") or {}).get(sender) or {}) if sender else {}
        vip = sender is not None and sender in (prefs.get("vips") or ())
        rule_category = _pick(rule.get("category"), CATEGORIES)
        rule_priority = "high" if vip else _pick(rule.get("priority"), PRIORITIES)  # BQ-134
        if rule_category and rule_priority:  # the user already decided both: no model call
            category, priority, source = rule_category, rule_priority, "rule"
        else:
            answer = self._ask(mail)
            category, priority, source = (*answer, "model") if answer else (*FALLBACK, "fallback")
            if rule_category:
                category, source = rule_category, "rule"
            priority = rule_priority or priority
        if rule.get("muted") is True and category == "needs_reply":  # "don't ask me about these" (BQ-133)
            category, source = "fyi", "rule"
        return {**doc, "category": category, "priority": priority, "source": source}

    def _ask(self, mail: Mapping[str, Any]) -> tuple[str, str] | None:
        fields = {name: _data(mail.get("from" if name == "sender" else name), cap) for name, cap in FIELD_CAPS.items()}
        request = GenerateRequest(
            system=self._system,
            prompt=load_prompt(ROLE, "triage_task.md", fields),
            json_mode=True,
            max_output_tokens=64,
        )
        response = self._model.generate(request)  # raises: nothing stored, nothing emitted
        answer = None if response.tool_calls else _parse(response.text)
        if answer is None:
            _LOG.info("triage fallback: %s", "tool_call" if response.tool_calls else "unusable_answer")
        return answer

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
        if doc.get("sender"):  # the latest correction for an address wins; a relabel ends a mute
            self._update_rule(user_id, doc["sender"], change, drop="muted" if category else None)
        if category:
            doc["label"] = category
        if priority:
            doc["label_priority"] = priority
        self._results.put(user_id, message_id, doc)

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
