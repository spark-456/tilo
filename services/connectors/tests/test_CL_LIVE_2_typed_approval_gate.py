"""CL-LIVE-2 (CONNECTORS-LIVE slice 2): with `allow_writes`, the real Gmail draft / Drive save (and, with `allow_send`,
Gmail send) execute for real, but only through the outbox AND a typed `yes` at an interactive terminal for exactly the
payload that is then written. Fake Google (`FakeGoogleApis`), fake broker, no network, no real token.
API pinned in API_CL_LIVE_2.md.
"""

from __future__ import annotations

import pytest
from _cl_live2_lib import (  # noqa: F401
    SECRET,
    STAND_IN,
    WriteEnv,
    clean_process_env,
    make_write_env,
    second_case,
    socket_guard,
)
from _cl_live_lib import DRIVE_FILE, GMAIL_COMPOSE, GMAIL_READONLY, GMAIL_SEND


def _no_request(g: WriteEnv, case: dict) -> None:
    assert g.state(case) == "failed"
    assert g.apis.requests == [], "not even a read went out"
    assert [e for e in g.emitted if e["type"] == "data.transfer"] == []


def test_CL_LIVE_2_without_allow_writes_nothing_changes_from_read_only():
    from tilo_connectors import real

    g = make_write_env()
    adapters = g.build(allow_writes=False)
    assert real.is_real_read_only(adapters) and real.write_gate_of(adapters) is None
    case = g.mail_case()
    g.run(case)
    _no_request(g, case)


def test_CL_LIVE_2_send_without_writes_is_refused_before_anything():
    from tilo_connectors import real

    g = make_write_env(send=True)
    with pytest.raises(real.RealConnectorsRefused) as info:
        g.build(allow_writes=False, allow_send=True)
    assert info.value.code == "send_needs_writes" and g.apis.requests == [] and g.spy.asked == []


@pytest.mark.parametrize("env", [{}, {"LIVE": "true"}, {"LIVE": "1", "CI": "true"}, {"LIVE": "1", "K_SERVICE": "x"}])
def test_CL_LIVE_2_the_write_flags_obey_the_same_guards_as_read_only(env):
    from tilo_connectors import real

    g = make_write_env()
    with pytest.raises(real.RealConnectorsRefused):
        g.build(environ=env)
    with pytest.raises(real.RealConnectorsRefused) as info:
        g.build(mode="replay")
    assert info.value.code == "not_live_mode" and g.apis.requests == []


def test_CL_LIVE_2_an_approved_draft_is_written_exactly_once_with_an_authorised_transfer():
    g = make_write_env()
    g.build()
    case = g.mail_case(recipients=("buyer@example.net",))
    assert g.approve(case)

    g.run(case)

    assert g.state(case) == "sent"
    assert len(g.posts("/drafts")) == 1 and len(g.apis.draft_messages()) == 1
    (draft,) = g.apis.draft_messages()
    assert draft["To"] == "buyer@example.net" and g.apis.sent() == []
    (transfer,) = [e for e in g.emitted if e["type"] == "data.transfer"]
    assert transfer["authz"]["by"] == "person" and transfer["data"]["action_type"] == "create_draft"
    assert g.adapters["gmail"].sent == ("gmail.create_draft",)
    assert GMAIL_COMPOSE in g.scopes_asked() and GMAIL_SEND not in g.scopes_asked()


def test_CL_LIVE_2_no_approval_means_no_request_at_all():
    g = make_write_env()
    g.build()
    case = g.mail_case()
    g.run(case)
    _no_request(g, case)


@pytest.mark.parametrize(
    ("said", "interactive"),
    [("y", True), ("no", True), ("", True), ("yes please", True), ("sure", True), ("yes", False)],
    ids=["y", "no", "empty", "yes_please", "sure", "yes_without_a_terminal"],
)
def test_CL_LIVE_2_only_a_typed_yes_at_an_interactive_terminal_approves(said, interactive):
    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case, said=said, interactive=interactive) is False
    g.run(case)
    _no_request(g, case)


def test_CL_LIVE_2_an_approval_covers_exactly_the_payload_reviewed():
    """Approved as A, then the recipients, the body, or the destination became B: no request, the entry fails."""
    for change in ("recipients", "body", "destination", "subject"):
        g = make_write_env()
        g.build()
        case = g.mail_case(recipients=("buyer@example.net",))
        assert g.approve(case)
        entry = case["entry"]
        if change == "recipients":
            entry["recipients"] = ["other@example.net"]
        elif change == "destination":
            entry["destination"] = "thr_other"
        else:
            ref = entry["item"]
            kept = g.artifacts.get(ref["artifact_id"], ref["version"])
            g.artifacts.put_email(
                ref["artifact_id"], subject="changed" if change == "subject" else kept["subject"],
                body_text="changed" if change == "body" else kept["body_text"],
            )  # fmt: skip
        g.run(case)
        _no_request(g, case)


def test_CL_LIVE_2_a_retry_after_a_lost_response_never_makes_a_second_draft():
    """The request is carried out, the answer is lost: ambiguous. The next dispatch finds the draft by its marker."""
    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case) and g.approve(case), "approving twice is still one approval"
    g.apis.lose_response(lambda r: r.method == "POST" and r.url.endswith("/drafts"))

    g.run(case)
    for _ in range(3):
        g.outbox.dispatch_due()

    assert g.state(case) == "sent"
    assert len(g.apis.draft_messages()) == 1 and len(g.posts("/drafts")) == 1


def test_CL_LIVE_2_an_approval_is_spent_by_its_first_entry():
    g = make_write_env()
    g.build()
    first = g.mail_case(recipients=("buyer@example.net",))
    assert g.approve(first)
    g.run(first)
    twin = second_case(first, key="r_live:U2:create_draft:twin")
    from _gapi_lib import enqueue

    enqueue(g.outbox, twin)
    g.outbox.dispatch_due()

    assert g.state(first) == "sent" and g.state(twin) == "failed"
    assert len(g.apis.draft_messages()) == 1


def test_CL_LIVE_2_a_forged_grant_or_a_policy_authz_never_gets_through():
    from tilo_connectors.errors import MissingGrant
    from tilo_connectors.real_writes import WriteRefused

    g = make_write_env()
    g.build()
    case = g.mail_case()
    assert g.approve(case)
    with pytest.raises(MissingGrant):
        g.adapters["gmail"].execute_side_effect(case["entry"], object())
    policy = {**case["entry"], "authz": {"by": "policy", "ref": "pol_1", "at": case["entry"]["created_at"]}}
    with pytest.raises(WriteRefused) as info:
        g.gate.authorise(policy, "gmail")
    assert info.value.code == "not_a_person"
    with_files = {**case["entry"], "attachments": [{"artifact_id": "art_x", "version": 1}]}
    with pytest.raises(WriteRefused) as info:
        g.gate.authorise(with_files, "gmail")
    assert info.value.code == "attachments_off"
    assert g.apis.requests == []


def test_CL_LIVE_2_send_is_off_unless_allow_send_and_a_card_for_it_is_held():
    g = make_write_env(send=True)
    g.build()
    case = g.mail_case("send_email")
    review = g.gate.review(g.card(case))
    assert review is not None and review.allowed is False and "not enabled" in review.why
    assert g.gate.approve(review, said="yes", interactive=True) is False
    g.run(case)
    _no_request(g, case)


def test_CL_LIVE_2_with_allow_send_an_approved_send_goes_out_once_and_only_then():
    g = make_write_env(send=True)
    g.build(allow_send=True)
    unapproved = g.mail_case("send_email", recipients=("buyer@example.net",))
    g.run(unapproved)
    _no_request(g, unapproved)

    case = g.mail_case("send_email", recipients=("buyer@example.net",))
    assert g.approve(case)
    g.run(case)

    assert g.state(case) == "sent" and len(g.posts("/messages/send")) == 1 and len(g.apis.sent()) == 1
    assert GMAIL_SEND in g.scopes_asked() and g.gate.executed == ["gmail.send_email"]


def test_CL_LIVE_2_an_approved_drive_save_makes_one_upload_in_the_tilo_folder_and_no_approval_makes_none():
    g = make_write_env()
    g.build()
    refused = g.drive_case()
    g.run(refused)
    _no_request(g, refused)

    case = g.drive_case()
    assert g.approve(case)
    g.run(case)

    assert g.state(case) == "sent"
    assert len([r for r in g.apis.requests if r.method == "POST" and "upload" in r.url]) == 1
    assert DRIVE_FILE in g.scopes_asked()


@pytest.mark.parametrize(
    ("connector", "action"),
    [("google_calendar", "create_event"), ("meeting_host", "create_meeting_event"), ("lovable", "build_handoff")],
)
def test_CL_LIVE_2_calendar_and_the_stubs_still_refuse_every_write(connector, action):
    from tilo_connectors.real import RealWritesDisabled

    g = make_write_env()
    adapters = g.build()
    with pytest.raises(RealWritesDisabled):
        adapters[connector].execute_side_effect({"connector": connector, "action_type": action}, None)
    assert g.apis.requests == []


def test_CL_LIVE_2_scopes_are_pinned_per_flag_combination():
    from tilo_connectors import real
    from tilo_connectors.real_writes import WriteFlags

    g = make_write_env(send=True)
    read, compose = {GMAIL_READONLY, GMAIL_COMPOSE}, {"write_gated", "read_only"}
    for flags, gmail_scopes, modes in [
        (WriteFlags(), read, {"read_only"}),
        (WriteFlags(True), read, compose),
        (WriteFlags(True, True), read | {GMAIL_SEND}, {"write_gated_send", *compose}),
    ]:
        plan, writes = real.real_write_plan(g.registry, flags)
        assert {s for r in plan if r["connector"] == "gmail" for s in r["scopes"]} == gmail_scopes
        assert {r["mode"] for r in plan} == modes
        assert [r["scopes"] for r in plan if r["connector"] == "google_calendar"] == [
            (real.REAL_SCOPES["google_calendar"])
        ]
        assert ("gmail", "send_email") in writes if flags.allow_send else ("gmail", "send_email") not in writes
        assert all(c in ("gmail", "google_drive") for c, _a in writes)


def test_CL_LIVE_2_a_widened_scope_or_a_missing_write_token_refuses_to_build(tmp_path):
    import yaml
    from _cl_live_lib import CONNECTORS_YAML
    from tilo_connectors import real
    from tilo_connectors.registry import load_registry

    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    gmail = next(e for e in entries if e["id"] == "gmail")
    gmail["scopes"]["send"] = ["https://www.googleapis.com/auth/gmail.modify"]
    (tmp_path / "c.yaml").write_text(yaml.safe_dump(entries), encoding="utf-8")
    g = make_write_env(send=True)
    widened = load_registry(tmp_path / "c.yaml")
    g.build(registry=widened, allow_send=False)  # an unused send scope is never requested, so never checked
    with pytest.raises(real.RealConnectorsRefused) as info:
        g.build(registry=widened, allow_send=True)
    assert info.value.code == "scope_widened"
    for env, flags in [(make_write_env(compose=False), {}), (make_write_env(), {"allow_send": True})]:
        with pytest.raises(real.RealConnectorsRefused) as info:
            env.build(**flags)
        assert info.value.code == "no_token" and env.apis.requests == []


def test_CL_LIVE_2_the_card_shows_the_exact_payload_bounded_and_redacted():
    g = make_write_env()
    g.build()
    long = "x" * 900
    ref = g.email(subject="Note " + SECRET, body_text=f"Hello {SECRET} {long}")
    case = g.mail_case(item=ref, recipients=("a@example.net", "b@example.net"))
    review = g.gate.review(g.card(case))

    assert review.allowed and review.recipients == ("a@example.net", "b@example.net")
    assert review.destination == "no thread: a new message" and review.connector == "gmail"
    assert SECRET not in review.title + review.preview and len(review.preview) <= 300 and review.size > 900
    assert review.digest and g.gate.review({**g.card(case), "world_id": "w_other"}).digest != review.digest
    assert g.gate.review({"gate": {"action": {"type": "build_handoff", "connector": "lovable"}}}) is None


def test_CL_LIVE_2_an_unbound_gate_holds_every_card():
    g = make_write_env()
    g.build()
    g.gate.bind(None, None)  # type: ignore[arg-type]
    review = g.gate.review(g.card(g.mail_case()))
    assert review.allowed is False and "not bound" in review.why


def test_CL_LIVE_2_no_attribute_path_reaches_the_inner_adapter_and_the_surface_is_pinned():
    from tilo_connectors import real
    from tilo_connectors.adapters._google import GoogleAdapter

    g = make_write_env()
    adapters = g.build()
    for connector in ("gmail", "google_drive"):
        adapter = adapters[connector]
        public = {n for n in dir(adapter) if not n.startswith("_") and callable(getattr(adapter, n))}
        assert public == real.READ_METHODS[connector] | {"execute_side_effect"}
        reachable = [getattr(adapter, n) for n in dir(adapter) if not n.startswith("__")]
        assert not [v for v in reachable if isinstance(v, GoogleAdapter)]
        assert not [v for v in vars(adapter).values() if isinstance(v, GoogleAdapter)]


def test_CL_LIVE_2_content_and_tokens_reach_only_the_draft_not_events_logs_or_output(capsys, caplog):
    g = make_write_env()
    g.build()
    ref = g.email(subject="subj-marker", body_text="body-marker-" + SECRET)
    case = g.mail_case(item=ref)
    assert g.approve(case)
    g.run(case)

    seen = repr(g.adapters) + repr(g.emitted) + caplog.text + "".join(capsys.readouterr()) + repr(g.gate.executed)
    secrets_ = [*g.env.google.issued_access, *g.env.google.live_refresh, *g.env.secrets.values(), SECRET]
    assert not [s for s in ["subj-marker", "body-marker"] + secrets_ if s in seen]


def test_CL_LIVE_2_the_new_modules_name_no_side_effect_method_and_real_names_no_send_scope():
    from _cl_live_lib import REAL_PY
    from tilo_connectors.side_effects import scan_for_side_effect_calls

    src = REAL_PY.parent
    assert scan_for_side_effect_calls([src / "real_writes.py", REAL_PY], allowed_path=src / "outbox.py") == []
    assert ".env" not in (src / "real_writes.py").read_text(encoding="utf-8")
