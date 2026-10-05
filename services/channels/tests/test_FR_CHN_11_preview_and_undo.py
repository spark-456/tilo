"""FR-CHN-11: Preview with Send / Edit / Cancel (L1) and send with undo window (L2). Acceptance: "L2 send can be
cancelled within 60 s; no send after cancel" (PRD 11.6). Also PRD 10.4 (L2 "instruction is approval", undo window
default 60 s), 11.2 (preview step), 11.4 Preview (To, subject, first 600 characters) and Undo (L2 sends queued in
the outbox with a scheduled time; Cancel works until then), FR-HIL-05, OB-02, OB-03, FR-CHN-13 (exactly once).
API: API_FR_CHN_11.md. Fake clock, fake outbox; no real send, no network, no paid call."""

from __future__ import annotations

import ast
import importlib.util
import json
import threading
from concurrent.futures import ThreadPoolExecutor

from _chn10_lib import OTHER_USER
from _chn11_lib import (
    BENIGN,
    DAVID,
    POLICY_ID,
    USER,
    make_bench,
    pair,
    parse_ts,
    scripted_thread,
)
from _chn_contracts_lib import data_errors, registered_types


def _l2_scheduled(**kw):
    bench = make_bench("L2", **kw)
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN))
    return bench, thread, card


def test_FR_CHN_11_preview_card_has_send_edit_cancel_to_subject_and_600_char_excerpt() -> None:
    bench = make_bench("L1")
    thread = scripted_thread(bench)
    body = "Hi David,\n\n" + "Friday 2pm works for us. See you then. " * 40 + "\n\nBest,\nSarah"
    card = bench.ap.preview(USER, *pair(thread, body))
    assert card.options == ("send", "edit", "cancel")
    assert card.to == (DAVID,) and card.cc == ()
    assert card.subject == "Re: Engine tune-up scheduling and estimate"
    assert card.body == body and card.excerpt == body[:600] and len(card.excerpt) == 600
    assert (card.level, card.tier, card.undo_window_s, card.outbox_id) == ("L1", "T2", 0, None)
    assert bench.outbox.entries == {}, "L1: nothing is queued before a person taps Send"


def test_FR_CHN_11_l1_send_tap_queues_one_person_authorised_entry() -> None:
    bench = make_bench("L1")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    card = bench.ap.preview(USER, ctx, result)
    out = bench.ap.send(USER, card.card_id)
    assert out.status == "queued"
    (entry,) = bench.outbox.all()
    assert entry["id"] == out.outbox_id
    assert entry["authz"]["by"] == "person" and entry["authz"]["ref"] == USER
    assert (entry["action_type"], entry["risk_tier"], entry["undo_window_s"]) == ("send_email", "T2", 0)
    assert entry["recipients"] == [DAVID] and entry["destination"] == thread.thread_id
    assert entry["item"]["artifact_id"] == result.draft.artifact_id
    assert len(bench.outbox.dispatch_due()) == 1


def test_FR_CHN_11_l1_cancel_closes_the_card_and_nothing_is_ever_queued() -> None:
    bench = make_bench("L1")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN))
    assert bench.ap.cancel(USER, card.card_id).status == "cancelled"
    assert bench.ap.send(USER, card.card_id).status == "refused"
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {} and bench.outbox.sent == []


def test_FR_CHN_11_l2_schedules_send_with_60_s_undo_window_in_the_outbox() -> None:
    bench, thread, card = _l2_scheduled()
    assert (card.level, card.tier, card.undo_window_s) == ("L2", "T2", 60)
    entry = bench.outbox.entries[card.outbox_id]
    assert entry["state"] == "scheduled" and entry["undo_window_s"] == 60
    assert card.scheduled_at == entry["scheduled_at"]
    assert (parse_ts(entry["scheduled_at"]) - parse_ts(entry["created_at"])).total_seconds() == 60
    assert entry["authz"]["by"] == "policy" and entry["authz"]["ref"] == POLICY_ID
    assert entry["risk_tier"] == "T2" and entry["modifiers"] == [] and entry["recipients"] == [DAVID]
    bench.rig.clock.advance(59)
    assert bench.outbox.dispatch_due() == [], "nothing leaves before the 60 s window ends"
    bench.rig.clock.advance(1)
    assert [e["id"] for e in bench.outbox.dispatch_due()] == [card.outbox_id], "sends after 60 s unless cancelled"


def test_FR_CHN_11_l2_cancel_within_60_s_means_no_send_ever() -> None:
    bench, _, card = _l2_scheduled()
    bench.rig.clock.advance(59.5)
    out = bench.ap.cancel(USER, card.card_id)
    assert out.status == "cancelled" and out.outbox_id == card.outbox_id
    assert bench.outbox.state(card.outbox_id) == "cancelled"
    for _ in range(3):
        bench.rig.clock.advance(600)
        bench.outbox.dispatch_due()
    assert bench.outbox.sent == []
    assert bench.ap.send(USER, card.card_id).status == "refused", "a cancelled card cannot be sent again"
    assert bench.outbox.sent == [] and len(bench.outbox.entries) == 1


def test_FR_CHN_11_cancel_after_the_send_reports_too_late_never_cancelled() -> None:
    bench, _, card = _l2_scheduled()
    bench.rig.clock.advance(61)
    bench.outbox.dispatch_due()
    assert bench.ap.cancel(USER, card.card_id).status == "too_late"
    assert bench.outbox.state(card.outbox_id) == "sent"


def test_FR_CHN_11_only_the_cards_owner_can_send_or_cancel() -> None:
    bench, _, card = _l2_scheduled()
    assert bench.ap.cancel(OTHER_USER, card.card_id).status == "refused"
    assert bench.outbox.state(card.outbox_id) == "scheduled"
    l1 = make_bench("L1")
    thread = scripted_thread(l1)
    other = l1.ap.preview(USER, *pair(thread, BENIGN))
    assert l1.ap.send(OTHER_USER, other.card_id).status == "refused" and l1.outbox.entries == {}


def test_FR_CHN_11_exactly_once_under_replayed_previews_taps_and_restarts() -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    first = bench.ap.preview(USER, ctx, result)
    again = bench.ap.preview(USER, ctx, result)
    restarted = bench.new_autopilot().preview(USER, ctx, result)
    assert first.outbox_id == again.outbox_id == restarted.outbox_id
    assert len(bench.outbox.entries) == 1
    bench.rig.clock.advance(60)
    for _ in range(5):
        bench.outbox.dispatch_due()
    assert len(bench.outbox.sent) == 1

    l1 = make_bench("L1")
    thread = scripted_thread(l1)
    card = l1.ap.preview(USER, *pair(thread, BENIGN))
    taps = [l1.ap.send(USER, card.card_id) for _ in range(3)] + [l1.new_autopilot().send(USER, card.card_id)]
    assert len({t.outbox_id for t in taps}) == 1 and len(l1.outbox.entries) == 1
    l1.outbox.dispatch_due()
    l1.outbox.dispatch_due()
    assert len(l1.outbox.sent) == 1


def test_FR_CHN_11_concurrent_replays_on_eight_instances_schedule_one_send() -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    instances = [bench.new_autopilot() for _ in range(8)]
    barrier = threading.Barrier(8)

    def run(ap):
        barrier.wait()
        return ap.preview(USER, ctx, result)

    with ThreadPoolExecutor(8) as pool:
        cards = list(pool.map(run, instances))
    assert len({c.outbox_id for c in cards}) == 1 and len(bench.outbox.entries) == 1
    bench.rig.clock.advance(60)
    bench.outbox.dispatch_due()
    assert len(bench.outbox.sent) == 1


def test_FR_CHN_11_crash_after_enqueue_then_replay_still_one_send(monkeypatch) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    ctx, result = pair(thread, BENIGN)
    crashed: list[str] = []

    def dies_once_after_enqueue(real):
        def wrapped(*args):
            if bench.outbox.enqueue_calls and not crashed:
                crashed.append("x")
                raise RuntimeError("instance died")
            return real(*args)

        return wrapped

    monkeypatch.setattr(bench.cards, "create", dies_once_after_enqueue(bench.cards.create))
    monkeypatch.setattr(bench.cards, "put", dies_once_after_enqueue(bench.cards.put))
    try:
        bench.ap.preview(USER, ctx, result)
    except RuntimeError:
        pass
    card = bench.new_autopilot().preview(USER, ctx, result)
    assert len(bench.outbox.entries) == 1 and card.outbox_id in bench.outbox.entries
    bench.rig.clock.advance(60)
    bench.outbox.dispatch_due()
    assert len(bench.outbox.sent) == 1


def test_FR_CHN_11_a_cancel_on_another_instance_stops_the_send() -> None:
    bench, _, card = _l2_scheduled()
    bench.rig.clock.advance(30)
    assert bench.new_autopilot().cancel(USER, card.card_id).status == "cancelled"
    bench.rig.clock.advance(120)
    bench.outbox.dispatch_due()
    assert bench.outbox.sent == []


def test_FR_CHN_11_events_registered_valid_and_free_of_mail_content() -> None:
    bench, _, card = _l2_scheduled()
    bench.ap.cancel(USER, card.card_id)
    l1 = make_bench("L1")
    thread = scripted_thread(l1)
    l1.ap.send(USER, l1.ap.preview(USER, *pair(thread, BENIGN)).card_id)
    known = registered_types()
    for part in bench.events.parts + l1.events.parts:
        assert part["type"] in known and part["type"] != "data.transfer", "only the outbox emits data.transfer"
        assert data_errors(part["type"], part["data"]) == []
        dumped = json.dumps(part)
        assert "Friday 2pm works" not in dumped and DAVID not in dumped


def test_FR_CHN_11_autopilot_imports_no_connector_sender_or_network_client() -> None:
    spec = importlib.util.find_spec("tilo_channels.autopilot")
    assert spec is not None and spec.origin, "tilo_channels.autopilot is missing"
    tree = ast.parse(open(spec.origin, encoding="utf-8").read())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    banned = ("tilo_connectors", "requests", "httpx", "urllib", "socket", "smtplib", "http", "google", "aiohttp")
    assert not [n for n in names for b in banned if n == b or n.startswith(b + ".")]
