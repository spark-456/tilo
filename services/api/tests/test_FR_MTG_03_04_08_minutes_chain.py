"""M5: exact #1064 owner HTTP chain, production dependencies, offline providers/Firestore ports."""

import copy
import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from _mtg08_lib import answer
from _ppl11a_lib import OWNER, PRIYA, SAM
from fastapi import HTTPException, Request
from test_FR_MTG_03_analysis_publication import integration  # noqa: F401
from test_FR_MTG_03_owner_analysis_mode import owner_call  # noqa: F401
from test_FR_MTG_03_owner_minutes_caller import caller_app  # noqa: F401
from test_FR_MTG_08_draft_retention import DB
from tilo_api import app as production_app
from tilo_api import deps, outbox_firestore, people, store_door
from tilo_api.access import AccessGate
from tilo_api.assistant.config import load_assistant_config
from tilo_api.assistant.metering import InMemorySpendLedger
from tilo_api.owner_minutes_routes import MINUTES_FLAG, install_owner_minutes_routes
from tilo_api.people_limits import NoStore

WORK_MODE = deps.get_work_mode
BASE = "/v1/meetings/mt_q4_plan"


@pytest.fixture
def chain(caller_app, monkeypatch):  # noqa: F811
    c = caller_app
    c.db, c.allowance, c.cap = DB(), InMemorySpendLedger(), 100
    c.during, c.calls, c.modes = None, [], []
    c.rig._ids = [f"art_m5_{i}" for i in range(20)]
    original = copy.deepcopy(c.router.doc)

    class Router:
        def generate(self, role, request, *, budget):
            c.calls.append(role)
            if c.during is not None:
                c.during(role)
            assert role in {"meeting_analyst", "autopilot"}
            text = json.dumps(original) if role == "meeting_analyst" else answer(original["decisions"][0]["text"])
            return SimpleNamespace(
                response=SimpleNamespace(text=text, tool_calls=()), outcome="ok", budget=max(0, budget - 1)
            )

    def router(mode):
        c.modes.append(mode)
        assert mode == "replay"
        return Router()

    def principal(request: Request):
        if request.headers.get("authorization") != "Bearer test-owner":
            raise HTTPException(401, "sign_in_required")
        return deps.Principal(c.writer.actor, "owner", demo_session=c.demo)

    monkeypatch.setenv("K_SERVICE", "offline-minutes-test")
    monkeypatch.setenv("TILO_OUTBOX_STORE", "firestore")
    monkeypatch.setattr(deps, "get_work_mode", WORK_MODE)
    monkeypatch.setattr(deps, "router_for_mode", router)

    def opened(*args, **kwargs):
        return SimpleNamespace(client=c.db)

    monkeypatch.setattr(store_door, "open_api_store", opened)
    monkeypatch.setattr(outbox_firestore, "open_api_store", opened)
    c.app.dependency_overrides.update(
        {
            deps.get_current_principal: principal,
            deps.get_flag_store: lambda: c.flags,
            deps.get_spend_ledger: lambda: c.allowance,
            deps.get_assistant_config: lambda: replace(load_assistant_config(), user_day_credits=c.cap),
        }
    )
    c.flags.set(MINUTES_FLAG, True, reason="isolated offline M5 test app")
    c.app.include_router(people.router)
    assert install_owner_minutes_routes(c.app, c.flags)
    c.app.add_middleware(AccessGate)
    c.app.add_middleware(NoStore)
    return c


def post(c, action, body=None, headers=None):
    return c.client.post(
        f"{BASE}/{action}", json={} if body is None else body, headers=c.headers if headers is None else headers
    )


def stored(c):
    return c.rig.stored("meetings", "mt_q4_plan")


def rows(c, collection):
    return [snapshot.to_dict() for snapshot in c.db.collection_group(collection).stream()]


def analyze_confirm(c):
    response = post(c, "analyze-minutes")
    assert response.status_code == 200, response.text
    assert stored(c)["minutes"] == response.json()["minutes"]
    assert stored(c)["minutes_confirmed_by"] is None
    before = list(c.calls)
    response = post(c, "confirm")
    assert response.status_code == 200, response.text
    assert stored(c)["minutes_confirmed_by"]["by"] == OWNER and c.calls == before


def draft(c):
    return post(c, "draft-followup", {"recipients": [PRIYA]})


def no_preview(c):
    assert rows(c, "cards") == [] and rows(c, "stops") == []
    assert deps.get_outbox_store().all_entries() == []
    assert all(event["type"] != "approval.requested" for event in c.rig.event_store.events.get(c.scope.world_id, []))


def acceptance(c):
    analyze_confirm(c)
    response = draft(c)
    assert response.status_code == 200, response.text
    preview = response.json()
    assert (preview["tier"], preview["level"], preview["status"]) == ("T3", "L1", "ready")
    assert preview["to"] == ["priya@example.com"] and preview["options"] == ["send", "edit", "cancel"]
    snapshot = [rows(c, name) for name in ("followup_drafts", "cards", "stops")]
    assert snapshot[0] and snapshot[1]
    for group in snapshot:
        for row in group:
            assert row["owner"] == OWNER and row["org_id"] == c.rig.org
            assert row["source"]["meeting_id"] == "mt_q4_plan"
            assert row["source"]["minutes"] == stored(c)["minutes"] and row["expires_at"] > row["created_at"]
    events = list(c.rig.event_store.events[c.scope.world_id])
    calls, spent = list(c.calls), c.allowance.spent(OWNER, c.writer.now[:10])
    assert draft(c).json()["card_id"] == preview["card_id"]
    assert [rows(c, name) for name in ("followup_drafts", "cards", "stops")] == snapshot
    assert c.rig.event_store.events[c.scope.world_id] == events and c.calls == calls
    assert c.allowance.spent(OWNER, c.writer.now[:10]) == spent == 2
    assert [event["type"] for event in events].count("approval.requested") == 1
    assert deps.get_outbox_store().all_entries() == [] and set(c.modes) == {"replay"}


def test_FR_MTG_03_04_08_full_http_chain_durable_preview_and_replay(chain):
    acceptance(chain)


def test_FR_MTG_03_04_08_default_off_absent_even_with_wired_dependencies(chain):
    assert all("analyze-minutes" not in p and "draft-followup" not in p for p in production_app.openapi()["paths"])
    chain.flags.set(MINUTES_FLAG, False, reason="offline revoke")
    assert post(chain, "analyze-minutes").status_code == 404 and chain.calls == []
    no_preview(chain)


@pytest.mark.parametrize("denial", ["auth", "appcheck", "owner", "demo"])
@pytest.mark.parametrize("action", ["analyze-minutes", "draft-followup"])
def test_FR_MTG_03_04_08_boundary_denial_no_model_or_durable_preview(chain, denial, action):
    c = chain
    headers = dict(c.headers)
    if denial == "auth":
        headers.pop("Authorization")
    elif denial == "appcheck":
        headers.pop("X-Firebase-AppCheck")
    elif denial == "owner":
        c.writer.actor = SAM
    else:
        c.demo = True
    response = post(c, action, {"recipients": [PRIYA]} if action == "draft-followup" else {}, headers)
    assert response.status_code == {"auth": 401, "appcheck": 401, "owner": 404, "demo": 403}[denial]
    assert response.headers["cache-control"] == "no-store" and not c.calls
    no_preview(c)


@pytest.mark.parametrize("cap", [0, -1, "exhausted"])
@pytest.mark.parametrize("action", ["analyze-minutes", "draft-followup"])
def test_FR_MTG_03_04_08_allowance_denied_before_provider(chain, cap, action):
    c = chain
    if action == "draft-followup":
        analyze_confirm(c)
    if cap == "exhausted":
        hold = c.allowance.reserve(OWNER, c.writer.now[:10], 100, 200)
        c.allowance.commit(hold, 100)
    else:
        c.cap = cap
    calls = list(c.calls)
    response = post(c, action, {"recipients": [PRIYA]} if action == "draft-followup" else {})
    assert response.status_code == 429 and response.json()["detail"] == "allowance_capped"
    assert c.calls == calls
    no_preview(c)


@pytest.mark.parametrize("boundary", ["analyze", "followup"])
@pytest.mark.parametrize("change", ["expiry", "erasure", "cas"])
def test_FR_MTG_03_04_08_provider_return_source_race_refuses_publication(chain, boundary, change):
    c = chain
    if boundary == "followup":
        analyze_confirm(c)
    before = list(c.rig.event_store.events.get(c.scope.world_id, []))

    def mutate(role):
        current = c.rig.real.meetings.get(c.rig.org, "mt_q4_plan")
        if change == "expiry":
            c.writer.now = current.record[
                "delete_minutes_after" if boundary == "followup" else "delete_transcript_after"
            ]
        elif change == "erasure":
            ref = current.record["minutes" if boundary == "followup" else "transcript"]
            for record in c.rig.artifacts.retention().records():
                if ref["artifact_id"] in record.record_id:
                    c.rig.artifacts._purge(record.record_id)
        else:
            c.rig.real.meetings.replace({**current.record, "title": "Rival edit"}, expected_version=current.version)

    c.during = mutate
    response = (
        post(c, "draft-followup", {"recipients": [PRIYA]}) if boundary == "followup" else post(c, "analyze-minutes")
    )
    assert response.status_code == 409, response.text
    no_preview(c)
    assert c.rig.event_store.events.get(c.scope.world_id, []) == before
    if boundary == "analyze":
        assert stored(c)["minutes"] is None


def test_FR_MTG_03_04_08_confirm_is_required_and_cannot_be_model_generated(chain):
    c = chain
    assert post(c, "analyze-minutes").status_code == 200
    calls = list(c.calls)
    assert draft(c).status_code == 409 and c.calls == calls
    assert stored(c)["minutes_confirmed_by"] is None
    no_preview(c)


def test_FR_MTG_03_04_08_owner_delete_after_preview_erases_and_retry_cannot_resurrect(chain):
    c = chain
    acceptance(c)
    calls = list(c.calls)
    response = post(c, "delete")
    assert response.status_code == 200, response.text
    assert all(rows(c, name) == [] for name in ("followup_drafts", "cards", "stops"))
    assert draft(c).status_code == 404 and c.calls == calls
    assert deps.get_outbox_store().all_entries() == []


@pytest.mark.emulator
def test_FR_MTG_03_04_08_local_firestore_sdk_full_chain(people_fs_client, chain):
    from google.cloud import firestore
    from tilo_api.people_firestore import firestore_people_stores

    assert people_fs_client.project.startswith("demo-")
    c = chain
    # Isolate rows from other lanes; the existing fixture owns only a loopback emulator, never cloud credentials.
    client = firestore.Client(project="demo-m5-" + uuid4().hex[:12])
    try:
        c.db = client
        durable = firestore_people_stores(client)
        for name in ("persons", "meetings", "work_items"):
            for record in getattr(c.rig.real, name).list(c.rig.org):
                getattr(durable, name).create(record.record)
        c.rig.real = durable
        acceptance(c)
        assert post(c, "delete").status_code == 200
        assert all(rows(c, name) == [] for name in ("followup_drafts", "cards", "stops"))
        calls = list(c.calls)
        assert draft(c).status_code == 404 and c.calls == calls
    finally:
        client.close()
