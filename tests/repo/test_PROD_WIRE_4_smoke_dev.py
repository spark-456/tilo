"""PROD-WIRE-4 (slice 4, deployed edge): `just smoke-dev`, a deployed smoke of tilo-dev, `scripts/smoke_dev.py`.

Pinned interface (test-writer brief, PROD-WIRE-4; the step names, the module function and its keyword arguments are
this file's own choices, resolved from the brief, and are listed in the report):

  * `scripts/smoke_dev.py` is importable and exposes
    `main(argv, *, transport=None, env=None, sleep=time.sleep, timeout_s=60.0) -> int`. `argv` is `[url]`;
    `transport` is an `httpx` transport (tests pass `httpx.MockTransport`); `env` is the environment mapping (default
    `os.environ`); `sleep` and `timeout_s` bound the two polls. It prints to stdout and returns the exit code (0 only
    when every step ran and passed, 1 otherwise). Run as a script it is `python scripts/smoke_dev.py <url>`.
  * The url must fully match the Cloud Run pattern (the same one `just deploy-web` takes) or the run is refused
    before any request: `FAIL url: <reason>`.
  * Steps, each one line, `PASS <step>` or `FAIL <step>: <reason>`, stopping at the first FAIL:
      health          GET /health -> 200
      cors-allowed    a preflight (OPTIONS) to a gated route from https://essential-wares-510320-f0.web.app -> granted
      cors-denied     a preflight from a disallowed origin -> not granted
      gate-closed     a gated route with no token -> 401 or 403 (fail closed)
    then, only when `TILO_SMOKE_ID_TOKEN` is set (a Firebase ID token the person pastes; replay mode, no paid call):
      intake          POST /intake (multipart text)                              -> 201 {task_id, questions}
      answers         POST /tasks/{id}/answers (every question skipped)          -> 200
      approaches      GET  /tasks/{id}/approaches                                -> 200 {recommended}
      approve         POST /tasks/{id}/approve {approach_id, budget_cap <= 50}   -> 200 {world_id}
      gate-card       GET  /worlds/{id}/cards, polled, until a `kind: gate` card
      answer-card     POST /worlds/{id}/cards/{card}/answer {option: approve}    -> 200
      delivery        GET  /worlds/{id}/delivery, polled until 200 (409 until the run completes)
    With no token: `SKIP signed-in steps: set TILO_SMOKE_ID_TOKEN`.
    The route set is the dev-mode flow of `test_CL_INT_5c_dev_run_to_gate.py` and the web client's own calls.
  * Only what a browser could use: no test backdoor, no `LIVE` switch, no paid call. `X-Tilo-Channel: web`, and the
    token only as `Authorization: Bearer ...` on the signed-in requests, never printed, logged, written or sent
    anywhere but the given url (redirects are not followed). HTTP is `httpx` with a timeout.

The server here is a fake behind `httpx.MockTransport`; no network, no cloud, no real account. Tokens are assembled
at runtime.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import re
import shutil
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "smoke_dev.py"

URL = "https://tilo-api-abc123def4-as.a.run.app"
WEB_APP = "https://essential-wares-510320-f0.web.app"
FIREBASE_APP = "https://essential-wares-510320-f0.firebaseapp.com"
ALLOWED = (WEB_APP, FIREBASE_APP)
PUBLIC_PATHS = {"/health", "/healthz", "/access", "/access/declaration", "/internal/schedules/tick"}
TOKEN_ENV = "TILO_SMOKE_ID_TOKEN"

UNSIGNED = ["health", "cors-allowed", "cors-denied", "gate-closed"]
SIGNED = ["intake", "answers", "approaches", "approve", "gate-card", "answer-card", "delivery"]
ORDER = UNSIGNED + SIGNED
SKIP_LINE = "SKIP signed-in steps: set TILO_SMOKE_ID_TOKEN"


def fake_token() -> str:
    """Assembled at runtime and different on every run: never a literal in the repo. JWT-shaped (three url-safe base64
    segments), because the smoke refuses any other shape before it sends anything (security round 1)."""
    return ".".join(["idtok-" + uuid.uuid4().hex, uuid.uuid4().hex, uuid.uuid4().hex[:12]])


def load():
    spec = importlib.util.spec_from_file_location("smoke_dev_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # a missing script is a failing test here, not a collection error
    return module


def json_response(status: int, body: object, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers)


def label(request: httpx.Request) -> str:
    """Which smoke step a request belongs to, from the request alone."""
    method, path = request.method, request.url.path
    if method == "GET" and path == "/health":
        return "health"
    if method == "OPTIONS":
        return "cors-allowed" if request.headers.get("origin") in ALLOWED else "cors-denied"
    if "authorization" not in request.headers:
        return "gate-closed"
    routes = (
        ("POST", r"/intake", "intake"),
        ("POST", r"/tasks/[^/]+/answers", "answers"),
        ("GET", r"/tasks/[^/]+/approaches", "approaches"),
        ("POST", r"/tasks/[^/]+/approve", "approve"),
        ("GET", r"/worlds/[^/]+/cards", "gate-card"),
        ("POST", r"/worlds/[^/]+/cards/[^/]+/answer", "answer-card"),
        ("GET", r"/worlds/[^/]+/delivery", "delivery"),
    )
    for verb, pattern, name in routes:
        if method == verb and re.fullmatch(pattern, path):
            return name
    return f"unexpected {method} {path}"


@dataclass
class Edge:
    """A well-behaved deployed tilo-api. `override(request)` returns a response to replace one, or None."""

    token: str | None = None
    override: Callable[[httpx.Request], httpx.Response | None] | None = None
    polls_before_gate: int = 2
    polls_before_delivery: int = 2
    requests: list[httpx.Request] = field(default_factory=list)
    cards_polls: int = 0
    delivery_polls: int = 0
    answered: bool = False

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    @property
    def labels(self) -> list[str]:
        return [label(r) for r in self.requests]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.override and (replaced := self.override(request)) is not None:
            return replaced
        method, path, origin = request.method, request.url.path, request.headers.get("origin")
        if method == "GET" and path == "/health":
            return json_response(200, {"status": "ok"})
        if method == "OPTIONS":
            if origin in ALLOWED:
                return httpx.Response(
                    204,
                    headers={
                        "access-control-allow-origin": origin,
                        "access-control-allow-methods": "GET, POST, PATCH, DELETE, OPTIONS",
                        "access-control-allow-headers": "authorization, x-tilo-channel, x-firebase-appcheck",
                        "vary": "Origin",
                    },
                )
            return httpx.Response(400, text="Disallowed CORS origin")
        signed = (
            self.token is not None
            and request.headers.get("authorization") == f"Bearer {self.token}"
            and request.headers.get("x-tilo-channel") == "web"
        )
        if not signed:
            return json_response(401, {"detail": "Sign in to use this."})
        body = (
            json.loads(request.content)
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        step = label(request)
        if step == "intake":
            return json_response(
                201, {"task_id": "t_smoke", "questions": [{"field": "audience"}, {"field": "deadline"}]}
            )
        if step == "answers":
            return json_response(200, {"ok": True})
        if step == "approaches":
            return json_response(200, {"recommended": "ap_1", "approaches": [{"id": "ap_1"}, {"id": "ap_2"}]})
        if step == "approve":
            return json_response(200, {"world_id": "w_smoke"})
        if step == "gate-card":
            self.cards_polls += 1
            if self.cards_polls <= self.polls_before_gate:
                return json_response(200, [])
            in_app_gate = {  # the only gate the smoke answers: not T3, no recipient, no connector, item or destination
                "id": "g_smoke",
                "action": {
                    "type": "save_note",
                    "connector": None,
                    "exact": "Keep it.",
                    "item": None,
                    "destination": None,
                },
                "recipients": [],
                "irreversible": False,
                "risk_tier": "T1",
            }
            card = {
                "id": "c_smoke",
                "kind": "gate",
                "options": [{"id": "approve"}, {"id": "hold"}],
                "gate": in_app_gate,
            }
            return json_response(200, [card])
        if step == "answer-card":
            assert body == {"option": "approve"}, body
            self.answered = True
            return json_response(200, {"outcome": "answered"})
        if step == "delivery":
            self.delivery_polls += 1
            if self.delivery_polls <= self.polls_before_delivery:
                return json_response(409, {"detail": "Nothing is delivered until the work is done."})
            return json_response(200, {"world_id": "w_smoke", "artifacts": [], "credits_used": 0, "time_saved": None})
        return json_response(404, {"detail": "Not Found"})


def run(capsys, edge: Edge, *, env: dict[str, str] | None = None, url: str = URL, **kwargs):
    smoke = load()
    code = smoke.main([url], transport=edge.transport, env=env or {}, sleep=lambda _s: None, **kwargs)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def status_lines(out: str) -> list[tuple[str, str]]:
    """(PASS|FAIL, step) for every status line, in order."""
    return [(m.group(1), m.group(2)) for m in re.finditer(r"(?m)^(PASS|FAIL) ([a-z-]+)\b", out)]


def fail_reason(out: str, step: str) -> str:
    match = re.search(rf"(?m)^FAIL {re.escape(step)}: (.+)$", out)
    assert match, f"expected a line `FAIL {step}: <reason>` in:\n{out}"
    return match.group(1)


def only_requests_up_to(edge: Edge, step: str) -> None:
    later = set(ORDER[ORDER.index(step) + 1 :])
    seen_later = [lab for lab in edge.labels if lab in later]
    assert not seen_later, f"requests made after the failed step {step}: {seen_later}"


# --- the unsigned steps ---------------------------------------------------------------------------------------


def test_PROD_WIRE_4_smoke_without_a_token_runs_the_four_unsigned_steps_then_skips_the_rest(capsys):
    edge = Edge()

    code, out, _ = run(capsys, edge)

    assert code == 0, out
    assert status_lines(out) == [("PASS", s) for s in UNSIGNED], out
    assert SKIP_LINE in out and "FAIL" not in out
    assert edge.labels == UNSIGNED, "exactly one request per unsigned step, in order, nothing signed-in"
    assert all("authorization" not in r.headers for r in edge.requests), "no token, so no Authorization anywhere"


def test_PROD_WIRE_4_smoke_probes_cors_with_real_origins_against_a_gated_route(capsys):
    edge = Edge()

    run(capsys, edge)

    allowed, denied = edge.requests[1], edge.requests[2]
    assert allowed.method == denied.method == "OPTIONS"
    assert allowed.headers["origin"] == WEB_APP
    assert denied.headers["origin"] not in ALLOWED and denied.headers["origin"].startswith("https://")
    for preflight in (allowed, denied):
        assert preflight.headers.get("access-control-request-method"), "a preflight names the method it asks for"
        assert preflight.url.path not in PUBLIC_PATHS, "the preflight goes to a gated route, not a public one"
    closed = edge.requests[3]
    assert closed.url.path not in PUBLIC_PATHS and closed.method != "OPTIONS", "the fail-closed probe is a gated route"


def test_PROD_WIRE_4_a_gated_route_with_no_token_may_say_401_or_403(capsys):
    for status in (401, 403):

        def closed(r: httpx.Request, status: int = status) -> httpx.Response | None:
            return json_response(status, {"detail": "no"}) if label(r) == "gate-closed" else None

        code, out, _ = run(capsys, Edge(override=closed))

        assert code == 0 and ("PASS", "gate-closed") in status_lines(out), (status, out)


def only(step: str, response: Callable[[httpx.Request], httpx.Response]):
    """An override that replaces the answer to one step and leaves the rest alone."""
    return lambda r: response(r) if label(r) == step else None


FAILING_UNSIGNED = {
    "health-500": ("health", only("health", lambda r: json_response(500, {}))),
    "allowed-origin-not-granted": (
        "cors-allowed",
        only("cors-allowed", lambda r: httpx.Response(400, text="Disallowed CORS origin")),
    ),
    "allowed-origin-granted-star": (
        "cors-allowed",
        only("cors-allowed", lambda r: httpx.Response(204, headers={"access-control-allow-origin": "*"})),
    ),
    "allowed-preflight-refused-by-the-gate": (
        "cors-allowed",
        only("cors-allowed", lambda r: json_response(403, {"code": "under_construction"})),
    ),
    "denied-origin-echoed": (
        "cors-denied",
        only(
            "cors-denied", lambda r: httpx.Response(204, headers={"access-control-allow-origin": r.headers["origin"]})
        ),
    ),
    "denied-origin-star": (
        "cors-denied",
        only("cors-denied", lambda r: httpx.Response(204, headers={"access-control-allow-origin": "*"})),
    ),
    "gate-open-200": ("gate-closed", only("gate-closed", lambda r: json_response(200, []))),
}


@pytest.mark.parametrize("case", FAILING_UNSIGNED)
def test_PROD_WIRE_4_each_unsigned_step_fails_by_name_with_a_reason_and_the_run_stops(capsys, case):
    step, override = FAILING_UNSIGNED[case]
    edge = Edge(override=override)

    code, out, _ = run(capsys, edge)

    assert code != 0
    assert fail_reason(out, step).strip(), "a FAIL line carries a reason"
    assert [s for s in status_lines(out) if s[0] == "FAIL"] == [("FAIL", step)], "exactly one FAIL, the first"
    assert status_lines(out)[-1] == ("FAIL", step), "nothing is reported after the first failure"
    assert SKIP_LINE not in out
    only_requests_up_to(edge, step)


def test_PROD_WIRE_4_the_first_failure_wins_when_two_steps_would_fail(capsys):
    def everything_broken(request: httpx.Request) -> httpx.Response | None:
        return json_response(500, {}) if request.method != "OPTIONS" else httpx.Response(400)

    code, out, _ = run(capsys, Edge(override=everything_broken))

    assert code != 0 and status_lines(out) == [("FAIL", "health")], out


def test_PROD_WIRE_4_a_transport_error_is_a_named_fail_not_a_traceback(capsys):
    smoke = load()
    for error in (httpx.ConnectError("refused"), httpx.ReadTimeout("slow"), httpx.RemoteProtocolError("garbled")):

        def boom(request: httpx.Request, error: Exception = error) -> httpx.Response:
            raise error

        code = smoke.main([URL], transport=httpx.MockTransport(boom), env={}, sleep=lambda _s: None)
        captured = capsys.readouterr()

        assert code != 0, error
        assert status_lines(captured.out) == [("FAIL", "health")], captured.out
        assert "Traceback" not in captured.out + captured.err


# --- url validation and where requests go ---------------------------------------------------------------------

BAD_URLS = (
    "",
    "http://tilo-api-abc-as.a.run.app",
    "https://tilo-api-abc-as.a.run.app/",
    "https://tilo-api-abc-as.a.run.app/health",
    "https://tilo-api-abc-as.a.run.app?x=1",
    "https://tilo-api-abc-as.a.run.app:8080",
    "https://a@b.a.run.app",
    "https://tilo-api-abc-as.a.run.app;touch pwned",
    "https://tilo-api-abc-as.a.run.app$(touch pwned)",
    "https://tilo-api-abc-as.a.run.app`touch pwned`",
    "https://tilo-api-abc-as.a.run.app touch",
    "https://tilo-api-abc-as.a.run.app\n",
    "https://essential-wares-510320-f0.web.app",
    "https://tilo-api-abc-as.a.run.app.evil.test",
    "https://TILO-API-ABC-AS.a.run.app",
    "http://localhost:8080",
    "https://api-123456789012.us-central1.run.app",
    # security round 1: only tilo-api's own Cloud Run service, so a token never goes to a stranger's service
    "https://tilo-api.a.run.app",
    "https://api-123456789012.asia-southeast1.run.app",
    "https://other-svc-abc-as.a.run.app",
    "https://evil-123.asia-southeast1.run.app",
    "https://tilo-apix-abc-as.a.run.app",
    "https://xtilo-api-abc-as.a.run.app",
    "https://tilo-api-abc.a.run.app",
    "https://tilo-api-abc-def-as.a.run.app",
    "https://tilo-api--as.a.run.app",
    "https://tilo-api-123456789012.us-central1.run.app",
    "https://tilo-api-12ab.asia-southeast1.run.app",
)


def test_PROD_WIRE_4_a_bad_url_is_refused_before_any_request(capsys):
    for bad in BAD_URLS:
        edge = Edge()

        code, out, _ = run(capsys, edge, url=bad, env={TOKEN_ENV: fake_token()})

        assert code != 0, repr(bad)
        assert edge.requests == [], f"{bad!r}: nothing is sent for a url that is not a plain Cloud Run url"
        assert re.search(r"(?m)^FAIL url: .+", out), (bad, out)


def test_PROD_WIRE_4_every_request_goes_to_the_given_url_and_nowhere_else(capsys):
    token = fake_token()
    edge = Edge(token=token)

    code, out, _ = run(capsys, edge, env={TOKEN_ENV: token})

    assert code == 0, out
    assert len(edge.requests) > len(ORDER) - 1
    hosts = {(r.url.scheme, r.url.host, r.url.port) for r in edge.requests}
    assert hosts == {("https", "tilo-api-abc123def4-as.a.run.app", None)}, hosts


def test_PROD_WIRE_4_a_redirect_is_not_followed_so_a_request_never_goes_to_another_host(capsys):
    edge = Edge(override=only("health", lambda r: httpx.Response(302, headers={"location": "https://evil.example/h"})))

    code, out, _ = run(capsys, edge)

    assert code != 0 and status_lines(out) == [("FAIL", "health")], out
    assert {r.url.host for r in edge.requests} == {"tilo-api-abc123def4-as.a.run.app"}


def test_PROD_WIRE_4_a_redirect_on_a_signed_in_call_never_carries_the_token_elsewhere(capsys):
    token = fake_token()
    edge = Edge(
        token=token,
        override=only("intake", lambda r: httpx.Response(307, headers={"location": "https://evil.example/intake"})),
    )

    code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0 and ("FAIL", "intake") in status_lines(out)
    assert {r.url.host for r in edge.requests} == {"tilo-api-abc123def4-as.a.run.app"}
    assert token not in out + err


# --- the signed-in steps --------------------------------------------------------------------------------------


def test_PROD_WIRE_4_with_a_token_the_signed_in_flow_runs_in_order_and_every_step_passes(capsys, caplog):
    token = fake_token()
    edge = Edge(token=token)

    with caplog.at_level("DEBUG"):
        code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code == 0, out
    assert status_lines(out) == [("PASS", s) for s in ORDER], out
    assert "SKIP" not in out
    steps = [lab for i, lab in enumerate(edge.labels) if i == 0 or lab != edge.labels[i - 1]]
    assert steps == ORDER, f"request order: {steps}"
    assert edge.answered
    assert edge.cards_polls == 3 and edge.delivery_polls == 3, "both polls are repeated until they succeed"
    for stream in (out, err, caplog.text):
        assert token not in stream, "a passing run does not print or log the token either"


def test_PROD_WIRE_4_signed_in_requests_say_web_and_carry_the_token_only_as_a_bearer_header(capsys):
    token = fake_token()
    edge = Edge(token=token)

    run(capsys, edge, env={TOKEN_ENV: token})

    signed = [r for r in edge.requests if label(r) in SIGNED]
    unsigned = [r for r in edge.requests if label(r) in UNSIGNED]
    assert signed and unsigned
    for r in signed:
        assert r.headers["authorization"] == f"Bearer {token}"
        assert r.headers["x-tilo-channel"] == "web"
    for r in unsigned:
        assert "authorization" not in r.headers, f"{label(r)} must not send the token: it tests the open door"
    for r in edge.requests:
        elsewhere = [str(r.url), r.content.decode("latin-1")] + [
            f"{k}: {v}" for k, v in r.headers.items() if k.lower() != "authorization"
        ]
        assert not any(token in part for part in elsewhere), f"the token leaked outside Authorization in {label(r)}"


def test_PROD_WIRE_4_signed_in_requests_have_the_shapes_the_real_routes_take(capsys):
    token = fake_token()
    edge = Edge(token=token)
    run(capsys, edge, env={TOKEN_ENV: token})
    by_step = {}
    for r in edge.requests:
        by_step.setdefault(label(r), r)

    intake = by_step["intake"]
    assert intake.headers["content-type"].startswith("multipart/form-data") and b'name="text"' in intake.content
    answers = json.loads(by_step["answers"].content)
    assert by_step["answers"].url.path == "/tasks/t_smoke/answers"
    assert answers == {
        "answers": [{"field": "audience", "answer": None}, {"field": "deadline", "answer": None}],
        "brief_edits": {},
    }, "every question is skipped (answer null), nothing is invented"
    assert by_step["approaches"].url.path == "/tasks/t_smoke/approaches"
    approve = json.loads(by_step["approve"].content)
    assert by_step["approve"].url.path == "/tasks/t_smoke/approve"
    assert approve["approach_id"] == "ap_1", "the recommended approach"
    cap = approve["budget_cap"]
    assert isinstance(cap, int | float) and not isinstance(cap, bool) and 0 < cap <= 50, "a small cap (dev flow: 50)"
    assert set(approve) == {"approach_id", "budget_cap"}
    assert by_step["gate-card"].url.path == "/worlds/w_smoke/cards"
    assert by_step["answer-card"].url.path == "/worlds/w_smoke/cards/c_smoke/answer"
    assert by_step["delivery"].url.path == "/worlds/w_smoke/delivery"


def test_PROD_WIRE_4_a_blank_token_counts_as_no_token(capsys):
    for blank in ("", "   "):
        edge = Edge()

        code, out, _ = run(capsys, edge, env={TOKEN_ENV: blank})

        assert code == 0 and SKIP_LINE in out, repr(blank)
        assert edge.labels == UNSIGNED and all("authorization" not in r.headers for r in edge.requests)


FAILING_SIGNED = {
    "intake-refused": (
        "intake",
        only("intake", lambda r: json_response(403, {"detail": "x", "code": "under_construction"})),
    ),
    "answers-refused": ("answers", only("answers", lambda r: json_response(400, {"detail": "no"}))),
    "approaches-none-recommended": (
        "approaches",
        only("approaches", lambda r: json_response(200, {"approaches": []})),
    ),
    "approve-replay-only": (
        "approve",
        only("approve", lambda r: json_response(503, {"detail": "x", "replay_only": True})),
    ),
    "answer-card-busy": (
        "answer-card",
        only("answer-card", lambda r: json_response(409, {"outcome": "rejected", "reason": "busy"})),
    ),
    "answer-card-rejected-200": (
        "answer-card",
        only("answer-card", lambda r: json_response(200, {"outcome": "rejected", "reason": "already_resolved"})),
    ),
}


@pytest.mark.parametrize("case", FAILING_SIGNED)
def test_PROD_WIRE_4_each_signed_in_step_fails_by_name_and_the_run_stops(capsys, case):
    step, replacement = FAILING_SIGNED[case]
    token = fake_token()
    edge = Edge(token=token, override=replacement)

    code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0
    assert fail_reason(out, step).strip()
    assert status_lines(out)[-1] == ("FAIL", step), out
    assert status_lines(out)[:-1] == [("PASS", s) for s in ORDER[: ORDER.index(step)]]
    only_requests_up_to(edge, step)
    assert token not in out + err


def test_PROD_WIRE_4_a_poll_that_never_succeeds_ends_in_a_named_fail_after_its_timeout(capsys):
    never = [
        ("gate-card", only("gate-card", lambda r: json_response(200, []))),
        (
            "gate-card",
            only("gate-card", lambda r: json_response(200, [{"id": "c1", "kind": "question", "options": []}])),
        ),
        ("delivery", only("delivery", lambda r: json_response(409, {"detail": "not yet"}))),
    ]
    for step, override in never:
        token = fake_token()
        edge = Edge(token=token, override=override)

        code, out, _ = run(capsys, edge, env={TOKEN_ENV: token}, timeout_s=0.05)

        assert code != 0 and status_lines(out)[-1] == ("FAIL", step), (step, out)
        assert fail_reason(out, step).strip()
        only_requests_up_to(edge, step)


# --- the token is never printed, logged or written ------------------------------------------------------------


def _echo_json(request: httpx.Request) -> httpx.Response:
    return json_response(400, {"detail": f"bad token {request.headers.get('authorization')}"})


def _echo_text(request: httpx.Request) -> httpx.Response:
    return httpx.Response(500, text=f"upstream said: Authorization={request.headers.get('authorization')}")


@pytest.mark.parametrize("echo", [_echo_json, _echo_text], ids=["json-body", "text-body"])
def test_PROD_WIRE_4_the_token_is_not_printed_even_when_a_failing_response_echoes_it(
    capsys, caplog, tmp_path, monkeypatch, echo
):
    monkeypatch.chdir(tmp_path)
    token = fake_token()
    edge = Edge(token=token, override=lambda r: echo(r) if label(r) == "intake" else None)

    with caplog.at_level("DEBUG"):
        code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0 and status_lines(out)[-1] == ("FAIL", "intake")
    for stream in (out, err, caplog.text):
        assert token not in stream, "the token reached output or a log"
        assert token.split("-")[1] not in stream, "not even a piece of it"
    assert list(tmp_path.iterdir()) == [], "nothing is written to disk"


def test_PROD_WIRE_4_the_token_is_not_printed_when_the_transport_error_message_contains_it(capsys, caplog):
    token = fake_token()

    def boom(request: httpx.Request) -> httpx.Response:
        if "authorization" in request.headers:
            raise httpx.ConnectError(f"cannot reach host with {request.headers['authorization']}")
        return Edge(token=token).handle(request)

    smoke = load()
    with caplog.at_level("DEBUG"):
        code = smoke.main([URL], transport=httpx.MockTransport(boom), env={TOKEN_ENV: token}, sleep=lambda _s: None)
    captured = capsys.readouterr()

    assert code != 0 and status_lines(captured.out)[-1] == ("FAIL", "intake"), captured.out
    for stream in (captured.out, captured.err, caplog.text):
        assert token not in stream


def test_PROD_WIRE_4_the_script_run_as_a_program_refuses_a_bad_url_without_a_request(tmp_path):
    env = {k: v for k, v in os.environ.items() if k != TOKEN_ENV}
    env[TOKEN_ENV] = fake_token()
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "http://not-cloud-run.example"],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=tmp_path,
        env=env,
    )

    assert proc.returncode != 0
    assert re.search(r"(?m)^FAIL url: .+", proc.stdout), proc.stdout + proc.stderr
    assert env[TOKEN_ENV] not in proc.stdout + proc.stderr
    assert list(tmp_path.iterdir()) == []


# --- security round 1: the token's shape is checked first, reasons never hold a raw body ---------------------------


def fragments(token: str) -> list[str]:
    """Every segment of 4 or more characters of a token, however it is split (dots, line breaks, NUL)."""
    return [part for part in re.split(r"[.\r\n\x00]", token) if len(part) >= 4]


def jwt_parts() -> tuple[str, str, str]:
    a, b, c = (uuid.uuid4().hex + uuid.uuid4().hex[:8] for _ in range(3))
    return a, b, c


def malformed_tokens() -> dict[str, str]:
    a, b, c = jwt_parts()
    return {
        "newline": f"{a}.{b[:20]}\n{b[20:]}.{c}",
        "carriage-return": f"{a}.{b[:20]}\r{b[20:]}.{c}",
        "nul": f"{a}.{b[:20]}\x00{b[20:]}.{c}",
        "crlf": f"{a}.{b[:20]}\r\n{b[20:]}.{c}",
        "trailing-newline": f"{a}.{b}.{c}\n",
        "no-dots": f"{a}{b}{c}",
        "two-segments": f"{a}.{b}",
        "four-segments": f"{a}.{b}.{c}.{a}",
        "empty-segment": f"{a}..{c}",
        "space": f"{a}.{b[:20]} {b[20:]}.{c}",
        "bearer-prefix": f"Bearer {a}.{b}.{c}",
    }


@pytest.mark.parametrize("kind", list(malformed_tokens()))
def test_PROD_WIRE_4_a_token_that_is_not_a_jwt_is_refused_before_any_request_and_never_echoed(capsys, caplog, kind):
    token = malformed_tokens()[kind]
    edge = Edge(token=token)

    with caplog.at_level("DEBUG"):
        code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0 and edge.requests == [], "refused before ANY request, even the unsigned health check"
    assert out.splitlines() == ["FAIL token: TILO_SMOKE_ID_TOKEN is not a JWT"], out
    for stream in (out, err, caplog.text):
        for fragment in fragments(token):
            assert fragment not in stream, f"a fragment of the token reached output or a log: {fragment[:6]}..."


def test_PROD_WIRE_4_a_jwt_shaped_token_is_accepted_and_a_blank_one_still_counts_as_unset(capsys):
    a, b, c = jwt_parts()
    shaped = f"{a}-_.{b}.{c}"  # the url-safe base64 alphabet
    code, out, _ = run(capsys, Edge(token=shaped), env={TOKEN_ENV: shaped})
    assert code == 0 and "FAIL" not in out, out

    code, out, _ = run(capsys, Edge(), env={TOKEN_ENV: "  \n "})
    assert code == 0 and SKIP_LINE in out


def test_PROD_WIRE_4_an_exception_on_a_signed_call_reports_only_its_type_name(capsys, caplog):
    token = fake_token()

    def boom(request: httpx.Request) -> httpx.Response:
        if "authorization" in request.headers:  # h11 puts the header value in the message, as a bytes repr
            raise httpx.LocalProtocolError(f"Illegal header value {request.headers['authorization'].encode()!r}")
        return Edge(token=token).handle(request)

    smoke = load()
    with caplog.at_level("DEBUG"):
        code = smoke.main([URL], transport=httpx.MockTransport(boom), env={TOKEN_ENV: token}, sleep=lambda _s: None)
    captured = capsys.readouterr()

    assert code != 0 and status_lines(captured.out)[-1] == ("FAIL", "intake")
    assert fail_reason(captured.out, "intake") == "LocalProtocolError"
    for stream in (captured.out, captured.err, caplog.text):
        for fragment in fragments(token):
            assert fragment not in stream


def _escaped_echo(request: httpx.Request) -> httpx.Response:
    token = request.headers["authorization"].removeprefix("Bearer ")
    return json_response(400, {"detail": "bad token " + token.replace(".", "&#46;")})


def _split_echo(request: httpx.Request) -> httpx.Response:
    token = request.headers["authorization"].removeprefix("Bearer ")
    return json_response(400, {"detail": "bad token " + "\n".join(token[i : i + 9] for i in range(0, len(token), 9))})


def _half_echo(request: httpx.Request) -> httpx.Response:
    token = request.headers["authorization"].removeprefix("Bearer ")
    return json_response(400, {"detail": f"bad {token[: len(token) // 2]}"})


@pytest.mark.parametrize("echo", [_escaped_echo, _split_echo, _half_echo], ids=["html-escaped", "split-lines", "half"])
def test_PROD_WIRE_4_a_detail_that_echoes_the_token_in_any_form_prints_no_fragment(capsys, caplog, echo):
    token = fake_token()
    edge = Edge(token=token, override=lambda r: echo(r) if label(r) == "intake" else None)

    with caplog.at_level("DEBUG"):
        code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0 and status_lines(out)[-1] == ("FAIL", "intake")
    assert "400" in fail_reason(out, "intake"), "the status is still reported"
    for stream in (out, err, caplog.text):
        for fragment in fragments(token):
            assert fragment not in stream, "a fragment of the token reached output or a log"


def test_PROD_WIRE_4_a_fail_reason_is_the_status_plus_a_short_detail_and_never_the_raw_body(capsys):
    token = fake_token()
    secret_body = "RAWBODY-" + uuid.uuid4().hex
    bodies = {
        "json-other-fields": json_response(500, {"trace": secret_body, "code": "boom", "items": [secret_body]}),
        "html": httpx.Response(502, text=f"<html><body>{secret_body}</body></html>"),
        "plain": httpx.Response(500, text=secret_body),
        "detail-list": json_response(422, {"detail": [{"msg": secret_body}]}),
        "detail-number": json_response(500, {"detail": 12345678}),
    }
    for name, response in bodies.items():
        edge = Edge(token=token, override=only("intake", lambda r, response=response: response))

        _, out, _ = run(capsys, edge, env={TOKEN_ENV: token})

        reason = fail_reason(out, "intake")
        assert str(response.status_code) in reason, name
        assert secret_body not in out, f"{name}: the raw body was printed"
        assert "12345678" not in out, f"{name}: a non-string detail was printed"

    edge = Edge(token=token, override=only("intake", lambda r: json_response(403, {"detail": "Sign in to use this."})))
    _, out, _ = run(capsys, edge, env={TOKEN_ENV: token})
    assert "403" in fail_reason(out, "intake") and "Sign in to use this." in fail_reason(out, "intake")

    edge = Edge(token=token, override=only("intake", lambda r: json_response(400, {"detail": "word " * 100})))
    _, out, _ = run(capsys, edge, env={TOKEN_ENV: token})
    printed = fail_reason(out, "intake").split(":", 1)[1].strip()
    assert 0 < len(printed) <= 120, len(printed)


# --- security round 1: the smoke approves only an in-app card ---------------------------------------------------------

REFUSED_CARD = "not an in-app card; the smoke approves nothing that leaves Tilo"


def gate_card(*, tier: str | None = "T1", recipients: list[str] | None = None, connector: str | None = None) -> dict:
    """A gate card as `contracts/card.schema.json` shapes it: `gate.risk_tier`, `gate.recipients`, `gate.action`."""
    action = {"type": "send_email", "connector": connector, "exact": "Send it.", "item": None, "destination": None}
    return {
        "id": "c_smoke",
        "kind": "gate",
        "options": [{"id": "approve"}, {"id": "hold"}],
        "gate": {
            "id": "g_1",
            "action": action,
            "recipients": recipients or [],
            "irreversible": False,
            "risk_tier": tier,
        },
    }


def _with_gate(**changes: object) -> dict:
    card = gate_card()
    card["gate"] = {**card["gate"], **changes}
    return card


OUTBOUND_CARDS = {
    "t3": gate_card(tier="T3"),
    "t3-with-recipient": gate_card(tier="T3", recipients=["new.person@example.com"]),
    "email-recipient": gate_card(tier="T1", recipients=["someone@example.com"]),
    "whatsapp-connector": gate_card(tier="T1", connector="whatsapp"),
    "email-connector": gate_card(tier="T2", connector="gmail"),
    "drive-connector": gate_card(tier="T1", connector="google_drive"),
    "no-tier": gate_card(tier=None),
    "gate-not-an-object": {**gate_card(), "gate": "T1"},
    "gate-missing": {k: v for k, v in gate_card().items() if k != "gate"},
    "gate-null": {**gate_card(), "gate": None},
    "action-missing": _with_gate(action=None),
    "recipients-not-a-list": _with_gate(recipients="a@example.com"),
    "item-pinned": _with_gate(action={**gate_card()["gate"]["action"], "item": {"id": "a_1"}}),
    "destination-set": _with_gate(action={**gate_card()["gate"]["action"], "destination": "thread-1"}),
}


@pytest.mark.parametrize("case", list(OUTBOUND_CARDS))
def test_PROD_WIRE_4_a_gate_card_that_could_send_something_out_is_never_answered(capsys, case):
    token = fake_token()
    card = OUTBOUND_CARDS[case]
    edge = Edge(token=token, override=only("gate-card", lambda r: json_response(200, [card])))

    code, out, err = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0
    assert fail_reason(out, "gate-card") == REFUSED_CARD
    assert status_lines(out)[-1] == ("FAIL", "gate-card")
    assert not [r for r in edge.requests if r.url.path.endswith("/answer")], "no answer request is made"
    assert not edge.answered
    only_requests_up_to(edge, "gate-card")
    assert token not in out + err


def test_PROD_WIRE_4_an_outbound_card_among_others_is_refused_and_a_question_card_is_skipped(capsys):
    token = fake_token()
    cards = [{"id": "c_q", "kind": "question", "options": []}, gate_card(tier="T3")]
    edge = Edge(token=token, override=only("gate-card", lambda r: json_response(200, cards)))

    code, out, _ = run(capsys, edge, env={TOKEN_ENV: token})

    assert code != 0 and fail_reason(out, "gate-card") == REFUSED_CARD and not edge.answered


# --- the script's source: only what a browser could use -------------------------------------------------------


def test_PROD_WIRE_4_the_script_uses_httpx_with_a_timeout_and_no_backdoor_live_switch_or_file_write():
    src = SCRIPT.read_text(encoding="utf-8")
    code = re.sub(r"(?m)^\s*#.*$", "", src)

    assert re.search(r"^\s*import httpx\b|^\s*from httpx\b", code, re.M), "HTTP is httpx"
    assert re.search(r"timeout\s*=", code), "every HTTP call has a timeout"
    assert not re.search(r"\brequests\b|urllib\.request|\bsocket\b|aiohttp", code), "no other HTTP stack"
    live = "LIVE"  # spelled apart: the repo's guard hook looks for the literal switch
    assert not re.search(rf"{live}\s*['\"]?\s*[=:]", code) and f"environ['{live}']" not in code, (
        "never sets the live switch"
    )
    assert "TILO_API_DEV" not in code and "/internal/" not in code, "no dev-mode or internal route: browser-only calls"
    assert not re.search(r"open\([^)]*['\"][wa]b?['\"]|write_text|write_bytes", code), "nothing is written to disk"
    assert "follow_redirects=True" not in code.replace(" ", ""), "redirects are never followed"


# --- the recipe -----------------------------------------------------------------------------------------------

NEEDS_JUST = pytest.mark.skipif(shutil.which("just") is None, reason="just is not installed")
GOOD_URLS = (
    "https://tilo-api-abc123def4-as.a.run.app",
    "https://tilo-api-4k2j9x7q1a-as.a.run.app",
    "https://tilo-api-123456789012.asia-southeast1.run.app",
)


def _just_text() -> str:
    return (REPO_ROOT / "justfile").read_text(encoding="utf-8")


def _recipe() -> str:
    text = _just_text()
    header = re.search(r"^smoke-dev\b[^\n:]*:[^\n]*$", text, re.M)
    assert header, "justfile must define a `smoke-dev` recipe"
    lines = text[header.start() :].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        if line and not line[0].isspace():
            break
        body.append(line)
    return "\n".join(body)


def _fake_bin(tmp_path: pathlib.Path) -> tuple[dict[str, str], pathlib.Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True)
    log = tmp_path / "calls.log"
    for name in ("uv", "python", "python3", "pnpm", "node"):
        exe = bindir / name
        exe.write_text('#!/bin/sh\nprintf "%s %s\\n" "$0" "$*" >> "$TILO_FAKE_CALL_LOG"\n')
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    env = dict(os.environ, TILO_FAKE_CALL_LOG=str(log), PATH=str(bindir) + os.pathsep + os.environ["PATH"])
    return env, log


def test_PROD_WIRE_4_the_smoke_dev_recipe_takes_a_url_and_checks_it_in_just_before_any_shell():
    recipe = _recipe()
    header = recipe.splitlines()[0]
    code = re.sub(r"(?m)^\s*#.*$", "", recipe)

    assert header.split(":")[0].split()[1:] in (['url=""'], ["url=''"]), header
    interpolations = " ".join(ln for ln in code.splitlines() if "{{" in ln)
    assert "error(" in interpolations and "=~" in interpolations, "the url check is `{{ if url =~ ... error() }}`"
    assert "tilo-api-" in interpolations and "-as" in interpolations, "the check is pinned to tilo-api's own service"
    first_command = next(ln for ln in code.splitlines()[1:] if ln.strip())
    assert "error(" in first_command, "the check is on the first command line"
    assert "scripts/smoke_dev.py" in code
    commands = [ln.strip() for ln in code.splitlines()[1:] if ln.strip()]
    assert all(c.lstrip("@-").split()[0] in ("uv", "python", "pnpm", "node") for c in commands), commands
    assert not re.search(r"\$\(|`|--token|Bearer|TILO_SMOKE_ID_TOKEN\s*=", code), (
        "the token never goes through the recipe"
    )
    assert "tilo-demo" not in code


@NEEDS_JUST
def test_PROD_WIRE_4_dry_run_of_smoke_dev_with_a_cloud_run_url_runs_the_script_against_it():
    for url in GOOD_URLS:
        proc = subprocess.run(
            ["just", "--justfile", str(REPO_ROOT / "justfile"), "--dry-run", "smoke-dev", url],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=REPO_ROOT,
        )

        out = proc.stdout + proc.stderr
        assert proc.returncode == 0, out
        assert "scripts/smoke_dev.py" in out and url in out


@NEEDS_JUST
def test_PROD_WIRE_4_smoke_dev_refuses_an_empty_or_bad_url_before_any_shell_runs(tmp_path):
    env, log = _fake_bin(tmp_path / "anchor")
    ok = subprocess.run(
        ["just", "--justfile", str(REPO_ROOT / "justfile"), "--dry-run", "smoke-dev", GOOD_URLS[0]],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert ok.returncode == 0, "anchor: a good url is accepted, so the refusals below mean something"

    reached = []
    for i, bad in enumerate(BAD_URLS):
        env, log = _fake_bin(tmp_path / f"bad{i}")
        canary = tmp_path / f"bad{i}" / "pwned"
        payload = bad.replace("touch pwned", f"touch {canary}")
        proc = subprocess.run(
            ["just", "--justfile", str(REPO_ROOT / "justfile"), "smoke-dev", payload],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        if proc.returncode == 0 or log.exists() or canary.exists():
            reached.append(bad)
    assert not reached, f"smoke-dev let these through to a shell or a script: {reached!r}"


def test_PROD_WIRE_4_no_workflow_or_cloud_build_config_runs_smoke_dev_and_the_gate_does_not_depend_on_it():
    offenders = []
    candidates = [*REPO_ROOT.glob(".github/**/*.yml"), *REPO_ROOT.glob(".github/**/*.yaml")]
    candidates += [*REPO_ROOT.glob("cloudbuild*.yaml"), *REPO_ROOT.glob("*/cloudbuild*.yaml")]
    assert candidates, "the workflow files exist"
    for path in candidates:
        if re.search(r"smoke[-_]dev", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        f"a deployed smoke needs a person's token and a real deployment; CI must never run it: {offenders}"
    )
    text = _just_text()
    for gate in ("check", "check-fast", "test"):
        header = re.search(rf"^{gate}:.*$", text, re.M).group(0)
        assert "smoke" not in header, f"`just {gate}` must not depend on the deployed smoke"
    for recipe in ("check-fast", "test", "check"):
        body = text[re.search(rf"^{recipe}:", text, re.M).start() :].split("\n\n")[0]
        assert "smoke-dev" not in body and "smoke_dev" not in body
