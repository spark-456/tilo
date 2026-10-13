"""FR-CHN-18b and FR-PA-06c (stacked on FR-PA-06b; FR-CHN-18, PE-09, PE-12, PE-20, SEC-03): the production plate mailer.

The tick's `plate_links.sweep` hands each person's plate to `plate_mailer.DeskPlateMailer`, which sends it through the
FR-CHN-18 `DigestService` with real adapters: the person's own standing L3 rule from the API store (pinned to their own
address, no undo window), the mail as an artifact of their own Desk world, their own record's mailbox, Desk-world
events, the outbox and the Gmail connector stub. The stub here is a fake: nothing leaves the process; fake secrets are
assembled at run time; no model, no network.
"""

from __future__ import annotations

import copy
import datetime as dt
import secrets
from types import SimpleNamespace
from typing import Any

import pytest
from _ppl11a_lib import PRIYA, SAM
from _ppl11c_lib import emitted, work_rig
from fastapi import Request
from tilo_api import deps, plate_links, plate_mailer
from tilo_channels.links import KeyRing
from tilo_channels.plate_digest import PlateDigestBuilder
from tilo_connectors import InMemoryOutboxStore
from tilo_connectors.errors import ProviderUnavailable, SideEffectRefused
from tilo_memory.artifacts import ArtifactStore, MemoryBlobBackend, MemoryMetaBackend

BASE = "https://api.tilo.example"
DESK = "w_desk_priya"
IN_WINDOW = "2026-10-06T05:00:00.000Z"  # 10:30 IST, inside 09:00 to 18:00


class FakeGmail:
    """`ConnectorRpcStub`'s outbox face: `bound(...)` is the run's copy, `hand_evidence` its case, `execute_side_effect`
    the one send (grant first). `mode` makes it fail the way connectors can."""

    needs_run = True

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.evidence: dict[str, dict[str, Any]] = {}
        self.mode = "ok"
        self.owner: str | None = None
        self._read: Any = None

    def bound(self, read_item: Any, sink: Any, owner: str) -> FakeGmail:
        self._read, self.owner = read_item, owner
        return self

    def hand_evidence(self, outbox_id: str, evidence: dict[str, Any]) -> None:
        self.evidence[outbox_id] = copy.deepcopy(evidence)

    def execute_side_effect(self, entry: dict[str, Any], grant: Any) -> None:
        grant.verify(entry["idempotency_key"])  # SEC-03: only the outbox's own dispatch
        if entry["id"] not in self.evidence:
            raise SideEffectRefused("no evidence was handed for this entry")
        if self.mode == "unavailable":
            raise ProviderUnavailable("the action may have reached connectors")
        import json  # noqa: PLC0415

        doc = json.loads(self._read(entry["item"]))
        self.sent.append(
            {"to": list(entry["recipients"]), "subject": doc["subject"], "body": doc["body_text"], "owner": self.owner}
        )


class _Screener:
    def check(self, text: str, *, content: bytes | None = None, mime_type: str | None = None) -> dict[str, Any]:
        return {"flagged": False, "reason": None}


def _policy(address: str, **over: Any) -> dict[str, Any]:
    created = "2026-10-01T09:00:00.000Z"
    scope = {"connectors": ["gmail"], "recipients": [address], "domains": [], "districts": ["D1"]}
    conds = {"no_attachments": True, "no_new_recipients": True, "no_safety_flags": True}
    hist = [{"by": PRIYA, "at": created, "change": "Created at L3", "level": "L3"}]
    pol: dict[str, Any] = {"id": "pol_plate_mail", "owner": PRIYA, "action_type": "send_email", "scope": scope}
    pol |= {"limits": {"per_day": 3, "credits": 10}, "conditions": conds, "level": "L3", "undo_window_s": 0}
    pol |= {"expiry": None, "notify_channel": "email", "team_lead_domains": []}
    return (pol | {"created_by": {"by": PRIYA, "at": created}, "changed_by": None, "history": hist}) | over


class Env(SimpleNamespace):
    rig: Any
    store: deps.Store
    outbox: InMemoryOutboxStore
    gmail: FakeGmail
    meta: MemoryMetaBackend
    builder: PlateDigestBuilder
    address: str

    def tick(self, now: str = IN_WINDOW) -> int:
        request = Request({"type": "http", "app": self.rig.app, "headers": [], "method": "POST", "path": "/"})
        return plate_links.sweep(request, now)


def _env(people_rig: Any, monkeypatch: pytest.MonkeyPatch, *, policy: dict[str, Any] | None | str = "default") -> Env:
    rig = work_rig(people_rig)
    monkeypatch.setenv(plate_links.ENV_DIGEST, "1")
    address = rig.stored("persons", PRIYA)["email"]
    store = rig.event_store
    store.worlds[DESK] = deps.WorldRecord(owner=PRIYA, districts={}, run_id="r_desk_priya")
    if policy == "default":
        policy = _policy(address)
    if isinstance(policy, dict):
        store.policies[policy["id"]] = policy
    meta, outbox, gmail = MemoryMetaBackend(), InMemoryOutboxStore(), FakeGmail()
    artifacts = ArtifactStore(
        meta, MemoryBlobBackend(), clock=lambda: dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC),
        redactor=deps.get_redactor(), archive_lookup=lambda scope, ref: None, alert_sink=lambda alert: None,
        screener=_Screener(),
    )  # fmt: skip
    builder = PlateDigestBuilder(
        base_url=BASE,
        keys=KeyRing({"k_test": secrets.token_bytes(32)}, active="k_test"),
        nonces=plate_links.MemoryNonces(),
    )
    ov = rig.app.dependency_overrides
    ov[deps.get_store] = lambda: store
    ov[deps.get_outbox_store] = lambda: outbox
    ov[deps.get_connector_adapters] = lambda: {"gmail": gmail}
    ov[deps.get_artifact_store] = lambda: artifacts
    ov[plate_links.get_link_builder] = lambda: builder
    return Env(rig=rig, store=store, outbox=outbox, gmail=gmail, meta=meta, builder=builder, address=address)


def test_FR_CHN_18b_the_plate_goes_to_the_owners_own_mailbox_through_policy_and_outbox_once_a_day(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)

    assert env.tick() == 1  # Priya holds the standing rule; nobody else in the org does
    (mail,) = env.gmail.sent
    assert mail["to"] == [env.address] and mail["owner"] == PRIYA and mail["subject"] == "Your plate (2026-10-06)"
    assert "Your plate for 2026-10-06" in mail["body"] and f"{BASE}/l/" in mail["body"]
    (entry,) = env.outbox.all_entries()
    assert entry["state"] == "sent" and entry["world_id"] == DESK and entry["recipients"] == [env.address]
    assert entry["authz"]["by"] == "policy" and entry["authz"]["ref"] == "pol_plate_mail"
    assert entry["idempotency_key"] == "plate_digest:u_priya:2026-10-06" and entry["undo_window_s"] == 0

    assert [(w, p["type"]) for w, p in emitted(env.rig)] == [(DESK, "policy.applied"), (DESK, "data.transfer")]
    applied, transfer = (p for _w, p in emitted(env.rig))
    assert applied["vis"] == [] and transfer["vis"] == []  # PE-12: the Desk world is owner-only
    assert applied["authz"] == transfer["authz"] == entry["authz"]
    assert "@" not in repr(applied) and "@" not in repr(transfer)  # recipients stay in the entry, never an event

    assert env.tick("2026-10-06T06:00:00.000Z") == 0 and len(env.gmail.sent) == 1  # one a day (idempotency key)
    assert env.tick("2026-10-07T05:00:00.000Z") == 1 and len(env.gmail.sent) == 2  # the next UTC day goes again


def test_FR_CHN_18b_the_mail_is_an_artifact_of_the_persons_own_desk_world_with_its_links_intact(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    assert env.tick() == 1

    paths = env.meta.paths("")
    assert paths and all(f"/worlds/{DESK}/" in p for p in paths)  # never a shared or run world (SEC-REVIEW-6)
    body = env.gmail.sent[0]["body"]
    assert deps.get_redactor()(body) == body  # the store's redactor leaves Tilo's own bearer links as they are
    links = [line.split(": ", 1)[1] for line in body.splitlines() if line.strip().startswith(("Done:", "Snooze:"))]
    assert links and all(link.startswith(f"{BASE}/l/") for link in links)


@pytest.mark.parametrize(
    "policy",
    [
        None,
        {
            "scope": {
                "connectors": ["gmail"],
                "recipients": ["someone.else@example.com"],
                "domains": [],
                "districts": ["D1"],
            }
        },
        {"undo_window_s": 60},
        {"level": "L2"},
        {"scope": {"connectors": ["google_drive"], "recipients": [], "domains": [], "districts": ["D1"]}},
        {"owner": SAM},
    ],
    ids=["no_policy", "other_recipient", "undo_window", "l2", "other_connector", "someone_elses"],
)
def test_FR_CHN_18b_without_the_persons_own_pinned_l3_rule_nothing_is_built_stored_or_sent(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch, policy: dict[str, Any] | None
) -> None:
    env = _env(people_rig, monkeypatch, policy=None)
    if policy is not None:
        env.store.policies["pol_plate_mail"] = _policy(env.address, **policy)

    assert env.tick() == 0
    assert env.gmail.sent == [] and env.outbox.all_entries() == []
    assert env.meta.paths("") == [] and emitted(env.rig) == [] and env.gmail.evidence == {}


def test_FR_CHN_18b_a_rule_with_extra_recipients_is_not_the_pinned_rule(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch, policy=None)
    wide = _policy(env.address)
    wide["scope"]["recipients"] = [env.address, "attacker@example.com"]
    env.store.policies[wide["id"]] = wide

    assert env.tick() == 0 and env.gmail.sent == [] and env.outbox.all_entries() == []


def test_FR_CHN_18b_a_changed_mailbox_no_longer_matches_the_pinned_rule_and_a_paused_desk_sends_nothing(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    env.store.worlds[DESK].paused = True
    assert env.tick() == 0 and env.gmail.sent == [] and env.outbox.all_entries() == []

    env.store.worlds[DESK].paused = False
    env.store.policies["pol_plate_mail"] = _policy("old.address@example.com")  # the person's address is not it now
    assert env.tick() == 0 and env.gmail.sent == []


def test_FR_PA_06c_a_send_that_may_have_gone_out_is_never_failed_or_repeated_and_is_told_to_a_person_once(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    env.gmail.mode = "unavailable"

    assert env.tick() == 0 and env.gmail.sent == []
    (entry,) = env.outbox.all_entries()
    assert entry["state"] != "failed" and env.outbox.retry_state(entry["id"])["ambiguous"] is True
    alerts = [p for _w, p in emitted(env.rig) if p["type"] == "alert.raised"]
    assert len(alerts) == 1 and alerts[0]["vis"] == [] and alerts[0]["data"]["card_id"] is None

    env.gmail.mode = "ok"
    assert env.tick("2026-10-06T05:05:00.000Z") == 0 and env.gmail.sent == []  # same day: never sent twice
    assert len(env.outbox.all_entries()) == 1


def test_FR_PA_06c_a_refused_send_is_final_and_the_day_does_not_retry(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    env.gmail.evidence = {}
    monkeypatch.setattr(FakeGmail, "hand_evidence", lambda self, outbox_id, evidence: None)  # no evidence reaches it

    assert env.tick() == 0 and env.gmail.sent == []
    (entry,) = env.outbox.all_entries()
    assert entry["state"] == "failed"
    assert [p["type"] for _w, p in emitted(env.rig) if p["type"] == "alert.raised"] == []


def test_FR_PA_06c_the_tick_is_off_without_the_switch_in_a_demo_and_without_a_connector(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    monkeypatch.delenv(plate_links.ENV_DIGEST)
    assert env.tick() == 0 and env.gmail.sent == []  # the switch is the user's: off by default

    monkeypatch.setenv(plate_links.ENV_DIGEST, "1")
    env.rig.app.dependency_overrides[deps.get_connector_adapters] = lambda: {}  # dev, CI, a demo: no live connector
    assert env.tick() == 0 and env.gmail.sent == [] and env.outbox.all_entries() == []

    env.rig.app.dependency_overrides[deps.get_connector_adapters] = lambda: {"gmail": object()}  # not the stub
    assert env.tick() == 0


def test_FR_PA_06c_a_failure_inside_the_mailer_is_a_plain_false_with_nothing_sent(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = _env(people_rig, monkeypatch)
    mailer = plate_mailer.production_mailer(env.rig.app.dependency_overrides)

    def boom(*_: Any, **__: Any) -> bool:
        raise RuntimeError("store down for " + PRIYA)

    monkeypatch.setattr(mailer, "_deliver", boom)
    assert mailer.deliver(PRIYA, {"rows": [], "user": PRIYA}, now=IN_WINDOW) is False  # never raises into the tick
    assert env.gmail.sent == [] and env.outbox.all_entries() == []


def test_FR_CHN_18b_the_events_commit_through_the_real_world_writer_in_the_desk_world(
    people_rig: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_api.world_writer import WorldWriterAdapter  # noqa: PLC0415
    from tilo_harness.store import MemoryStore  # noqa: PLC0415

    env = _env(people_rig, monkeypatch)
    real = WorldWriterAdapter(env.store, MemoryStore(), clock=lambda: dt.datetime(2026, 10, 6, 10, 0, tzinfo=dt.UTC))
    env.rig.app.dependency_overrides[deps.get_event_writer] = lambda: real

    assert env.tick() == 1 and len(env.gmail.sent) == 1
    kinds = [e["type"] for e in env.store.events[DESK]]
    assert kinds == ["policy.applied", "data.transfer"]
    assert all(e["vis"] == [] and e["authz"]["by"] == "policy" for e in env.store.events[DESK])
