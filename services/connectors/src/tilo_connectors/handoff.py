"""tilo_connectors.handoff — a build handoff to a partner's link route (FR-CON-16, BH-01..BH-09).

Code, not a model, decides what leaves: the prompt is rendered from the texts the owner accepted (the approved brief
and the chosen approach, for one deliverable) and from granted excerpts. A writer may supply one framing paragraph,
used only if it passes deterministic checks; otherwise a fixed framing is used. There is no thread, message or event
anywhere in this module. No network, no model; the redactor and the safety screen are injected (BQ-109: the shared
redactor is not built, so none is defaulted here). Pinned API: services/connectors/tests/API_FR_CON_16_17_20.md.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from ._schema import approach_validator, brief_validator
from ._text import collapse, flagged, has_hidden, redacted_unchanged, safe_id
from .adapters.lovable import link_length
from .errors import BriefTooLong, BuildPartnerConfigError, HandoffRefused
from .registry import ConnectorRegistry, _NoAliasLoader

if TYPE_CHECKING:
    from .grants import Excerpt, GrantStore

DEFAULT_BUILD_PARTNERS = Path(__file__).resolve().parents[4] / "config" / "build_partners.yaml"
DEFAULT_FRAMING = (
    "Build the {title} described below. Follow the requirements exactly and add nothing that is not listed."
)
_WORD = re.compile(r"[^\W_]+")
_PARTNER_KEYS = {
    "action",
    "route",
    "max_prompt_chars",
    "max_url_length",
    "max_framing_chars",
    "max_excerpt_chars",
    "max_items",
}
_PLAIN_PUNCTUATION = frozenset(" .,;:!?'\"()-")
_MAX_EXACT = 500  # card.schema.json gate.action.exact
_MAX_FRAMING_WORDS = 300


class Screen(Protocol):  # a tilo_providers SafetyProvider fits: check(text) -> {"flagged": bool, "reason": ...}
    def check(self, text: str) -> Mapping[str, Any]: ...


# --- config/build_partners.yaml -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class BuildPartnerConfig:
    connector: str
    action: str
    route: str
    max_prompt_chars: int
    max_url_length: int
    max_framing_chars: int
    max_excerpt_chars: int
    max_items: int
    framing_words: frozenset[str]


def _int_in(partner: Mapping[str, Any], key: str, low: int, high: int) -> int:
    value = partner.get(key)
    if type(value) is not int or not low <= value <= high:
        raise BuildPartnerConfigError(f"build partners: {key} must be an integer from {low} to {high}")
    return value


def _is_gated_t3(declaration: Mapping[str, Any], action_id: Any) -> bool:
    """The declared action is T3, gated by an approval and irreversible (never trusted from a partner file)."""
    return any(
        a.get("id") == action_id
        and a.get("risk_tier") == "T3"
        and a.get("gate_type") == "approval"
        and a.get("irreversible") is True
        for a in declaration.get("actions", ())
    )


def _framing_words(raw: Any) -> frozenset[str]:
    ok = isinstance(raw, list) and len(raw) <= _MAX_FRAMING_WORDS
    for word in raw if ok else ():
        ok = ok and isinstance(word, str) and _WORD.fullmatch(word) is not None
        ok = ok and unicodedata.normalize("NFKC", word).casefold() == word
    if not ok or len(set(raw)) != len(raw):
        raise BuildPartnerConfigError(
            "build partners: framing_words must be unique casefolded single words, at most 300"
        )
    return frozenset(raw)


def load_build_partners(
    path: str | os.PathLike[str] = DEFAULT_BUILD_PARTNERS, *, registry: ConnectorRegistry
) -> dict[str, BuildPartnerConfig]:
    """Every partner of the file, or BuildPartnerConfigError for the whole file (it names a key, never a value)."""
    try:
        raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_NoAliasLoader)  # noqa: S506
    except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError):
        raise BuildPartnerConfigError("build partners: not a readable YAML file without aliases") from None
    if not isinstance(raw, dict) or set(raw) != {"partners", "framing_words"} or not isinstance(raw["partners"], dict):
        raise BuildPartnerConfigError("build partners: needs exactly the keys partners (a mapping) and framing_words")
    words = _framing_words(raw["framing_words"])
    partners: dict[str, BuildPartnerConfig] = {}
    for connector, partner in raw["partners"].items():
        if not isinstance(connector, str) or connector not in registry:
            raise BuildPartnerConfigError("build partners: a partner is not declared in connectors.yaml")
        if not isinstance(partner, dict) or set(partner) != _PARTNER_KEYS:
            raise BuildPartnerConfigError(f"build partners: {connector} needs exactly the keys of a partner")
        if partner["route"] != "link":
            raise BuildPartnerConfigError("build partners: route must be link")
        if not _is_gated_t3(registry.get(connector), partner["action"]):
            raise BuildPartnerConfigError("build partners: action must be declared T3, approval and irreversible")
        max_prompt = _int_in(partner, "max_prompt_chars", 1, 50_000)
        partners[connector] = BuildPartnerConfig(
            connector=connector,
            action=partner["action"],
            route="link",
            max_prompt_chars=max_prompt,
            max_url_length=_int_in(partner, "max_url_length", 100, 2_000_000),
            max_framing_chars=_int_in(partner, "max_framing_chars", 1, 1000),
            max_excerpt_chars=_int_in(partner, "max_excerpt_chars", 1, max_prompt),
            max_items=_int_in(partner, "max_items", 1, 6),
            framing_words=words,
        )
    return partners


# --- the accepted requirements ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptedRequirements:  # every text is whitespace-collapsed
    world_id: str
    run_id: str
    accepted_by: str
    accepted_at: str
    goal: str
    deliverable_index: int
    deliverable_title: str
    audience: str
    approach_id: str
    approach_label: str
    approach_summary: str
    constraints: tuple[str, ...]
    assumptions: tuple[str, ...]
    skips: tuple[str, ...]

    def fields(self) -> tuple[str, ...]:  # every accepted text, in render order
        return (
            self.goal,
            self.deliverable_title,
            self.audience,
            self.approach_label,
            self.approach_summary,
            *self.constraints,
            *self.assumptions,
            *self.skips,
        )


def accepted_requirements(
    *,
    world_id: str,
    run_id: str,
    world_owner: str,
    brief: Mapping[str, Any],
    approach: Mapping[str, Any],
    chosen_approach_id: str,
    deliverable_index: int,
    approval: Mapping[str, Any],
) -> AcceptedRequirements:
    """What the owner accepted for ONE deliverable. Sources, deadline, sensitivity, preferences and the approach's
    risks and estimates are never read (BQ-BUILD-1)."""
    if not brief_validator().is_valid(brief):
        raise HandoffRefused("BH-01", "the brief does not match brief.schema.json")
    if not approach_validator().is_valid(approach) or approach["id"] != chosen_approach_id:
        raise HandoffRefused("BH-01", "the approach is not the one the owner picked")
    if type(deliverable_index) is not int or not 0 <= deliverable_index < len(brief["deliverables"]):
        raise HandoffRefused("BH-01", "the deliverable index is out of range")
    by_owner = isinstance(approval, Mapping) and set(approval) == {"by", "ref", "at"}
    if (
        not by_owner
        or approval["by"] != "person"
        or approval["ref"] != world_owner
        or not isinstance(approval["at"], str)
    ):
        raise HandoffRefused("BH-01", "the requirements were not approved by the world's owner")
    return AcceptedRequirements(
        world_id=world_id,
        run_id=run_id,
        accepted_by=world_owner,
        accepted_at=approval["at"],
        goal=collapse(brief["goal"]),
        deliverable_index=deliverable_index,
        deliverable_title=collapse(brief["deliverables"][deliverable_index]["title"]),
        audience=collapse(brief["audience"]),
        approach_id=approach["id"],
        approach_label=collapse(approach["label"]),
        approach_summary=collapse(approach["summary"]),
        constraints=tuple(collapse(c) for c in brief["constraints"]),
        assumptions=tuple(collapse(a["assumed"]) for a in brief["assumptions"]),
        skips=tuple(collapse(s) for s in approach["skips"]),
    )


def declined_texts(
    *,
    draft_brief: Mapping[str, Any],
    approved_brief: Mapping[str, Any],
    approaches: Sequence[Mapping[str, Any]],
    chosen_approach_id: str,
) -> tuple[str, ...]:
    """The texts the owner did not accept, whitespace-collapsed, unique and sorted."""

    def listed(brief: Mapping[str, Any]) -> dict[str, list[str]]:
        return {
            "constraints": [collapse(c) for c in brief.get("constraints", ())],
            "assumed": [collapse(a["assumed"]) for a in brief.get("assumptions", ())],
            "titles": [collapse(d["title"]) for d in brief.get("deliverables", ())],
        }

    draft, approved = listed(draft_brief), listed(approved_brief)
    found = {
        collapse(approach[k])
        for approach in approaches
        if approach["id"] != chosen_approach_id
        for k in ("label", "summary")
    }
    for key in ("goal", "audience"):
        if collapse(draft_brief[key]) != collapse(approved_brief[key]):
            found.add(collapse(draft_brief[key]))
    for key, texts in draft.items():
        found.update(t for t in texts if t not in approved[key])
    return tuple(sorted(t for t in found if t))


# --- words, leaks, the prompt -------------------------------------------------------------------------------------


def words(text: str) -> list[str]:
    return _WORD.findall(unicodedata.normalize("NFKC", text).casefold())


def _joined(text: str) -> str:  # words never hold a space, so a run of words is a substring of this form
    return " " + " ".join(words(text)) + " "


def _occurs(needle: str, haystack_joined: str) -> bool:
    found = words(needle)
    return bool(found) and " " + " ".join(found) + " " in haystack_joined


def find_leaks(text: str, planted: Sequence[str]) -> tuple[str, ...]:
    """The planted strings whose words occur, in order and whole, in `text`; in planted order, each once."""
    haystack = _joined(text)
    return tuple(dict.fromkeys(p for p in planted if _occurs(p, haystack)))


def _fence(text: str) -> str:
    return "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)


def writer_brief(accepted: AcceptedRequirements) -> str:
    """The requirements block: the only data the writer sees, and the first part of the prompt."""
    lines = [
        "## Goal",
        accepted.goal,
        "",
        "## Deliverable",
        accepted.deliverable_title,
        "",
        "## Audience",
        accepted.audience,
        "",
        "## Approach",
        f"{accepted.approach_label}: {accepted.approach_summary}",
    ]
    for heading, texts in (
        ("Requirements", accepted.constraints),
        ("Assumptions", accepted.assumptions),
        ("Leave out", accepted.skips),
    ):
        if texts:
            lines += ["", f"## {heading}", *(f"- {t}" for t in texts)]
    return "\n".join(lines) + "\n"


def render_prompt(accepted: AcceptedRequirements, framing: str, excerpts: Sequence[Excerpt]) -> str:
    prompt = framing + "\n\n" + writer_brief(accepted)
    if excerpts:
        lines = ["## Reference material", "The client shared these excerpts as reference material."]
        for e in excerpts:
            lines += ["", f"### {collapse(e.item.label)}", _fence(e.text), e.text, _fence(e.text)]
        prompt += "\n" + "\n".join(lines) + "\n"
    return prompt


# --- preparing a handoff ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PreparedHandoff:
    world_id: str
    run_id: str
    connector: str
    action_type: str
    deliverable_index: int
    prompt: str
    prompt_sha256: str
    framing_source: str  # "writer" | "default"
    framing_rule: str | None  # why the default framing was used
    grant_id: str | None
    items: tuple[tuple[str, int], ...]  # (artifact_id, version) of the excerpts' items, first-use order, distinct
    redacted_items: tuple[tuple[str, int], ...]
    exact: str  # gate.action.exact for the card (BH-08)
    link_length: int


def _unaccepted(declined: Sequence[str], accepted: AcceptedRequirements) -> list[str]:
    """Declined texts the owner did not also accept in that form (the owner may keep a text a draft once held)."""
    fields = [_joined(f) for f in accepted.fields()]
    return [d for d in declined if not any(_occurs(d, f) for f in fields)]


def _framing_rule(
    framing: str | None,
    accepted: AcceptedRequirements,
    partner: BuildPartnerConfig,
    banned: list[str],
    redact: Callable[[str], str],
    safety: Screen,
) -> tuple[str, str | None]:
    """BH-03: (the writer's framing, None) when it passes every check, else ("", the first rule it fails)."""
    text = collapse(framing) if isinstance(framing, str) else ""
    if not text:
        return "", "absent"
    if len(text) > partner.max_framing_chars:
        return "", "too_long"
    if not redacted_unchanged(redact, text):
        return "", "secret"
    if flagged(safety, text):
        return "", "flagged"
    known = partner.framing_words.union(*(words(f) for f in accepted.fields()))
    if _stray(text) or not set(words(text)) <= known:  # any code point outside a word and plain punctuation counts
        return "", "unknown_word"
    if find_leaks(text, banned):
        return "", "declined"
    return text, None


def _stray(value: str) -> bool:
    """True when `value` holds a code point that is neither part of a word nor a space or plain ASCII punctuation
    (tag characters, enclosed or regional-indicator letters, symbols, direction controls, combining marks)."""
    return any(c not in _PLAIN_PUNCTUATION for c in _WORD.sub("", value))


def _declaration_ok(declaration: Mapping[str, Any], connector: str, action: str) -> bool:
    return declaration.get("id") == connector and _is_gated_t3(declaration, action)


def prepare_handoff(
    *,
    accepted: AcceptedRequirements,
    framing: str | None,
    excerpts: Sequence[Excerpt],
    grant_id: str | None,
    grants: GrantStore,
    declined: Sequence[str],
    partner: BuildPartnerConfig,
    declaration: Mapping[str, Any],
    redact: Callable[[str], str],
    safety: Screen,
) -> PreparedHandoff:
    """The prompt the owner will see at the gate, or a refusal; the first failing check raises (API doc table)."""
    if partner.route != "link" or not _declaration_ok(declaration, partner.connector, partner.action):  # BH-09
        raise HandoffRefused("BH-09", "the partner is not a gated, irreversible build partner on the link route")
    if excerpts:
        if grant_id is None:
            raise HandoffRefused("DG-03", "excerpts need an active grant")
        grant = grants.require_active(  # DG-03
            grant_id, world_id=accepted.world_id, run_id=accepted.run_id, connector=partner.connector
        )
        for e in excerpts:  # DG-02
            if e.item not in grant.items or e.item.kind != "artifact" or type(e.item.version) is not int:
                raise HandoffRefused("DG-02", f"{safe_id(e.item.ref)} is not an item of grant {grant.id}")
    items = tuple(dict.fromkeys((e.item.ref, int(e.item.version or 0)) for e in excerpts))
    if len(items) > partner.max_items:  # DG-04
        raise HandoffRefused("DG-04", f"at most {partner.max_items} distinct items per handoff")
    banned = _unaccepted(declined, accepted)
    for e in excerpts:  # BH-04
        if find_leaks(e.text, banned) or find_leaks(e.item.label, banned):
            raise HandoffRefused("BH-04", f"{safe_id(e.item.ref)} holds text the owner did not accept")
    used, rule = _framing_rule(framing, accepted, partner, banned, redact, safety)
    if rule is not None:
        used = DEFAULT_FRAMING.format(title=accepted.deliverable_title)
    prompt = render_prompt(accepted, used, excerpts)
    if has_hidden(prompt) or not redacted_unchanged(redact, prompt) or flagged(safety, prompt):  # BH-05
        raise HandoffRefused("BH-05", "the prompt did not pass the redactor and the safety screen")
    try:
        sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        raise HandoffRefused("BH-05", "the prompt is not valid text") from None
    length = link_length(prompt)
    if len(prompt) > partner.max_prompt_chars or length > partner.max_url_length:  # BH-06
        raise BriefTooLong(
            prompt_chars=len(prompt),
            link_length=length,
            max_prompt_chars=partner.max_prompt_chars,
            max_url_length=partner.max_url_length,
        )
    name = declaration["name"]
    carries = (
        f"It carries excerpts of {len(items)} granted item{'s' if len(items) != 1 else ''}: "
        f"{', '.join(f'{a}@{v}' for a, v in items)}."
        if items
        else "It carries no granted data."
    )
    exact = (
        f"Makes a {name} build link from the prompt shown ({len(prompt):,} characters). {carries} "
        f"Nothing leaves Tilo until you open the link; {name} starts building only when you press send there."
    )
    if len(exact) > _MAX_EXACT:  # BH-08: never cut
        raise HandoffRefused("BH-08", "the card text would be over 500 characters")
    return PreparedHandoff(
        world_id=accepted.world_id,
        run_id=accepted.run_id,
        connector=partner.connector,
        action_type=partner.action,
        deliverable_index=accepted.deliverable_index,
        prompt=prompt,
        prompt_sha256=sha,
        framing_source="default" if rule else "writer",
        framing_rule=rule,
        grant_id=grant_id if excerpts else None,
        items=items,
        redacted_items=tuple(dict.fromkeys((e.item.ref, int(e.item.version or 0)) for e in excerpts if e.redacted)),
        exact=exact,
        link_length=length,
    )


# --- after the prompt is stored -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class HandoffRecord:
    world_id: str
    run_id: str
    unit_id: str
    agent_id: str
    attempt: int
    connector: str
    action_type: str
    prompt: dict[str, Any]  # {"artifact_id", "version"} of the stored prompt
    prompt_sha256: str
    grant_id: str | None
    items: tuple[tuple[str, int], ...]
    exact: str
    link_idempotency_key: str  # the link is the unit's output 1 (AR-05)


class HandoffStore:
    """In memory and lock-guarded (a Firestore one later); hands out copies."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str, int], HandoffRecord] = {}
        self._lock = threading.Lock()

    def record(
        self, prepared: PreparedHandoff, stored: Mapping[str, Any], *, unit_id: str, agent_id: str, attempt: int
    ) -> HandoffRecord:
        """BH-07: `stored` is the artifact store's record of exactly the prepared prompt, unscreened by nothing."""
        key = f"{prepared.run_id}:{unit_id}:{attempt}"
        try:
            ref = {"artifact_id": stored["artifact"]["artifact_id"], "version": stored["artifact"]["version"]}
            matches = (
                hashlib.sha256(prepared.prompt.encode("utf-8")).hexdigest() == prepared.prompt_sha256
                and stored["world_id"] == prepared.world_id
                and stored["run_id"] == prepared.run_id
                and stored["media_type"] == "text/markdown"
                and stored["content_sha256"] == prepared.prompt_sha256
                and stored["screening"] == "clean"
                and stored["origin"] == {"kind": "unit", "unit": unit_id, "agent": agent_id}
                and stored["idempotency_key"] == f"{key}:0"
                and isinstance(ref["artifact_id"], str)
                and type(ref["version"]) is int
                and type(attempt) is int
            )
        except (KeyError, TypeError, UnicodeEncodeError):
            matches = False
        if not matches:
            raise HandoffRefused("BH-07", "the stored prompt is not exactly the prompt prepared")
        made = HandoffRecord(
            world_id=prepared.world_id,
            run_id=prepared.run_id,
            unit_id=unit_id,
            agent_id=agent_id,
            attempt=attempt,
            connector=prepared.connector,
            action_type=prepared.action_type,
            prompt=ref,
            prompt_sha256=prepared.prompt_sha256,
            grant_id=prepared.grant_id,
            items=prepared.items,
            exact=prepared.exact,
            link_idempotency_key=f"{key}:1",
        )
        with self._lock:
            slot = (made.world_id, ref["artifact_id"], ref["version"])
            first = self._records.setdefault(slot, made)
            if first != made:
                raise HandoffRefused("BH-07", f"{safe_id(ref['artifact_id'])} was already recorded with other content")
            return deepcopy(first)

    def get(self, world_id: str, ref: Mapping[str, Any]) -> HandoffRecord | None:
        version = ref.get("version")
        if type(version) is not int or not isinstance(ref.get("artifact_id"), str):
            return None
        with self._lock:
            found = self._records.get((world_id, ref["artifact_id"], version))
            return deepcopy(found) if found is not None else None


def handoff_gate(record: HandoffRecord, declaration: Mapping[str, Any]) -> dict[str, Any]:
    """What the card builder, `approval.requested` and the outbox entry copy (CR-10 to CR-12, OB-05)."""
    if not _declaration_ok(declaration, record.connector, record.action_type):
        raise HandoffRefused("BH-09", "the declaration is not a gated, irreversible build partner action")
    return {
        "action_type": record.action_type,
        "connector": record.connector,
        "risk_tier": "T3",
        "irreversible": True,
        "modifiers": ["external_sharing"],
        "recipients": [],
        "attachments": [],
        "item": deepcopy(record.prompt),
        "destination": None,
        "exact": record.exact,
        "undo_window_s": 0,
    }
