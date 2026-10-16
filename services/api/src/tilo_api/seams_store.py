"""The production backends of the four people seams (PEOPLE-SEAMS-1; ADR-0021, ADR-0026, PE-12, PE-26, BQ-273).

Each class is built per request over the API's own `deps.Store` (the durable write-through cache when deployed, the
demo session's or a test's plain one otherwise) and answers for one person only: the seams are the owner-scoping
boundary, so every read is keyed by the signed-in user, an id that does not match its schema never reaches a backend,
and anything unknown, malformed or ambiguous is `None` or absent (deny by default). Reads are bounded (`MAX_FACTS`).
A store that fails raises, and the route answers 503 (an honest plate is complete or absent, HR-1).

* `StorePlateSources`: cards (the open cards of the person's runs, `CardStore.plate_facts`), runs (the person's worlds
  joined to their task's brief and their events) and mail (`orgs/{org}/mail_triage`, see `FirestoreMailTriage`).
* `StoreSourceOwners`: who owns a mail message (the triage record) or a request (a world or task of this store).
* `StoreDeskWorlds`: the person's one Desk world, the same one the assistant panel uses (`desk.ensure_desk`).
* `StoreMeetingWorlds`: the Outpost world of a meeting, one persisted world per meeting, id derived from the meeting.
No model, no clock read, no log of record text.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException

from tilo_api import deps, desk

_USER = re.compile(r"u_[0-9A-Za-z_]{1,48}")
_WORLD = re.compile(r"w_[0-9A-Za-z_]{1,48}")
_DESK_WORLD = re.compile(r"w_desk_[0-9A-Za-z_]{1,43}")
_TASK = re.compile(r"t_[0-7][0-9A-HJKMNP-TV-Z]{25}")
_MEETING = re.compile(r"mt_[0-9A-Za-z_]{1,48}")
_MESSAGE = re.compile(r"[A-Za-z0-9_]{1,64}")
_DAY = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])"
_DATE = re.compile(_DAY)
_STAMP = re.compile(_DAY + r"T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]\.[0-9]{3}Z")  # common.schema.json timestamp
MAX_FACTS = 500  # per source and person: a plate shows 200 rows and 100 parked, so more is never read
MAIL_COLLECTION = "mail_triage"
_TERMINAL = frozenset({"world.completed", "world.failed"})


def _valid(pattern: re.Pattern[str], value: Any) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _store_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="store_unavailable")


# -- mail: the triage records tilo-channels keeps for a person's connected account ----------------------------------


class FirestoreMailTriage:
    """`orgs/{org}/mail_triage/{doc}`: `{owner, message_id, category, flagged, label?, received_at, answered,
    dismissed}`, one document per triaged message, no subject, body or sender (BQ-269). Reads only, always by one
    field: `owner` for a person's rows, `message_id` for who owns a message."""

    def __init__(self, client: Any, org_id: str) -> None:
        self._client, self._org = client, org_id

    def _where(self, field: str, value: str, limit: int) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415

        query = self._client.collection(f"orgs/{self._org}/{MAIL_COLLECTION}")
        try:
            docs = [d.to_dict() for d in query.where(filter=FieldFilter(field, "==", value)).limit(limit).stream()]
        except Exception:
            raise _store_unavailable() from None  # never the library's text
        return [d for d in docs if isinstance(d, dict)]

    def rows(self, owner: str) -> tuple[list[dict[str, Any]], bool]:
        """(at most `MAX_FACTS` rows, whether there were more): one extra document is read to know."""
        found = self._where("owner", owner, MAX_FACTS + 1)
        return found[:MAX_FACTS], len(found) > MAX_FACTS

    def owner_of(self, message_id: str) -> str | None:
        found = self._where("message_id", message_id, 2)
        owner = found[0].get("owner") if len(found) == 1 else None  # two holders: ambiguous, so nobody
        return owner if _valid(_USER, owner) else None


def _mail_facts(rows: Iterable[Mapping[str, Any]], owner: str) -> list[dict[str, Any]]:
    """The plate's mail facts from triage records: this person's, unflagged, effectively `needs_reply`, well formed."""
    facts = []
    for row in rows:
        category = row.get("label") if isinstance(row.get("label"), str) else row.get("category")
        flags = (row.get("answered", False), row.get("dismissed", False))
        if (
            row.get("owner") != owner
            or row.get("flagged") is not False
            or category != "needs_reply"
            or not _valid(_MESSAGE, row.get("message_id"))
            or not _valid(_STAMP, row.get("received_at"))
            or not all(type(flag) is bool for flag in flags)
        ):
            continue
        facts.append(
            {
                "message_id": row["message_id"], "account_owner": owner, "received_at": row["received_at"],
                "flagged": False, "answered": flags[0], "dismissed": flags[1],
            }
        )  # fmt: skip
    return sorted(facts, key=lambda f: (f["received_at"], f["message_id"]))


def _mail_source(store: deps.Store) -> FirestoreMailTriage | None:
    """The triage reader over the store's own Firestore client; none (no mail rows) for an in-memory store."""
    client = getattr(getattr(store, "backend", None), "client", None)
    return None if client is None else FirestoreMailTriage(client, getattr(store, "org_id", deps.ORG_ID))


# -- the plate's sources --------------------------------------------------------------------------------------------


class StorePlateSources:
    def __init__(self, store: deps.Store) -> None:
        self._store = store
        self.truncated = False  # the mail read hit its cap (the plate builder reads this after `mail`)

    def cards(self, user_id: str) -> list[dict[str, Any]]:
        """Open cards of the runs this process holds that the person owns, and gates that name them as Approver."""
        if not _valid(_USER, user_id):
            return []
        self._store.load_owner(user_id, settle=False)
        with self._store.runs_guard:
            runs = list(self._store.runs.values())
        facts: list[dict[str, Any]] = []
        for run in runs:
            for fact in run.cards.plate_facts(user_id, limit=MAX_FACTS):
                world = self._store.worlds.get(fact["data"].get("world_id"))
                mine = fact["world_owner"] == user_id and getattr(world, "owner", None) == user_id
                if mine or (fact["approver"] == user_id and fact["data"].get("kind") == "gate"):
                    facts.append(fact)
        return sorted(facts, key=lambda f: (f["data"]["created_at"], f["data"]["id"]))[:MAX_FACTS]

    def runs(self, user_id: str) -> list[dict[str, Any]]:
        """Running or blocked runs of the worlds the person owns (PE-27), from the recorded events. The goal and date
        come from the world's stored task, else from the process's own `Run.brief` (a scheduled routine or a meeting
        host run stores no task), else the row has no title."""
        if not _valid(_USER, user_id):
            return []
        store = self._store
        store.load_owner(user_id, settle=False)
        facts = []
        for world_id in sorted(w for w, rec in list(store.worlds.items()) if rec.owner == user_id):
            world = store.worlds.get(world_id)
            state = (
                None
                if world is None or world.owner != user_id or world.paused
                else _run_state(store.events.get(world_id, []))
            )
            if state is None:
                continue
            brief = self._brief(world_id, user_id)
            goal, deadline = brief.get("goal"), brief.get("deadline")
            facts.append(
                {
                    "world_id": world_id, "world_owner": user_id, "state": state[1],
                    "goal": goal if isinstance(goal, str) and goal else None,
                    "deadline": deadline if _valid(_DATE, deadline) else None, "started_at": state[0],
                }
            )  # fmt: skip
        return sorted(facts, key=lambda f: (f["started_at"], f["world_id"]))[:MAX_FACTS]

    def _brief(self, world_id: str, user_id: str) -> Mapping[str, Any]:
        task = self._store.load_world_task(world_id)
        run = self._store.runs.get(world_id)
        for owner, brief in ((getattr(task, "owner", None), getattr(task, "brief", None)),
                             (getattr(run, "owner", None), getattr(run, "brief", None))):  # fmt: skip
            if owner == user_id and isinstance(brief, dict):
                return brief
        return {}

    def mail(self, user_id: str) -> list[dict[str, Any]]:
        triage = _mail_source(self._store)
        if triage is None or not _valid(_USER, user_id):
            return []
        rows, self.truncated = triage.rows(user_id)
        return _mail_facts(rows, user_id)


def _run_state(stream: Iterable[Mapping[str, Any]]) -> tuple[str, str] | None:
    """(started_at, "running" | "blocked") from a world's recorded events; None before `world.started` or after the end.
    Blocked while an agent has an `agent.blocked` that no `agent.recovered` or `agent.retired` of it has followed."""
    started, blocked = None, set()
    for event in stream:
        kind, actor = event.get("type"), event.get("actor")
        if kind in _TERMINAL:
            return None
        if kind == "world.started" and started is None and _valid(_STAMP, event.get("ts")):
            started = event["ts"]
        elif kind == "agent.blocked":
            blocked.add(actor)
        elif kind in ("agent.recovered", "agent.retired"):
            blocked.discard(actor)
    return None if started is None else (started, "blocked" if blocked else "running")


class StoreSourceOwners:
    def __init__(self, store: deps.Store, briefs: Any = None) -> None:
        self._store = store
        self._briefs = briefs  # the morning brief's index of message ids (MO-11), or None
        self._known: dict[tuple[str, str], str | None] = {}  # per request: one read per (kind, ref), misses too

    def owner_of(self, kind: str, ref: str) -> str | None:
        """Who owns a mail message or a request; None for anything unknown, malformed, ambiguous or of another kind."""
        if not (isinstance(kind, str) and isinstance(ref, str)):
            return None
        if (kind, ref) not in self._known:
            self._known[(kind, ref)] = self._look_up(kind, ref)
        return self._known[(kind, ref)]

    def _brief_owner(self, ref: str) -> str | None:
        return _brief_owner_of(self._briefs, ref)

    def _look_up(self, kind: str, ref: str) -> str | None:
        if kind == "mail" and _valid(_MESSAGE, ref):
            triage = _mail_source(self._store)
            owner = None if triage is None else triage.owner_of(ref)
            return owner if owner is not None else self._brief_owner(ref)
        if kind == "request" and _valid(_WORLD, ref):
            world = self._store.load_world(ref, settle=False)
            owner = getattr(world, "owner", None)
        elif kind == "request" and _valid(_TASK, ref):
            task = self._store.load_task(ref, settle=False)
            owner = getattr(task, "owner", None)
        else:
            return None
        return owner if _valid(_USER, owner) else None


# -- worlds ---------------------------------------------------------------------------------------------------------


class StoreDeskWorlds:
    """The person's Desk world is the one `desk.ensure_desk` makes (its id comes from the org and the person, it is
    never adopted from another owner); its events are what is durable, the record is made again on first use."""

    def __init__(self, store: deps.Store) -> None:
        self._store = store

    def desk_world(self, org_id: str, user_id: str) -> str:
        if org_id != deps.ORG_ID or not _valid(_USER, user_id):
            raise ValueError("no Desk world for this person")
        return desk.ensure_desk(self._store, org_id=org_id, user=user_id).world_id

    def desk_owner(self, world_id: str) -> str | None:
        held = self._store.worlds.get(world_id) if _valid(_DESK_WORLD, world_id) else None
        return held.owner if isinstance(held, deps.WorldRecord) else None


class StoreMeetingWorlds:
    """One persisted Outpost world per meeting (BQ-273): `w_mtg_<24 hex of org and meeting>`, owned by the meeting's
    owner with no districts. Asked again it answers the same id; an id already held by another owner is refused."""

    def __init__(self, store: deps.Store) -> None:
        self._store = store

    def make_meeting_world(self, *, org_id: str, owner: str, meeting_id: str) -> str:
        if org_id != deps.ORG_ID or not _valid(_USER, owner) or not _valid(_MEETING, meeting_id):
            raise ValueError("no Outpost world for this meeting")
        digest = hashlib.sha256(f"{org_id}:{meeting_id}".encode()).hexdigest()[:24]
        world_id = f"w_mtg_{digest}"
        for _ in range(2):
            held = self._store.load_world(world_id, settle=False)
            if held is not None:
                if held.owner != owner:
                    raise ValueError("that world belongs to someone else")  # never adopted
                return world_id
            try:
                record = deps.WorldRecord(owner=owner, districts={}, run_id=f"r_mtg_{digest}")
                self._store.commit(worlds={world_id: record}, create=[("worlds", world_id)])
                return world_id
            except HTTPException:  # 409 `stale`: another instance made it first; read it and check its owner
                continue
        raise _store_unavailable()


def _brief_owner_of(briefs: Any, ref: str) -> str | None:
    """MO-11: a message id that appears in exactly one person's own brief of the last 7 days belongs to that person."""
    if briefs is None:
        return None
    try:
        found = briefs.mail_owner(deps.ORG_ID, ref, datetime.now(UTC).date().isoformat())
    except Exception:  # an unreadable index vouches for nobody
        return None
    return found if _valid(_USER, found) else None


def resolve_store(request: Any) -> deps.Store:
    """The request's store through the seam as the app is wired (an override that takes no argument still works)."""
    import inspect  # noqa: PLC0415

    if request is None:
        return deps.get_store()
    seam = request.app.dependency_overrides.get(deps.get_store, deps.get_store)
    return seam(request) if inspect.signature(seam).parameters else seam()  # type: ignore[no-any-return]
