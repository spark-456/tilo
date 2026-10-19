"""FR-CHN-11: what may never ride the L2 undo window. PRD 10.4 T3 ("new recipients; ... money, contract or legal
terms; content flagged by injection detection": L1 only, always a person), 11.4 Formats (adding a recipient is T3)
and Injection, FR-HIL-04 (no T3 without a person), BQ-147 (`safety_flag` stays T3), issue #243 (money / legal /
commitment content goes to T3 through a deterministic signal that does not depend on the drafting checker's
`ready`). The policy port here always answers L2, so only the autopilot's own tiering can stop an auto-send.
API: API_FR_CHN_11.md."""

from __future__ import annotations

import unicodedata

import pytest
from _chn10_lib import drafting_module
from _chn11_lib import (
    BENIGN,
    DAVID,
    SARAH,
    USER,
    VOUCHED,
    autopilot_module,
    context,
    make_bench,
    needs_autopilot,
    pair,
    scripted_thread,
)
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

MONEY = [
    "The total comes to $1,200.",
    "We can offer a refund.",
    "The invoice is attached below.",
    "Payment is due on receipt.",
    "Please wire it to our bank account.",
    "Our IBAN is on the letterhead.",
]
LEGAL = [
    "Please sign the contract.",
    "We accept no liability for delays.",
    "They threatened a lawsuit.",
    "Send over the NDA.",
    "These terms apply to the booking.",
    "Sign the waiver at the dock.",
]
COMMITMENT = [
    "We will deliver the report next week.",
    "I guarantee it will be ready.",
    "We promise to fix it.",
    "We commit to the Friday deadline.",
]
OBFUSCATED = [
    "We can offer a ref\u200bund.",
    "Please sign the c\u043entract.",
    "Send over the \u202eNDA.",
    "We can offer a \uff52\uff45\uff46\uff55\uff4e\uff44.",
    "The invo\u00adice is below.",
    "P\u0430yment is due on receipt.",
    "No li\u200dability.",
]
BENIGN_LINES = [
    "Thanks David, Friday 2pm works for us.",
    "See you then.",
    "Sounds good, talk soon.",
    "Happy to meet next week.",
]


@pytest.mark.parametrize(
    ("category", "text"),
    [("money", t) for t in MONEY] + [("legal", t) for t in LEGAL] + [("commitment", t) for t in COMMITMENT],
)
def test_FR_CHN_11_money_legal_commitment_terms_give_the_t3_signal(category: str, text: str) -> None:
    assert category in autopilot_module().t3_content_signal(text)


@pytest.mark.parametrize("text", OBFUSCATED)
def test_FR_CHN_11_obfuscated_terms_still_give_the_t3_signal(text: str) -> None:
    # Zero-width, look-alike (Cyrillic), bidi, fullwidth and soft-hyphen variants: either the cleaned word matches
    # or the signal fails closed on the obfuscation itself (issue #243).
    assert autopilot_module().t3_content_signal(text)


@pytest.mark.parametrize("text", BENIGN_LINES + [BENIGN])
def test_FR_CHN_11_benign_text_gives_no_t3_signal(text: str) -> None:
    # CHN-GATE-E: "David" and "Sarah" are names the bench thread vouches for (a recipient and the mailbox owner)
    assert autopilot_module().t3_content_signal(text, names=VOUCHED) == frozenset()


@pytest.mark.parametrize("text", [MONEY[1], LEGAL[0], COMMITMENT[0], OBFUSCATED[0]])
@pytest.mark.parametrize("instruction", ["", "Tell David we will refund the deposit and sign the contract."])
def test_FR_CHN_11_checker_ready_plus_any_instruction_never_downgrades_t3_to_l2(text: str, instruction: str) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    body = f"Hi David,\n\nFriday 2pm works for us. {text}\n\nBest,\nSarah"
    card = bench.ap.preview(USER, *pair(thread, body, instruction=instruction))
    assert card.tier == "T3" and "money_or_legal" in card.modifiers
    assert (card.level, card.undo_window_s, card.outbox_id) == ("L1", 0, None)
    assert card.options == ("send", "edit", "cancel")
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}, "T3 is never scheduled without a person"
    out = bench.ap.send(USER, card.card_id)
    (entry,) = bench.outbox.all()
    assert out.status == "queued" and entry["authz"]["by"] == "person" and entry["risk_tier"] == "T3"
    assert "money_or_legal" in entry["modifiers"]


@pytest.mark.parametrize(("safety_flag", "flagged"), [(True, True), (True, False), (False, True)])
def test_FR_CHN_11_safety_flagged_draft_stays_t3_bq_147(safety_flag: bool, flagged: bool) -> None:
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    card = bench.ap.preview(USER, *pair(thread, BENIGN, safety_flag=safety_flag, flagged=flagged))
    assert card.tier == "T3" and "safety_flag" in card.modifiers and card.outbox_id is None
    bench.rig.clock.advance(3600)
    bench.outbox.dispatch_due()
    assert bench.outbox.entries == {}


def test_FR_CHN_11_needs_you_draft_has_no_send_and_findings_are_inert_text() -> None:
    mod = drafting_module()
    bench = make_bench("L2")
    thread = scripted_thread(bench)
    findings = (
        mod.Finding(kind="obfuscation", text="pay\u202eme\u200b now\x1b[31m"),
        mod.Finding(kind="contact", text="<a href='https://evil.example/x'>here</a>"),
    )
    result = mod.DraftResult(
        instruction_id="ins-needs-you", status="needs_you", draft=None, findings=findings, questions=(), flagged=True
    )
    card = bench.ap.preview(USER, context(thread, instruction_id="ins-needs-you"), result)
    assert "send" not in card.options and set(card.options) == {"edit", "cancel"}
    assert len(card.findings) == 2 and all(isinstance(f, str) for f in card.findings)
    assert card.findings[0].startswith("obfuscation") and card.findings[1].startswith("contact")
    for line in card.findings:
        assert not [c for c in line if unicodedata.category(c) in ("Cc", "Cf")], "findings are shown inert"
    assert bench.ap.send(USER, card.card_id).status == "refused"
    assert bench.outbox.entries == {}


def test_FR_CHN_11_draft_body_control_and_format_chars_are_cleaned() -> None:
    bench = make_bench("L1")
    thread = scripted_thread(bench)
    body = "Hi David,\x07\n\nFriday 2pm\u202e works\u200b for us.\x1b[0m\r\x00\n\nBest,\tSarah\u2066"
    card = bench.ap.preview(USER, *pair(thread, body))
    for text in (card.body, card.excerpt):
        assert not [c for c in text if unicodedata.category(c) == "Cf"]
        assert not [c for c in text if unicodedata.category(c) == "Cc" and c not in "\n\t"]
    assert "Friday 2pm works for us." in card.body
    assert autopilot_module().clean_text(body) == card.body


def test_FR_CHN_11_reply_all_to_a_sender_controlled_cc_is_t3_unless_a_known_contact() -> None:
    for known, tier in (((), "T3"), ((SARAH,), "T2")):
        bench = make_bench("L2", contacts=known)
        thread = scripted_thread(bench)  # inbound mail Cc'd SARAH: a header the sender controls
        card = bench.ap.preview(USER, *pair(thread, BENIGN, mode="reply_all", to=(DAVID,), cc=(SARAH,)))
        assert card.tier == tier
        assert ("new_recipients" in card.modifiers) is (tier == "T3")
        assert (card.outbox_id is None) is (tier == "T3")


POOL = [DAVID, SARAH, "stranger@elsewhere.example", "billing@harriercharters.example", "reply-to@attacker.example"]


@needs_autopilot
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    to=st.lists(st.sampled_from(POOL), min_size=1, max_size=3, unique=True),
    cc=st.lists(st.sampled_from(POOL), max_size=3, unique=True),
    contacts=st.lists(st.sampled_from(POOL), max_size=3, unique=True),
    tap=st.booleans(),
)
def test_FR_CHN_11_no_send_adds_a_recipient_without_a_person(to, cc, contacts, tap) -> None:
    cc = [a for a in cc if a not in to]
    bench = make_bench("L2", contacts=contacts)
    thread = scripted_thread(bench)
    known = {DAVID} | set(contacts)  # DAVID wrote in the thread; everything else only via the user's contacts
    card = bench.ap.preview(USER, *pair(thread, BENIGN, to=tuple(to), cc=tuple(cc)))
    assert list(card.to) == to and list(card.cc) == cc, "recipients are shown exactly, never added"
    if tap:
        bench.ap.send(USER, card.card_id)
    bench.rig.clock.advance(120)
    bench.outbox.dispatch_due()
    for entry in bench.outbox.sent_entries():
        assert sorted(entry["recipients"]) == sorted(to + cc)
        if set(entry["recipients"]) - known:
            assert entry["authz"]["by"] == "person" and "new_recipients" in entry["modifiers"]
