"""DEMO-EPHEMERAL-1 helpers: recording fakes behind the durable seams, and a run flow whose storage seams are the
app's own defaults (not overrides), so what a demo or a Google principal reaches is decided by tilo-api itself.

`Spy` wraps a durable backend and records the name of every method called on it. `WRITES` are the names that change
state in the records backend (`commit`, `ack`) and in the events store (`transact`); an ephemeral session must leave
all of them uncalled. Nothing here is a secret and no network is used."""

from __future__ import annotations

import dataclasses
from typing import Any

from _clint2_lib import MOCK_ID
from tilo_api import deps, durable_store, ephemeral
from tilo_api.durable_store import DurableStore, MemoryBackend
from tilo_api.world_writer import WorldWriterAdapter
from tilo_connectors import InMemoryOutboxStore
from tilo_harness.store import MemoryStore

WRITES = frozenset({"commit", "ack", "transact"})


class Spy:
    def __init__(self, inner: Any) -> None:
        self.inner, self.calls = inner, []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def call(*args: Any, **kwargs: Any) -> Any:
            self.calls.append(name)
            return attr(*args, **kwargs)

        return call

    def writes(self) -> list[str]:
        return [c for c in self.calls if c in WRITES]


class SpyOutbox(InMemoryOutboxStore):
    """The process-wide outbox a Google session uses: counts what is inserted."""

    def __init__(self) -> None:
        super().__init__()
        self.inserts = 0

    def _insert_if_absent(self, entry: dict) -> bool:
        self.inserts += 1
        return super()._insert_if_absent(entry)


class Durable:
    """The 'deployed' store: a `DurableStore` over spied memory backends, installed where `deps.get_store` and
    `deps.get_event_writer` look for it (`durable_store.deployed`)."""

    def __init__(self, monkeypatch: Any) -> None:
        self.records, self.events = Spy(MemoryBackend()), Spy(MemoryStore())
        self.store = DurableStore(self.records, self.events, org_id=deps.ORG_ID)
        self.store.writer = WorldWriterAdapter(self.store, self.events, org_id=deps.ORG_ID)
        monkeypatch.setattr(durable_store, "deployed", lambda: (self.store, self.store.writer))

    def writes(self) -> list[str]:
        return self.records.writes() + self.events.writes()


def install_run_seams(rf: Any, monkeypatch: Any, outbox: SpyOutbox) -> None:
    """Moves the run flow's storage seams from dependency overrides to the module defaults, as production has them:
    the app picks what a demo gets; a Google session gets these recording fakes."""
    ov = rf.app.dependency_overrides
    for seam in (
        deps.get_store, deps.get_event_writer, deps.get_outbox_store, deps.get_artifact_store, deps.get_redactor,
        deps.get_run_archive, deps.get_connector_adapters,
    ):  # fmt: skip
        ov.pop(seam, None)
    monkeypatch.setattr(deps, "get_outbox_store", lambda: outbox)
    monkeypatch.setattr(deps, "get_artifact_store", lambda request=None: rf.rig.store)
    monkeypatch.setattr(deps, "get_redactor", lambda request=None: rf.rig.redactor)
    monkeypatch.setattr(deps, "get_run_archive", lambda request=None: rf.rig.open_archive)
    monkeypatch.setattr(deps, "get_connector_adapters", lambda: {MOCK_ID: rf.adapter})


def as_session(rf: Any, store: Any, **flags: bool) -> None:
    """Every request of this flow is the owner's, with these session flags (`demo_session` or `full_session`)."""
    rf.flow.store = rf.store = store

    def as_member(
        user_id: str = rf.flow.principal.user_id, role: str = "owner", districts: tuple[str, ...] = ()
    ) -> None:
        rf.flow._deny = False
        rf.flow.principal = deps.Principal(
            user_id=user_id,
            role=role,
            world_id=rf.world_id or None,
            districts=districts,
            **flags,  # type: ignore[arg-type]
        )

    rf.as_member = as_member
    rf.flow.principal = dataclasses.replace(rf.flow.principal, **flags)


def fresh_registry(**limits: Any) -> ephemeral.Registry:
    return ephemeral.configure(**limits)
