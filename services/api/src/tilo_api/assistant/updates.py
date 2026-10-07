"""FR-PA-10: free-text updates ("done", "move it to Friday") become a confirmable proposal of the typed actions of
FR-PA-16 (`mark_done`, `snooze`), by the grammar below first and a vetted `assistant` role reply as the fallback
(API_FR_PA_10.md). Nothing here writes: a proposal is a `ui_action` the web posts to the work-item routes. Reopen,
put back and not mine have no `ui_action` kind yet (BQ-PPL11C-34), so they only open the item on My plate.
A rule reads the whole utterance or nothing; the day is `resolve_due` in the person's zone, never a model's."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from tilo_people.dates import resolve_due
from tilo_people.text import clean_line

from tilo_api.assistant.config import AssistantConfig
from tilo_api.assistant.facts import fill, moment_of, zone_of
from tilo_api.assistant.gate import Ref, RefGate
from tilo_api.assistant.navigation import route_for
from tilo_api.assistant.words import question_key, words

if TYPE_CHECKING:
    from tilo_api.assistant.core import Ask, Menu

PERSONAL = Path(__file__).resolve().parents[5] / "config" / "personal.yaml"
_OK = re.compile(r"[a-z0-9' -]+")  # no delimiter, id (underscore) or sentence mark survives into a rule hit
_START = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")
_LABEL_MAX = 140
_SNOOZE_MAX = timedelta(days=30)
_PRON = ("it", "this", "that")
_PREP = frozenset({"to", "until", "till", "for", "on", "in"})
_SNOOZE = frozenset({"snooze", "postpone", "defer", "push", "move", "reschedule"})
_DONE = frozenset(
    {("done",), ("all", "done"), ("finished",), ("it", "is", "done"), ("it's", "done"), ("that", "is", "done")}
)
_VERBS = ("reopen", "re-open", "reassign", "unsnooze")
_HAND_OFF = frozenset(
    {("put", "it", "back"), ("put", "it", "back", "on", "my", "plate"), ("not", "mine"), ("it's", "not", "mine")}
    | {(v,) for v in _VERBS}
    | {(v, p) for v in _VERBS for p in _PRON}
    | {(p, "is", "not", "mine") for p in _PRON}
)
Split = tuple[tuple[str, ...], str | None]  # (the words that name the item, the day phrase)


@dataclass(frozen=True)
class Update:
    decline: str | None = None  # a `declines` key
    action: Mapping[str, Any] | None = None  # the proposal, or for a hand-off the navigate to My plate
    line: str | None = None
    ref: Ref | None = None
    hand_off: bool = False


def _parse(key: str, config: AssistantConfig) -> tuple[str, Sequence[Split]] | None:
    line = key.rstrip(" .!")
    if not _OK.fullmatch(line):
        return None
    t = line.split()
    while t and t[0].split("'")[0] in config.words["fillers"]:
        t.pop(0)
    spoken = tuple(t)
    if spoken[:3] == ("i", "am", "done"):
        spoken = ("done", *spoken[3:])
    if not spoken:
        return None
    if spoken in _HAND_OFF:
        return "hand_off", [((), None)]
    if spoken in _DONE:
        return "mark_done", [((), None)]
    verb, rest = spoken[0], spoken[1:]
    if verb == "mark" and rest[-1:] == ("done",):
        mid = rest[:-1]
        named = mid[:-1] if mid[-1:] == ("as",) else mid
        return ("mark_done", [(named, None)]) if named else None
    if verb == "done" and rest[:1] == ("with",) and len(rest) > 1:
        return "mark_done", [(rest[1:], None)]
    if verb == "finished" and rest:
        return "mark_done", [(rest, None)]
    if verb in _SNOOZE:  # the last preposition first: a title may hold "for" or "in"
        splits = [
            (rest[:i], " ".join(rest[i:] if rest[i] == "in" else rest[i + 1 :]))
            for i in reversed(range(len(rest)))
            if rest[i] in _PREP
        ]
        return "snooze", [*splits, *([(rest, "tomorrow")] if verb == "snooze" else [])]
    return None


def _target(
    named: tuple[str, ...], rows: Sequence[Mapping[str, Any]], ask: Ask, config: AssistantConfig
) -> tuple[bool, Ref | None]:
    """(decided, item): the words name one gated work item, the selection (pronoun or no title), or are ambiguous
    (decided, None). A title that names nothing is not decided: the rules cannot read the phrase."""
    wanted = {w.split("'")[0] for w in named if w not in config.words["title_skip"]}
    if not wanted or set(named) <= set(_PRON):
        return True, ask.context if ask.context is not None and ask.context.kind == "work_item" else None
    if not any(len(w) >= 3 for w in wanted):
        return False, None
    hits = [
        r
        for r in rows
        if r["ref"]["kind"] == "work_item"
        and isinstance(r["title"], str)
        and wanted <= set(words(question_key(r["title"]), config))
    ]
    return (len(hits) > 0), (Ref("work_item", hits[0]["ref"]["id"]) if len(hits) == 1 else None)


def _window_start() -> time:
    """`working_window.start` of config/personal.yaml: where a snooze ends (BQ-PPL11C-28)."""
    raw = yaml.safe_load(PERSONAL.read_text(encoding="utf-8"))["working_window"]["start"]
    if type(raw) is not str or not _START.fullmatch(raw):
        raise ValueError("working_window.start")
    return time(int(raw[:2]), int(raw[3:]))


def propose(
    kind: str, ref: Ref, phrase: str | None, ask: Ask, gate: RefGate, config: AssistantConfig, tz: str | None
) -> Update:
    """The same vet for a rule's and a model's update: the record as stored now, the oracle as the signed-in person
    (`mark_done` for a done, `edit` for a snooze), then the day by code. Only the first refusal is ever shown."""
    item = gate.stored(ref, "mark_done" if kind == "mark_done" else "edit")
    if item is None or item.get("status") != "open" or item.get("owner") != ask.user:
        return Update(decline="update_refused")
    title = None if item.get("flagged") or not isinstance(item.get("title"), str) else item["title"]
    label = clean_line(title)[:_LABEL_MAX] if title else ""
    label = label or config.answer["untitled"]
    template = config.answer["update"]
    if kind == "mark_done":
        return Update(None, {"kind": "mark_done", "work_item_id": ref.id}, fill(template["done"], label=label), ref)
    zone, now = zone_of(tz), moment_of(ask.now)
    if now is None:
        raise ValueError("now")
    found = resolve_due(phrase, meeting_at=ask.now, time_zone=tz if zone is not None and tz else "UTC")
    if found.reason != "resolved" or found.due is None:
        return Update(decline="which_day")
    day = date.fromisoformat(found.due)
    until = datetime.combine(day, _window_start(), tzinfo=zone or UTC).astimezone(UTC)
    if not timedelta(0) < until - now <= _SNOOZE_MAX:
        return Update(decline="snooze_range")
    stamp = until.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    action = {"kind": "snooze", "work_item_id": ref.id, "until": stamp}
    return Update(None, action, fill(template["snooze"], label=label, day=found.due), ref)


def match_update(
    key: str,
    rows: Sequence[Mapping[str, Any]],
    ask: Ask,
    gate: RefGate,
    config: AssistantConfig,
    tz: str | None,
) -> Update | None:
    """None unless the whole utterance is an update (or reopen/put back/not mine) the grammar reads."""
    parsed = _parse(key, config)
    if parsed is None:
        return None
    kind, splits = parsed
    for named, phrase in splits:
        decided, ref = _target(named, rows, ask, config)
        if decided:
            break
    else:
        return None
    if ref is None:
        return Update(decline="which_item")
    if kind == "hand_off":
        return Update(action=route_for(ref, gate), ref=ref, hand_off=True)
    return propose(kind, ref, phrase, ask, gate, config, tz)


def vet_update(
    doc: object, menu: Menu, ask: Ask, gate: RefGate, config: AssistantConfig, tz: str | None
) -> Update | None:
    """A model's `update` document (exact keys and types, checked by `parse_decision`): an offered work item, then the
    same vet as a rule's. Anything that fails is None, which the core answers `dropped`."""
    if not isinstance(doc, Mapping) or type(doc.get("work_item_id")) is not str:
        return None
    ref = Ref("work_item", doc["work_item_id"])
    if ref not in menu.refs:
        return None
    kind, when = doc.get("kind"), doc.get("when")
    if kind not in ("mark_done", "snooze") or (kind == "snooze" and not (type(when) is str and when.strip())):
        return None
    got = propose(kind, ref, when, ask, gate, config, tz)
    return got if got.decline is None and got.action is not None else None
