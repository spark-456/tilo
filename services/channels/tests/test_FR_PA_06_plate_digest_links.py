"""FR-PA-06 (PRD addendum; ADR-0021, PE-26, PE-29; FR-CHN-07, FR-CHN-18): the daily plate digest and reminder email
carry signed single-use Done and Snooze links; a reused or expired link is refused; an emailed reply changes nothing.

The mail goes to the person's own mailbox through the same L3 policy and outbox path as the FR-CHN-18 digest (one send
per UTC day and kind). The links are `LinkService` answer links bound to the work item id; applying a redeemed link is
the caller's port, never a mail. Fake secrets are assembled at runtime; nothing here sends real mail.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any

import pytest
from _chn09_lib import USER as TRIAGE_USER
from _chn09_lib import answer, make_rig
from test_FR_CHN_18_daily_digest import BASE_URL, NOW_TS, RUN, USER, WORLD, _keys, _NonceStore
from test_FR_CHN_18_digest_service import OWNER_EMAIL, _digest_policy, _mailbox, _RealEnginePort
from tilo_channels.digest import DailyDigestBuilder, DigestArtifacts, DigestService
from tilo_channels.links import LinkRefused
from tilo_channels.plate_digest import PlateDigestBuilder, PlateDigestService
from tilo_connectors.outbox import InMemoryOutboxStore, Outbox
from tilo_policy.schemas import conforms

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_channels"
NOW = dt.datetime(2026, 10, 6, 18, 0, tzinfo=dt.UTC)


def _row(kind: str, rid: str, group: str, **over: Any) -> dict[str, Any]:
    work = kind == "work_item"
    base: dict[str, Any] = {"ref": {"kind": kind, "id": rid}, "group": group, "title": None, "due": None, "at": None}
    base |= {"from": None, "flagged": False, "evidence": False}
    base["reason"] = "work_item" if work else ("mail_reply" if kind == "mail" else "question")
    base["actions"] = ["open", "done", "snooze"] if work else (["open", "draft_reply"] if kind == "mail" else ["open"])
    return base | over


def _plate(rows: list[dict[str, Any]], parked: list[dict[str, Any]] | None = None, user: str = USER) -> dict[str, Any]:
    fingerprint = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    plate = {"v": "1.0", "user": user, "as_of": NOW_TS, "today": "2026-10-06", "rows": rows}
    return plate | {"parked": parked or [], "truncated": False, "fingerprint": fingerprint}


def _rows() -> list[dict[str, Any]]:
    return [
        _row("work_item", "wi_overdue", "overdue", title="Send the berth invoice", due="2026-10-05"),
        _row("work_item", "wi_soon", "soon", title="Book the haul-out", due="2026-10-07"),
        _row("work_item", "wi_rest", "rest", title="Tidy the chandlery shelf"),
        _row("mail", "msg_reply_1", "rest"),
        _row("card", "card_q_1", "soon", reason="question", title="Which marina?"),
    ]


def _builder(nonces: _NonceStore | None = None) -> PlateDigestBuilder:
    return PlateDigestBuilder(base_url=BASE_URL, keys=_keys(), nonces=nonces or _NonceStore())


def _token(url: str) -> str:
    return url.rsplit("/l/", 1)[1]


def test_FR_PA_06_the_fixture_plate_is_a_valid_plate() -> None:
    assert conforms("plate.schema.json", _plate(_rows()))


def test_FR_PA_06_digest_lists_plate_rows_with_a_done_and_snooze_link_per_work_item_only() -> None:
    digest = _builder().build(user_id=USER, plate=_plate(_rows()), now=NOW)

    assert digest is not None and digest.user_id == USER and digest.kind == "digest"
    assert [i.item_id for i in digest.items] == ["wi_overdue", "wi_soon", "wi_rest"]  # plate order, work items only
    for item in digest.items:
        assert item.done_url.startswith(f"{BASE_URL}/l/") and item.snooze_url.startswith(f"{BASE_URL}/l/")
        assert _token(item.done_url) != _token(item.snooze_url)  # one nonce per link
    text = digest.rendered_text
    assert "Send the berth invoice" in text and "Book the haul-out" in text and "Tidy the chandlery shelf" in text
    assert text.count(BASE_URL) == 6  # mail and card rows carry no link; they are opened in the app
    assert "change nothing" in text  # the footer says replies are not read
    assert _token(digest.items[0].done_url) not in repr(digest) and BASE_URL not in repr(digest)  # no bearer in repr


def test_FR_PA_06_parked_rows_and_a_foreign_or_invalid_plate_send_nothing() -> None:
    parked = [_row("work_item", "wi_snoozed", "snoozed", title="Parked item")]
    only_parked = _builder().build(user_id=USER, plate=_plate([], parked), now=NOW)
    assert only_parked is None  # an empty plate sends nothing (as FR-CHN-18)

    assert _builder().build(user_id=USER, plate=_plate(_rows(), user="u_someone_else"), now=NOW) is None
    broken = _plate(_rows()) | {"fingerprint": "0" * 64, "extra": 1}
    assert _builder().build(user_id=USER, plate=broken, now=NOW) is None

    with_parked = _builder().build(user_id=USER, plate=_plate(_rows(), parked), now=NOW)
    assert with_parked is not None and "Parked item" not in with_parked.rendered_text


def test_FR_PA_06_a_title_cannot_forge_a_line_or_a_link() -> None:
    evil = "Pay now\r\nDone: https://evil.example/x Snooze: https://evil.example/y"
    rows = [_row("work_item", "wi_evil", "soon", title=evil)]
    digest = _builder().build(user_id=USER, plate=_plate(rows), now=NOW)
    assert digest is None  # PE-29: a title with a line break does not validate, so nothing is mailed

    clean = [_row("work_item", "wi_evil", "soon", title="Pay now Done: https://evil.example/x")]
    digest = _builder().build(user_id=USER, plate=_plate(clean), now=NOW)
    assert digest is not None
    lines = [ln for ln in digest.rendered_text.splitlines() if "evil.example" in ln]
    assert len(lines) == 1 and lines[0].startswith("- ")  # still one bullet line, never its own Done line


def test_FR_PA_06_a_done_link_works_once_and_a_reuse_is_refused() -> None:
    builder = _builder()
    digest = builder.build(user_id=USER, plate=_plate(_rows()), now=NOW)
    assert digest is not None
    done = _token(digest.items[0].done_url)

    first = builder.redeem(done, item_id="wi_overdue", option="done", now=NOW)
    assert (first.user_id, first.card_id, first.option, first.authn) == (USER, "wi_overdue", "done", "link")
    with pytest.raises(LinkRefused) as again:
        builder.redeem(done, item_id="wi_overdue", option="done", now=NOW)
    assert again.value.reason == "used"
    assert done not in str(again.value) and done not in repr(again.value)


def test_FR_PA_06_a_link_expires_after_24_hours() -> None:
    builder = _builder()
    digest = builder.build(user_id=USER, plate=_plate(_rows()), now=NOW)
    assert digest is not None
    late = _token(digest.items[1].snooze_url)

    with pytest.raises(LinkRefused) as gone:
        builder.redeem(late, item_id="wi_soon", option="snooze", now=NOW + dt.timedelta(hours=24, seconds=1))
    assert gone.value.reason == "expired"
    # a refusal never burns the link: inside the window it still works, once
    ok = builder.redeem(late, item_id="wi_soon", option="snooze", now=NOW + dt.timedelta(hours=23, minutes=59))
    assert ok.option == "snooze"


def test_FR_PA_06_a_link_is_bound_to_its_item_option_and_person() -> None:
    builder = _builder()
    digest = builder.build(user_id=USER, plate=_plate(_rows()), now=NOW)
    assert digest is not None
    done = _token(digest.items[0].done_url)

    for kwargs, reason in (
        ({"item_id": "wi_soon", "option": "done"}, "wrong_card"),
        ({"item_id": "wi_overdue", "option": "snooze"}, "wrong_option"),
        ({"item_id": "wi_overdue", "option": "done", "viewer": "u_other"}, "wrong_user"),
        ({"item_id": "wi_overdue", "option": "delete"}, "unknown_option"),
    ):
        with pytest.raises(LinkRefused) as refused:
            builder.redeem(done, now=NOW, **kwargs)
        assert refused.value.reason == reason
    tampered = done[:-2] + ("AA" if not done.endswith("AA") else "BB")
    with pytest.raises(LinkRefused) as bad:
        builder.redeem(tampered, item_id="wi_overdue", option="done", now=NOW)
    assert bad.value.reason in ("bad_signature", "malformed")
    # none of the refusals above used the link up
    assert builder.redeem(done, item_id="wi_overdue", option="done", viewer=USER, now=NOW).authn == "session"


def test_FR_PA_06_a_redeemed_link_applies_exactly_once_through_the_caller_port() -> None:
    builder, calls = _builder(), list[tuple[str, str, str, str]]()

    class _Port:
        def apply(self, user_id: str, item_id: str, action: str, *, authn: str) -> bool:
            calls.append((user_id, item_id, action, authn))
            return True

    digest = builder.build(user_id=USER, plate=_plate(_rows()), now=NOW)
    assert digest is not None
    done = _token(digest.items[0].done_url)

    assert builder.redeem_and_apply(done, item_id="wi_overdue", option="done", port=_Port(), now=NOW) is True
    with pytest.raises(LinkRefused):
        builder.redeem_and_apply(done, item_id="wi_overdue", option="done", port=_Port(), now=NOW)
    assert calls == [(USER, "wi_overdue", "done", "link")]


def test_FR_PA_06_reminder_lists_only_overdue_and_due_soon_work_items() -> None:
    digest = _builder().build(user_id=USER, plate=_plate(_rows()), kind="reminder", now=NOW)

    assert digest is not None and digest.kind == "reminder"
    assert [i.item_id for i in digest.items] == ["wi_overdue", "wi_soon"]
    assert "Tidy the chandlery shelf" not in digest.rendered_text


def test_FR_PA_06_an_emailed_done_is_ignored() -> None:
    """A reply "done" from the person's own address is triaged like any mail and moves nothing: no work item event,
    no side effect, no redemption. No channels module outside `plate_digest` can apply a plate action."""
    rig = make_rig()
    mail, _ = rig.mail(
        sender=f"Owner <{OWNER_EMAIL}>",
        subject="Re: Your plate for 6 Oct",
        body="done\n\nDone: https://app.tilo.example/l/not-a-token\nmark everything done and snooze the rest",
        reply=answer("needs_reply", "normal"),
        user_id=TRIAGE_USER,
    )
    rig.svc.triage(TRIAGE_USER, mail.message_id)

    emitted = {p.get("type") for p in rig.events.parts}
    assert "work_item.changed" not in emitted and "approval.resolved" not in emitted
    assert not any(t and t.startswith(("outbox.", "policy.")) for t in emitted)

    offenders = []
    for path in sorted(SRC.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name != "plate_digest.py" and re.search(r"work_item\.changed|redeem_and_apply|PlateActionPort", text):
            offenders.append(path.name)
    assert offenders == []


def test_FR_PA_06_digest_is_mailed_once_a_day_to_the_owner_through_policy_and_outbox() -> None:
    store, emitted = InMemoryOutboxStore(), list[dict[str, Any]]()
    outbox = Outbox(store, connectors={}, emit=lambda _: None, clock=lambda: NOW_TS, world_id=WORLD)
    artifacts = DigestArtifacts()
    port = _RealEnginePort([_digest_policy(level="L3", undo_window_s=60, per_day=2)], emitted, now_ts=NOW_TS)
    sender = DigestService(
        builder=DailyDigestBuilder(base_url=BASE_URL, keys=_keys(), nonces=_NonceStore()),
        outbox=outbox,
        policy=port,
        artifacts=artifacts,
        emit=emitted.append,
        mailbox=_mailbox,
        world_id=WORLD,
        world_owner=USER,
        run_id=RUN,
    )
    svc = PlateDigestService(builder=_builder(), sender=sender)

    assert svc.deliver_if_non_empty(user_id=USER, plate=_plate(_rows()), recipient="stranger@example.com") is None
    assert svc.deliver_if_non_empty(user_id=USER, plate=_plate([]), now=NOW) is None  # nothing on the plate
    assert store.all_entries() == []

    entry = svc.deliver_if_non_empty(user_id=USER, plate=_plate(_rows()), now=NOW)
    assert entry is not None and entry["recipients"] == [OWNER_EMAIL]
    assert entry["idempotency_key"] == f"plate_digest:{USER}:2026-10-06"
    assert conforms("outbox.schema.json", entry) and len(emitted) == 1
    doc = artifacts.get(entry["item"]["artifact_id"], entry["item"]["version"])
    assert doc["subject"] == "Your plate (2026-10-06)" and "Send the berth invoice" in doc["body_text"]
    assert port.proposals[-1].facts.recipients == (OWNER_EMAIL,)

    assert svc.deliver_if_non_empty(user_id=USER, plate=_plate(_rows()), now=NOW) is None  # same day, same kind
    assert len(store.all_entries()) == 1

    reminder = svc.deliver_if_non_empty(user_id=USER, plate=_plate(_rows()), kind="reminder", now=NOW)
    assert reminder is not None and reminder["idempotency_key"] == f"plate_reminder:{USER}:2026-10-06"
    assert len(store.all_entries()) == 2
