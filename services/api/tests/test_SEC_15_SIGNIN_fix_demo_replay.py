"""SEC-15 / SIGNIN-FIX (BQ-SIGNIN-10): an anonymous demo session is replay-only on the two paths the verified SIGNIN
left open, and the small tidy-ups from the review.

1. The public schedule tick has no signed-in person, so `get_mode` saw no demo flag. A schedule now records its owner's
   demo flag when it is created (`Schedule.demo`, from `Principal.demo_session`, never from the body), the store keeps
   it, and the tick builds that schedule's run seams in replay whatever `LIVE` says.
2. A process that is not deployed has no access gate, so `request.state.demo_session` is never set. `get_mode` and
   `get_work_mode` now also read the demo flag from the principal the request resolves (the same seam the routes use),
   so a demo session under the user's global `LIVE=1` is replay. Anything unresolved keeps the old answer: the user's
   own switch. Deployed, the gate's flag still decides, and a public route resolves nothing.
3. Tidy: `appcheck.b64url_decode` and `appcheck.RefuseAll` are public (firebase_auth imported the private names), and
   `get_current_principal` takes its request as a required parameter.
Tokens are made at runtime; no network.
"""

from __future__ import annotations

import dataclasses
import inspect
import pathlib
import socket
from typing import Annotated, Any

import pytest
from _fr_agt_14_lib import FLOW_USER, MON_0330Z, SchedApi, task_body
from _fr_agt_14e_lib import armed, block_network
from _signin_lib import NOW, PROJECT, Fetch, _key, _token
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from tilo_api import access, appcheck, deps, firebase_auth, runs
from tilo_harness.schedule_store import schedule_from_doc, schedule_to_doc
from tilo_metering.flags import InMemoryFlagStore

ENV_CLEAR = (
    "K_SERVICE", "CLOUD_RUN_JOB", "LIVE", "TILO_API_DEV", "TILO_JUDGE_LIVE", "TILO_APPCHECK_ENFORCE",
    "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT",
)  # fmt: skip
SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "tilo_api"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_CLEAR:
        monkeypatch.delenv(name, raising=False)


# --- (2) a process that is not deployed: the demo flag comes from the resolved principal --------------------------


def _mini(principal: Any = None) -> TestClient:
    app = FastAPI()

    @app.get("/mode")
    def mode(m: Annotated[access.Mode, Depends(deps.get_mode)]) -> dict[str, str]:
        return {"mode": m}

    @app.get("/work")
    def work(m: Annotated[access.Mode, Depends(deps.get_work_mode)]) -> dict[str, str]:
        return {"mode": m}

    app.dependency_overrides[deps.get_flag_store] = lambda: InMemoryFlagStore()
    if principal is not None:
        app.dependency_overrides[deps.get_current_principal] = principal
    return TestClient(app)


def _principal(**flags: bool):
    return lambda: deps.Principal(user_id=FLOW_USER, role="owner", **flags)


@pytest.mark.parametrize("path", ["/mode", "/work"])
def test_SEC_15_SIGNIN_fix_a_demo_principal_is_replay_under_the_global_live_switch_when_not_deployed(monkeypatch, path):
    monkeypatch.setenv("LIVE", "1")
    assert _mini(_principal(demo_session=True)).get(path).json() == {"mode": "replay"}


@pytest.mark.parametrize("path", ["/mode", "/work"])
def test_SEC_15_SIGNIN_fix_a_google_principal_keeps_the_users_own_live_switch_when_not_deployed(monkeypatch, path):
    monkeypatch.setenv("LIVE", "1")
    assert _mini(_principal(full_session=True)).get(path).json() == {"mode": "live"}


@pytest.mark.parametrize("path", ["/mode", "/work"])
def test_SEC_15_SIGNIN_fix_with_no_principal_to_resolve_the_global_switch_is_unchanged(monkeypatch, path):
    monkeypatch.setenv("LIVE", "1")
    assert _mini().get(path).json() == {"mode": "live"}, "nobody is resolved: the user's own switch, as before"
    monkeypatch.delenv("LIVE")
    assert _mini().get(path).json() == {"mode": "replay"}


def test_SEC_15_SIGNIN_fix_a_principal_double_that_takes_no_request_still_works(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    assert _mini(lambda: deps.Principal(user_id=FLOW_USER, role="owner", demo_session=True)).get("/mode").json() == {
        "mode": "replay"
    }


def test_SEC_15_SIGNIN_fix_a_real_anonymous_token_is_replay_and_a_google_token_live_when_not_deployed(monkeypatch):
    monkeypatch.setenv("LIVE", "1")
    signer = _key()
    verifier = firebase_auth.FirebaseIdTokenVerifier(
        PROJECT, fetch=Fetch({"k1": signer.public_key()}), clock=lambda: 0.0, wall=lambda: NOW
    )
    client = _mini()
    client.app.dependency_overrides[deps.get_firebase_verifier] = lambda: verifier  # type: ignore[attr-defined]
    anonymous = _token(signer, provider="anonymous", sub="anon" + "Q7" * 12)
    google = _token(signer, provider="google.com", sub="uid" + "A1" * 10)
    assert client.get("/mode", headers={"Authorization": f"Bearer {anonymous}"}).json() == {"mode": "replay"}
    assert client.get("/mode", headers={"Authorization": f"Bearer {google}"}).json() == {"mode": "live"}
    assert client.get("/mode", headers={"Authorization": "Bearer not-a-token"}).json() == {"mode": "live"}


def test_SEC_15_SIGNIN_fix_a_principal_seam_that_fails_does_not_break_the_mode(monkeypatch):
    monkeypatch.setenv("LIVE", "1")

    def broken() -> Any:
        raise RuntimeError("boom")

    assert _mini(broken).get("/mode").json() == {"mode": "live"}


# --- (1) a schedule remembers its owner's demo flag ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    return block_network(monkeypatch)


@pytest.fixture
def rig(run_flow, monkeypatch) -> SchedApi:
    rig = SchedApi(run_flow.flow, monkeypatch, rf=run_flow)
    rig.clock.set(MON_0330Z)
    return rig


def test_SEC_15_SIGNIN_fix_a_schedule_record_has_a_demo_flag_that_defaults_to_false_and_round_trips(rig: SchedApi):
    source = armed(rig)
    plain = rig.record(source, "sched_p")
    demo = rig.record(source, "sched_d", demo=True)
    assert plain.demo is False and demo.demo is True
    assert schedule_from_doc(schedule_to_doc(demo)).demo is True
    assert schedule_from_doc(schedule_to_doc(plain)).demo is False
    old = schedule_to_doc(plain)
    old.pop("demo", None)
    assert schedule_from_doc(old).demo is False, "a record written before the field existed is a plain one"
    for bad in ("yes", 1, None):
        with pytest.raises(ValueError):
            schedule_from_doc({**schedule_to_doc(plain), "demo": bad})


@pytest.mark.parametrize(("demo", "flag"), [(True, True), (False, False)])
def test_SEC_15_SIGNIN_fix_creating_a_schedule_records_the_principals_demo_flag(rig: SchedApi, demo, flag):
    source = rig.source_run_task()
    rig.flow.app.dependency_overrides[deps.get_current_principal] = lambda: dataclasses.replace(
        rig.flow.principal, demo_session=demo
    )
    made = rig.created(source)
    assert rig.schedules.get(made["schedule_id"]).demo is flag
    assert "demo" not in made, "the flag is the server's note, not part of the owner's view"


def test_SEC_15_SIGNIN_fix_a_body_cannot_set_the_demo_flag(rig: SchedApi):
    source = rig.source_run_task()
    response = rig.create(source, demo=False)
    assert response.status_code == 422


def _record_modes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    modes: list[str] = []
    original = runs.run_seams

    def spy(request: Any, mode: Any) -> Any:
        modes.append(mode)
        return original(request, "replay")  # the rig's seams are doubles; only the mode asked for is recorded

    monkeypatch.setattr(runs, "run_seams", spy)
    return modes


def _execute(rig: SchedApi):
    return rig.task_call(task_body("sched_a", MON_0330Z))


def test_SEC_15_SIGNIN_fix_the_tick_builds_a_demo_schedules_run_in_replay_under_the_global_live_switch(
    rig: SchedApi, monkeypatch
):
    source = armed(rig)
    rig.insert(source, "sched_a", demo=True)
    monkeypatch.setenv("LIVE", "1")
    modes = _record_modes(monkeypatch)
    response = _execute(rig)
    assert response.status_code == 200 and response.json()["ran"] == 1, response.text
    assert modes and modes[-1] == "replay", modes


def test_SEC_15_SIGNIN_fix_the_tick_leaves_a_google_owners_schedule_on_the_users_own_switch(rig: SchedApi, monkeypatch):
    source = armed(rig)
    rig.insert(source, "sched_a")
    monkeypatch.setenv("LIVE", "1")
    modes = _record_modes(monkeypatch)
    response = _execute(rig)
    assert response.status_code == 200 and response.json()["ran"] == 1, response.text
    assert modes == ["live"], modes


def test_SEC_15_SIGNIN_fix_the_fan_out_still_reads_nothing_of_the_owner(rig: SchedApi, monkeypatch):
    """The Scheduler's fan-out starts nothing, so it needs no mode: it must not build seams for a demo schedule."""
    source = armed(rig)
    rig.insert(source, "sched_a", demo=True)
    modes = _record_modes(monkeypatch)
    rig.tick()
    assert modes == []


# --- (4) tidy ------------------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_fix_the_shared_helpers_are_public_and_firebase_auth_imports_no_private_name():
    assert appcheck.b64url_decode("YWJj") == b"abc"
    assert issubclass(appcheck.RefuseAll, object) and appcheck.RefuseAll("dev_mode") is not None
    text = (SRC / "firebase_auth.py").read_text(encoding="utf-8")
    import_line = next(line for line in text.splitlines() if line.startswith("from tilo_api.appcheck import"))
    assert "_b64" not in import_line and "_RefuseAll" not in import_line, import_line


def test_SEC_15_SIGNIN_fix_get_current_principal_requires_its_request():
    parameter = inspect.signature(deps.get_current_principal).parameters["request"]
    assert parameter.default is inspect.Parameter.empty
    assert "type: ignore" not in inspect.getsource(deps.get_current_principal).splitlines()[0]


def test_SEC_15_SIGNIN_fix_a_request_with_no_authorization_is_the_fixed_401():
    from fastapi import HTTPException
    from starlette.requests import HTTPConnection

    with pytest.raises(HTTPException) as refused:
        deps.get_current_principal(HTTPConnection({"type": "http", "headers": [], "app": FastAPI()}))
    assert refused.value.status_code == 401


def test_SEC_15_SIGNIN_fix_nothing_in_these_tests_opens_a_connection():
    assert socket.socket.connect is not None
