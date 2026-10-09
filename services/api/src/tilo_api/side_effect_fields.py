"""tilo_api.side_effect_fields: the production action resolver (ADR-0035 L6c, FR-CON-02, BQ-ADR35L6c-1..3).

Deterministic and generic over the action type. It maps STRUCTURED answers the person gave (their typed answer to a
Director question or their chip edit, keyed by brief field) and the values they supplied on the fields route to the
recipients and the declared document fields of a live side-effect step, by the keys in `config/side_effect_fields.yaml`.
It never reads the brief's text or a unit's output: an address in prose is not an answer. An answer counts only when the
whole of it is a list of plain addresses (strict syntax, ASCII, no display name, no control or format character, no
duplicates), in the entry's recipients only (never Cc or Bcc), at most the configured cap. What is missing raises
`Missing`, which the run turns into a needs-you card; risk tiers for new recipients stay the policy table's.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tilo_api import item_documents
from tilo_api.item_documents import DocumentRefused

CONFIG = Path(__file__).resolve().parents[4] / "config" / "side_effect_fields.yaml"
RECIPIENT = "recipient"  # the one field that is not in the document: who the entry reaches
CONTRACT_CAP = 50  # card.gate.recipients and outbox.recipients maxItems
_ADDRESS = re.compile(
    r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}"
)
_DOCUMENT_FIELDS = frozenset({"subject", "name", "title", "start", "end", "time_zone", "mime_type"})


class Missing(Exception):
    """Required recipients or fields nobody has declared; `reason` says why an answer was not used, if one was given."""

    def __init__(self, fields: tuple[str, ...], reason: str | None = None) -> None:
        super().__init__(", ".join(fields))
        self.fields, self.reason = fields, reason


@dataclass(frozen=True)
class Rule:
    recipient_answer: str | None  # the brief field whose answer holds the recipients; None = the person is asked
    cap: int  # recipients allowed; 0 = the action reaches no one
    fields: Mapping[str, str]  # document field -> the brief field whose answer is it


def parse_addresses(text: Any, *, cap: int = CONTRACT_CAP) -> list[str]:
    """Plain addresses from a comma-separated answer; DocumentRefused (plain reason) for anything else."""
    if not isinstance(text, str) or not text.strip():
        raise DocumentRefused("the recipient must be an email address")
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Zl", "Zp") for c in text):
        raise DocumentRefused("the recipient has line breaks or hidden characters")
    found: dict[str, str] = {}
    for number, part in enumerate(text.split(","), start=1):  # the reason names the place, never echoes the text
        address = part.strip()
        if len(address) > 254 or "@" not in address or len(address.split("@")[0]) > 64:
            raise DocumentRefused(f"address {number} is not an email address")
        if not _ADDRESS.fullmatch(address):  # a display name, angle brackets, spaces or a second @ end up here
            raise DocumentRefused(f"address {number} is not a plain email address like name@example.org")
        found.setdefault(address.lower(), address)
    if len(found) > cap:
        raise DocumentRefused(f"at most {cap} recipients; this names {len(found)}")
    return list(found.values())


def load_config(path: Path = CONFIG) -> tuple[dict[str, Rule], dict[str, dict[str, Any]]]:
    """(rules per action, label/hint per field). A bad file is a ValueError at load, so a mistake never ships."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("version") != 1 or set(raw) - {"version", "labels", "actions"}:
        raise ValueError("side_effect_fields.yaml: unknown shape")
    labels = {str(k): dict(v) for k, v in (raw.get("labels") or {}).items()}
    rules: dict[str, Rule] = {}
    for action, spec in (raw.get("actions") or {}).items():
        if action not in item_documents.KIND_OF or not isinstance(spec, dict) or set(spec) - {"recipient", "fields"}:
            raise ValueError(f"side_effect_fields.yaml: bad action {action!r}")
        fields = dict(spec.get("fields") or {})
        if set(fields) - _DOCUMENT_FIELDS or not all(isinstance(v, str) and v for v in fields.values()):
            raise ValueError(f"side_effect_fields.yaml: bad fields for {action}")
        recipient = spec.get("recipient")
        if recipient is not None and (
            action in item_documents.NO_RECIPIENT_ACTIONS
            or not isinstance(recipient.get("answer"), str)
            or not 1 <= int(recipient.get("max", 0)) <= CONTRACT_CAP
        ):
            raise ValueError(f"side_effect_fields.yaml: bad recipient rule for {action}")
        needs_one = action not in item_documents.NO_RECIPIENT_ACTIONS
        rules[action] = Rule(
            recipient.get("answer") if recipient else None,
            int(recipient["max"]) if recipient else (CONTRACT_CAP if needs_one else 0),
            fields,
        )
    return rules, labels


_LOADED: tuple[dict[str, Rule], dict[str, dict[str, Any]]] | None = None


def _config() -> tuple[dict[str, Rule], dict[str, dict[str, Any]]]:
    global _LOADED  # noqa: PLW0603
    if _LOADED is None:
        _LOADED = load_config()
    return _LOADED


def describe(names: tuple[str, ...]) -> list[dict[str, Any]]:
    """What the web form shows for each missing field: its label, hint and length limit (from the config)."""
    labels = _config()[1]
    return [{"name": n, "label": labels.get(n, {}).get("label", n), "hint": labels.get(n, {}).get("hint", ""),
             "max_length": labels.get(n, {}).get("max_length", 150)} for n in names]  # fmt: skip


def check_recipient(action: str, text: Any) -> str:
    """The fields route's check of a supplied recipient list: the normalised, comma-joined addresses."""
    rule = _config()[0].get(action)
    if rule is None or rule.cap == 0:
        raise DocumentRefused("this action has no recipient to add")
    return ", ".join(parse_addresses(text, cap=rule.cap))


def make_resolver(
    rules: Mapping[str, Rule] | None = None,
) -> Callable[..., dict[str, Any]]:
    """`resolve(*, unit, action_type, item, brief, answers, supplied) -> {destination, recipients, known_recipients,
    fields}`. `answers` are the person's structured answers by brief field, `supplied` what they typed on the fields
    route by field name; the unit and the brief's text are not read."""
    table = _config()[0] if rules is None else rules

    def resolve(
        *, unit: dict, action_type: str, item: dict, brief: dict,
        answers: Mapping[str, Any] | None = None, supplied: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:  # fmt: skip
        rule, answers, supplied = table.get(action_type), answers or {}, supplied or {}
        if rule is None:
            raise LookupError(f"no field rule for {action_type}")
        recipients: list[str] = []
        if rule.cap:
            reason: str | None = None
            source = supplied.get(RECIPIENT) or (answers.get(rule.recipient_answer) if rule.recipient_answer else None)
            if isinstance(source, str) and source.strip():
                try:
                    recipients = parse_addresses(source, cap=rule.cap)
                except DocumentRefused as exc:
                    reason = exc.reason if "@" in source else None  # "My own team" is just not an address
            if not recipients:
                raise Missing((RECIPIENT,), reason)
        fields: dict[str, Any] = {}
        for name, key in rule.fields.items():
            candidate = supplied.get(name) or answers.get(key)
            if isinstance(candidate, str) and candidate.strip():
                try:
                    fields |= item_documents.check_fields(action_type, {name: candidate})
                except DocumentRefused:
                    continue  # not usable as this field: the person is asked instead
        fields |= {k: v for k, v in supplied.items() if k != RECIPIENT and k in _DOCUMENT_FIELDS}
        return {"destination": None, "recipients": recipients, "known_recipients": [], "fields": fields}

    resolve.takes_answers = True  # type: ignore[attr-defined]  # the run passes the person's answers only to this one
    return resolve
