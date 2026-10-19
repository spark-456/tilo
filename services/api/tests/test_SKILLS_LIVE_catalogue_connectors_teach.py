"""SKILLS-LIVE (found on the live /skills page, 15 Oct):

* the built-in catalogue (`GET /v1/skills?include_builtin=true`) lists only skills a person's agent can use for their
  work; `skills/automation/` is Tilo's own machinery and is never offered (the skills stay in the registry);
* `GET /v1/connectors` made one network call per request (4.9 s live): a person's views are now kept in-process for a
  short TTL (a failure for a shorter one), dropped by that person's own connect/disconnect, and the metadata ID token
  is reused; all deterministic here (a replaced clock, a counting fake client, no network, no paid call);
* "Teach a skill" end to end through the real routes with a scripted provider: describe -> Tilo's version -> save ->
  listed; no paid model.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest
from _api_lib import as_full_session, as_principal, make_principal
from _ppl11a_lib import ORG, PRIYA
from _skills4_lib import CLEAR
from tilo_api import deps, meeting_host_rpc

USER = "u_skills_live"


# ---- 2. the catalogue --------------------------------------------------------------------------------------------


def test_SKILLS_LIVE_the_builtin_catalogue_hides_internal_automation_skills(skills4):
    skills4.rig.as_user(PRIYA)
    response = skills4.rig.get("/v1/skills?include_builtin=true")
    assert response.status_code == 200, response.text
    ids = {b["id"] for b in response.json()["builtins"]}
    assert {"web-research", "question-bank-extraction", "quiz-assessment"} <= ids
    assert ids.isdisjoint({"agent-self-report", "skill-from-description", "try-run-match"})
    assert all(b["description"] and b["version"] for b in response.json()["builtins"])


def test_SKILLS_LIVE_internal_skills_stay_in_the_registry_for_the_planner():
    registry = deps.get_skill_registry()
    catalog = {skill_id for skill_id, _ in registry.catalog()}
    assert {"agent-self-report", "skill-from-description", "try-run-match"} <= catalog  # not deleted
    folder = registry.folder("agent-self-report")
    assert folder is not None and folder.parent.name == "automation"


def test_SKILLS_LIVE_the_registries_are_built_once_per_root_not_once_per_request(tmp_path, monkeypatch):
    assert deps.get_skill_registry() is deps.get_skill_registry()
    assert deps.get_connector_registry() is deps.get_connector_registry()
    monkeypatch.setattr(deps, "_REPO_ROOT", tmp_path)  # another root is another registry (and an empty one, here)
    assert list(deps.get_connector_registry().ids()) == []
    assert deps.get_skill_registry().catalog() == []


def test_SKILLS_LIVE_a_changed_connectors_file_is_read_again(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    real = (deps._REPO_ROOT / "config" / "connectors.yaml").read_text(encoding="utf-8")
    path = tmp_path / "config" / "connectors.yaml"
    path.write_text(real, encoding="utf-8")
    monkeypatch.setattr(deps, "_REPO_ROOT", tmp_path)
    first = deps.get_connector_registry()
    assert deps.get_connector_registry() is first
    path.write_text(real + "# edited, a longer file\n", encoding="utf-8")
    assert deps.get_connector_registry() is not first


def test_SKILLS_LIVE_the_builtin_listing_reads_no_skill_file(skills4, monkeypatch):
    registry = deps.get_skill_registry()
    monkeypatch.setattr(registry, "load", lambda skill_id: pytest.fail("a listing must not re-read " + skill_id))
    skills4.rig.as_user(PRIYA)
    response = skills4.rig.get("/v1/skills?include_builtin=true")
    assert response.status_code == 200, response.text
    assert (
        registry.version("web-research") == {b["id"]: b["version"] for b in response.json()["builtins"]}["web-research"]
    )


# ---- 3. connectors: the list path is cached ---------------------------------------------------------------------


class _Client:
    """A stand-in for the connectors RPC client: counts calls, can be slow, can fail."""

    def __init__(self, delay_s: float = 0.0) -> None:
        self.calls: list[str] = []
        self.delay_s = delay_s
        self.answer: Any = [
            SimpleNamespace(
                connector="gmail", state="connected", scopes=["https://www.googleapis.com/auth/gmail.readonly"]
            )
        ]
        self.views_not_configured = False

    def connection_views(self, user_id: str, *, order: Any) -> Any:
        self.calls.append(user_id)
        if self.delay_s:
            time.sleep(self.delay_s)
        return self.answer


@pytest.fixture()
def wired(monkeypatch):
    client = _Client()
    clock = SimpleNamespace(now=1000.0)
    deps.get_meeting_host_client.cache_clear()
    monkeypatch.setattr(deps, "get_meeting_host_client", lambda: client)
    monkeypatch.setattr(deps._CONNECTION_VIEWS_CACHE, "clock", lambda: clock.now)
    yield client, clock
    deps._CONNECTION_VIEWS_CACHE.forget()
    monkeypatch.undo()
    deps.get_meeting_host_client.cache_clear()


def _list(client_http, user: str = USER) -> dict[str, Any]:
    as_principal(as_full_session(make_principal(user_id=user, role="owner", world_id=None)))
    response = client_http.get("/v1/connectors")
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()["connectors"]}


def test_SKILLS_LIVE_connectors_list_asks_the_connectors_service_once_within_the_ttl(client, wired):
    rpc, clock = wired
    first = _list(client)
    clock.now += deps._ConnectionViewsCache.VIEWS_TTL_S - 1
    second = _list(client)
    assert rpc.calls == [USER]
    assert first == second and first["gmail"]["state"] == "connected" and first["gmail"]["state_known"] is True


def test_SKILLS_LIVE_connectors_list_asks_again_after_the_ttl(client, wired):
    rpc, clock = wired
    _list(client)
    clock.now += deps._ConnectionViewsCache.VIEWS_TTL_S + 0.1
    _list(client)
    assert rpc.calls == [USER, USER]


def test_SKILLS_LIVE_a_failed_read_is_remembered_only_briefly_and_stays_unknown(client, wired):
    rpc, clock = wired
    rpc.answer = None
    rows = _list(client)
    assert all(r["state_known"] is False and r["state"] == "available" for r in rows.values())
    clock.now += deps._ConnectionViewsCache.VIEWS_FAILURE_TTL_S - 0.5
    _list(client)
    assert rpc.calls == [USER]  # a cold connectors instance is waited for once, not once per click
    clock.now += 1.0
    rpc.answer = [SimpleNamespace(connector="gmail", state="connected", scopes=[])]
    assert _list(client)["gmail"]["state_known"] is True
    assert rpc.calls == [USER, USER]


def test_SKILLS_LIVE_one_persons_views_are_never_served_to_another(client, wired):
    rpc, _ = wired
    _list(client, "u_one")
    _list(client, "u_two")
    _list(client, "u_one")
    assert rpc.calls == ["u_one", "u_two"]


def test_SKILLS_LIVE_a_connect_or_disconnect_drops_that_persons_entry(client, wired):
    rpc, _ = wired
    _list(client)
    deps.forget_connection_views(USER)
    _list(client)
    assert rpc.calls == [USER, USER]


def test_SKILLS_LIVE_the_cache_is_bounded(wired):
    rpc, clock = wired
    cache = deps._CONNECTION_VIEWS_CACHE
    for n in range(cache.VIEWS_MAX_USERS + 5):
        cache.get(f"u_{n}", lambda: ([], False))
    assert len(cache._rows) <= cache.VIEWS_MAX_USERS


def test_SKILLS_LIVE_a_slow_connectors_service_costs_one_wait_not_one_per_request(client, wired):
    rpc, _ = wired
    rpc.delay_s = 0.4
    t0 = time.perf_counter()
    _list(client)
    cold = time.perf_counter() - t0
    t1 = time.perf_counter()
    _list(client)
    warm = time.perf_counter() - t1
    assert cold >= 0.4 and warm < cold - 0.3  # the second read never waits on the service
    print(f"SKILLS-LIVE connectors list (simulated 400 ms RPC): cold {cold * 1000:.0f} ms -> warm {warm * 1000:.0f} ms")


def test_SKILLS_LIVE_the_id_token_is_minted_once_per_audience_and_reused(monkeypatch):
    from google.oauth2 import id_token

    minted: list[str] = []
    now = SimpleNamespace(t=50.0)
    monkeypatch.setattr(
        id_token, "fetch_id_token", lambda request, audience: (minted.append(audience), f"tok{len(minted)}")[1]
    )
    monkeypatch.setattr(meeting_host_rpc, "id_token_clock", lambda: now.t)
    monkeypatch.setattr(meeting_host_rpc, "_id_tokens", {})
    assert meeting_host_rpc.metadata_id_token("https://a.run.app") == "tok1"
    assert meeting_host_rpc.metadata_id_token("https://a.run.app") == "tok1"
    assert meeting_host_rpc.metadata_id_token("https://b.run.app") == "tok2"
    now.t += meeting_host_rpc._ID_TOKEN_REUSE_S + 1
    assert meeting_host_rpc.metadata_id_token("https://a.run.app") == "tok3"


def test_SKILLS_LIVE_a_failed_id_token_mint_is_never_cached(monkeypatch):
    from google.oauth2 import id_token

    def boom(request, audience):
        raise RuntimeError("metadata down")

    monkeypatch.setattr(id_token, "fetch_id_token", boom)
    monkeypatch.setattr(meeting_host_rpc, "_id_tokens", {})
    with pytest.raises(RuntimeError):
        meeting_host_rpc.metadata_id_token("https://a.run.app")
    assert meeting_host_rpc._id_tokens == {}


# ---- 4. Teach a skill, end to end through the real routes --------------------------------------------------------


def test_SKILLS_LIVE_teach_a_skill_describe_version_save_and_list(skills4):
    made = skills4.capture(CLEAR)
    assert made.status_code == 201, made.text
    capture_id = made.json()["capture_id"]
    steps = made.json()["captured_steps"]
    assert [s["text"] for s in steps] and all("text" in s for s in steps)

    version = skills4.version(capture_id)
    assert version.status_code == 200, version.text
    plan = version.json()["plan_steps"]
    sends = [s for s in plan if s["action"] == "send_email"]
    assert sends and all(s["ask_first"] is True and s["must_ask"] is True for s in sends)  # code decides, not the model

    # The body the web client posts for a taught version (apps/web saveBody): the plan as the server made it.
    skills4.rig.as_user(PRIYA)
    saved = skills4.rig.post(
        "/v1/skills",
        {
            "name": "Accountant mail",
            "scope": {"kind": "just_me", "team": None},
            "trigger": {"kind": "on_demand"},
            "plan_steps": [
                {k: s[k] for k in ("text", "tool", "action", "verb")} | {"ask_first": s["ask_first"]} for s in plan
            ],
            "captured_steps": [{"text": s["text"]} for s in steps],
        },
    )
    assert saved.status_code == 201, saved.text
    row = saved.json()
    assert row["name"] == "Accountant mail" and row["owner"] == PRIYA and row["status"] == "learning"

    listing = skills4.rig.get("/v1/skills?include_builtin=true")
    assert listing.status_code == 200, listing.text
    assert row["id"] in {s["id"] for s in listing.json()["skills"]}
    assert skills4.store.get(ORG, row["id"]) is not None
    assert len(skills4.model.calls) == 2  # exactly two model calls, both on the scripted provider


def test_SKILLS_LIVE_a_person_cannot_skip_ask_first_on_a_send_step_when_saving(skills4):
    capture_id = skills4.made(CLEAR)
    plan = skills4.version(capture_id).json()["plan_steps"]
    skills4.rig.as_user(PRIYA)
    body = {
        "name": "Loose send",
        "scope": {"kind": "just_me", "team": None},
        "trigger": {"kind": "on_demand"},
        "plan_steps": [{k: s[k] for k in ("text", "tool", "action", "verb")} | {"ask_first": False} for s in plan],
    }
    assert skills4.rig.post("/v1/skills", body).status_code == 422
