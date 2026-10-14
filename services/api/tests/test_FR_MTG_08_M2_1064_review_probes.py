"""Independent exact-1064 probes; no network, production edits or M1 acceptance file edits."""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _chn_wire1_lib import resolved
from _ppl11a_lib import OWNER
from fastapi import HTTPException
from test_ACT_1_cleanup import Indexed, cleanup  # noqa: F401
from test_ACT_1_state_retention import retained  # noqa: F401
from test_FR_MTG_03_minutes_publication import publication, publish  # noqa: F401
from test_FR_MTG_08_owner_followup import followup, run  # noqa: F401
from test_FR_MTG_08_owner_followup_boundaries import remove_minutes
from test_FR_MTG_08_request_binding import durable  # noqa: F401
from tilo_api import deps
from tilo_api.followup_autopilot_factory import build_factory
from tilo_api.outbox_firestore import FirestoreOutboxStore


@pytest.mark.parametrize("target", ["draft", "card", "stop"])
def test_FR_MTG_08_M2_sdk_late_write_after_completed_owner_erasure(cleanup, monkeypatch, target):  # noqa: F811
    c = cleanup
    document = c.db.document
    raced = []

    def lookup(path):
        ref = document(path)
        create = ref.create

        def delayed_create(row):
            if not raced:
                raced.append(True)
                c.alive = False
                for policy in c.policies:
                    policy.erase_owner_complete(OWNER)
                assert c.db.docs == {}
            return create(row)

        ref.create = delayed_create
        return ref

    monkeypatch.setattr(c.db, "document", lookup)
    operation = {
        "draft": lambda: c.drafts.create(OWNER, "late", {"body": "private minutes"}),
        "card": lambda: c.cards.create(OWNER, "late", {"body": "private minutes"}),
        "stop": lambda: c.stops.add(OWNER, "late"),
    }[target]
    with pytest.raises(HTTPException):
        operation()
    assert raced and c.db.docs == {}, "completed erasure must not leave resurrected source-owned rows"


def test_FR_MTG_03_M2_committed_minutes_survive_lost_CAS_ack(publication, monkeypatch):  # noqa: F811
    rig, _, scope, _ = publication
    replace = rig.stores.meetings.replace

    def lose_ack(record, *, expected_version):
        replace(record, expected_version=expected_version)
        raise RuntimeError("offline acknowledgement lost after successful CAS")

    monkeypatch.setattr(rig.stores.meetings, "replace", lose_ack)
    with pytest.raises(RuntimeError):
        publish(publication)
    stored = rig.stored("meetings", "mt_q4_plan")
    assert stored["minutes"] is not None
    assert rig.artifacts.head(scope, stored["minutes"]) is not None, "authoritative pointer must not dangle"


def production_preview(c):
    c.box = FirestoreOutboxStore(c.db)
    owner = SimpleNamespace(
        principal=deps.Principal(OWNER, "owner"),
        request=c.request,
        store=c.rig.event_store,
        clock=lambda: c.writer.now,
    )
    factory = build_factory(owner, client=c.db, outbox_store=c.box, drafts=c.raw)

    def capture(world, run_id, user, emit):
        c.ap = factory(world, run_id, user, emit)
        return c.ap

    c.factory = capture
    card = run(c)
    gate = c.ap.approval_requested(OWNER, card.card_id)
    return card, resolved(gate, c.line, ref=OWNER, at=c.writer.now)


@pytest.mark.parametrize("authority", ["absent", "agent", "foreign", "person"])
def test_FR_MTG_08_M2_real_durable_outbox_person_evidence(durable, authority):  # noqa: F811
    c = durable
    card, approval = production_preview(c)
    assert card.tier == "T3" and card.level == "L1"
    assert not [p for p in c.db.docs if p.startswith("outbox/")]
    if authority == "absent":
        approval = None
    elif authority != "person":
        approval["authz"].update(
            by="agent" if authority == "agent" else "person", ref="a_test" if authority == "agent" else "u_foreign"
        )
    outcome = c.ap.send(OWNER, card.card_id, approval=approval)
    assert outcome.status == ("queued" if authority == "person" else "refused")
    assert len([p for p in c.db.docs if p.startswith("outbox/")]) == (1 if authority == "person" else 0)
    assert c.line.api.sent == []


def test_FR_MTG_08_M2_source_revocation_inside_outbox_insert_never_queues(durable, monkeypatch):  # noqa: F811
    c = durable
    card, approval = production_preview(c)
    insert = c.box._insert_if_absent
    insert_calls = []

    def delayed_insert(entry):
        # Existing inner store may wait after the outer guard; deletion closes the source while the world stays valid.
        remove_minutes(c, "metadata")
        insert_calls.append(entry["id"])
        return insert(entry)

    monkeypatch.setattr(c.box, "_insert_if_absent", delayed_insert)
    with pytest.raises(HTTPException):
        c.ap.send(OWNER, card.card_id, approval=approval)
    assert len(insert_calls) == 1
    entries = [d["entry"] for p, d in c.db.docs.items() if p.startswith("outbox/")]
    assert not [e for e in entries if e["state"] in ("queued", "scheduled", "sending")], (
        f"stale source left queued outbox; factory halted={c.ap._ledger._outbox._inner._halted()}"
    )
    assert c.line.api.sent == []


@pytest.mark.parametrize("cap", [0, -1, float("nan"), True])
def test_FR_MTG_08_M2_durable_capped_request_never_generates_or_publishes(durable, cap):  # noqa: F811
    c = durable
    c.allowance_cap = cap
    with pytest.raises(HTTPException) as refused:
        run(c)
    assert refused.value.status_code == 429
    assert c.calls == [] and c.db.docs == {} and c.box.all_entries() == []


@pytest.mark.parametrize("override", [None, "0", "true"])
def test_FR_MTG_03_08_M2_default_closed_real_startup(override):
    env = dict(os.environ)
    env.pop("LIVE", None)
    env.pop("TILO_RECORD", None)
    env.pop("TILO_MEETING_MINUTES_ENABLED", None)
    if override is not None:
        env["TILO_MEETING_MINUTES_ENABLED"] = override
    command = (
        "from tilo_api import app, deps; import json; "
        "print('CHECK=' + json.dumps([deps.get_flag_store().get('meeting.minutes.enabled'), "
        "list(app.openapi()['paths'])]))"
    )
    done = subprocess.run([sys.executable, "-c", command], env=env, capture_output=True, text=True, timeout=45)
    assert done.returncode == 0, done.stderr
    state = json.loads(next(line[6:] for line in done.stdout.splitlines() if line.startswith("CHECK=")))
    assert state[0] is False
    assert not [p for p in state[1] if p.endswith(("/analyze-minutes", "/draft-followup"))]


def test_FR_MTG_08_M2_actual_cleanup_filters_match_ACT1_declarations(cleanup):  # noqa: F811
    c = cleanup
    for policy in c.policies:
        policy.erase_owner(OWNER)
        policy.erase_meeting(OWNER, "mt_a")
        policy.purge_expired()
    group_queries = {
        (path, tuple((f.field_path, f.op_string) for f in filters))
        for path, filters, _ in c.db.queries
        if path in ("cards", "stops")
    }
    expected = {
        (group, (("org_id", "=="), ("retention_namespace", "=="), *tail))
        for group in ("cards", "stops")
        for tail in ((("owner", "=="),), (("owner", "=="), ("source.meeting_id", "==")), (("expires_at", "<="),))
    }
    assert group_queries == expected
    text = Path("infra/envs/dev/followup_retention.tf").read_text()
    for fields in (
        '["org_id", "retention_namespace", "owner"]',
        '["org_id", "retention_namespace", "owner", "source.meeting_id"]',
        '["org_id", "retention_namespace", "expires_at"]',
        '["owner", "source.meeting_id"]',
    ):
        assert fields in text
    assert 'scope = "COLLECTION_GROUP"' in text and 'scope = "COLLECTION"' in text
