"""Helpers for the CL-LIVE-1 tests of `--real-connectors` in `just live-e2e` / `just live-run`. API pinned in
services/connectors/tests/API_CL_LIVE_1.md ("The run: evals"). Nothing here talks to a network or makes a paid call.

- Fake Google: `PlantedTransport` (GET reads with planted marker strings, records every request) and a real
  `TokenBroker` holding fake grants (tokens assembled at runtime), so the real `tilo_connectors.real.real_adapters`
  runs on top of fakes.
- `ConnectorFactory`: the zero-argument `real_connectors_factory` seam the run calls once the guards pass. It builds the
  adapters through the real factory, wraps each in a spy (counts `sent` reads and write-door attempts) and reads from
  each connector once, as an agent step would, so the planted content is in memory when the run goes on.
- Runners for both commands (`tilo_evals.live_e2e.main`, `tilo_evals.live_topic.main`) in process, with stdout, stderr
  and logging captured. The live switch is only ever set inside a patched environment (`lib.env`).
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import io
import json
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import _live_e2e_lib as lib
from tilo_providers.safety import FakeSafetyProvider

CONNECTORS_YAML = lib.REPO_ROOT / "config" / "connectors.yaml"
USER = "u_cl_live"
LIVE_ENV = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": lib.PROJECT}
SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose"],
    "google_drive": ["https://www.googleapis.com/auth/drive.file"],
    "google_calendar": ["https://www.googleapis.com/auth/calendar.readonly"],
}
TOPIC = "Write a one-page note for a small team on how to start composting at the office."
HOLD = ("", "y", "looks right", "n", "not now")  # recommended approach, yes, reason; the gate card: no, reason
PLAN_LINE = r"^real-connector (?P<id>[a-z_]+): scopes=(?P<scopes>\S+) mode=read_only$"


def real() -> Any:
    return importlib.import_module("tilo_connectors.real")


def _ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------------------------------------
# Fake Google


@dataclass
class Resp:
    status_code: int
    body: Any = None
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=lambda: {"content-type": "application/json"})

    def __post_init__(self) -> None:
        if not self.content:
            self.content = json.dumps(self.body).encode("utf-8")

    def json(self) -> Any:
        if self.body is None:
            raise ValueError("not JSON")
        return json.loads(json.dumps(self.body))


@dataclass(frozen=True)
class Markers:
    mail: str = field(default_factory=lambda: "mail" + secrets.token_hex(8))
    drive: str = field(default_factory=lambda: "drive" + secrets.token_hex(8))
    event: str = field(default_factory=lambda: "event" + secrets.token_hex(8))

    def all(self) -> list[str]:
        return [self.mail, self.drive, self.event]


class PlantedTransport:
    def __init__(self, tokens: set[str], markers: Markers) -> None:
        self._tokens, self.markers = tokens, markers
        self.requests: list[tuple[str, str, dict[str, str]]] = []

    def writes(self) -> list[tuple[str, str, dict[str, str]]]:
        return [r for r in self.requests if r[0] != "GET"]

    def request(self, method: str, url: str, *, params: Any = None, headers: Any = None, json: Any = None,
                content: bytes | None = None) -> Resp:  # fmt: skip
        sent = {str(k).lower(): str(v) for k, v in dict(headers or {}).items()}
        self.requests.append((method.upper(), url, sent))
        if sent.get("authorization", "")[len("Bearer ") :] not in self._tokens:
            return Resp(401, {"error": {"code": 401}})
        if method.upper() != "GET":
            return Resp(200, {"id": "wrote_" + secrets.token_hex(4)})
        text = base64.urlsafe_b64encode(self.markers.mail.encode()).decode("ascii")
        if url.endswith("/threads"):
            return Resp(200, {"threads": [{"id": "thr_1", "snippet": self.markers.mail}]})
        if url.endswith("/messages/msg_1"):
            payload = {"mimeType": "text/plain", "headers": [{"name": "Subject", "value": self.markers.mail}],
                       "body": {"data": text}}  # fmt: skip
            return Resp(200, {"id": "msg_1", "threadId": "thr_1", "payload": payload})
        if url.endswith("/files/file_1"):
            if dict(params or {}).get("alt") == "media":
                return Resp(200, content=self.markers.drive.encode(), body=None)
            meta = {"id": "file_1", "name": self.markers.drive, "mimeType": "text/plain", "size": "10"}
            return Resp(200, meta)
        if url.endswith("/events"):
            event = {"id": "ev1", "status": "confirmed", "summary": self.markers.event,
                     "start": {"dateTime": "2026-10-02T10:00:00+00:00"},
                     "end": {"dateTime": "2026-10-02T11:00:00+00:00"}}  # fmt: skip
            return Resp(200, {"items": [event], "nextSyncToken": "sync_1"})
        return Resp(404, {"error": {"code": 404}})


class _NoHttp:
    """The broker's token-endpoint client: a grant here never needs a refresh, so any call is a bug."""

    def post(self, url: str, *, data: Any) -> Any:
        raise AssertionError("no token endpoint call is expected in these tests")


# ---------------------------------------------------------------------------------------------------------
# Spy adapters and the factory seam


class SpyAdapter:
    """Wraps one real read-only adapter: counts reads of `sent` (the run's own check) and write-door attempts."""

    def __init__(self, inner: Any) -> None:
        self._inner, self.sent_reads, self.write_attempts = inner, 0, 0

    @property
    def id(self) -> str:
        return str(self._inner.id)

    @property
    def sent(self) -> Any:
        self.sent_reads += 1
        return self._inner.sent

    def execute_side_effect(self, entry: Any, grant: Any) -> Any:
        self.write_attempts += 1
        return self._inner.execute_side_effect(entry, grant)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class ConnectorFactory:
    """The `real_connectors_factory`: zero arguments, called by the run once every guard has passed."""

    def __init__(self, *, connect: Iterable[str] = tuple(SCOPES), raises: Exception | None = None,
                 environ: dict[str, str] | None = None, world: Any = None) -> None:  # fmt: skip
        from tilo_connectors._time import format_ts  # noqa: PLC0415
        from tilo_connectors.registry import load_registry  # noqa: PLC0415
        from tilo_connectors.tokens import FakeKms, InMemoryTokenStore, OAuthSettings, TokenBroker  # noqa: PLC0415

        self.markers, self.raises, self.environ, self.world = Markers(), raises, dict(environ or LIVE_ENV), world
        self.calls, self.model_calls_at_call = 0, []
        self.access, self.refresh, self.events = {}, {}, []
        self.client_secret = "cs" + secrets.token_hex(12)
        self.registry = load_registry(CONNECTORS_YAML)
        self.broker = TokenBroker(
            store=InMemoryTokenStore(), kms=FakeKms(), http=_NoHttp(),
            settings=OAuthSettings(client_id="cid" + secrets.token_hex(6), client_secret=self.client_secret),
            clock=lambda: format_ts(datetime.now(UTC)), emit=self.events.append,
        )  # fmt: skip
        for connector in connect:
            self.access[connector], self.refresh[connector] = "at" + secrets.token_hex(16), "rt" + secrets.token_hex(16)
            self.broker.store_tokens(USER, connector, {"access_token": self.access[connector],
                                     "refresh_token": self.refresh[connector], "scope": " ".join(SCOPES[connector]),
                                     "expires_in": 3599})  # fmt: skip
        self.transport = PlantedTransport(set(self.access.values()), self.markers)
        self.adapters: dict[str, SpyAdapter] = {}
        self.read_back: dict[str, Any] = {}

    def secrets_in_play(self) -> list[str]:
        return [*self.access.values(), *self.refresh.values(), self.client_secret]

    def __call__(self) -> dict[str, SpyAdapter]:
        from tilo_connectors.adapters import InMemoryPicks  # noqa: PLC0415

        self.calls += 1
        self.model_calls_at_call.append(len(self.world.calls) if self.world is not None else 0)
        if self.raises is not None:
            raise self.raises
        picks = InMemoryPicks()
        picks.add(USER, ["file_1"])
        built = real().real_adapters(self.broker, self.registry, self.transport, user_id=USER, environ=self.environ,
                                     picks=picks, emit=self.events.append)  # fmt: skip
        self.adapters = {k: SpyAdapter(v) for k, v in built.items()}
        now = datetime.now(UTC)  # one read per connector, as an agent step would: the content is now in memory
        self.read_back = {
            "mail": built["gmail"].get_message(USER, "msg_1"),
            "drive": built["google_drive"].download(USER, "file_1"),
            "events": built["google_calendar"].list_events(USER, page_size=5, time_min=_ts(now),
                                                           time_max=_ts(now + timedelta(days=1))),
        }  # fmt: skip
        return self.adapters


# ---------------------------------------------------------------------------------------------------------
# Running the two commands in process


@dataclass
class Ran:
    code: int
    out: str
    err: str
    logs: str
    world: lib.FakeWorld

    @property
    def everything(self) -> str:
        return "\n".join((self.out, self.err, self.logs))

    def refused(self) -> str | None:
        last = self.err.strip().splitlines()[-1] if self.err.strip() else ""
        match = lib.REFUSED_RE.match(last)
        return match["code"] if match else None


def run_e2e(tmp_path: Path, extra: Iterable[str], *, values: dict[str, str] | None = None, case: str = "B-005",
            factory: Callable[[], Any] | None = None, world: lib.FakeWorld | None = None,
            report_json: Path | None = None) -> Ran:  # fmt: skip
    """`tilo_evals.live_e2e.main` with the fake live provider. `values` is the patched process environment."""
    module = importlib.import_module("tilo_evals.live_e2e")
    world = world or lib.world_for(case)
    argv = lib.cli_args(tmp_path, case=case, prices=lib.write_prices(tmp_path), extra=tuple(extra))
    if report_json is not None:
        argv += ["--report-json", str(report_json)]
    kwargs: dict[str, Any] = {"live_provider_factory": world.factory, "safety": FakeSafetyProvider()}
    if factory is not None:
        kwargs["real_connectors_factory"] = factory
    return _invoke(module.main, argv, values, world, kwargs)


def run_topic(tmp_path: Path, extra: Iterable[str], *, values: dict[str, str] | None = None,
              answers: Iterable[str] = HOLD, factory: Callable[[], Any] | None = None,
              world: lib.FakeWorld | None = None) -> Ran:  # fmt: skip
    """`tilo_evals.live_topic.main` (`just live-run`) with the fake live provider and the fake safety screen."""
    module = importlib.import_module("tilo_evals.live_topic")
    world = world or lib.world_for("B-007")
    queue = list(answers)

    def read(_prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    argv = ["--topic", TOPIC, "--auto-answer", "--prices-file", str(lib.write_prices(tmp_path)), *extra]
    kwargs: dict[str, Any] = {"live_provider_factory": world.factory, "safety": FakeSafetyProvider(), "read": read,
                              "tty": lambda: True}  # fmt: skip
    if factory is not None:
        kwargs["real_connectors_factory"] = factory
    return _invoke(module.main, argv, values, world, kwargs)


def _invoke(main: Callable[..., int], argv: list[str], values: dict[str, str] | None, world: lib.FakeWorld,
            kwargs: dict[str, Any]) -> Ran:  # fmt: skip
    out, err = io.StringIO(), io.StringIO()
    with lib.env(**(values or {})), lib._capture_logs() as logs:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv, **kwargs)
    return Ran(code, out.getvalue(), err.getvalue(), logs.getvalue(), world)
