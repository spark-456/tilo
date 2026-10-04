"""Test doubles for CHN-WIRE-1 (FR-CHN-11, issue #307 plan ticket 1, issue #256 gate 3): the person-approved L1 / T3
Send reaches the real outbox with real OB-01 evidence. The API they drive is pinned in API_CHN_WIRE_1.md.

Nothing here is production logic, and nothing here replaces `tilo_policy.check_entry`: the whole point of these tests is
that the REAL OB-01 / OB-05 check accepts or refuses what the Autopilot hands the outbox. The line is the FR-CHN-13 one
(real Drafter, real `tilo_connectors.Outbox` over `InMemoryOutboxStore`, real `GmailAdapter`, `FakeGmailApi` behind its
Transport seam: no network, no real mail) except that the Autopilot is built WITHOUT `fake_evidence`.

`tilo-api` is not built here. `resolved(...)` plays its part: it builds the `approval.resolved` event part the API would
record for a person's Send tap, from the `approval.requested` part the Autopilot emitted. Addresses are fictional.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import tilo_policy
from _chn11_lib import RUN, WORLD, autopilot_module
from _chn13_lib import USER, Line, iso, make_line

OTHER_PERSON = "u_mallory"
APPROVE = "approve"


class SpyOutbox:
    """Wraps the real outbox: records every `enqueue(entry, evidence)` call, then delegates (the real check runs)."""

    def __init__(self, real: Any) -> None:
        self._real = real
        self.calls: list[tuple[dict, dict]] = []

    def enqueue(self, entry: dict, evidence: dict) -> dict:
        self.calls.append((copy.deepcopy(entry), copy.deepcopy(evidence)))
        return self._real.enqueue(entry, evidence)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


def new_real_autopilot(line: Line, spy: SpyOutbox) -> Any:
    """Another instance over the same stores and outbox (a restart or a second Cloud Run instance), in PRODUCTION mode:
    no `fake_evidence`, so every entry carries the evidence the real `check_entry` reads."""
    bench = line.bench
    return autopilot_module().Autopilot(
        drafter=bench.rig.svc,
        reader=bench.rig.reader,
        contacts=bench.contacts,
        policy=bench.policy,
        outbox=spy,
        cards=bench.cards,
        clock=bench.rig.clock,
        emit=bench.events,
        world_id=WORLD,
        run_id=RUN,
    )


def make_wire_line(level: str = "L1", contacts: tuple[str, ...] = ()) -> Line:
    """The FR-CHN-13 line with a production-mode Autopilot (`line.ap`, `line.bench.new_autopilot()`), and
    `line.spy` recording what reaches the outbox."""
    line = make_line(level, contacts)
    spy = SpyOutbox(line.outbox)
    line.spy = spy  # type: ignore[attr-defined]
    line.bench.new_autopilot = lambda: new_real_autopilot(line, spy)  # type: ignore[method-assign]
    line.bench.ap = line.bench.new_autopilot()
    return line


def real_check_is_live() -> None:
    """Guards against a leaked monkeypatch: the module-scope `outbox_skips_ob01_evidence` of the FR-CHN-13 files."""
    assert tilo_policy.check_entry.__module__ == "tilo_policy.crossref", "tilo_policy.check_entry is patched"


def requested_part(line: Line, card: Any, ap: Any = None) -> dict:
    """The `approval.requested` part of a card, as the Autopilot stores it (API_CHN_WIRE_1.md)."""
    ap = ap or line.ap
    reader = getattr(ap, "approval_requested", None)
    assert callable(reader), "CHN-WIRE-1: Autopilot.approval_requested(user_id, card_id) is not built yet"
    part = reader(USER, card.card_id)
    assert part is not None, f"CHN-WIRE-1: preview of an L1/T3 card ({card.tier}) stored no approval.requested part"
    return copy.deepcopy(part)


def resolved(
    requested: dict,
    line: Line,
    *,
    option: str = APPROVE,
    by: str = "person",
    ref: str = USER,
    channel: str = "web",
    pin_verified: bool = False,
    at: str | None = None,
    **data: Any,
) -> dict:
    """The `approval.resolved` part `tilo-api` records for a tap: authz stamped with the tap time (now, by default)."""
    gate = requested["data"]
    body = {
        "gate_id": gate["gate_id"],
        "card_id": gate["card_id"],
        "outbox_id": gate["outbox_id"],
        "option": option,
        "channel": channel,
        "pin_verified": pin_verified,
    }
    return {
        "type": "approval.resolved",
        "authz": {"by": by, "ref": ref, "at": at or iso(line.clock())},
        "data": body | data,
    }


def try_send(ap: Any, card_id: str, approval: dict | None) -> Any | None:
    """`ap.send(USER, card_id, approval=...)`: the Outcome, or None when the outbox refused it. Anything else raised
    (a TypeError for a missing parameter included) propagates, so a not-yet-built API fails the test."""
    try:
        return ap.send(USER, card_id, approval=approval)
    except Exception as exc:
        if type(exc).__name__ == "OutboxRefused":
            return None
        raise


def was_refused(outcome: Any | None) -> bool:
    return outcome is None or outcome.status == "refused"


def assert_nothing_sent(line: Line, *, minutes: int = 10) -> None:
    """No entry, no Gmail call and no data.transfer, however long the clock runs and however hard the outbox is hit."""
    line.advance(minutes * 60)
    line.storm(10)
    assert line.entries() == [], "a refused Send must leave no outbox entry"
    assert line.api.sent == [], "a refused Send must reach Gmail never"
    assert line.transfers == []


def one_sent(line: Line) -> dict:
    """The card's one entry, dispatched through the real outbox and FakeGmail: sent exactly once."""
    line.storm(25, line.outbox, line.new_outbox())
    entries = line.entries()
    assert len(entries) == 1, f"expected one outbox entry, found {len(entries)}"
    assert entries[0]["state"] == "sent" and len(line.api.sent) == 1, "the entry must be sent exactly once"
    return entries[0]


def evidence_of(line: Line) -> list[tuple[dict, dict]]:
    return line.spy.calls  # type: ignore[attr-defined]


def t3_money_body() -> str:
    return "Hi David,\n\nWe will refund the deposit on Friday.\n\nBest,\nSarah"


def load_policy_applied_part() -> dict:
    """A contract-valid `policy.applied` part (the OB-01 crossref fixture of an L2 web instruction), for the tests that
    hand the Autopilot a policy part where an approval belongs."""
    from _chn_0305_lib import CONTRACTS

    path = CONTRACTS / "fixtures" / "outbox" / "crossref" / "valid" / "policy_reply_instructed_on_the_web.json"
    return json.loads(path.read_text(encoding="utf-8"))["authorised_by"]
