"""NFR-26 with SEC-15: the log context must not make a request do work the access gate has not admitted.

Deployed (`K_SERVICE` set, enforcement on), the gate runs before any path or world lookup, router or store work
(API_SEC_15.md, "The gate"). So a signed-out or visitor request to `/worlds/<id>/...` never calls the `get_store`
factory for a run id; only an admitted request does, and its log line then carries the stored `run_id`. The world id
comes from the path alone and needs no lookup, so it is on the line either way (the gate's own lines may carry it).
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from _sec15_lib import JUDGE, VISITOR
from tilo_api import app, deps
from tilo_logging import configure_logging

WORLD, RUN = "w_nfr26_gate", "r_nfr26_gate"
PROBE = "nfr26 gate probe"


@pytest.fixture
def rig(sec15_factory):
    sec = sec15_factory(declarations={VISITOR: "visitor", JUDGE: "judge"})
    store = deps.Store(worlds={WORLD: deps.WorldRecord(owner=JUDGE, districts={}, run_id=RUN)})
    store_calls: list[int] = []

    def counting_store() -> deps.Store:
        store_calls.append(1)
        return store

    def probe(world_id: str) -> dict:
        logging.getLogger("nfr26.gate").warning(PROBE)
        return {}

    app.dependency_overrides[deps.get_store] = counting_store
    app.add_api_route("/worlds/{world_id}/nfr26-gate-probe", probe, methods=["GET"])
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    stream = io.StringIO()
    configure_logging(stream=stream)
    try:
        yield sec, store_calls, stream
    finally:
        root.handlers[:], root.level = handlers, level
        app.router.routes.pop()


def _probe_lines(stream: io.StringIO) -> list[dict]:
    return [r for r in map(json.loads, filter(None, stream.getvalue().split("\n"))) if r["message"] == PROBE]


def test_NFR_26_signed_out_and_visitor_requests_never_reach_the_store_for_a_run_id(rig) -> None:
    sec, store_calls, stream = rig
    path = f"/worlds/{WORLD}/nfr26-gate-probe"
    sec.sign_out()
    assert sec.call("GET", path).status_code == 401
    sec.as_user(VISITOR)
    assert sec.call("GET", path).status_code == 403
    assert store_calls == [], "the log context looked a world up before the gate admitted the request"
    assert _probe_lines(stream) == []  # the probe route never ran


def test_NFR_26_an_admitted_request_gets_its_run_id_on_the_log_line(rig) -> None:
    sec, store_calls, stream = rig
    sec.as_user(JUDGE)
    assert sec.call("GET", f"/worlds/{WORLD}/nfr26-gate-probe").status_code == 200
    (rec,) = _probe_lines(stream)
    assert (rec["run_id"], rec["world_id"]) == (RUN, WORLD)
    assert store_calls, "an admitted request is the one that may look the world up"


def test_NFR_26_a_store_that_raises_costs_the_run_id_not_the_request(rig) -> None:
    sec, _, stream = rig

    def broken() -> deps.Store:
        raise RuntimeError("store down")

    app.dependency_overrides[deps.get_store] = broken
    sec.as_user(JUDGE)
    assert sec.call("GET", f"/worlds/{WORLD}/nfr26-gate-probe").status_code == 200
    (rec,) = _probe_lines(stream)
    assert rec["world_id"] == WORLD and "run_id" not in rec
