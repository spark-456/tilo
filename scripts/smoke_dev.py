#!/usr/bin/env python3
"""Deployed smoke of tilo-dev (PROD-WIRE-4): `just smoke-dev <api-url>`, or `python scripts/smoke_dev.py <api-url>`.

Drives a deployed tilo-api the way the web app's browser does, over HTTPS with `httpx`, and prints one line per step,
`PASS <step>` or `FAIL <step>: <reason>`, stopping at the first FAIL (exit 1; exit 0 only when every step ran).

Without a token (no sign-in needed):
  health        GET /health -> 200
  cors-allowed  a preflight from the Firebase Hosting origin to a gated route is granted for that origin only
  cors-denied   a preflight from a stranger's origin gets no grant
  gate-closed   a gated route with no token is refused (401 or 403): the gate fails closed
With TILO_SMOKE_ID_TOKEN (a Firebase ID token you paste into your own shell; replay mode, no paid call):
  intake, answers, approaches, approve, gate-card, answer-card, delivery: the dev flow of the web client, ending at
  the delivery of a completed run. It needs the Firebase ID-token verifier on the API (docs/deploy-dev.md).
Without it the run ends with `SKIP signed-in steps: set TILO_SMOKE_ID_TOKEN`.

Only what a browser could use: no test route, no switch to live mode, no paid call. The url must be tilo-api's own
Cloud Run url, the same check as `just deploy-web`, so a token never goes to another service. Redirects are never
followed, so a call cannot leave the given host. The token must be a JWT (checked before any request, refused with a
fixed message that does not echo it). It goes only in the `Authorization` header of the signed-in calls and is never
printed, logged or written to disk. A failure reason is the HTTP status plus at most a short `detail` string of a JSON
body (never the raw body, and withheld when it holds a run of the token, plain or escaped; only tilo-api, the token's
own audience, could re-encode it); an exception is reported by its type name only. The smoke answers a gate card
only when it cannot send anything out of Tilo.
"""

from __future__ import annotations

import html
import os
import re
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any
from urllib.parse import quote, unquote

import httpx

TOKEN_ENV = "TILO_SMOKE_ID_TOKEN"
WEB_ORIGIN = "https://essential-wares-510320-f0.web.app"  # the Firebase Hosting origin of the tilo-dev web app
STRANGER_ORIGIN = "https://stranger.example"
GATED_ROUTE = "/worlds"  # a gated GET route (SEC-15): a person's world list
BUDGET_CAP = 50  # the dev flow's small cap; replay mode spends nothing
CALL_TIMEOUT_S = 15.0
POLL_INTERVAL_S = 2.0
# Only tilo-api's own Cloud Run service (infra/modules/service names it `tilo-<key>`): a typo or a pasted link must
# never send a person's ID token to another service. The same two forms as the `deploy-web` and `smoke-dev` recipes
# (`-<hash>-as.a.run.app`, and `-<project-number>.asia-southeast1.run.app`); matched in full.
URL_PATTERN = re.compile(r"https://tilo-api-(?:[a-z0-9]+-as\.a\.run\.app|[0-9]+\.asia-southeast1\.run\.app)")
URL_REFUSED = "FAIL url: not tilo-api's Cloud Run url (https://tilo-api-<hash>-as.a.run.app or https://tilo-api-<project-number>.asia-southeast1.run.app)"
# A Firebase ID token is a JWT: three url-safe base64 segments. Anything else (a line-wrapped paste, a stray control
# character) is refused before any request, so a library error can never print a token it could not match.
TOKEN_SHAPE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
TOKEN_REFUSED = f"FAIL token: {TOKEN_ENV} is not a JWT"
CARD_REFUSED = "not an in-app card; the smoke approves nothing that leaves Tilo"
SKIP_LINE = f"SKIP signed-in steps: set {TOKEN_ENV}"
DETAIL_MAX = 120
WINDOW = 4  # a reason is withheld when it holds any run of this many characters of the token, however it is spelled
_BEARER = re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.I)


class Failed(Exception):
    """A step failed; the message is its reason, already safe to print."""


def _squash(text: str) -> str:
    """Lower-case letters and digits only, after undoing HTML and percent escapes: what is left of a token however a
    server dressed it up (escaped dots, line breaks, separators)."""
    plain = unquote(html.unescape(text))
    return "".join(ch for ch in plain.lower() if ch.isascii() and ch.isalnum())


def in_app_only(card: dict[str, Any]) -> bool:
    """True when answering a gate card cannot send anything out of Tilo (fields of contracts/card.schema.json): its
    tier is T1 or T2 (never T3), it has no recipient, and its action names no connector, item or destination. Every
    gate action names a connector today (CR-10), so a card of the real shape is refused; this guard must stay when
    adapters are wired (BQ-PW-4). Fail closed: a card with no gate details (missing, null, not an object) is refused."""
    gate = card.get("gate")
    if not isinstance(gate, dict) or gate.get("risk_tier") not in ("T1", "T2") or gate.get("recipients") != []:
        return False
    action = gate.get("action")
    if not isinstance(action, dict):
        return False
    return not action.get("connector") and action.get("item") is None and action.get("destination") is None


class Smoke:
    def __init__(self, base: str, client: httpx.Client, token: str | None, sleep: Callable[[float], None]) -> None:
        self.base, self.client, self.token, self.sleep = base, client, token, sleep
        self.windows = {s[i : i + WINDOW] for s in [_squash(token or "")] for i in range(len(s) - WINDOW + 1)}

    def safe(self, text: object) -> str:
        """Text a server sent, as one short printable line: never one that holds any run of the token."""
        raw = str(text)
        if any(w in _squash(raw) for w in self.windows):
            return "[withheld]"
        line = _BEARER.sub("Bearer [withheld]", " ".join(raw.split()))
        return "".join(ch if ch.isprintable() else "?" for ch in line)[:DETAIL_MAX]

    def detail(self, response: httpx.Response) -> str:
        """The short `detail` string of a JSON body, if there is one: never the raw body."""
        try:
            data = response.json()
        except ValueError:
            return ""
        value = data.get("detail") if isinstance(data, dict) else None
        return f": {self.safe(value)}" if isinstance(value, str) and value else ""

    def call(
        self, method: str, path: str, *, signed: bool = False, headers: Mapping[str, str] | None = None, **kw: Any
    ) -> httpx.Response:
        sent = {"X-Tilo-Channel": "web", **(headers or {})}
        if signed:
            sent["Authorization"] = f"Bearer {self.token}"
        try:
            return self.client.request(method, self.base + path, headers=sent, **kw)
        except (httpx.HTTPError, httpx.InvalidURL, UnicodeError, ValueError) as exc:
            raise Failed(type(exc).__name__) from None  # never the message: a library may echo the header value

    def refused(self, response: httpx.Response, wanted: str) -> Failed:
        return Failed(f"HTTP {response.status_code}, wanted {wanted}{self.detail(response)}")

    def body(self, response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            raise Failed(f"HTTP {response.status_code} with a body that is not JSON") from None

    def expect(self, response: httpx.Response, status: int) -> Any:
        if response.status_code != status:
            raise self.refused(response, str(status))
        return self.body(response)

    def poll(self, check: Callable[[], Any], what: str, timeout_s: float) -> Any:
        deadline = time.monotonic() + timeout_s
        while True:
            found = check()
            if found:
                return found
            if time.monotonic() >= deadline:
                raise Failed(f"no {what} within {timeout_s:g} s")
            self.sleep(POLL_INTERVAL_S)

    # --- unsigned steps -------------------------------------------------------------------------------------

    def health(self) -> None:
        self.expect(self.call("GET", "/health"), 200)

    def dependencies(self) -> None:
        # Cloud Run reserves /healthz; the alias exposes the same inventory.
        response = self.call("GET", "/health/deps")
        if response.status_code != 200:
            raise Failed("dependency configuration unavailable")
        try:
            data = response.json()
        except ValueError:
            raise Failed("invalid dependency configuration") from None
        kinds = {
            "api_store": {"firestore", "memory", "unconfigured", "invalid"},
            "artifacts_store": {"gcs", "unconfigured", "invalid"},
            "archive_store": {"gcs", "unconfigured", "invalid"},
            "skills_store": {"firestore", "memory", "unconfigured", "invalid"},
        }
        flags = {
            "firestore_project_configured",
            "artifacts_bucket_configured",
            "archive_bucket_configured",
            "connectors_url_configured",
            "live_mode",
        }
        if (
            not isinstance(data, dict)
            or set(data) != set(kinds) | flags
            or any(not isinstance(data[key], str) or data[key] not in values for key, values in kinds.items())
            or any(type(data[key]) is not bool for key in flags)
        ):
            raise Failed("invalid dependency configuration")

    def preflight(self, origin: str) -> httpx.Response:
        asked = {
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,x-tilo-channel",
        }
        return self.call("OPTIONS", GATED_ROUTE, headers=asked)

    def cors_allowed(self) -> None:
        response = self.preflight(WEB_ORIGIN)
        if response.status_code not in (200, 204):
            raise self.refused(response, "200 or 204")
        granted = response.headers.get("access-control-allow-origin")
        if granted != WEB_ORIGIN:
            raise Failed(f"Access-Control-Allow-Origin is {self.safe(granted)!r}, wanted the hosting origin exactly")
        if response.headers.get("access-control-allow-credentials", "").lower() == "true":
            raise Failed("credentials are allowed, wanted none")
        listed = {h.strip().lower() for h in response.headers.get("access-control-allow-headers", "").split(",")}
        if not {"authorization", "x-tilo-channel"} <= listed:
            raise Failed("Authorization and X-Tilo-Channel are not both allowed request headers")

    def cors_denied(self) -> None:
        response = self.preflight(STRANGER_ORIGIN)
        granted = response.headers.get("access-control-allow-origin")
        if granted is not None:
            raise Failed(f"Access-Control-Allow-Origin {self.safe(granted)!r} was sent to a stranger's origin")

    def gate_closed(self) -> None:
        response = self.call("GET", GATED_ROUTE)
        if response.status_code not in (401, 403):
            raise self.refused(response, "401 or 403 with no token")

    # --- signed-in steps ------------------------------------------------------------------------------------

    def text_id(self, data: Any, key: str) -> str:
        value = data.get(key) if isinstance(data, dict) else None
        if not isinstance(value, str) or not value:
            raise Failed(f"the answer has no {key}")
        return value

    def intake(self) -> dict[str, Any]:
        files = {"text": (None, "Prepare the weekly supplier summary.")}  # multipart, as the browser's form sends it
        data = self.expect(self.call("POST", "/intake", signed=True, files=files), 201)
        task_id = self.text_id(data, "task_id")
        questions = data.get("questions")
        if not isinstance(questions, list):
            raise Failed("the answer has no questions list")
        fields = [q.get("field") for q in questions if isinstance(q, dict)]
        if len(fields) != len(questions) or not all(isinstance(f, str) for f in fields):
            raise Failed("a question has no field")
        return {"task": f"/tasks/{quote(task_id, safe='')}", "fields": fields}

    def answers(self, task: str, fields: list[str]) -> None:
        body = {"answers": [{"field": f, "answer": None} for f in fields], "brief_edits": {}}  # every question skipped
        self.expect(self.call("POST", f"{task}/answers", signed=True, json=body), 200)

    def approaches(self, task: str) -> str:
        return self.text_id(self.expect(self.call("GET", f"{task}/approaches", signed=True), 200), "recommended")

    def approve(self, task: str, approach_id: str) -> str:
        body = {"approach_id": approach_id, "budget_cap": BUDGET_CAP}
        data = self.expect(self.call("POST", f"{task}/approve", signed=True, json=body), 200)
        return f"/worlds/{quote(self.text_id(data, 'world_id'), safe='')}"

    def gate_card(self, world: str, timeout_s: float) -> str:
        def gate() -> str | None:
            cards = self.expect(self.call("GET", f"{world}/cards", signed=True), 200)
            if not isinstance(cards, list):
                raise Failed("the answer is not a list of cards")
            for card in cards:
                if isinstance(card, dict) and card.get("kind") == "gate" and isinstance(card.get("id"), str):
                    if not in_app_only(card):
                        raise Failed(CARD_REFUSED)  # nothing is answered: the run stops here
                    return str(card["id"])
            return None

        return self.poll(gate, "gate card", timeout_s)

    def answer_card(self, world: str, card_id: str) -> None:
        data = self.expect(
            self.call(
                "POST", f"{world}/cards/{quote(card_id, safe='')}/answer", signed=True, json={"option": "approve"}
            ),
            200,
        )
        if not isinstance(data, dict) or data.get("outcome") != "answered":
            reason = data.get("reason") if isinstance(data, dict) else None
            raise Failed(f"the card was not answered{f': {self.safe(reason)}' if isinstance(reason, str) else ''}")

    def delivery(self, world: str, timeout_s: float) -> None:
        def delivered() -> bool:
            response = self.call("GET", f"{world}/delivery", signed=True)
            if response.status_code == 409:  # not until the run completes
                return False
            self.expect(response, 200)
            return True

        self.poll(delivered, "delivery", timeout_s)


def _report(step: str, action: Callable[[], Any]) -> tuple[bool, Any]:
    try:
        result = action()
    except Failed as failure:
        print(f"FAIL {step}: {failure}")
        return False, None
    print(f"PASS {step}")
    return True, result


def main(
    argv: Sequence[str],
    *,
    transport: httpx.BaseTransport | None = None,
    env: Mapping[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    timeout_s: float = 60.0,
) -> int:
    url = argv[0] if len(argv) == 1 else ""
    if not URL_PATTERN.fullmatch(url):
        print(URL_REFUSED)
        return 1
    raw = (os.environ if env is None else env).get(TOKEN_ENV) or ""
    token = raw if raw.strip() else None  # blank counts as unset
    if token is not None and not TOKEN_SHAPE.fullmatch(token):
        print(TOKEN_REFUSED)  # before any request, and without a word of the value
        return 1
    with httpx.Client(transport=transport, timeout=CALL_TIMEOUT_S, follow_redirects=False) as client:
        smoke = Smoke(url, client, token, sleep)
        for step, action in (
            ("health", smoke.health),
            ("dependencies", smoke.dependencies),
            ("cors-allowed", smoke.cors_allowed),
            ("cors-denied", smoke.cors_denied),
            ("gate-closed", smoke.gate_closed),
        ):
            if not _report(step, action)[0]:
                return 1
        if token is None:
            print(SKIP_LINE)
            return 0
        ok, intake = _report("intake", smoke.intake)
        if not ok:
            return 1
        task = intake["task"]
        if not _report("answers", lambda: smoke.answers(task, intake["fields"]))[0]:
            return 1
        ok, approach_id = _report("approaches", lambda: smoke.approaches(task))
        if not ok:
            return 1
        ok, world = _report("approve", lambda: smoke.approve(task, approach_id))
        if not ok:
            return 1
        ok, card_id = _report("gate-card", lambda: smoke.gate_card(world, timeout_s))
        if not ok or not _report("answer-card", lambda: smoke.answer_card(world, card_id))[0]:
            return 1
        return 0 if _report("delivery", lambda: smoke.delivery(world, timeout_s))[0] else 1


def hosted_main(argv: Sequence[str], *, transport: httpx.BaseTransport | None = None) -> int:
    """Signed-out Hosting, API and dependency configuration checks over HTTP.

    Demo Home/world verification belongs to the existing hosted Playwright smoke
    in playwright.hosted.config.ts; this command reports only its HTTP scope.
    """
    from smoke_unsigned import main as unsigned_main  # noqa: PLC0415

    unsigned_status = unsigned_main(argv, transport=transport)
    if unsigned_status == 1:
        print("FAIL hosted: signed-out Hosting, bundle, health or security check failed")
        return 1
    with httpx.Client(transport=transport, timeout=CALL_TIMEOUT_S, follow_redirects=False, trust_env=False) as client:

        def configured() -> bool:
            try:
                with client.stream("GET", argv[0] + "/health/deps", headers={"X-Tilo-Channel": "web"}) as response:
                    if response.status_code == 404:
                        print("NOT DEPLOYED dependency-configuration: HTTP 404; /health/deps is not deployed yet")
                        return False
                    if response.status_code != 200:
                        raise Failed(f"HTTP {response.status_code}, wanted 200")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise Failed("dependency response exceeds 64 KiB")
                    data = httpx.Response(200, content=bytes(body)).json()
            except (httpx.HTTPError, ValueError) as exc:
                raise Failed(f"dependency response could not be read ({type(exc).__name__})") from None
            if not isinstance(data, dict):
                raise Failed("dependency configuration is not an object")
            required = {
                "api_store": "firestore",
                "artifacts_store": "gcs",
                "archive_store": "gcs",
                "skills_store": "firestore",
                "firestore_project_configured": True,
                "artifacts_bucket_configured": True,
                "archive_bucket_configured": True,
                "live_mode": True,
            }
            for key, wanted in required.items():
                if type(data.get(key)) is not type(wanted) or data.get(key) != wanted:
                    raise Failed(f"{key} does not report the required deployed configuration")

            return True

        try:
            dependencies_present = configured()
        except Failed as failure:
            print(f"FAIL dependency-configuration: {failure}")
            return 1
        if dependencies_present:
            print("PASS dependency-configuration (configuration only, not readiness)")
    print("SKIP demo: Home and recorded world require the existing playwright.hosted.config.ts hosted smoke")
    if unsigned_status == 2 or not dependencies_present:
        print("NOT DEPLOYED hosted-http: required deployment endpoints are missing; demo unverified")
        return 1
    print("PASS hosted-http (signed-out HTTP checks only; demo unverified)")
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--unsigned"]:
        sys.exit(hosted_main(sys.argv[2:]))
    sys.exit(main(sys.argv[1:]))
