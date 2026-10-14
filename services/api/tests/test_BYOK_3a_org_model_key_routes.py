"""BYOK-3a (ADR-0041, issue 934): `GET`, `PUT`, `PATCH` and `DELETE /v1/org/model-key`, the key reference, the in-memory
vault and the T3 pin. Variant P: tilo-api never stores or returns a key.

No network, no model, no cloud, no real key: a fake key is assembled at runtime (CLAUDE.md), the vault is the
in-memory one, the stores are in memory and the clock is fixed. With the flag off (`config/byok.yaml` `enabled:
false`, the shipped value) signed-in callers receive 503 `not_configured` and nothing is read or written.
Anonymous callers always receive 401 before the flag or request body is consulted (SEC-05)."""

from __future__ import annotations

import json
import logging
import pathlib
import secrets
from datetime import datetime
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tilo_api import app, byok_routes, deps
from tilo_api.byok_store import MemoryModelKeyVault, OrgKeyStore
from tilo_people.stores import PeopleStores
from tilo_policy import load_risk_table
from tilo_providers.byok import ByokConfig, OrgBundle

REPO = pathlib.Path(__file__).resolve().parents[3]
ORG, OTHER_ORG = "org_tilo", "org_other"
OWNER, MEMBER, STRANGER = "u_owner", "u_member", "u_stranger"
NOW = "2026-10-13T10:00:00.000Z"
EPOCH = datetime.fromisoformat(NOW.replace("Z", "+00:00")).timestamp()
PATH = "/v1/org/model-key"


def fake_key() -> str:  # assembled at runtime: no literal in this file looks like a secret
    return "".join(["k", "ey-", secrets.token_hex(24)])


def _person(user: str, org: str, role: str) -> dict[str, Any]:
    return {
        "id": user, "org_id": org, "display_name": user.removeprefix("u_").title(), "aliases": [],
        "email": f"{user.removeprefix('u_')}@example.com", "time_zone": "Asia/Kolkata", "preferred_channel": "email",
        "org_role": role, "memberships": [], "created_by": {"by": OWNER, "at": "2026-10-01T09:00:00.000Z"},
    }  # fmt: skip


CFG = ByokConfig(
    enabled=True,
    day_cap_credits_max=10_000,
    calls_per_org_per_minute=120,
    consent_version=3,
    bundles={
        "oa": OrgBundle("oa", "OpenAI-compatible (example)", "openai_compat", {"writer": ("org-big", "org-small")}),
        "gk": OrgBundle("gk", "Gemini API key", "google_api_key", {"writer": ("org-g", "org-g")}),
        "vx": OrgBundle("vx", "Own Vertex project", "google_vertex_iam", {"writer": ("org-g", "org-g")}),
    },
)


class Rig:
    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, config: ByokConfig | None = CFG) -> None:
        for name in ("K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV", "TILO_JUDGE_LIVE"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(deps, "ORG_ID", ORG)
        self.stores = PeopleStores.in_memory()
        for user, org, role in ((OWNER, ORG, "owner"), (MEMBER, ORG, "member"), (STRANGER, OTHER_ORG, "owner")):
            self.stores.persons.create(_person(user, org, role))
        self.user, self.full, self.demo, self.age = OWNER, True, False, 120.0  # seconds since the sign-in
        self.vault, self.store = MemoryModelKeyVault(), OrgKeyStore()
        self.now = NOW
        ov = app.dependency_overrides
        ov[deps.get_current_principal] = self._principal
        ov[deps.get_people_stores] = lambda: self.stores
        ov[deps.get_clock] = lambda: lambda: self.now
        ov[byok_routes.get_model_key_vault] = lambda: self.vault
        ov[byok_routes.get_org_key_store] = lambda: self.store
        if config is not None:
            ov[byok_routes.get_byok_config] = lambda: config
        self.client = TestClient(app, raise_server_exceptions=False)

    def _principal(self) -> deps.Principal:
        return deps.Principal(
            user_id=self.user, role="owner", channel="web", full_session=self.full and not self.demo,
            demo_session=self.demo, auth_time=EPOCH - self.age,
        )  # fmt: skip

    def put(self, **over: Any) -> Any:
        body = {"confirm": True, "consent_version": 3, "bundle_id": "oa", "day_cap_credits": 500, "key": fake_key()}
        body.update(over)
        return self.client.put(PATH, json={k: v for k, v in body.items() if v is not None})


@pytest.fixture
def rig(monkeypatch: pytest.MonkeyPatch) -> Rig:
    return Rig(monkeypatch)


# --- the flag: off is inert ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, patch",
    [
        ("active", {"paused": False}),
        ("paused", {"paused": True}),
        ("unverified", {"paused": False}),
        ("invalid", {"paused": False}),
        ("active", {"day_cap_credits": 500}),
        ("active", {"fallback_to_tilo": False}),
        ("active", {"paused": False, "day_cap_credits": 500, "fallback_to_tilo": False}),
    ],
)
def test_ADR_0041_R34_8_noop_patch_preserves_reference_and_audit(
    rig: Rig,
    status: str,
    patch: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert rig.put().status_code == 200
    held = rig.store.get(ORG)
    assert held is not None
    if status != held.status:
        assert rig.store.cas(ORG, held.bumped(status=status), expected_rev=held.rev)
    before = rig.store.get(ORG)
    audit = rig.store.audit_entries(ORG)
    writes: list[str] = []
    monkeypatch.setattr(rig.store, "cas", lambda *args, **kwargs: writes.append("cas") or False)
    rig.age = 601.0  # a no-op does not widen access or require fresh sign-in
    got = rig.client.patch(PATH, json=patch)
    assert got.status_code == 200, got.text
    assert got.json()["state"] == status
    assert rig.store.get(ORG) == before
    assert rig.store.audit_entries(ORG) == audit
    assert writes == []


def test_BK_12_shipped_flag_is_off_and_every_route_answers_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    shipped = yaml.safe_load((REPO / "config" / "byok.yaml").read_text(encoding="utf-8"))
    assert shipped["enabled"] is False and shipped["bundles"] == {}
    rig = Rig(monkeypatch, config=None)  # the real `get_byok_config`, reading the shipped file
    for call in (
        lambda: rig.client.get(PATH),
        lambda: rig.client.put(PATH, json={"confirm": True}),
        lambda: rig.client.patch(PATH, json={"paused": True}),
        lambda: rig.client.delete(PATH),
    ):
        got = call()
        assert (got.status_code, got.json()["detail"]) == (503, "not_configured")
    assert rig.store.get(ORG) is None and rig.store.audit_entries(ORG) == [] and rig.vault.versions(ORG) == {}


def test_BK_12_flag_off_does_not_consult_the_directory_or_the_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig(monkeypatch, config=ByokConfig())
    rig.user, rig.full = STRANGER, False
    assert rig.client.put(PATH, content=b"{not json", headers={"content-type": "text/plain"}).status_code == 503


@pytest.mark.parametrize("method", ["GET", "PUT", "PATCH", "DELETE"])
@pytest.mark.parametrize("enabled", [False, True])
def test_W_SEC05_anonymous_byok_is_401_before_flag_directory_or_body(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    enabled: bool,
) -> None:
    rig = Rig(monkeypatch, config=CFG if enabled else ByokConfig())
    app.dependency_overrides.pop(deps.get_current_principal)

    def forbidden_read() -> Any:
        pytest.fail("anonymous BYOK must not read config, directory or body")

    app.dependency_overrides[byok_routes.get_byok_config] = forbidden_read
    app.dependency_overrides[deps.get_people_stores] = forbidden_read
    monkeypatch.setattr(byok_routes, "_capped_body", forbidden_read)
    # Isolate route dependencies: middleware must not mask their authentication ordering.
    isolated = FastAPI()
    isolated.include_router(byok_routes.router)
    isolated.dependency_overrides.update(app.dependency_overrides)
    got = TestClient(isolated).request(method, PATH, content=b"{not json", headers={"content-type": "application/json"})
    assert got.status_code == 401
    assert rig.store.get(ORG) is None and rig.store.audit_entries(ORG) == [] and rig.vault.versions(ORG) == {}


def test_BK_12_the_flag_default_is_off_when_the_config_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(byok_routes, "load_byok_config", lambda **_: (_ for _ in ()).throw(ValueError("x")))
    assert byok_routes.get_byok_config() == ByokConfig()


def test_BK_12_no_lease_route_exists_variant_L_is_not_built(rig: Rig) -> None:
    paths = {getattr(r, "path", "") for r in app.routes}
    assert not [p for p in paths if "lease" in p and "model-key" in p]


# --- BK-05: who ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("as_user", [MEMBER, STRANGER, "u_unknown"])
def test_BK_05_only_the_directory_owner_may_set_a_key(rig: Rig, as_user: str) -> None:
    rig.user = as_user  # Principal.role is "owner" for all of them: the directory record decides
    got = rig.put()
    assert got.status_code == 403
    assert rig.store.get(ORG) is None and rig.vault.versions(ORG) == {}


def test_BK_05_a_demo_or_non_web_session_is_refused(rig: Rig) -> None:
    rig.demo = True
    assert rig.put().status_code == 403
    rig.demo, rig.full = False, False
    assert rig.put().status_code == 403
    assert rig.vault.versions(ORG) == {}


def test_BK_08_the_org_comes_from_the_principal_a_body_cannot_name_one(rig: Rig) -> None:
    got = rig.put(org_id=OTHER_ORG)
    assert got.status_code == 422 and got.json()["code"] == "invalid_body"
    assert rig.store.get(OTHER_ORG) is None and rig.store.get(ORG) is None


def test_BK_08_json_only(rig: Rig) -> None:
    got = rig.client.put(PATH, content=b'{"confirm": true}', headers={"content-type": "text/plain"})
    assert got.status_code == 415 and rig.vault.versions(ORG) == {}


# --- BK-06: a fresh, explicit act ---------------------------------------------------------------------------------


def test_BK_06_a_sign_in_older_than_ten_minutes_is_401_reauth_required(rig: Rig) -> None:
    rig.age = 601.0
    got = rig.put()
    assert (got.status_code, got.json()["code"]) == (401, "reauth_required")
    assert rig.vault.versions(ORG) == {}
    rig.age = 599.0
    assert rig.put().status_code == 200


def test_BK_06_a_session_with_no_auth_time_is_never_fresh(rig: Rig) -> None:
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(
        user_id=OWNER, role="owner", full_session=True
    )
    assert rig.put().status_code == 401


@pytest.mark.parametrize("patch", [{"confirm": False}, {"consent_version": 2}, {"consent_version": "3"}])
def test_BK_06_confirm_and_the_consent_version_seen_are_required(rig: Rig, patch: dict[str, Any]) -> None:
    got = rig.put(**patch)
    assert (got.status_code, got.json()["code"]) == (422, "confirm_required")
    assert rig.vault.versions(ORG) == {} and rig.store.get(ORG) is None


# --- BK-02: the key is nowhere ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "x" * 700,  # over-long
        "has a space in it 123456",  # not a token
        '{"type": "service" "private_material": "x"}',  # a JSON blob (a service-account file) is never a key
        "short",  # under 8
        "",
    ],
)
def test_BK_02_a_bad_key_gets_a_fixed_code_and_is_never_echoed(
    rig: Rig, bad: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    got = rig.put(key=bad if bad else None)
    assert got.status_code == 422 and got.json()["code"] == "key_refused"
    seen = got.text + caplog.text + json.dumps(rig.store.audit_entries(ORG))
    if bad.strip():
        assert bad not in seen
    assert rig.vault.versions(ORG) == {}


def test_BK_02_a_wrongly_typed_or_unknown_field_is_a_fixed_code_without_the_input(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    secret = fake_key()
    body = {"confirm": True, "consent_version": 3, "bundle_id": "oa", "day_cap_credits": 5, "key": 12345, secret: 1}
    got = rig.client.put(PATH, json=body)
    assert got.status_code == 422 and secret not in got.text + caplog.text
    assert got.json()["detail"] in ("key_refused", "invalid_body")


def test_BK_02_BK_04_a_set_stores_a_reference_with_no_key_characters_and_answers_none(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    key = fake_key()
    got = rig.put(key=key)
    assert got.status_code == 200 and got.json() == {"state": "active", "secret_version": 1, "validated": True}
    ref = rig.store.get(ORG)
    assert ref is not None and ref.status == "active" and ref.set_by == OWNER and ref.bundle_id == "oa"
    seen = "\n".join(
        [got.text, json.dumps(ref.to_dict()), json.dumps(rig.store.audit_entries(ORG)), caplog.text,
         rig.client.get(PATH).text, repr(ref)]
    )  # fmt: skip
    assert key not in seen and key[:8] not in seen and key[-8:] not in seen
    audit = rig.store.audit_entries(ORG)
    # BQ-BYOKC-5c: the entry's authz is the common person authz (the T3 tier is the act's, pinned in autonomy.yaml)
    assert [e["action"] for e in audit] == ["set"] and audit[0]["authz"] == {"by": "person", "ref": OWNER, "at": NOW}


def test_BK_04_a_member_reads_active_and_label_only_the_owner_reads_the_rest(rig: Rig) -> None:
    rig.put()
    rig.user = MEMBER
    assert rig.client.get(PATH).json() == {"active": True, "label": "OpenAI-compatible (example)"}
    rig.user = OWNER
    owner = rig.client.get(PATH).json()
    assert owner["state"] == "active" and owner["day_cap_credits"] == 500 and owner["bundle_id"] == "oa"
    assert not {"key", "secret", "hash", "last4"} & set(owner)


def test_BK_17_B4_the_owner_and_members_are_told_when_the_keys_bundle_left_the_config(rig: Rig) -> None:
    """SEC-REVIEW-29 B4 (route half): units of that key are refused `not_configured`, so no screen may say active."""
    rig.put()
    assert rig.client.get(PATH).json()["active"] is True
    gone = ByokConfig(
        enabled=True, day_cap_credits_max=10_000, calls_per_org_per_minute=120, consent_version=3, bundles={}
    )
    app.dependency_overrides[byok_routes.get_byok_config] = lambda: gone
    owner = rig.client.get(PATH).json()
    assert owner["active"] is False and owner["last_error"] == "not_configured" and owner["bundle_id"] == "oa"
    rig.user = MEMBER
    assert rig.client.get(PATH).json() == {"active": False, "label": None}


def test_BK_20_another_orgs_key_is_never_seen_or_used(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    rig.put()
    monkeypatch.setattr(deps, "ORG_ID", OTHER_ORG)
    rig.user = STRANGER
    assert rig.client.get(PATH).json()["active"] is False
    assert rig.store.get(OTHER_ORG) is None


# --- BK-03, BK-04: the vault -------------------------------------------------------------------------------------


def test_BK_04_a_rotation_disables_every_earlier_version_and_a_removal_destroys_all(rig: Rig) -> None:
    assert rig.put().json()["secret_version"] == 1
    got = rig.put()
    assert got.json()["secret_version"] == 2
    assert rig.vault.versions(ORG) == {1: False, 2: True}, "a rotated-away key never stays enabled"
    assert rig.store.get(ORG).rotated_at == NOW  # type: ignore[union-attr]
    assert rig.client.delete(PATH).json() == {"removed": True}
    assert rig.vault.versions(ORG) == {} and rig.store.get(ORG) is None
    assert [e["action"] for e in rig.store.audit_entries(ORG)] == ["set", "rotate", "remove"]


def test_BK_03_a_refused_key_keeps_no_version_and_the_old_key_stays_active(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    assert rig.put().status_code == 200
    rig.vault._accepts = lambda _key: False  # noqa: SLF001  - the provider refuses the next key
    got = rig.put()
    assert (got.status_code, got.json()["code"]) == (422, "key_refused")
    assert rig.vault.versions(ORG) == {1: True} and rig.store.get(ORG).status == "active"  # type: ignore[union-attr]


def test_BK_03_no_half_state_a_failed_reference_write_removes_the_new_version(rig: Rig) -> None:
    rig.put()
    rig.store.cas = lambda *a, **k: False  # type: ignore[method-assign]  # the reference write loses
    got = rig.put()
    assert got.status_code == 503
    assert rig.vault.versions(ORG) == {1: True}, "the new version is gone and the old key is still the active one"


def test_BK_03_an_unverified_put_cannot_be_used(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    rig.vault.validates = False  # the process may not go live (EFF-01): no validation, a disabled version
    got = rig.put()
    assert got.json() == {"state": "unverified", "secret_version": 1, "validated": False}
    assert rig.vault.status(ORG, "models").state == "unverified"


# --- BK-17 (SEC-REVIEW-29 B2): a pause and a resume never make an unverified or invalid key usable ------------------


def _force_status(rig: Rig, status: str) -> None:
    held = rig.store.get(ORG)
    assert held is not None
    assert rig.store.cas(ORG, held.bumped(status=status), expected_rev=held.rev)


@pytest.mark.parametrize("status", ["invalid", "unverified"])
def test_ADR_0041_R34_6_BK_17_B2_invalid_or_unverified_resume_is_200_unchanged(rig: Rig, status: str) -> None:
    rig.put()
    _force_status(rig, status)
    refused = rig.client.patch(PATH, json={"paused": True})
    assert refused.status_code == 422 and refused.json()["code"] == "invalid_body"
    assert rig.store.get(ORG).status == status  # type: ignore[union-attr]
    before = rig.store.get(ORG)
    resumed = rig.client.patch(PATH, json={"paused": False, "confirm": True, "consent_version": 3})
    assert rig.store.get(ORG).status == status, "a resume never makes it active"  # type: ignore[union-attr]
    assert resumed.status_code == 200
    assert rig.store.get(ORG) == before
    assert rig.client.get(PATH).json()["state"] == status
    rig.user = MEMBER
    assert rig.client.get(PATH).json()["active"] is False


def test_ADR_0041_R34_6_BK_17_B2_invalid_while_paused_resume_is_200_unchanged(rig: Rig) -> None:
    rig.put()
    assert rig.client.patch(PATH, json={"paused": True}).json()["state"] == "paused"
    _force_status(rig, "invalid")
    before = rig.store.get(ORG)
    got = rig.client.patch(PATH, json={"paused": False, "confirm": True, "consent_version": 3})
    assert got.status_code == 200
    assert rig.store.get(ORG) == before
    assert rig.store.get(ORG).status == "invalid"  # type: ignore[union-attr]


def test_BK_17_B2_pause_then_resume_of_a_verified_key_still_works(rig: Rig) -> None:
    rig.put()
    assert rig.client.patch(PATH, json={"paused": True}).json()["state"] == "paused"
    resumed = rig.client.patch(PATH, json={"paused": False, "confirm": True, "consent_version": 3})
    assert resumed.status_code == 200 and resumed.json()["state"] == "active"
    assert [e["action"] for e in rig.store.audit_entries(ORG)] == ["set", "change", "change"]


def test_BK_17_B2_pausing_twice_changes_nothing(rig: Rig) -> None:
    rig.put()
    assert rig.client.patch(PATH, json={"paused": True}).status_code == 200
    again = rig.client.patch(PATH, json={"paused": True})
    assert again.status_code == 200 and again.json()["state"] == "paused"


# --- BK-07, BK-08: widening is T3, narrowing is immediate ---------------------------------------------------------


def test_BK_07_autonomy_lists_the_key_change_at_T3() -> None:
    raw = yaml.safe_load((REPO / "config" / "autonomy.yaml").read_text(encoding="utf-8"))
    assert raw["actions"]["org_model_key_change"] == "T3", "listed, not left to the unlisted-is-T3 default"
    assert load_risk_table().tier_of("org_model_key_change", []) == "T3"


def test_BK_07_narrowing_needs_no_confirm_and_no_fresh_sign_in_widening_needs_both(rig: Rig) -> None:
    rig.put()
    rig.age = 7200.0  # a stale session
    assert rig.client.patch(PATH, json={"day_cap_credits": 100}).status_code == 200
    assert rig.client.patch(PATH, json={"paused": True}).json()["state"] == "paused"
    assert rig.client.patch(PATH, json={"fallback_to_tilo": False}).status_code == 200
    stale = rig.client.patch(PATH, json={"day_cap_credits": 400, "confirm": True, "consent_version": 3})
    assert (stale.status_code, stale.json()["code"]) == (401, "reauth_required")
    rig.age = 60.0
    no_confirm = rig.client.patch(PATH, json={"day_cap_credits": 400})
    assert (no_confirm.status_code, no_confirm.json()["code"]) == (422, "confirm_required")
    ok = rig.client.patch(PATH, json={"day_cap_credits": 400, "confirm": True, "consent_version": 3})
    assert ok.status_code == 200 and ok.json()["day_cap_credits"] == 400
    assert rig.client.patch(PATH, json={"fallback_to_tilo": True}).status_code == 422, "fallback on is T3"
    assert rig.client.patch(PATH, json={"paused": False, "confirm": True, "consent_version": 3}).status_code == 200


def test_BK_07_removal_is_never_harder_than_a_grant(rig: Rig) -> None:
    rig.put()
    rig.age = 10**6  # a very stale sign-in
    assert rig.client.delete(PATH).json() == {"removed": True}
    assert rig.client.delete(PATH).json() == {"removed": True}, "idempotent"


def test_BK_08_at_most_five_widening_acts_an_hour_per_org_narrowing_is_exempt(rig: Rig) -> None:
    for _ in range(5):
        assert rig.put().status_code == 200
    sixth = rig.put()
    assert sixth.status_code == 429 and int(sixth.headers["retry-after"]) >= 1
    assert rig.client.patch(PATH, json={"paused": True}).status_code == 200
    assert rig.client.delete(PATH).status_code == 200


def test_BK_16_the_cap_is_required_and_never_above_the_ceiling(rig: Rig) -> None:
    for cap in (0, 10_001, -5):
        assert rig.put(day_cap_credits=cap).status_code == 422
    assert rig.put(day_cap_credits=None).status_code == 422
    assert rig.put(day_cap_credits=10_000).status_code == 200


# --- BQ-BYOK-2: both Google modes ---------------------------------------------------------------------------------


def test_BQ_BYOK_2_the_gemini_api_key_mode_takes_a_key_and_no_project(rig: Rig) -> None:
    assert rig.put(bundle_id="gk", project_id="my-vertex-project").status_code == 422
    got = rig.put(bundle_id="gk")
    assert got.status_code == 200 and rig.store.get(ORG).auth_mode == "api_key"  # type: ignore[union-attr]


def test_BQ_BYOK_2_B1_a_vertex_iam_bundle_is_refused_whatever_project_is_typed(rig: Rig) -> None:
    """SEC-REVIEW-29 B1: in variant P Tilo's own identity would call the typed project, so an owner-typed project id
    (Tilo's own first of all) would be Tilo-billed spend outside SEC-16. Refused with a fixed code, nothing written,
    until BQ-BYOK-2 is answered and BYOK-4/6 prove the project is the org's."""
    for project in ("my-vertex-project", "essential-wares-510320-f0", "tilo-dev-project", "NOT A PROJECT"):
        got = rig.put(bundle_id="vx", key=None, project_id=project)
        assert (got.status_code, got.json()["code"]) == (422, "key_refused"), project
        assert project not in got.text
    assert rig.put(bundle_id="vx", key=None).status_code == 422
    assert rig.put(bundle_id="vx", key=fake_key(), project_id="my-vertex-project").status_code == 422
    assert rig.vault.versions(ORG) == {} and rig.store.get(ORG) is None and rig.store.audit_entries(ORG) == []
    assert rig.client.patch(PATH, json={"paused": True}).status_code == 422, "no reference was created either"
    assert rig.put(bundle_id="gk").status_code == 200, "the Gemini API-key bundle is unaffected"


def test_BQ_BYOK_2_B1_a_refused_vertex_put_does_not_spend_a_widening_act(rig: Rig) -> None:
    for _ in range(8):
        assert rig.put(bundle_id="vx", key=None, project_id="my-vertex-project").status_code == 422
    assert rig.put().status_code == 200, "refused before the hourly act limiter, so five real acts remain"


def test_BQ_BYOK_2_the_vertex_iam_mode_takes_a_project_and_never_a_key(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(byok_routes, "VERTEX_GRANT_CHECKED", True)  # the later BYOK-4/6 state: a grant check exists
    assert rig.put(bundle_id="vx", project_id="my-vertex-project").status_code == 422, "a key sent with IAM mode"
    assert rig.put(bundle_id="vx", key=None).status_code == 422, "IAM mode needs a project"
    assert rig.put(bundle_id="vx", key=None, project_id="NOT A PROJECT").status_code == 422
    got = rig.put(bundle_id="vx", key=None, project_id="my-vertex-project")
    assert got.status_code == 200
    ref = rig.store.get(ORG)
    assert ref is not None and (ref.auth_mode, ref.project_id) == ("vertex_iam", "my-vertex-project")


def test_BQ_BYOK_2_an_unknown_bundle_is_refused(rig: Rig) -> None:
    assert rig.put(bundle_id="nope").status_code == 422
    assert rig.vault.versions(ORG) == {}


# --- deployed: no memory store, no vault ---------------------------------------------------------------------------


def test_BK_01_deployed_with_no_vault_the_routes_say_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    rig = Rig(monkeypatch)
    del app.dependency_overrides[byok_routes.get_model_key_vault]
    assert rig.put().status_code == 503
    monkeypatch.setenv("K_SERVICE", "tilo-api")
    with pytest.raises(Exception) as caught:  # noqa: PT011
        byok_routes.get_org_key_store()
    assert getattr(caught.value, "status_code", None) == 503
