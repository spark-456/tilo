"""PEOPLE-SEAMS-1 helpers (services/api/tests/API_PEOPLE_SEAMS_1.md): a `DurableStore` over a memory backend that also
holds a tiny Firestore-shaped client for the mail triage collection, runs with real `CardStore`s, and a mail-client
fake. No network, no credentials."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from _api_lib import ulid
from _cards_lib import FakeClock, clone_card, load_valid_card, new_ulid
from _pw1b_lib import OTHER, OWNER, PwRig, make_rig, task, world
from tilo_api import deps, seams_store
from tilo_api.cards import CardStore
from tilo_api.durable_store import DurableStore, MemoryBackend
from tilo_api.world_writer import WorldWriterAdapter

NOW = "2026-09-29T09:31:00.000Z"
STAMP = "2026-10-08T09:00:00.000Z"
W1, W2, W3, W4, W5 = (f"w_ps1_{n}" for n in "abcde")
MAIL = f"orgs/{deps.ORG_ID}/{seams_store.MAIL_COLLECTION}"


class _Snap:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class _Query:
    def __init__(self, client: MailClient, path: str, flt: Any = None, cap: int | None = None) -> None:
        self.client, self.path, self.flt, self.cap = client, path, flt, cap

    def where(self, *, filter: Any) -> _Query:  # noqa: A002 - the library's keyword
        return _Query(self.client, self.path, filter, self.cap)

    def limit(self, count: int) -> _Query:
        return _Query(self.client, self.path, self.flt, count)

    def stream(self) -> Any:
        if self.client.fail:
            raise RuntimeError("secret store text: tok_abcdefghijklmnopqrstuvwxyz0123456789ABCDEF")
        assert self.flt is not None, "a mail read is always by one field"
        self.client.queries.append((self.path, self.flt.field_path, self.flt.value, self.cap))
        rows = [d for d in self.client.docs.get(self.path, []) if d.get(self.flt.field_path) == self.flt.value]
        return iter([_Snap(d) for d in rows[: self.cap]])


class MailClient:
    """The slice of a Firestore client the mail reader uses: `collection(path).where(filter=).limit(n).stream()`."""

    def __init__(self, docs: list[dict[str, Any]] | None = None) -> None:
        self.docs: dict[str, list[dict[str, Any]]] = {MAIL: list(docs or [])}
        self.queries: list[tuple[str, str, str, int | None]] = []
        self.fail = False

    def collection(self, path: str) -> _Query:
        return _Query(self, path)


class ClientBackend(MemoryBackend):
    """A memory records backend that also carries the Firestore-shaped client the mail reader looks for."""

    def __init__(self, client: MailClient | None = None) -> None:
        super().__init__()
        self.client = client if client is not None else MailClient()


def mail_doc(owner: str, message_id: str, **over: Any) -> dict[str, Any]:
    base = {
        "owner": owner, "message_id": message_id, "category": "needs_reply", "flagged": False,
        "received_at": STAMP, "answered": False, "dismissed": False,
    }  # fmt: skip
    return base | over


def rig_with_mail(docs: list[dict[str, Any]] | None = None) -> tuple[PwRig, MailClient]:
    client = MailClient(docs)
    rig = make_rig("memory")
    rig.backend = ClientBackend(client)
    return rig, client


def process(rig: PwRig) -> DurableStore:
    store, _ = rig.process()
    return store


def seed_world(store: DurableStore, world_id: str, owner: str, *, goal: str | None = "Compare prices", **brief: Any):
    """A world of `owner` with its task (the brief's goal and date) saved to the backend."""
    made = {"goal": goal, "deadline": brief.pop("deadline", None), **brief}
    tid = "t_" + ulid(int(world_id[-1], 36))
    record = task(world_id, owner=owner, brief=made, draft=made)
    store.commit(
        worlds={world_id: world(owner=owner)}, tasks={tid: record}, create=[("worlds", world_id), ("tasks", tid)]
    )
    return tid


def ev(kind: str, ts: str = STAMP, actor: str = "A_director") -> dict[str, Any]:
    return {"type": kind, "ts": ts, "actor": actor}


def run_with_cards(store: DurableStore, world_id: str, owner: str, clock: FakeClock) -> CardStore:
    """A run's `CardStore` the way `runs.Run` builds one, registered in the process's runs."""
    cards = CardStore(clock=clock, writer=SimpleNamespace(write=lambda part: None), world_owners={world_id: owner})
    store.runs[world_id] = SimpleNamespace(cards=cards, owner=owner)
    return cards


def card(world_id: str, n: int, *, name: str = "gate_send_reply", created_at: str = "2026-09-29T09:30:00.000Z") -> dict:
    out = clone_card(load_valid_card(name), id_=new_ulid(f"ps1-{n}"), created_at=created_at)
    out["world_id"] = world_id
    return out


GATE_OUTBOX = ulid(7)
__all__ = [
    "GATE_OUTBOX", "OTHER", "OWNER", "NOW", "STAMP", "W1", "W2", "W3", "W4", "W5", "WorldWriterAdapter",
    "card", "ev", "mail_doc", "process", "rig_with_mail", "run_with_cards", "seed_world",
]  # fmt: skip
