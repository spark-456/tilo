"""FR-CHN-10: untrusted text is cut to a fixed raw length before any NFKC, fold or regex (PRD 16.3, EFF-03).

NFKC is quadratic on characters that expand (U+FDFA expands to 18 characters, U+3300 to 4), and a regex that
fails after scanning a long run is quadratic too, so an unbounded mail body, header or model answer would be an
unauthenticated denial of service (security review of #211, FR-CHN-09).
"""

from __future__ import annotations

import time

import pytest
from _chn10_lib import INJECTION_MARKER, answer, drafting_module, make_rig

INSTRUCTION = "Tell David Friday 2pm works."
CLEAN = "Hi David,\n\nFriday at 2pm works for us.\n\nBest regards,\nSarah"


def test_FR_CHN_10_huge_expanding_thread_is_drafted_in_under_a_second() -> None:
    rig = make_rig()
    thread, _ = rig.thread(body="ﷺ" * 1_000_000, subject="㌀" * 100_000)

    start = time.process_time()
    result = rig.draft(thread, INSTRUCTION)
    elapsed = time.process_time() - start

    assert elapsed < 1.0, elapsed
    assert result.status == "ready"
    assert len(result.draft.subject) <= 600


def test_FR_CHN_10_huge_header_lists_and_answer_are_bounded() -> None:
    rig = make_rig()
    long_address = "a" * 100_000 + "@harriercharters.example"
    thread, key = rig.thread(
        to=["ops@harborview.example", long_address, *(f"x{n}@y.example" for n in range(10_000))],
        cc=["ﷺ" * 100_000],
        headers={"References": "<r@mail.example> " * 50_000},
    )
    rig.model.script(key, answer("ﷺ" * 200_000))

    start = time.process_time()
    result = rig.draft(thread, INSTRUCTION, mode="reply_all")
    elapsed = time.process_time() - start

    assert elapsed < 1.0, elapsed
    assert result.status == "failed" and result.draft is None


def test_FR_CHN_10_safety_screen_sees_the_model_prompt_and_the_raw_rest() -> None:
    # The screen gets exactly what the model gets (normalised, capped prefix) plus the raw text past each cap, so a
    # marker hidden past a cap is still flagged although the model never sees it (security review of #211).
    rig = make_rig()
    tail = "ﷺ" * 10 + INJECTION_MARKER
    thread, _ = rig.thread(body="Can Marcus come Friday?" + " pad" * 5_000 + tail, subject="Tune-up" + "x" * 600 + tail)

    result = rig.draft(thread, INSTRUCTION)

    for request in rig.model.requests:
        assert any(request.prompt in text for text in rig.safety.texts)
        assert INJECTION_MARKER not in request.prompt
    assert rig.safety.screened(tail)
    assert result.flagged is True
    assert result.draft is None or result.draft.safety_flag is True


HOSTILE_FROM = "(" * 497 + ")" * 497 + " <a@b.example>"


@pytest.mark.parametrize("where", ["from", "to", "cc"])
def test_FR_CHN_10_hostile_address_header_never_raises(where: str) -> None:
    rig = make_rig()
    fields = {"from": {"sender": HOSTILE_FROM}, "to": {"to": [HOSTILE_FROM]}, "cc": {"cc": [HOSTILE_FROM, ":" * 1_500]}}
    thread, _ = rig.thread(answers=[answer(CLEAN)], **fields[where])

    result = rig.draft(thread, INSTRUCTION, mode="reply_all")

    assert rig.safety.texts, "the safety screen runs before any address is parsed"
    if where == "from":
        assert result.status == "failed" and result.draft is None  # no parseable sender: no one to reply to
    else:
        assert result.status == "ready"
        assert "a@b.example" not in result.draft.to + result.draft.cc


def test_FR_CHN_10_address_parser_errors_mean_no_address(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = drafting_module()

    def explode(values: object) -> object:
        raise RecursionError("nested comments")

    monkeypatch.setattr(mod, "getaddresses", explode)
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN)])

    result = rig.draft(thread, INSTRUCTION)

    assert rig.safety.texts
    assert result.status == "failed" and result.draft is None


def test_FR_CHN_10_checker_regexes_are_linear_on_long_runs() -> None:
    mod = drafting_module()
    body = "a" * 19_000 + " 1" + "b@" * 400

    start = time.process_time()
    mod.find_invented(body, instruction="x" * 100_000, thread=["y" * 1_000_000], trusted=["z@" * 500_000])
    elapsed = time.process_time() - start

    assert elapsed < 1.0, elapsed
