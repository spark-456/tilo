"""Evidence quotes (PPL-11a slice A; ADR-0020, people.rules.md PE-19, PE-22 to PE-25). A quote is computed per
request from the stored meeting, its minutes and the transcript version they pin, read through the artifact store in
the meeting's own `Scope`; it is never stored, logged, cached or put in an event. `None` from either function is the
one 404. Deterministic code only: no model, no clock read (`now` is handed in), no network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from tilo_memory.artifacts import ArtifactNotFound, ArtifactStore, Scope
from tilo_people.access import AccessRequest, decide
from tilo_people.directory import Directory
from tilo_people.stores import PeopleStores
from tilo_people.text import clean_line

MAX_HISTORY = 200  # `work_item.history` has no maxItems: a longer record is unreadable, never run through `decide`
_GONE = ("discarded", "deleted")
_MASK = re.compile(r"[^\s@]+@[^\s@]+|\S+://\S+|www\.\S+|\+?\d[\d ().-]{6,}\d")  # addresses, phone numbers, links


@dataclass(frozen=True)
class Reader:
    """Who asks and what they may read through: everything an answer needs, from the seams, nothing from the request
    but the ids."""

    stores: PeopleStores
    artifacts: ArtifactStore
    redact: Callable[[str], str]
    org: str
    actor: str
    now: str

    def directory(self) -> Directory:
        return Directory.of(s.record for s in self.stores.persons.list(self.org))


def meeting_quotes(r: Reader, meeting_id: str, ids: list[str]) -> dict[str, Any] | None:
    """The owner route: one quote per id for the meeting's owner, else None. A discarded or deleted meeting (its
    tombstone keeps the owner) answers every id `expired`."""
    directory = r.directory()
    stored = r.stores.meetings.get(r.org, meeting_id)
    if directory.record(r.actor) is None or stored is None or stored.record["owner"] != r.actor:
        return None
    m = stored.record
    return _expired(m["id"], ids) if m["status"] in _GONE else _answer(r, directory, m, ids, None)


def item_quote(r: Reader, item_id: str) -> dict[str, Any] | None:
    """The item route: at most one quote for the owner of a Tilo-made item confirmed by its assigner, else None."""
    directory = r.directory()
    stored = r.stores.work_items.get(r.org, item_id)
    if directory.record(r.actor) is None or stored is None:
        return None
    wi = stored.record
    ref = wi["source"]["ref"] or ""
    if len(wi["history"]) > MAX_HISTORY or not ref or not _own_item(wi, r.actor, r.now):
        return None
    meeting_id = ref.partition("#")[0]
    found = r.stores.meetings.get(r.org, meeting_id)
    if found is None or found.record["status"] in _GONE:
        return _expired(meeting_id, _lowest_cited(wi))
    return _answer(r, directory, found.record, [], wi)


def _own_item(wi: Mapping[str, Any], actor: str, now: str) -> bool:
    """PE-03, PE-07 on the item alone: the actor's own Tilo-made meeting item, confirmed by its assigner."""
    assigned, confirmed = wi["assigned_by"], wi["confirmed_by"]
    if wi["owner"] != actor or wi["status"] not in ("open", "done", "dropped") or not (assigned and confirmed):
        return False
    made = wi["created_by"]["by"] == "tilo" and wi["source"]["kind"] == "meeting"
    return made and confirmed["by"] == assigned["by"] and wi["created_by"]["at"] <= confirmed["at"] <= now


def _num(utterance_id: str) -> int:
    return int(utterance_id[1:])


def _lowest_cited(wi: Mapping[str, Any]) -> list[str]:
    """An expired quote on the item route names the lowest id the item itself cites, on every gone path."""
    return sorted(wi["source"]["evidence"], key=_num)[:1]


def _expired(meeting_id: str, ids: list[str]) -> dict[str, Any]:
    return {"quotes": [_quote(meeting_id, None, uid, "expired") for uid in ids]}


def _quote(meeting_id: str, ref: Mapping[str, Any] | None, uid: str, state: str) -> dict[str, Any]:
    return {
        "meeting_id": meeting_id,
        "transcript": None if ref is None else dict(ref),
        "utterance_id": uid,
        "state": state,
        "speaker": None,
        "text": None,
        "truncated": False,
    }


def _read(artifacts: ArtifactStore, scope: Scope, ref: Mapping[str, Any]) -> dict[str, Any] | None:
    """A stored JSON document, or None when the scope holds no such version. A corrupt one raises (the route's 503)."""
    try:
        doc = json.loads(artifacts.read(scope, ref))
    except ArtifactNotFound:
        return None
    if not isinstance(doc, dict):
        raise ValueError("not a document")
    return doc


def _shared(
    r: Reader, directory: Directory, m: Mapping[str, Any], wi: Mapping[str, Any], mins: Mapping[str, Any]
) -> list[str] | None:
    """PE-23: the ids both the item and its minutes action item cite, lowest first, once PE-03 lets the actor read
    the item and the meeting owner has confirmed the minutes; None refuses."""
    request = AccessRequest(r.actor, "read_full", "work_item", wi, r.now, meeting=m)
    confirmed = m["minutes_confirmed_by"]
    if not decide(request, directory).allowed or confirmed is None or confirmed["by"] != m["owner"]:
        return None
    item = wi["source"]["ref"].partition("#")[2]
    ai = next((a for a in mins["action_items"] if a["id"] == item and a["work_item_id"] == wi["id"]), None)
    if ai is None or ai["owner"] != wi["owner"] or confirmed["at"] > r.now:
        return None
    return sorted(set(wi["source"]["evidence"]) & set(ai["evidence"]), key=_num)


def _answer(
    r: Reader, directory: Directory, m: Mapping[str, Any], ids: list[str], wi: Mapping[str, Any] | None
) -> dict[str, Any] | None:
    """Both routes from a live meeting. `wi` is None on the owner route (the owner asked for `ids`)."""
    world, minutes_ref = m.get("world_id"), m["minutes"]
    if world is None or m["status"] != "minuted" or minutes_ref is None:
        return None  # a meeting with no world yields no quote (BQ-273)
    scope = Scope(m["org_id"], world, m["owner"])
    mins = _read(r.artifacts, scope, minutes_ref)
    if mins is None or mins["meeting_id"] != m["id"]:
        return None
    ref = {k: mins["transcript"][k] for k in ("artifact_id", "version")}
    if m["transcript"] not in (None, ref):
        return None
    shared: list[str] = []
    if wi is not None:
        found = _shared(r, directory, m, wi, mins)
        if found is None:
            return None
        shared = found
    swept = m["transcript"] is None or r.now >= (m["delete_transcript_after"] or "9")
    head = None if swept else r.artifacts.head(scope, ref)  # none in this scope looks swept (ambiguity 3)
    gone = _expired(m["id"], ids if wi is None else _lowest_cited(wi))
    if head is None:
        return gone
    # A non-owner's id comes from the two citations alone while the transcript is held back (ambiguity 4).
    held = wi is not None and (head.doc["screening"] != "clean" or bool(mins["flagged"]))
    utterances: dict[str, Any] = {}
    if not held:
        tr = _read(r.artifacts, scope, ref)
        if tr is None:
            return gone
        if tr["meeting_id"] != m["id"]:
            return None
        utterances = {u["id"]: u for u in tr["utterances"]}
    if wi is None:
        chosen = ids
    elif held:
        chosen = shared[:1]
    else:
        chosen = [next((u for u in shared if u in utterances), shared[0])] if shared else []
    return {"quotes": [_one(r, directory, m, ref, uid, utterances.get(uid), held, wi is None) for uid in chosen]}


def _one(
    r: Reader,
    directory: Directory,
    m: Mapping[str, Any],
    ref: Mapping[str, Any],
    uid: str,
    utterance: Mapping[str, Any] | None,
    held: bool,
    owner: bool,
) -> dict[str, Any]:
    if held:
        return _quote(m["id"], ref, uid, "withheld")
    if utterance is None:
        return _quote(m["id"], ref, uid, "missing")
    text, truncated = _line(r, utterance["text"], owner)
    if not text:
        return _quote(m["id"], ref, uid, "withheld")
    quote = _quote(m["id"], ref, uid, "shown")
    quote.update(text=text, truncated=truncated)
    label = utterance["speaker"]
    if owner:
        quote["speaker"] = r.redact(clean_line(label))[:80] or None
    else:
        quote["speaker"] = _speaker(r, directory, m, label)
    return quote


def _line(r: Reader, text: str, owner: bool) -> tuple[str, bool]:
    """PE-24: control, format and separator characters removed, the secret redactor, then (non-owner) addresses,
    phone numbers and links masked, then a 240-character cut on a word boundary."""
    t = r.redact(clean_line(text))
    if not owner:
        t = _MASK.sub("[removed]", t)
    if len(t) <= 240:
        return t, False
    return (t[:241].rsplit(" ", 1)[0] if " " in t[:241] else t[:240]).rstrip(), True


def _speaker(r: Reader, directory: Directory, m: Mapping[str, Any], label: str) -> str | None:
    """A non-owner sees the display name of the attendee the label resolved to, only for themselves or a teammate."""
    user = next((a["user"] for a in m["attendees"] if a["name"] == label and a["user"]), None)
    person = directory.record(user) if user is not None else None
    if user is None or person is None or (user != r.actor and not directory.teammates(r.actor, user, r.now)):
        return None
    return clean_line(person["display_name"]) or None
