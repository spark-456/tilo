"""Shared pytest fixtures for services/api acceptance tests: FR-HIL-09/SEC-07 (roles and
redaction) and FR-INT-01/FR-INT-02 (intake, PRD 7.1).

No business logic lives here (root CLAUDE.md test-writer rule): every helper below either loads
a contract schema unchanged or returns a literal dict/dataclass shaped like the contract or an API
this repo pins (services/api/tests/API_ST3a.md for redaction; the HTTP contract documented in
`_api_contracts_lib.py` for intake). Fixture builders and schema validation live in `_api_lib.py`
(redaction) and `_api_contracts_lib.py` (intake), kept out of this file under package-unique module
names: every test directory in the repo has its own conftest.py, so `from conftest import ...`
resolves to whichever one was imported first when the whole suite runs together -- the same
global-bare-module-name reason `_api_contracts_lib.py`'s own docstring gives for its name.

This directory has no __init__.py, so pytest's default "prepend" import mode puts it on
sys.path when collecting any test_*.py here, the same plain-module-import pattern
packages/policy/tests/conftest.py and packages/providers/tests/conftest.py use.
"""

from __future__ import annotations

import pathlib

import pytest
from _api_contracts_lib import build_registry, make_safety_provider
from _api_lib import FakeEventWriter, make_store, make_writer
from fastapi.testclient import TestClient
from tilo_api import app, deps
from tilo_api.intake import get_safety

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]


def pytest_configure(config: pytest.Config) -> None:
    # The same registration as services/harness/tests/conftest.py (PPL-11c-FS emulator tests), so running only this
    # directory with `-m "not emulator"` does not warn about an unknown marker.
    config.addinivalue_line(
        "markers",
        "emulator: exercises the real Firestore emulator via tilo_harness.emulator "
        "(needs Java + firebase-tools); slower than the rest of the suite.",
    )


@pytest.fixture(autouse=True)
def _no_dev_unit_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """CL-INT-5d: the dev unit runner paces a dev run by default; the suite runs it unpaced unless a test sets it."""
    monkeypatch.setenv("TILO_DEV_UNIT_DELAY_S", "0")


@pytest.fixture(scope="session")
def repo_root() -> pathlib.Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def registry(repo_root: pathlib.Path):
    return build_registry(repo_root)


@pytest.fixture()
def store() -> deps.Store:
    return make_store()


@pytest.fixture()
def writer(store: deps.Store) -> FakeEventWriter:
    """The in-memory stand-in for "the harness is the only writer of events" (PRD 15.3, PI-18):
    tilo-api hands it unstamped event parts; it stamps id/seq/ts/run_id and appends to
    store.events. Built on the same store instance the test holds, so store.events reflects every
    write immediately."""
    return make_writer(store)


@pytest.fixture()
def client(store: deps.Store, writer: FakeEventWriter):
    """A TestClient over the real `tilo_api.app`, with the store, the event writer and a
    deterministic fake safety provider injected: the app itself ships no safety provider (the
    screen belongs to packages/providers) and `/intake` fails closed with 503 without one. No
    principal is set for the world routes -- individual tests set
    `app.dependency_overrides[deps.get_current_principal]` for the role they want; until they do,
    an intake tester is signed in, since `/intake` needs a principal (CL-INT-1). The model router is
    a real Router over a scripted Director (no network). `dependency_overrides` is cleared at
    teardown so tests do not leak into each other."""
    from _clint1_lib import APPROACHES_REPLY, RoleScriptedProvider, brief_reply, build_router

    safety = make_safety_provider()
    model_router = build_router(REPO_ROOT, RoleScriptedProvider(brief_reply([]), APPROACHES_REPLY))
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_event_writer] = lambda: writer
    app.dependency_overrides[get_safety] = lambda: safety
    app.dependency_overrides[deps.get_current_principal] = lambda: deps.Principal(user_id="u_intake", role="owner")
    app.dependency_overrides[deps.get_router] = lambda: model_router
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# --- CL-INT-1 (CP2 thin slice, API flow): see API_CL_INT_1.md and _clint1_lib.py -----------------


@pytest.fixture()
def flow_factory(repo_root: pathlib.Path, store: deps.Store):
    """Builds a `Flow` (the real app with a fake principal, the in-memory Store, a scripted director behind
    a real Router, and by default a SafetyProvider spy). `safety=None` leaves `get_safety` un-overridden."""
    from _clint1_lib import Flow, brief_reply, make_spy_safety

    made: list[Flow] = []

    def build(ambiguous: list[str] | None = None, *, safety: object = "spy") -> Flow:
        spy = make_spy_safety() if safety == "spy" else safety
        flow = Flow(repo_root, store, spy, brief_reply(["audience", "deadline"] if ambiguous is None else ambiguous))
        made.append(flow)
        return flow

    yield build
    app.dependency_overrides.clear()


@pytest.fixture()
def flow(flow_factory):
    """Default flow: the Director marks the audience and the deadline ambiguous (two questions)."""
    return flow_factory()


@pytest.fixture()
def clear_flow(flow_factory):
    """The Director marks nothing ambiguous (a clear task: zero questions)."""
    return flow_factory([])


# --- CL-INT-2 (CP2 thin slice, the run after approve): see API_CL_INT_2.md and _clint2_lib.py ----


@pytest.fixture()
def run_flow(repo_root: pathlib.Path):
    """A clear task (no questions) with the run seams installed: scripted plan compiler, layout builder, unit runner
    and action resolver, one mock connector, an in-memory outbox store and a stand-in for the single event writer."""
    from _clint2_lib import build_run_flow

    rf = build_run_flow(repo_root, covered=True)
    yield rf
    rf.close()
    app.dependency_overrides.clear()


@pytest.fixture()
def crashing_run_flow(repo_root: pathlib.Path):
    """Same, but the mock connector records its first send and then raises (a send step that must be retried)."""
    from _clint2_lib import CrashAfterSendMock, build_run_flow

    rf = build_run_flow(repo_root, adapter_factory=CrashAfterSendMock, covered=True)
    yield rf
    rf.close()
    app.dependency_overrides.clear()


# --- SEC-15 (deployed access: visitor or judge): see API_SEC_15.md and _sec15_lib.py ---------------


@pytest.fixture()
def sec15_factory(monkeypatch: pytest.MonkeyPatch):
    """`make(declarations=..., deployed=True)` -> a `Sec15` over the real app, deployed-style (K_SERVICE set, the
    live switches cleared), with a fake access store and a scripted router behind a spy on `deps.router_for_mode`."""
    import _sec15_lib

    def make(**kwargs):
        return _sec15_lib.build(monkeypatch, **kwargs)

    yield make
    _sec15_lib.close()


# --- SEC-16 (per-uid rate limit, spend caps, durable replay-only): see API_SEC_16.md and _sec16_lib.py ---------


@pytest.fixture()
def sec16_factory(monkeypatch: pytest.MonkeyPatch):
    """`make(declarations=..., deployed=True, judge_live=True, ledger=..., flags=..., **cap_overrides)` -> a `Sec16`:
    the SEC-15 harness (deployed-style app, fake access store, scripted router behind a spy) plus a spy over the real
    in-memory ledger, a rate limiter on a fake clock and small test caps. `ledger=None` leaves the seam unwired."""
    import _sec16_lib

    def make(**kwargs):
        return _sec16_lib.build(monkeypatch, **kwargs)

    yield make
    _sec16_lib.close()


# --- PPL-11a (people API: quotes, plate, confirm, writes): see API_PPL_11a.md and _ppl11a_lib.py ----------------------


@pytest.fixture()
def people_rig(monkeypatch: pytest.MonkeyPatch):
    """`make(org=..., now=..., deployed=False, access=None)` -> a `Rig` over the real app with every people seam
    faked (stores, artifact store, redactor, clock, plate sources, source owners)."""
    import _ppl11a_lib

    made: list[_ppl11a_lib.Rig] = []

    def make(**kwargs):
        rig = _ppl11a_lib.Rig(monkeypatch, **kwargs)
        made.append(rig)
        return rig

    yield make
    for rig in made:
        rig.close()


# --- PPL-11c-FS (Firestore people stores): see API_PPL_11c_FS.md and _ppl11c_fs_lib.py --------


@pytest.fixture(scope="session")
def people_fs_client():
    """One Firestore client on the emulator for the whole session (`tilo_harness.emulator.running_emulator()`, a
    `demo-` project, no credentials), for every `@pytest.mark.emulator` PPL-11c-FS test."""
    from tilo_harness.emulator import running_emulator

    with running_emulator():
        from google.cloud import firestore

        yield firestore.Client(project="demo-tilo")


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def backend(request):
    """A `_ppl11c_fs_lib.Backend`: `MemoryStore` or the Firestore store behind the same `PeopleStores` (FS-02)."""
    import _ppl11c_fs_lib

    if request.param == "memory":
        return _ppl11c_fs_lib.Backend("memory", None)
    return _ppl11c_fs_lib.Backend("firestore", request.getfixturevalue("people_fs_client"))


@pytest.fixture
def fs_backend(people_fs_client):
    """The Firestore backend alone, for the tests that only make sense against it."""
    import _ppl11c_fs_lib

    return _ppl11c_fs_lib.Backend("firestore", people_fs_client)


@pytest.fixture(scope="session")
def pw1b_emulator_host():
    """PROD-WIRE 1b: the Firestore emulator for the session (a `demo-` project only), as the harness tests do."""
    from tilo_harness.emulator import running_emulator

    with running_emulator() as host:
        yield host


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def pw1b_rig(request):
    """PROD-WIRE 1b: a `PwRig` (records backend, events store) in memory, and again on the emulator (`-m emulator`)."""
    import _pw1b_lib

    if request.param == "firestore":
        request.getfixturevalue("pw1b_emulator_host")
    return _pw1b_lib.make_rig(request.param)


def pytest_collection_modifyitems(items):
    """PPL-11a: tests that need a slice B or C route are strict xfails until that slice lands (`SLICE_BC_PENDING`).
    PPL-11c: the same for each slice of the rest of the people API (`SLICE_PENDING`, API_PPL_11c.md section 0)."""
    if any("test_PPL_11a_" in item.nodeid for item in items):
        from _ppl11a_lib import SLICE_BC_PENDING

        for item in items:
            if "test_PPL_11a_" in item.nodeid and any(entry in item.nodeid for entry in SLICE_BC_PENDING):
                item.add_marker(pytest.mark.xfail(strict=True, reason="PPL-11a slice B/C"))
    if any("test_PPL_11c_" in item.nodeid for item in items):
        from _ppl11c_lib import PENDING_EXEMPT, SLICE_PENDING

        for item in items:
            if any(entry in item.nodeid for entry in PENDING_EXEMPT):
                continue  # passes once an earlier slice lands: pinned, never a strict xfail
            if "test_PPL_11c_" in item.nodeid and any(entry in item.nodeid for entry in SLICE_PENDING):
                item.add_marker(pytest.mark.xfail(strict=True, reason="PPL-11c slice pending"))
    if any("test_PPL_11c_FS_" in item.nodeid for item in items):
        from _ppl11c_fs_lib import is_pending

        for item in items:
            if "test_PPL_11c_FS_" in item.nodeid and is_pending(item.nodeid):
                item.add_marker(pytest.mark.xfail(strict=True, reason="PPL-11c-FS-1 pending (API_PPL_11c_FS.md)"))
    if any("test_FR_PA_08_" in item.nodeid for item in items):
        # FR-PA-08 (people assistant STATUS and weekly summary, API_FR_PA_08.md section 0): a slice is a strict xfail
        # until its builder deletes its entry from `SLICE_PENDING`; the guards file is never pending.
        from _fr_pa_08_lib import PENDING_EXEMPT as FR_PA_08_EXEMPT
        from _fr_pa_08_lib import SLICE_PENDING as FR_PA_08_PENDING

        for item in items:
            if any(entry in item.nodeid for entry in FR_PA_08_EXEMPT):
                continue
            if any(entry in item.nodeid for entry in FR_PA_08_PENDING):
                item.add_marker(pytest.mark.xfail(strict=True, reason="FR-PA-08 slice pending"))
