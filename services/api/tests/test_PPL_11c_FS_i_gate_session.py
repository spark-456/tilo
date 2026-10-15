"""PPL-11c-FS FS-19 (issue #577 item 4): `/v1/people/first` needs the bootstrap uid's FULL web or mobile_web sign-in
session, not just its uid. Spec: `API_PPL_11c_FS1c.md` section 4. None needs the emulator.

`Principal` already carries what the check needs (`channel`: web, mobile_web or email; `full_session`: set only by the
server for a full sign-in, BQ-XWORLD-10), so no sign-in work and no contract change is behind this. Today the route asks
the gate only about `principal.user_id`: once sign-in is wired, an email or signed-link session of the bootstrap uid
could found the org with a display name and address of its choosing. The refusal is the same 403 `forbidden` body as
every other refusal of `/first`, decided before any store is read (and, as FS-12 pins, after the closed body model).

The check is independent of the gate seam (whose predicate over a uid FS-12 pins), so each refusal case runs twice: with
the rig's gate that says yes to every uid, and with the production gate configured to the founder.
"""

from __future__ import annotations

import pytest
from _ppl11c_lib import PERSON_BODY, R_PERSON_FIRST

ENV_UID = "TILO_PEOPLE_BOOTSTRAP_UID"
FOUNDER = "u_founder"
FORBIDDEN = {"detail": "forbidden"}
# (channel, full_session): every session that is not a full web or mobile_web sign-in. "whatsapp" and "" are not
# channels any more (SD-01); an allow-list refuses them, a deny-list for "email" alone would not.
NOT_FULL = [
    ("email", True),
    ("email", False),
    ("web", False),
    ("mobile_web", False),
    ("whatsapp", True),
    ("", True),
]


def _rig(people_rig, monkeypatch, gate: str):
    for name in (ENV_UID, "TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    rig = people_rig()
    if gate == "bootstrap_uid":
        rig.unwire("founder_gate")
        monkeypatch.setenv(ENV_UID, FOUNDER)
    rig.as_user(FOUNDER)
    rig.require_route(R_PERSON_FIRST)
    return rig


def _first(rig, **body):
    rig.email = {**PERSON_BODY, **body}["email"]  # the sign-in's verified address (SELF-SERVE-TEAMS)
    return rig.client.post("/v1/people/first", json={**PERSON_BODY, **body})


@pytest.mark.parametrize("gate", ["any_uid", "bootstrap_uid"])
@pytest.mark.parametrize(("channel", "full_session"), NOT_FULL, ids=lambda v: repr(v))
def test_PPL_11c_FS_19_a_session_that_is_not_a_full_web_sign_in_cannot_found_the_org(
    people_rig, monkeypatch, gate, channel, full_session
):
    rig = _rig(people_rig, monkeypatch, gate)
    rig.channel, rig.full_session = channel, full_session
    before = rig.snapshot()
    refused = _first(rig)
    assert refused.status_code == 403 and refused.json() == FORBIDDEN, (refused.status_code, refused.text[:200])
    assert rig.snapshot() == before and rig.stored("persons", FOUNDER) is None
    assert rig.store_calls == [], "the session is checked before any store is read or written"
    rig.channel, rig.full_session = "web", True  # nothing was used up: the same uid, signed in properly, founds the org
    assert _first(rig).status_code == 201
    assert rig.real.persons.founded(rig.org) is True


@pytest.mark.parametrize("gate", ["any_uid", "bootstrap_uid"])
@pytest.mark.parametrize("channel", ["web", "mobile_web"])
def test_PPL_11c_FS_19_guard_a_full_web_or_mobile_web_session_of_the_bootstrap_uid_founds_the_org(
    people_rig, monkeypatch, gate, channel
):
    rig = _rig(people_rig, monkeypatch, gate)
    rig.channel, rig.full_session = channel, True
    created = _first(rig)
    assert created.status_code == 201, created.text[:300]
    assert created.json()["id"] == FOUNDER and created.json()["org_role"] == "owner"
    assert rig.stored("persons", FOUNDER)["org_role"] == "owner"
    assert rig.real.persons.founded(rig.org) is True


def test_PPL_11c_FS_19_every_refusal_of_first_is_one_body(people_rig, monkeypatch):
    """An email session, a session that is not a full sign-in, an org founded before: one status and one body, so a
    refusal says nothing about which rule closed the door. (SELF-SERVE-TEAMS: another uid on a full session joins as a
    member, and people already there no longer block founding; neither is a refusal any more.)"""
    rig = _rig(people_rig, monkeypatch, "any_uid")
    refusals = []
    rig.as_user(FOUNDER)
    for channel, full_session in (("email", True), ("web", False), ("mobile_web", False)):
        rig.channel, rig.full_session = channel, full_session
        refusals.append(_first(rig))
    rig.channel, rig.full_session = "web", True
    assert _first(rig).status_code == 201
    rig.as_user("u_other")  # the rig's gate calls everyone the bootstrap uid: the org was founded before
    refusals.append(_first(rig, email="other@example.com"))
    assert {r.status_code for r in refusals} == {403}
    assert len({r.text for r in refusals}) == 1 and refusals[0].json() == FORBIDDEN, [r.text for r in refusals]


def test_PPL_11c_FS_19_the_session_marker_comes_from_the_server_never_the_request(people_rig, monkeypatch):
    """A body or header that claims a full session changes nothing: bodies are closed (422) and headers are not read."""
    rig = _rig(people_rig, monkeypatch, "bootstrap_uid")
    rig.channel, rig.full_session = "email", False
    claim = rig.client.post(
        "/v1/people/first",
        json={**PERSON_BODY, "full_session": True, "channel": "web"},
        headers={"x-full-session": "1", "x-channel": "web"},
    )
    assert claim.status_code in (403, 422), claim.status_code
    assert rig.store_calls == [] and rig.stored("persons", FOUNDER) is None
    headers_only = rig.client.post(
        "/v1/people/first", json=PERSON_BODY, headers={"x-full-session": "1", "x-channel": "web"}
    )
    assert headers_only.status_code == 403 and headers_only.json() == FORBIDDEN
