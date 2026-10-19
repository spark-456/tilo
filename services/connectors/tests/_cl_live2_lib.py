"""Test doubles for the CL-LIVE-2 tests (real Google WRITES behind the outbox and a typed approval). API pinned in
API_CL_LIVE_2.md. No production code, no network, no real token: the fake Google is `_gapi_lib.FakeGoogleApis` (it
keeps drafts, sent mail and Drive files, can lose a response, and records every request).

`WriteEnv.build(...)` is `real_adapters(..., allow_writes=...)` on a real TokenBroker; `WriteEnv.approve(case)` is the
typed `yes` a person gives at the terminal for a case's gate card; `WriteEnv.run(case)` is enqueue + dispatch_due.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from _cl_live_lib import (
    CALENDAR_READONLY,
    CONNECTORS_YAML,
    DRIVE_FILE,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    LIVE_ENV,
)
from _cl_live_lib import clean_process_env as clean_process_env  # autouse fixture
from _cl_live_lib import socket_guard as socket_guard  # autouse fixture
from _gapi_lib import FakeArtifacts, FakeGoogleApis, ScopeSpy, drive_case, enqueue, gmail_case
from _oauth_lib import OWNER, make_env

STAND_IN = "thread-dev-1"  # the run's dev destination (tilo_api.dev_run.DEV_DESTINATION)
SECRET = "sk-" + "A1b2C3d4" * 3  # a secret-shaped string assembled at runtime; the fake redactor removes it


def redact(text: str) -> str:
    return text.replace(SECRET, "[redacted]")


@dataclass
class WriteEnv:
    env: Any
    apis: FakeGoogleApis
    registry: Any
    spy: ScopeSpy
    artifacts: FakeArtifacts
    emitted: list[dict] = field(default_factory=list)
    adapters: dict[str, Any] = field(default_factory=dict)
    gate: Any = None
    outbox: Any = None

    def build(self, **over: Any) -> dict[str, Any]:
        from tilo_connectors import real
        from tilo_connectors.adapters import InMemoryPicks
        from tilo_connectors.outbox import Outbox, RetryPolicy
        from tilo_connectors.store import InMemoryOutboxStore

        kwargs: dict[str, Any] = {
            "user_id": OWNER,
            "environ": dict(LIVE_ENV),
            "clock": self.env.clock,
            "emit": self.emitted.append,
            "picks": InMemoryPicks(),
            "sleep": lambda _seconds: None,
            "allow_writes": True,
        }
        registry = over.pop("registry", self.registry)
        kwargs.update(over)
        self.adapters = real.real_adapters(self.spy, registry, self.apis, **kwargs)
        self.gate = real.write_gate_of(self.adapters)
        if self.gate is not None:
            self.gate.bind(lambda _world, ref, _kind: self.artifacts.get(ref["artifact_id"], ref["version"]), redact)
        retry = RetryPolicy(max_delay_s=0, clock_skew_s=0, ambiguous_delay_s=0, backoff_base_s=0)
        self.outbox = Outbox(InMemoryOutboxStore(), self.adapters, emit=self.emitted.append, clock=self.env.clock,
                             retry=retry)  # fmt: skip
        return self.adapters

    def email(self, **over: Any) -> dict:
        ref = self.artifacts.put_email("art_mail_" + str(len(self.artifacts._items)), **over)
        return ref

    def mail_case(self, action: str = "create_draft", **over: Any) -> dict:
        ref = over.pop("item", None) or self.email()
        return gmail_case(action_type=action, item=ref, destination=STAND_IN, **over)

    def drive_case(self, **over: Any) -> dict:
        ref = self.artifacts.put_file(
            "art_file_" + str(len(self.artifacts._items)), name="notes.txt", mime_type="text/plain", content=b"hello"
        )
        return drive_case(item=ref, destination=STAND_IN, **over)

    @staticmethod
    def card(case: dict) -> dict:
        """The gate card the run shows for this case: what `tilo_api` puts in `card["gate"]` (runs.py)."""
        entry = case["entry"]
        action = {"type": entry["action_type"], "connector": entry["connector"], "exact": "...", "item": entry["item"],
                  "destination": entry["destination"]}  # fmt: skip
        return {"world_id": entry["world_id"], "gate": {"action": action, "recipients": entry["recipients"],
                                                         "risk_tier": entry["risk_tier"]}}  # fmt: skip

    def approve(self, case: dict, *, said: str = "yes", interactive: bool = True) -> bool:
        review = self.gate.review(self.card(case))
        assert review is not None
        return bool(self.gate.approve(review, said=said, interactive=interactive))

    def run(self, case: dict) -> list[dict]:
        enqueue(self.outbox, case)
        return self.outbox.dispatch_due()

    def state(self, case: dict) -> str:
        return str(self.outbox.get(case["entry"]["id"])["state"])

    def posts(self, suffix: str) -> list[Any]:
        return [r for r in self.apis.requests if r.method == "POST" and r.url.endswith(suffix)]

    def scopes_asked(self) -> set[str]:
        return {s for _u, _c, scopes in self.spy.asked for s in scopes}


def make_write_env(*, send: bool = False, calendar: bool = True, compose: bool = True) -> WriteEnv:
    from tilo_connectors.registry import load_registry

    env = make_env()
    gmail = [GMAIL_READONLY, *([GMAIL_COMPOSE] if compose else []), *([GMAIL_SEND] if send else [])]
    env.connect(OWNER, "gmail", gmail)
    env.connect(OWNER, "google_drive", [DRIVE_FILE])
    if calendar:
        env.connect(OWNER, "google_calendar", [CALENDAR_READONLY])
    return WriteEnv(
        env, FakeGoogleApis(env.google), load_registry(CONNECTORS_YAML), ScopeSpy(env.broker), FakeArtifacts()
    )


def second_case(case: dict, *, key: str) -> dict:
    """The same payload under another idempotency key and outbox id: a second attempt to write the same thing."""
    other = copy.deepcopy(case)
    other["entry"]["idempotency_key"] = key
    other["entry"]["id"] = case["entry"]["id"][:-4] + "7777"
    for part in ("reserved_by", "authorised_by"):
        other[part]["data"]["outbox_id"] = other["entry"]["id"]
    return other
