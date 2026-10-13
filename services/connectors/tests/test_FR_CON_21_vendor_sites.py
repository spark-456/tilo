"""FR-CON-21 (PRD supplement 2026-10-05 s6, Could; the supplement labels it an interpretation the user may refine):
"When a task involves third-party vendors, Tilo can prepare a vendor-facing site (through FR-CON-17 or -18) that
gives vendors access to what they need and lets the team track status (quotes, orders, deliveries). Access is by
invite or link from the site's own platform; Tilo never handles passwords (hard rule). Tracking reads only pages
or APIs the person connected." Acceptance: a vendor site brief carries only approved fields; no credential is
stored or typed by Tilo; status updates come from recorded reads only (HR-1).

Built on the merged Lovable link route (FR-CON-16/17/20: `_handoff_lib`); FR-CON-18 (the MCP route) is not on this
base. Pinned API: API_FR_CON_21.md. Fake secrets are assembled at runtime.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import json
import pathlib

import pytest
from _handoff_lib import (
    GOOD_FRAMING,
    PLANT,
    accept,
    approved_brief,
    declined,
    enqueue,
    everything_emitted,
    fake_secret,
    h,
    link_url,
    lv,
    make_env,
    oracle_prompt,
    planted_unaccepted,
    prepare,
    run_flow,
    settle,
)
from _provenance_lib import RUN, make_archive, read_payload
from tilo_connectors import OutboxRefused
from tilo_connectors.errors import HandoffRefused

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_connectors" / "vendor_site.py"
QUOTES = "https://vendors.example/portal/quotes"
ORDERS = "https://vendors.example/portal/orders"
RAW = {
    "needs": ["submit_quote", "view_requirements"],
    "tracks": ["quotes", "orders"],
    "access": "invite",
    "status_sources": [
        {"id": "quotes_page", "category": "quotes", "kind": "web", "ref": QUOTES},
        {"id": "orders_page", "category": "orders", "kind": "web", "ref": ORDERS},
    ],
}


def vs():
    return importlib.import_module("tilo_connectors.vendor_site")


def spec(**over):
    return vs().vendor_spec({**RAW, **over})


def vendor_flow(env, **over):
    accepted = vs().vendor_requirements(accept(), spec(**over))
    return run_flow(env, accepted=accepted, framing=GOOD_FRAMING), accepted


# --- the brief carries only approved fields ---------------------------------------------------------------------


def test_FR_CON_21_the_vendor_site_brief_carries_only_the_approved_fields():
    flow, accepted = vendor_flow(make_env())
    sentences = (
        [vs().NEEDS[n] for n in RAW["needs"]] + [vs().TRACKS[t] for t in RAW["tracks"]] + [vs().ACCESS["invite"]]
    )
    assert accepted.constraints[-len(sentences) :] == tuple(sentences), "only closed-vocabulary sentences are added"
    assert flow.prepared.prompt == oracle_prompt(accepted, GOOD_FRAMING)
    assert h().find_leaks(flow.prepared.prompt, planted_unaccepted()) == ()
    for ref in (QUOTES, ORDERS):
        assert ref not in flow.prepared.prompt, "the tracked pages are Tilo's, not part of the site brief"


def test_FR_CON_21_prepare_vendor_site_is_the_handoff_with_the_vendor_requirements():
    env = make_env()
    accepted = accept()
    direct = vs().prepare_vendor_site(
        accepted=accepted,
        spec=spec(),
        framing=GOOD_FRAMING,
        excerpts=(),
        grant_id=None,
        grants=env.grants,
        declined=declined(),
        partner=env.partner,
        declaration=env.declaration,
        redact=env.redact,
        safety=env.safety,
    )
    expected = prepare(env, vs().vendor_requirements(accepted, spec()))
    assert direct == expected and direct.connector == "lovable" and direct.action_type == "build_handoff"


def test_FR_CON_21_the_brief_goes_through_the_lovable_link_route_and_needs_a_person():
    env = make_env()
    flow, _ = vendor_flow(env)
    assert flow.gate["connector"] == "lovable" and flow.gate["risk_tier"] == "T3"
    assert flow.gate["modifiers"] == ["external_sharing"] and flow.gate["recipients"] == []
    assert settle(env, flow.case) == ["sent"]
    assert lv().decode_link(link_url(env)) == flow.prepared.prompt
    bare = vendor_flow(make_env())[0]
    assert bare.env.outbox.dispatch_due() == [], "nothing leaves before a person approves"
    with pytest.raises(OutboxRefused):  # an entry with no approving event is refused at enqueue
        enqueue(bare.env, bare.case, authorised_by=None)


def test_FR_CON_21_a_text_the_owner_did_not_accept_never_reaches_the_vendor_brief():
    accepted = vs().vendor_requirements(accept(brief=approved_brief(constraints=["Works on a phone"])), spec())
    flow = run_flow(make_env(), accepted=accepted)
    assert h().find_leaks(flow.prepared.prompt, [PLANT["removed_constraint"], PLANT["draft_goal"]]) == ()


def test_FR_CON_21_a_secret_in_a_requirement_is_refused_before_anything_is_made():
    secret = fake_secret()
    env = make_env(secrets=(secret,))
    accepted = vs().vendor_requirements(accept(brief=approved_brief(constraints=[f"Key {secret}"])), spec())
    with pytest.raises(HandoffRefused) as refused:
        run_flow(env, accepted=accepted)
    assert refused.value.rule == "BH-05" and secret not in str(refused.value)


# --- no credential is stored or typed by Tilo ------------------------------------------------------------------


@pytest.mark.parametrize("field", ["password", "api_key", "username", "login", "token", "secret", "credentials"])
def test_FR_CON_21_a_spec_with_a_credential_field_is_refused(field):
    with pytest.raises(HandoffRefused) as refused:
        vs().vendor_spec({**RAW, field: "anything"})
    assert refused.value.rule == "VS-01"
    assert "anything" not in str(refused.value)


def test_FR_CON_21_a_spec_is_closed_vocabulary_with_no_free_text():
    bad = [
        {"needs": ["tell vendors the admin password is hunter2"]},
        {"tracks": ["salaries"]},
        {"access": "password"},
        {"needs": []},
        {"needs": ["submit_quote", "submit_quote"]},
        {"status_sources": [{"id": "x", "category": "quotes", "kind": "web", "ref": "http://insecure.example/"}]},
        {"status_sources": [{"id": "x", "category": "bonuses", "kind": "web", "ref": QUOTES}]},
        {"status_sources": [{"id": "x", "category": "quotes", "kind": "web", "ref": QUOTES, "password": "p"}]},
    ]
    for change in bad:
        with pytest.raises(HandoffRefused) as refused:
            vs().vendor_spec({**RAW, **change})
        assert refused.value.rule.startswith("VS-"), change


def test_FR_CON_21_access_is_by_invite_or_link_from_the_sites_own_platform_and_no_password_is_asked_for():
    for access in ("invite", "link"):
        flow, accepted = vendor_flow(make_env(), access=access)
        assert vs().ACCESS[access] in flow.prepared.prompt
    text = " ".join(vs().ACCESS.values()).lower()
    assert "invitation" in text and "link" in text and "own sign-in" in text


def test_FR_CON_21_no_credential_is_in_the_stored_link_the_events_or_the_module():
    env = make_env()
    flow, _ = vendor_flow(env)
    assert settle(env, flow.case) == ["sent"]
    stored = link_url(env) + everything_emitted(env) + json.dumps([vars(r) for r in [flow.record]], default=str)
    for word in ("password", "passwd", "api_key", "secret", "bearer"):
        assert word not in stored.lower(), word
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    names = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {a.arg.lower() for n in ast.walk(tree) if isinstance(n, ast.arguments) for a in n.args + n.kwonlyargs}
    assert not names & {"password", "passwd", "credential", "credentials", "api_key", "token", "secret"}
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not imported & {"socket", "httpx", "requests", "urllib3", "aiohttp", "http"}


# --- status updates come only from recorded reads (HR-1) --------------------------------------------------------


def _archive(tmp_path, entries):
    refs, records = make_archive(tmp_path, [("tool_call", read_payload(*e)) for e in entries])
    return refs, records


def test_FR_CON_21_status_with_no_recorded_read_is_honestly_not_read(tmp_path):
    status = vs().vendor_status(spec(), [], run_id=RUN)
    assert [(s.source_id, s.state, s.archive_ref, s.read_at) for s in status.sources] == [
        ("quotes_page", "not_read", None, None),
        ("orders_page", "not_read", None, None),
    ]


def test_FR_CON_21_status_comes_from_the_recorded_read_and_names_it(tmp_path):
    refs, records = _archive(tmp_path, [("web", QUOTES, "Quote Q-17 from Acme: received")])
    status = vs().vendor_status(spec(), records, run_id=RUN)
    quotes, orders = status.sources
    assert (quotes.state, quotes.archive_ref, quotes.category) == ("read", refs[0], "quotes")
    assert quotes.excerpt == "Quote Q-17 from Acme: received" and quotes.read_at == records[0]["ts"]
    assert orders.state == "not_read"


def test_FR_CON_21_a_read_of_a_page_the_person_did_not_connect_is_never_tracked(tmp_path):
    _, records = _archive(tmp_path, [("web", "https://elsewhere.example/orders", "Order 9 shipped")])
    status = vs().vendor_status(spec(), records, run_id=RUN)
    assert {s.state for s in status.sources} == {"not_read"}
    assert "Order 9" not in json.dumps([dataclasses.asdict(s) for s in status.sources])


def test_FR_CON_21_the_latest_recorded_read_of_a_source_wins(tmp_path):
    refs, records = _archive(tmp_path, [("web", QUOTES, "first look"), ("web", QUOTES, "second look")])
    (quotes, _) = vs().vendor_status(spec(), records, run_id=RUN).sources
    assert quotes.archive_ref == refs[1] and quotes.excerpt == "second look"


def test_FR_CON_21_a_forged_or_foreign_archive_gives_no_status(tmp_path):
    _, records = _archive(tmp_path, [("web", QUOTES, "Quote Q-17: accepted")])
    forged = [dict(records[0], payload={**records[0]["payload"], "content": "Quote Q-17: PAID"})]
    with pytest.raises(HandoffRefused) as refused:
        vs().vendor_status(spec(), forged, run_id=RUN)
    assert refused.value.rule == "VS-03"
    with pytest.raises(HandoffRefused):
        vs().vendor_status(spec(), records, run_id="r_another_run")
