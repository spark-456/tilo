"""CL-LIVE-2 fix pass (security review): the typed word is exact, a forged call cannot spend an approval, hidden
characters hold a write, a null destination matches, and unused approvals can be dropped. Fake Google, no network.
"""

from __future__ import annotations

import pytest
from _cl_live2_lib import WriteEnv, clean_process_env, make_write_env, socket_guard  # noqa: F401


def _held(g: WriteEnv, case: dict) -> None:
    assert g.state(case) == "failed" and g.apis.requests == []


@pytest.mark.parametrize("said", ["YES", "Yes", "yEs", "YES\n"])
def test_CL_LIVE_2_only_the_exact_lowercase_word_yes_approves(said):
    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case, said=said) is False
    g.run(case)
    _held(g, case)


def test_CL_LIVE_2_a_typed_yes_with_surrounding_spaces_still_approves():
    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case, said="  yes \n") is True


def test_CL_LIVE_2_a_call_without_a_real_grant_never_spends_the_approval():
    from tilo_connectors.errors import MissingGrant
    from tilo_connectors.outbox import Grant

    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case)
    forged_key = {**case["entry"], "idempotency_key": "r_live:U2:create_draft:forged"}
    for grant in (None, object(), Grant(case["entry"]["world_id"], forged_key["idempotency_key"])):
        with pytest.raises(MissingGrant):
            g.adapters["gmail"].execute_side_effect(forged_key, grant)

    g.run(case)

    assert g.state(case) == "sent" and len(g.apis.draft_messages()) == 1


@pytest.mark.parametrize("subject", ["Invoice ‮exe.gnp", "Hello​there", "Note⁦x"])
def test_CL_LIVE_2_a_subject_with_hidden_or_bidi_characters_is_held(subject):
    g = make_write_env()
    g.build()
    case = g.mail_case(item=g.email(subject=subject, body_text="plain body"))
    review = g.gate.review(g.card(case))
    assert review.allowed is False and "hidden" in review.why
    assert g.gate.approve(review, said="yes", interactive=True) is False
    g.run(case)
    _held(g, case)


def test_CL_LIVE_2_a_body_or_file_name_with_control_characters_is_held_but_newlines_and_tabs_are_fine():
    g = make_write_env()
    g.build()
    for body in ("line‮ one", "esc\x1b[2J here", "zero‍width"):
        review = g.gate.review(g.card(g.mail_case(item=g.email(subject="Fine", body_text=body))))
        assert review.allowed is False and "hidden" in review.why, body
    fine = g.gate.review(g.card(g.mail_case(item=g.email(subject="Fine", body_text="a\nb\r\n\tc"))))
    assert fine.allowed is True
    from _gapi_lib import drive_case

    ref = g.artifacts.put_file("art_hidden", name="notes.txt", mime_type="text/plain", content="x‮y".encode())
    drive = drive_case(item=ref, destination="thread-dev-1")
    assert g.gate.review(g.card(drive)).allowed is False


def test_CL_LIVE_2_a_null_destination_is_not_turned_into_the_word_none():
    g = make_write_env()
    g.build()
    case = g.mail_case(recipients=("buyer@example.net",))
    case["entry"]["destination"] = None
    review = g.gate.review(g.card(case))
    assert review.allowed and "None" not in review.destination and review.destination == "no thread: a new message"
    assert g.approve(case)

    g.run(case)

    assert g.state(case) == "sent" and len(g.apis.draft_messages()) == 1


def test_CL_LIVE_2_unused_approvals_can_be_dropped_and_a_dropped_one_no_longer_writes():
    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case) and g.gate.open_approvals == 1
    assert g.gate.clear() == 1 and g.gate.open_approvals == 0
    g.run(case)
    _held(g, case)


def test_CL_LIVE_2_clear_keeps_spent_approvals_spent():
    g = make_write_env()
    g.build()
    first = g.mail_case()
    assert g.approve(first)
    g.run(first)
    assert g.state(first) == "sent" and g.gate.clear() == 0 and g.gate.open_approvals == 0
    assert g.approve(first) and g.gate.open_approvals == 1, "a spent approval needs a new yes for a new send"
