"""PPL-11c-FS FS-18 (issue #577 item 5): a failed build of the process's people stores is negative-cached for a short
window. Spec: `API_PPL_11c_FS1c.md` section 3. None needs the emulator.

`deps.get_people_stores` retries a failed build under the process-wide lock on every request, so an instance whose ADC
or metadata server is slow queues every people request behind client construction. After a failed build, every request
inside the backoff window is the fixed 503 `not_configured` WITHOUT calling the client factory (`google.cloud.firestore
.Client`); after the window one request retries; a success clears it; `cache_clear` clears it too.

The seam the tests drive (both read at call time, so a test can replace them without sleeping):
`deps.PEOPLE_STORES_BACKOFF_S` (a number of seconds, 1 to 60) and `deps.people_stores_clock()` (a zero-argument callable
returning monotonic seconds, `time.monotonic` by default).
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

import pytest
from _ppl11a_lib import OWNER
from _ppl11c_fs_lib import SENTINEL, errs, oks, race
from _ppl11c_lib import R_WI_LIST
from fastapi import HTTPException
from tilo_people.stores import PeopleStores

ENV_STORE, ENV_PROJECT = "TILO_PEOPLE_STORE", "TILO_FIRESTORE_PROJECT"
DEFAULT_WINDOW_S = 5.0  # what `window` falls back to until the builder adds the constant


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Build:
    """The Firestore client factory: counts its calls, fails while `fail` is set, optionally slowly."""

    def __init__(self, *, delay: float = 0.0) -> None:
        self.fail, self.delay, self.calls = True, delay, 0
        self._lock, self._client = threading.Lock(), MagicMock(name="firestore_client")

    def __call__(self, *args, **kwargs):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.fail:
            raise RuntimeError(f"cannot reach {SENTINEL}")
        return self._client


@pytest.fixture
def backoff(monkeypatch):
    """`(deps, clock, build, window)`: configured for Firestore, a fake clock (replaced with `raising=False`, so a
    test that runs before the seam exists fails on behaviour, not on a missing attribute), a failing factory, and a
    cold cache."""
    from tilo_api import deps

    for name in ("TILO_PEOPLE_BOOTSTRAP_UID", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_API_DEV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(ENV_STORE, "firestore")
    monkeypatch.setenv(ENV_PROJECT, "tilo-test-project")
    clock, build = FakeClock(), Build()
    monkeypatch.setattr(deps, "people_stores_clock", clock, raising=False)
    monkeypatch.setattr("google.cloud.firestore.Client", build)
    deps.get_people_stores.cache_clear()
    yield deps, clock, build, float(getattr(deps, "PEOPLE_STORES_BACKOFF_S", DEFAULT_WINDOW_S))
    deps.get_people_stores.cache_clear()


def _refused(deps):
    """The HTTPException a request gets (the test fails if it gets stores)."""
    with pytest.raises(HTTPException) as caught:
        deps.get_people_stores()
    return caught.value


def _is_the_fixed_503(exc: HTTPException) -> bool:
    return exc.status_code == 503 and exc.detail == "not_configured"


# --- the seam --------


def test_PPL_11c_FS_18_the_window_and_the_clock_are_named_seams():
    from tilo_api import deps

    window = deps.PEOPLE_STORES_BACKOFF_S
    assert isinstance(window, int | float) and not isinstance(window, bool) and 1 <= window <= 60
    assert callable(deps.people_stores_clock) and isinstance(deps.people_stores_clock(), int | float)


# --- inside the window --------


def test_PPL_11c_FS_18_after_a_failed_build_requests_inside_the_window_do_not_call_the_factory(backoff):
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps)) and build.calls == 1
    for _ in range(5):
        assert _is_the_fixed_503(_refused(deps))
    clock.advance(window * 0.5)
    assert _is_the_fixed_503(_refused(deps))
    clock.advance(window * 0.49)  # still inside: the window runs from the failure
    assert _is_the_fixed_503(_refused(deps))
    assert build.calls == 1, "a request inside the window rebuilt the client"


def test_PPL_11c_FS_18_eight_first_requests_at_a_failing_factory_call_it_once(backoff):
    """The review's scenario: a slow failing factory (ADC, metadata) and every request queued behind it, one build
    each. The first build fails under the lock; the seven that waited see the backoff and do not build."""
    deps, clock, build, window = backoff
    build.delay = 0.05
    results = race([deps.get_people_stores for _ in range(8)])
    assert not oks(results), "a failing factory gave stores"
    assert all(isinstance(e, HTTPException) and _is_the_fixed_503(e) for e in errs(results)), errs(results)
    assert build.calls == 1, f"{build.calls} builds for one failure"


def test_PPL_11c_FS_18_eight_concurrent_requests_inside_the_window_are_not_queued_behind_a_build(backoff):
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps))
    build.delay = 0.3  # were any request to build again it would take this long, and `calls` would move
    started = time.monotonic()
    results = race([deps.get_people_stores for _ in range(8)])
    elapsed = time.monotonic() - started
    assert all(_is_the_fixed_503(e) for e in errs(results)) and not oks(results)
    assert build.calls == 1 and elapsed < 0.25, (build.calls, elapsed)


# --- after the window --------


def test_PPL_11c_FS_18_after_the_window_one_request_retries_and_a_second_failure_opens_a_new_window(backoff):
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps)) and build.calls == 1
    clock.advance(window + 0.001)
    results = race([deps.get_people_stores for _ in range(8)])
    assert all(_is_the_fixed_503(e) for e in errs(results)) and not oks(results)
    assert build.calls == 2, f"{build.calls}: one retry for the eight requests after the window"
    for _ in range(3):
        assert _is_the_fixed_503(_refused(deps))
    assert build.calls == 2, "the failed retry opened a new window"
    clock.advance(window + 0.001)
    assert _is_the_fixed_503(_refused(deps)) and build.calls == 3


def test_PPL_11c_FS_18_success_after_the_window_builds_exactly_once_and_is_kept(backoff):
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps))
    build.fail = False
    assert _is_the_fixed_503(_refused(deps)), "inside the window the factory is not even tried"
    clock.advance(window + 0.001)
    results = race([deps.get_people_stores for _ in range(8)])
    assert not errs(results), errs(results)
    assert build.calls == 2, f"{build.calls}: one build for the eight"
    stores = oks(results)
    assert all(isinstance(s, PeopleStores) for s in stores) and len({id(s) for s in stores}) == 1
    assert deps.get_people_stores() is stores[0] and build.calls == 2


def test_PPL_11c_FS_18_guard_a_success_clears_the_backoff(backoff):
    """After a success the old failure is forgotten: a later cold start (`cache_clear` is the test's stand-in for a
    new process) that fails again opens a window of its own, and the success that came first leaves no window behind."""
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps))
    clock.advance(window + 0.001)
    build.fail = False
    assert isinstance(deps.get_people_stores(), PeopleStores) and build.calls == 2
    deps.get_people_stores.cache_clear()
    build.fail = True
    assert _is_the_fixed_503(_refused(deps)) and build.calls == 3, "no window survived the success"


def test_PPL_11c_FS_18_guard_cache_clear_also_clears_the_backoff(backoff):
    deps, clock, build, window = backoff
    assert _is_the_fixed_503(_refused(deps)) and build.calls == 1
    deps.get_people_stores.cache_clear()
    build.fail = False
    assert isinstance(deps.get_people_stores(), PeopleStores), "inside the old window, but the process was reset"
    assert build.calls == 2


# --- what the 503 says --------


def test_PPL_11c_FS_18_guard_the_503_is_the_same_fixed_answer_and_never_echoes_the_error(backoff, caplog):
    deps, clock, build, window = backoff
    first = _refused(deps)
    inside = _refused(deps)
    clock.advance(window + 0.001)
    retried = _refused(deps)
    for exc in (first, inside, retried):
        assert _is_the_fixed_503(exc), (exc.status_code, exc.detail)
        assert SENTINEL not in repr(exc) and SENTINEL not in str(exc) and SENTINEL not in repr(exc.detail)
    assert repr(first) == repr(inside) == repr(retried)
    assert SENTINEL not in caplog.text


def test_PPL_11c_FS_18_over_http_a_failing_build_is_one_build_and_the_same_503_body(people_rig, backoff):
    deps, clock, build, window = backoff
    rig = people_rig()
    rig.unwire("people_stores")
    rig.as_user(OWNER)
    rig.require_route(R_WI_LIST)
    bodies = []
    for _ in range(4):
        response = rig.client.get("/v1/work-items")
        assert response.status_code == 503, (response.status_code, response.text[:120])
        bodies.append(response.json())
    assert bodies == [{"detail": "not_configured"}] * 4 and build.calls == 1
    assert SENTINEL not in str(bodies)
    clock.advance(window + 0.001)
    build.fail = False
    rig.client.get("/v1/work-items")  # the answer over a mock client is not the point: the factory is
    assert build.calls == 2, "one retry after the window"
