"""Request authority connects the durable draft store to the production preview factory."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from _ppl11a_lib import OWNER
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from test_FR_MTG_08_owner_followup import followup, replace, run  # noqa: F401
from tilo_api import deps
from tilo_api.draft_firestore import FirestoreDraftStore
from tilo_api.followup_autopilot_factory import build_factory
from tilo_api.people_writes import Refusal
from tilo_connectors import InMemoryOutboxStore
from tilo_people.stores import meeting_tombstone


def epoch(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


@pytest.fixture
def durable(followup, monkeypatch):  # noqa: F811
    c = followup
    c.db, c.box, c.publications, c.bindings = FakeFirestore(), InMemoryOutboxStore(), [], []
    c.raw = c.drafts = FirestoreDraftStore(c.db, org_id=c.rig.org)
    c.run_id = c.rig.event_store.worlds[c.meeting["world_id"]].run_id
    original_head = c.rig.artifacts.head
    c.metadata = {}
    c.retention_days = 90
    monkeypatch.setattr("tilo_api.meeting_followup.retention_days", lambda entity: c.retention_days, raising=False)

    def head(scope, ref):
        result = original_head(scope, ref)
        if result is None:
            return None
        doc = {**result.doc, **c.metadata}
        for key in c.missing:
            doc.pop(key, None)
        return SimpleNamespace(doc=doc)

    c.missing = set()
    monkeypatch.setattr(c.rig.artifacts, "head", head)
    original_bind = c.raw.bind

    def bind(**kwargs):
        bound = original_bind(**kwargs)
        c.bindings.append((kwargs, bound))
        return bound

    monkeypatch.setattr(c.raw, "bind", bind)
    owner = SimpleNamespace(
        principal=deps.Principal(OWNER, "owner"),
        request=c.request,
        store=c.rig.event_store,
        clock=lambda: c.writer.now,
    )
    factory = build_factory(owner, client=c.db, outbox_store=c.box, drafts=c.raw)

    def capture(world, run_id, owner, publication):
        c.publications.append(publication)
        return factory(world, run_id, owner, publication)

    c.factory = capture
    return c


def no_publication(c):
    assert c.db.docs == {} and c.box.all_entries() == [] and c.line.api.sent == []


@pytest.mark.parametrize("field", ["run_id", "screening"])
def test_FR_MTG_08_request_missing_artifact_metadata_is_controlled_refusal(durable, field):
    c = durable
    c.missing.add(field)
    with pytest.raises(Refusal) as refused:
        run(c)
    assert refused.value.status_code == 409 and refused.value.detail == "minutes_unavailable"
    assert c.calls == []
    no_publication(c)


def test_FR_MTG_08_request_binds_once_and_factory_reads_same_durable_store(durable):
    c = durable
    first = run(c)
    assert first.tier == "T3" and first.level == "L1"
    assert len(c.bindings) == 1
    kwargs, bound = c.bindings[0]
    assert c.publications[0].drafts is bound and bound is not c.raw
    assert kwargs["owner"] == OWNER
    source = kwargs["source"]
    assert source["org_id"] == c.rig.org and source["owner"] == OWNER
    assert source["world_id"] == c.meeting["world_id"] and source["run_id"] == c.run_id
    assert source["meeting_id"] == "mt_q4_plan" and source["minutes"] == c.meeting["minutes"]
    assert c.meeting["minutes_confirmed_by"] in source.values()
    assert any(isinstance(v, str) and len(v) == 64 for v in source.values())
    assert callable(kwargs["before_publication"])
    assert kwargs["clock"]() == epoch(c.writer.now)
    assert run(c).card_id == first.card_id and len(c.calls) == 1
    rows = [row for path, row in c.db.docs.items() if "/followup_drafts/" in path]
    assert rows and all(row["source"] == source for row in rows)
    assert c.box.all_entries() == [] and c.line.api.sent == []
    with pytest.raises(HTTPException) as caught:
        c.raw.get(OWNER, "arbitrary")
    assert caught.value.status_code == 503


@pytest.mark.parametrize("artifact_first", [True, False])
def test_FR_MTG_08_request_deadline_is_earlier_retention_bound(durable, artifact_first):
    c = durable
    c.metadata.update(created_at=c.writer.now)
    c.retention_days = 1 if artifact_first else 365
    run(c)
    expected = min(epoch(c.meeting["delete_minutes_after"]), epoch(c.writer.now) + c.retention_days * 86400)
    assert c.bindings[0][0]["expires_at"] == expected


@pytest.mark.parametrize(
    "invalid",
    ["missing_days", "missing_date", "nan", "negative", "bool", "expired", "bad_date", "wrong_run"],
)
def test_FR_MTG_08_request_invalid_artifact_retention_denies_before_provider(durable, invalid):
    c = durable
    if invalid == "missing_days":
        c.retention_days = None
    elif invalid == "missing_date":
        c.missing.add("created_at")
    elif invalid == "bad_date":
        c.metadata["created_at"] = "not-a-time"
    elif invalid == "wrong_run":
        c.metadata["run_id"] = "r_other"
    elif invalid == "expired":
        c.metadata.update(created_at="2020-01-01T00:00:00.000Z")
    else:
        c.retention_days = {"nan": float("nan"), "negative": -1, "bool": True}[invalid]
    with pytest.raises(Refusal):
        run(c)
    assert c.calls == []
    no_publication(c)


@pytest.mark.parametrize("change", ["meeting", "artifact", "run"])
def test_FR_MTG_08_request_rechecks_deletion_and_scope_after_generation(durable, change):
    c = durable

    def invalidate():
        if change == "meeting":
            replace(c, "meetings", "mt_q4_plan", **meeting_tombstone(c.meeting))
        elif change == "artifact":
            c.metadata.update(created_at="2020-01-01T00:00:00.000Z")
        else:
            c.metadata["run_id"] = "r_other"

    c.during.append(invalidate)
    with pytest.raises(Refusal):
        run(c)
    assert len(c.calls) == 1
    no_publication(c)


def test_FR_MTG_08_factory_requires_request_bound_drafts_in_publication(durable):
    c = durable
    owner = SimpleNamespace(
        principal=deps.Principal(OWNER, "owner"),
        request=c.request,
        store=c.rig.event_store,
        clock=lambda: c.writer.now,
    )
    factory = build_factory(owner, client=c.db, outbox_store=c.box, drafts=c.raw)

    class MissingDrafts:
        drafts = None

        def __call__(self, part):
            raise AssertionError("source-free publication")

        def before_publication(self):
            pass

    with pytest.raises(HTTPException) as caught:
        factory(c.meeting["world_id"], c.run_id, OWNER, MissingDrafts())
    assert caught.value.status_code == 503
    no_publication(c)
