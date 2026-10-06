"""FR-CHN-10 security review round 1 (PR #224): the content checker reads text the way a person sees it, counts
spelled numbers and bare links, honours negated commitments, checks the model's questions, and every untrusted size
is bounded (PRD 11.4 Content, 16.3, EFF-03)."""

from __future__ import annotations

import time

import pytest
from _chn10_lib import INJECTION_MARKER, USER, Msg, answer, drafting_module, load_drafting_cases, make_rig

INSTRUCTION = "Tell David Friday 2pm works."
THREAD = ["Can Marcus come by this Friday afternoon, and what is your hourly rate? We paid 1 deposit of 500."]
CLEAN = "Hi David,\n\nFriday at 2pm works for us.\n\nBest regards,\nSarah"


def _kinds(body: str, instruction: str = INSTRUCTION, thread: list[str] = THREAD) -> set[str]:
    return {f.kind for f in drafting_module().find_invented(body, instruction=instruction, thread=thread)}


CASES = load_drafting_cases()


def _case(case_id: str):
    return next(c for c in CASES if c.id == case_id)


# (a) one test per class of hidden or look-alike characters


@pytest.mark.parametrize(
    "body,kind",
    [
        ("We will re\u00adfund it.", "commitment"),  # soft hyphen (Cf)
        ("We will wai\u200bve the fee.", "commitment"),  # zero-width space (Cf)
        ("We will waive\u034f the fee.", "commitment"),  # combining grapheme joiner
        ("It is fr\ufe0fee.", "commitment"),  # variation selector
        ("It is fr\U000e0020ee.", "commitment"),  # tag character
        ("It is fr\u0435\u0435.", "commitment"),  # Cyrillic look-alikes
        ("It is \u0440\u0430\u0443able later.", "commitment"),  # all-Cyrillic "pay"
        ("It is fr\u03b5\u03b5.", "commitment"),  # Greek look-alikes
        ("We will re-fund it.", "commitment"),  # hyphen-split word
        ("We will re\x7ffund it.", "commitment"),  # control character
        ("We will re-\nfund it.", "commitment"),  # hyphen and line break
        ("Pay at https:/\u200b/settle.evil.example/inv now.", "contact"),
        ("The total is 1\u200b500.", "number"),  # 1 and 500 are both in the thread
    ],
)
def test_FR_CHN_10_hidden_and_look_alike_characters_are_read_as_seen(body: str, kind: str) -> None:
    assert kind in _kinds(body)


def test_FR_CHN_10_sources_are_cleaned_the_same_way() -> None:
    assert _kinds("Friday works.", instruction="Reply to David.", thread=["Fri\u200bday works?"]) == set()
    assert _kinds("Friday works.", instruction="Tell David Fr\u0456day w\u043erks.", thread=[]) == set()


def test_FR_CHN_10_hidden_characters_reach_needs_you_end_to_end() -> None:
    for sentence in ("It is fr\u0435\u0435.", "We will re\u00adfund it.", "See https:/\u200b/settle.evil.example/inv"):
        rig = make_rig()
        thread, _ = rig.thread(answers=[answer(CLEAN.replace("us.", "us. " + sentence))])
        result = rig.draft(thread, INSTRUCTION)
        assert result.status == "needs_you" and result.draft is None, sentence
        assert rig.events.of_type("artifact.created") == []


# (b) spelled numbers, ordinals and bare links


@pytest.mark.parametrize(
    "body", ["thirteen", "fifteen", "nineteen", "a million", "a billion", "on the fifteenth", "the twentieth"]
)
def test_FR_CHN_10_number_words_and_ordinals_are_numbers(body: str) -> None:
    assert "number" in _kinds(f"We can do {body}.")


def test_FR_CHN_10_spelled_ordinal_matches_its_digits() -> None:
    assert _kinds("See you on the fifteenth.", thread=["Is the 15th fine?"]) == set()


@pytest.mark.parametrize("link", ["evil-portal.example/inv", "pay.evil.example", "settle.example/a/b?x=1"])
def test_FR_CHN_10_bare_domain_is_a_contact(link: str) -> None:
    assert "contact" in _kinds(f"Pay at {link} today.")


def test_FR_CHN_10_spelled_percent_is_not_ready() -> None:
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer("Friday at 2pm works, at fifteen percent below the quote.")])
    result = rig.draft(thread, INSTRUCTION)
    assert result.status == "needs_you" and "number" in {f.kind for f in result.findings}


# (c) a negated instruction mention never allows the commitment


def test_FR_CHN_10_negated_instruction_does_not_allow_the_commitment() -> None:
    instruction = "Tell David Friday 2pm works, no refund of the deposit."
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer("Hi David,\n\nFriday at 2pm works, and we will refund your deposit.")])
    result = rig.draft(thread, instruction)
    assert result.status == "needs_you" and result.draft is None
    assert {f.kind for f in result.findings} == {"commitment"}

    rig = make_rig()
    thread, _ = rig.thread(answers=[answer("Hi David,\n\nFriday at 2pm works. There is no refund of the deposit.")])
    assert rig.draft(thread, instruction).status == "ready"  # negated the same way: still allowed


@pytest.mark.parametrize(
    "case_id,sentence",
    [
        ("E-MAIL-36", "We will refund the full amount in cash."),
        ("E-MAIL-48", "Our Harborview warranty also covers the parts you supply."),
    ],
)
def test_FR_CHN_10_eval_forbidden_commitments_are_found_without_any_added_fact(case_id: str, sentence: str) -> None:
    case = _case(case_id)
    find = drafting_module().find_invented
    assert find(case.clean, instruction=case.instruction, thread=case.sources()) == []
    findings = find(case.clean + "\n\n" + sentence, instruction=case.instruction, thread=case.sources())
    assert {f.kind for f in findings} == {"commitment"}


def test_FR_CHN_10_double_negation_is_not_a_negation() -> None:
    assert "commitment" in _kinds("We will not hesitate to refund it.", instruction="No refund, Friday 2pm works.")
    assert "commitment" in _kinds("Not without a refund.", instruction="No refund, Friday 2pm works.")


# (d) the model's questions get the same number, date and contact check


def test_FR_CHN_10_question_with_an_unsupported_fact_is_never_returned() -> None:
    rig = make_rig()
    asked = ["Should I pay the 9,999 invoice at https://evil.example/pay now?", "Which Friday does David mean?"]
    thread, _ = rig.thread(answers=[answer("", questions=asked)])
    result = rig.draft(thread, INSTRUCTION)
    assert result.status == "needs_you" and result.draft is None
    assert result.questions == ("Which Friday does David mean?",)
    assert {"number", "contact"} <= {f.kind for f in result.findings}


# Bounds


def test_FR_CHN_10_raw_rest_over_the_screen_cap_is_flagged_not_sent() -> None:
    mod = drafting_module()
    rig = make_rig()
    thread, _ = rig.thread(body="x" * (mod.SCREEN_CAP + 20_000) + INJECTION_MARKER, answers=[answer(CLEAN)])
    result = rig.draft(thread, INSTRUCTION)
    assert result.flagged is True and not rig.safety.screened(INJECTION_MARKER)
    assert max(len(t) for t in rig.safety.texts) < mod.SCREEN_CAP + 50_000


@pytest.mark.parametrize("char", ["\ufdfa", "\u3300"])
def test_FR_CHN_10_whole_thread_is_bounded(char: str) -> None:
    mod = drafting_module()
    rig = make_rig()
    big = [Msg(f"m{n}", f"x{n}@y.example", char * 600, char * 9_000, [char * 2_100], [char * 2_100]) for n in range(60)]
    thread, _ = rig.thread(earlier=big, body=char * 9_000, subject=char * 600, answers=[answer(CLEAN)])
    start = time.process_time()
    result = rig.draft(thread, INSTRUCTION)
    assert time.process_time() - start < 1.0
    assert result.status == "ready"
    assert all(len(r.prompt) < mod.THREAD_CAP + 5_000 for r in rig.model.requests)


def test_FR_CHN_10_reply_all_recipients_are_capped() -> None:
    mod = drafting_module()
    rig = make_rig()
    thread, _ = rig.thread(cc=[f"p{n}@crew.example" for n in range(45)], answers=[answer(CLEAN)])
    d = rig.draft(thread, INSTRUCTION, mode="reply_all").draft
    assert len(d.to) + len(d.cc) == mod.MAX_RECIPIENTS


def test_FR_CHN_10_deeply_nested_model_json_is_an_unusable_answer() -> None:
    rig = make_rig()
    thread, _ = rig.thread(answers=['{"body": ' + "[" * 9_000 + "]" * 9_000 + "}"])
    assert rig.draft(thread, INSTRUCTION).status == "failed"


def test_FR_CHN_10_address_parser_value_error_means_no_address(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = drafting_module()

    def explode(values: object) -> object:
        raise ValueError("bad header")

    monkeypatch.setattr(mod, "getaddresses", explode)
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN)])
    assert rig.draft(thread, INSTRUCTION).status == "failed"


def test_FR_CHN_10_draft_store_has_no_unused_put() -> None:
    assert not hasattr(drafting_module().DraftStore, "put")


def test_FR_CHN_10_empty_local_part_is_no_address() -> None:
    rig = make_rig()
    thread, _ = rig.thread(cc=["@evil.example", "sarah.chen@harborview.example"], answers=[answer(CLEAN)])
    d = rig.draft(thread, INSTRUCTION, mode="reply_all").draft
    assert "@evil.example" not in d.to + d.cc
    rig = make_rig()
    thread, _ = rig.thread(sender="@evil.example", answers=[answer(CLEAN)])
    assert rig.draft(thread, INSTRUCTION).status == "failed"


def test_FR_CHN_10_plus_tag_aliases_of_the_own_mailbox_are_own() -> None:
    rig = make_rig()
    david = Msg(
        "m0", "David Miller <david.miller@harriercharters.example>", "Tune-up", "Friday?", ["ops@harborview.example"]
    )
    own_alias = "ops+desk@harborview.example"
    thread, _ = rig.thread(earlier=[david], sender=own_alias, to=[david.sender], cc=[], answers=[answer(CLEAN)])
    d = rig.draft(thread, INSTRUCTION, mode="reply_all").draft
    assert d.to == ("david.miller@harriercharters.example",) and d.cc == ()  # replies to David, not to itself

    rig = make_rig()
    thread, _ = rig.thread(cc=["OPS+x@harborview.example", "sarah.chen@harborview.example"], answers=[answer(CLEAN)])
    d = rig.draft(thread, INSTRUCTION, mode="reply_all").draft
    assert "ops+x@harborview.example" not in d.to + d.cc


def test_FR_CHN_10_artifact_created_is_emitted_once_after_a_failed_emit() -> None:
    rig = make_rig()
    failures = [RuntimeError("event bus down")]

    def emit(part: dict) -> None:
        if failures:
            raise failures.pop()
        rig.events(part)

    svc = drafting_module().Drafter(
        reader=rig.reader, model=rig.model, safety=rig.safety, drafts=rig.drafts, clock=rig.clock, emit=emit
    )
    thread, _ = rig.thread(answers=[answer(CLEAN)])
    ask = {"instruction_id": "ins-emit", "thread_id": thread.thread_id, "instruction": INSTRUCTION}
    ask["mailbox"] = "ops@harborview.example"
    with pytest.raises(RuntimeError):
        svc.draft(USER, **ask)
    assert svc.draft(USER, **ask).status == "ready"
    assert rig.events.of_type("artifact.created") == []  # within the lease: no second emitter yet

    rig.clock.advance(drafting_module().EMIT_LEASE + 1)
    first = svc.draft(USER, **ask)
    svc.draft(USER, **ask)
    created = rig.events.of_type("artifact.created")
    assert len(created) == 1 and created[0]["data"]["artifact"]["artifact_id"] == first.draft.artifact_id
