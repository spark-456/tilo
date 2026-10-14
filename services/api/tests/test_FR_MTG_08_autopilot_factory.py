"""FR-MTG-08 inert scoped production factory acceptance, fake Firestore only."""

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from _ppl11c_fs_fake import FakeFirestore
from fastapi import HTTPException
from tilo_api import deps
from tilo_api.followup_autopilot_factory import build_factory
from tilo_api.outbox_firestore import FirestoreOutboxStore
from tilo_channels.autopilot import DraftContext
from tilo_channels.drafting import Draft, DraftResult
from tilo_connectors import InMemoryOutboxStore

USER, WORLD, RUN = "u_owner", "w_meet", "r_meet"
NOW = "2026-10-14T04:00:00.000Z"


@pytest.fixture
def rig():
    store = deps.Store(worlds={WORLD: deps.WorldRecord(USER, {}, run_id=RUN)})
    request = SimpleNamespace(state=SimpleNamespace(uid=USER, demo_session=False))
    owner = SimpleNamespace(
        principal=deps.Principal(USER, "owner"),
        request=request,
        store=store,
        clock=lambda: NOW,
    )
    db, outbox, drafts, emitted = FakeFirestore(), InMemoryOutboxStore(), Mock(), []
    drafts.get.return_value = None
    hook = Mock(side_effect=lambda: None)

    class Emit:
        def __init__(self):
            self.drafts = drafts

        def __call__(self, part):
            emitted.append(part)

        def before_publication(self):
            hook()

    factory = build_factory(owner, client=db, outbox_store=outbox, drafts=drafts)
    return SimpleNamespace(**locals())


def make(c, world=WORLD, run=RUN, user=USER, emit=None):
    return c.factory(world, run, user, c.Emit() if emit is None else emit)


def result(body="The confirmed notes are ready."):
    draft = Draft(
        "art_followup",
        1,
        None,
        "new",
        ("recipient@example.invalid",),
        (),
        (),
        "Confirmed minutes",
        "",
        "",
        body,
        (),
        False,
    )
    return DraftResult("instruction-meet", "ready", draft, (), (), False)


def context():
    return DraftContext("instruction-meet", None, "Share confirmed minutes", "owner@example.invalid", "new")


@pytest.mark.parametrize(
    "world,run,user",
    [
        ("../w_meet", RUN, USER),
        (WORLD, "r_", USER),
        (WORLD, RUN, "../u_owner"),
        ("w_" + "x" * 49, RUN, USER),
        (WORLD, RUN, "u_other"),
        ("w_missing", RUN, USER),
        (WORLD, "r_other", USER),
    ],
)
def test_FR_MTG_08_factory_refuses_untrusted_scope_before_publication(rig, world, run, user):
    with pytest.raises(HTTPException):
        make(rig, world, run, user)
    assert rig.db.docs == {} and rig.outbox.all_entries() == [] and rig.emitted == []


@pytest.mark.parametrize("change", ["principal_demo", "request_demo", "paused", "owner", "run", "missing"])
def test_FR_MTG_08_factory_fresh_authority_at_creation(rig, change):
    c = rig
    if change == "principal_demo":
        c.owner.principal = replace(c.owner.principal, demo_session=True)
    elif change == "request_demo":
        c.request.state.demo_session = True
    elif change == "missing":
        c.store.worlds.clear()
    else:
        setattr(
            c.store.worlds[WORLD],
            change if change != "run" else "run_id",
            True if change == "paused" else "u_other" if change == "owner" else "r_other",
        )
    with pytest.raises(HTTPException):
        make(c)
    assert c.db.docs == {} and c.outbox.all_entries() == []


@pytest.mark.parametrize("change", ["paused", "owner", "run", "hook"])
def test_FR_MTG_08_factory_revalidates_before_later_card_mutation(rig, change):
    c, autopilot = rig, make(rig)
    if change == "hook":
        c.hook.side_effect = HTTPException(409, "source_changed")
    else:
        setattr(
            c.store.worlds[WORLD],
            change if change != "run" else "run_id",
            True if change == "paused" else "u_other" if change == "owner" else "r_other",
        )
    with pytest.raises(HTTPException):
        autopilot.preview(USER, context(), result())
    assert c.db.docs == {} and c.outbox.all_entries() == [] and c.emitted == []


@pytest.mark.parametrize("emit", [object(), lambda part: None])
def test_FR_MTG_08_factory_missing_callable_publication_hook_is_closed(rig, emit):
    with pytest.raises(HTTPException) as caught:
        make(rig, emit=emit)
    assert caught.value.status_code == 503
    assert rig.db.docs == {} and rig.outbox.all_entries() == []


def test_FR_MTG_08_factory_new_email_gated_and_duplicate_card_preserved(rig):
    c, autopilot = rig, make(rig)
    first = autopilot.preview(USER, context(), result())
    assert (first.status, first.tier, first.level) == ("ready", "T3", "L1")
    assert first.options == ("send", "edit", "cancel") and first.scheduled_at is None
    original = dict(c.db.docs)
    replay = make(c).preview(USER, context(), result("Changed body must not replace first card."))
    assert replay.card_id == first.card_id and replay.body == first.body
    assert c.db.docs == original and c.outbox.all_entries() == []
    assert c.hook.call_count > 0
    c.drafts.get.assert_any_call(USER, "instruction-meet")


@pytest.mark.parametrize("mode", ["off", "wrong_case", "memory", "door", "valid"])
def test_FR_MTG_08_factory_resolver_requires_durable_shared_door(rig, monkeypatch, mode):
    from tilo_api import followup_autopilot_factory, store_door

    c = rig
    monkeypatch.setenv(
        "TILO_OUTBOX_STORE", "memory" if mode == "off" else "Firestore" if mode == "wrong_case" else "firestore"
    )
    box = c.outbox if mode == "memory" else FirestoreOutboxStore(c.db)
    monkeypatch.setattr(deps, "get_outbox_store", lambda: box)
    monkeypatch.setattr(deps, "get_followup_draft_store", lambda: c.drafts)
    opened = Mock(return_value=SimpleNamespace(client=c.db))
    if mode == "door":
        opened.side_effect = store_door.ApiStoreNotConfigured("private-client-error")
    monkeypatch.setattr(store_door, "open_api_store", opened)
    built = Mock(return_value=object())
    monkeypatch.setattr(followup_autopilot_factory, "build_factory", built)
    if mode == "valid":
        assert deps.get_followup_autopilot_factory(c.owner) is built.return_value
        built.assert_called_once_with(c.owner, client=c.db, outbox_store=box, drafts=c.drafts)
        opened.assert_called_once_with()
    else:
        with pytest.raises(HTTPException) as caught:
            deps.get_followup_autopilot_factory(c.owner)
        assert caught.value.status_code == 503
        assert caught.value.headers["Cache-Control"] == "no-store"
        assert "private-client-error" not in str(caught.value)
        built.assert_not_called()
