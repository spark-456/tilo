"""Shared helpers for the PL-LIVE-E2E tests (issue #340; PRD 6.4 PL-02/PL-03, 6.6 EFF-01, 9.4 HR-1, 16.1).

Nothing here talks to a network and nothing makes a paid call. A bank case is turned into a fake "live" model
(`CaseFakeModel`): the Director's brief, approaches and plan come from the case's own `director` script (the same data
the GEN-a bank scripts), every other role answers with a small synthetic reply, and every reply carries fixed token
usage so cost is exact. The fake is handed to the code under test through its `live_provider_factory` seam, so the real
Router, the real record-and-replay provider and the real pipeline run on top of it. The live switch is only ever set
inside a test's own patched environment (`env()`), never for real; the provider is always the fake.

API pinned for the implementer: `API_PL_LIVE_E2E.md` in this directory.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import json
import logging
import math
import os
import re
import socket
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import yaml
from tilo_evals.bank import BankCase, load_bank
from tilo_evals.scripted import standard_approaches
from tilo_providers.errors import RequestError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, PriceQuote
from tilo_providers.safety import FakeSafetyProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
BANK = REPO_ROOT / "evals" / "bank"
REAL_PRICES = REPO_ROOT / "config" / "prices.yaml"
REAL_MODELS = REPO_ROOT / "config" / "models.yaml"
MODULE = "tilo_evals.live_e2e"
SCRIPT = REPO_ROOT / "evals" / "scripts" / "live_e2e.py"
COMMITTED_RECORDINGS = (
    BANK / "live"
)  # evals/bank/live/<case id>/model-recordings/<role>/<key>.json (NOT `recordings/`: gitignored)
PROJECT = "demo-live-e2e-project"  # made up; the real one comes from the user's own environment

ENV_KEYS_CLEARED = (
    "LIVE",
    "TILO_RECORD",
    "CI",
    "GITHUB_ACTIONS",
    "K_SERVICE",
    "CLOUD_RUN_JOB",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_LOCATION",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "TILO_MODELS_FILE",
    "TILO_API_DEV",
)

# Text formats pinned in API_PL_LIVE_E2E.md.
ESTIMATE_RE = re.compile(
    r"^estimate credits_low=(?P<low>\d+\.\d{4}) credits_high=(?P<high>\d+\.\d{4}) cap=(?P<cap>\d+\.\d{4})$"
)
MODE_RE = re.compile(r"^mode=(?P<mode>live|replay|dry-run) case=(?P<case>\S+)$")
OUTCOME_RE = re.compile(r"^outcome=(?P<outcome>[a-z_]+) events=(?P<events>\d+)$")
ROW_RE = re.compile(
    r"^stage=(?P<stage>[a-z_]+) role=(?P<role>[a-z_]+) profile=(?P<profile>\S+) calls=(?P<calls>\d+) "
    r"tokens_in=(?P<tin>\d+) tokens_out=(?P<tout>\d+) credits=(?P<credits>\d+\.\d{4}) "
    r"latency_ms=(?P<latency>\d+(?:\.\d+)?)$"
)
TOTAL_RE = re.compile(r"^total credits=(?P<credits>\d+\.\d{4}) cap=(?P<cap>\d+\.\d{4})$")
CHECK_RE = re.compile(r"^check=(?P<name>[a-z_]+) findings=(?P<n>\d+)$")
REFUSED_RE = re.compile(r"^REFUSED (?P<code>[a-z_]+): (?P<message>.+)$")
STOP_RE = re.compile(r"^STOP (?P<outcome>[a-z_]+): (?P<message>.+)$")

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"\+\d[\d ()-]{7,}\d|\(\d{2,4}\)[ -]?\d{3,4}[ -]?\d{3,4}|\b\d{3}[ -]\d{3}[ -]\d{4}\b")
SECRET_RE = re.compile(r"ya29\.[\w.-]+|AIza[\w-]{20,}|(?i:bearer)\s+[\w.-]{10,}|sk-[\w-]{16,}")


def fake_secret(kind: str) -> str:
    """Fake credentials, assembled at runtime so no secret-shaped literal sits in the source."""
    if kind == "access_token":
        return "ya" + "29." + "FakeTokenAbc123_" + "def456-ghi789" * 2
    if kind == "bearer":
        return "Bearer " + "fakeBearer" + "Value0123456789"
    if kind == "api_key":
        return "AI" + "za" + "Fake" + "KeyValue0123456789abcdefghijklmn"
    if kind == "email":
        return "jo.tester" + "@" + "example.org"
    if kind == "phone":
        return "+" + "44 20 7946 0958"
    raise ValueError(kind)


def leak_text() -> str:
    """What a careless model reply could echo back: an email, a phone number, a token and an Authorization header."""
    return (
        f"Contact {fake_secret('email')} or {fake_secret('phone')}. token {fake_secret('access_token')}. "
        f"Authorization: {fake_secret('bearer')}"
    )


# ---------------------------------------------------------------------------------------------------------
# Environment, network guard, module under test
# ---------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def env(**overrides: str) -> Iterator[None]:
    """A clean process environment (no live switch, no CI or Cloud Run markers, no keys) plus `overrides`; restored
    on exit. This is the only place a test sets the live switch, and only inside its own patched environment."""
    with mock.patch.dict(os.environ, {}, clear=False):
        for key in ENV_KEYS_CLEARED:
            os.environ.pop(key, None)
        os.environ["CLOUDSDK_CONFIG"] = str(Path(tempfile.gettempdir()) / "tilo-test-no-gcloud-config")
        os.environ.update(overrides)
        if os.environ.get("LIVE") == "1":  # match the checked-in global price sheet (LIVE-GLOBAL-1)
            os.environ.setdefault("GOOGLE_LOCATION", "global")
        yield


@pytest.fixture(autouse=True)
def network_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """EFF-01: no test here may reach any host but loopback (the in-process API client talks to itself)."""
    real_connect = socket.socket.connect
    real_getaddrinfo = socket.getaddrinfo

    def connect(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"PL_LIVE_E2E tests must not connect to {host!r}")
        return real_connect(self, address)

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        if host not in ("127.0.0.1", "::1", "localhost", None):
            raise RuntimeError(f"PL_LIVE_E2E tests must not resolve {host!r}")
        return real_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)


def live_e2e() -> Any:
    """The module under test, imported inside each test so a missing module fails that test, not collection."""
    return importlib.import_module(MODULE)


class SpyEnviron(Mapping[str, str]):
    """A read-only environ that records every key the code under test looks at."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.touched: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.touched.add(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        self.touched.add("<iteration>")
        return iter(self._values)

    def __len__(self) -> int:
        self.touched.add("<len>")
        return len(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        self.touched.add(key)
        return self._values.get(key, default)

    def __contains__(self, key: object) -> bool:
        self.touched.add(str(key))
        return key in self._values


# ---------------------------------------------------------------------------------------------------------
# Fake live model scripted from a bank case
# ---------------------------------------------------------------------------------------------------------


def instance_for(schema: Mapping[str, Any], root: Mapping[str, Any] | None = None, depth: int = 0) -> Any:
    """A minimal instance that satisfies a JSON Schema (enough for the schemas the pipeline sends)."""
    root = root or schema
    if depth > 8:
        return None
    if "$ref" in schema:
        node: Any = root
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            node = node[part]
        return instance_for(node, root, depth + 1)
    for key in ("const",):
        if key in schema:
            return schema[key]
    if "enum" in schema:
        return schema["enum"][0]
    for key in ("oneOf", "anyOf"):
        if key in schema:
            return instance_for(schema[key][0], root, depth + 1)
    if "allOf" in schema:
        merged: dict[str, Any] = {}
        for part in schema["allOf"]:
            value = instance_for(part, root, depth + 1)
            if isinstance(value, dict):
                merged.update(value)
        return merged
    kind = schema.get("type")
    kind = kind[0] if isinstance(kind, list) else kind
    if kind == "object" or "properties" in schema:
        props = schema.get("properties", {})
        return {
            name: instance_for(props[name], root, depth + 1) for name in schema.get("required", props) if name in props
        }
    if kind == "array":
        item = instance_for(schema.get("items", {}), root, depth + 1)
        return [item for _ in range(schema.get("minItems", 1 if schema.get("items") else 0))]
    if kind == "string":
        return "ok" * max(1, math.ceil(schema.get("minLength", 2) / 2))
    if kind in ("integer", "number"):
        return max(schema.get("minimum", 0), 1)
    if kind == "boolean":
        return True
    return None


def request_kind(request: GenerateRequest) -> str:
    """brief / approaches / plan by `response_schema`, like the scripted Director; else `schema` or `text`."""
    properties = (request.response_schema or {}).get("properties", {})
    if "ambiguous_fields" in properties:
        return "brief"
    if "approaches" in properties:
        return "approaches"
    if "units" in properties:
        return "plan"
    return "schema" if request.response_schema else "text"


@dataclass
class FakeCall:
    role: str
    profile_id: str
    kind: str
    credits: float


@dataclass
class FakeWorld:
    """What every fake provider of one run shares: the case script, usage, price, and a log of what was asked."""

    script: dict[str, Any]
    usage: tuple[int, int] = (1000, 500)
    delay_s: float = 0.01
    per_million_usd: float = 1.0  # must match the prices file the run is given
    credit_usd: float = 0.005
    leak: str = ""
    fail_roles: dict[str, Exception] = field(default_factory=dict)
    calls: list[FakeCall] = field(default_factory=list)
    built: list[tuple[str, str]] = field(default_factory=list)
    stdout_at_first_call: str | None = None

    def factory(self, role: str, profile_id: str) -> ModelProvider:
        self.built.append((role, profile_id))
        return CaseFakeModel(self, role, profile_id)

    @property
    def spent(self) -> float:
        return math.fsum(call.credits for call in self.calls)

    def call_credits(self) -> float:
        tin, tout = self.usage
        return ((tin + tout) * self.per_million_usd / 1e6) / self.credit_usd

    def roles_called(self) -> set[str]:
        return {call.role for call in self.calls}


class CaseFakeModel(ModelProvider):
    """The stand-in for the live Vertex provider of one (role, profile). Not `dev_only`: it is handed in through the
    seam, so the live gate and the provider layer's own checks run exactly as they would for the real adapter.
    `SYNTHETIC_FAKE` is what `record_with_fake` (issue #367) looks for before it takes a provider."""

    SYNTHETIC_FAKE = True

    def __init__(self, world: FakeWorld, role: str, profile_id: str) -> None:
        self._world, self._role, self._profile_id = world, role, profile_id

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        world = self._world
        if world.stdout_at_first_call is None:
            out = sys.stdout
            world.stdout_at_first_call = out.getvalue() if isinstance(out, io.StringIO) else ""
        time.sleep(world.delay_s)
        kind = request_kind(request)
        world.calls.append(FakeCall(self._role, self._profile_id, kind, world.call_credits()))
        if (error := world.fail_roles.get(self._role)) is not None:
            raise error
        if kind in ("brief", "approaches", "plan"):
            reply = world.script.get(kind)
            if reply is None:  # a Director that could not answer: the pipeline must stop honestly
                raise RequestError(f"the script gives no {kind} reply")
            if kind == "approaches" and reply == "standard":
                deliverables = (world.script.get("brief") or {}).get("deliverables") or [{}]
                reply = standard_approaches(str(deliverables[0].get("format", "markdown")))
            if kind == "brief" and world.leak:
                reply = {**reply, "goal": f"{reply['goal']} {world.leak}"}
            text = json.dumps(reply, sort_keys=True)
        elif kind == "schema":
            text = json.dumps(instance_for(request.response_schema or {}), sort_keys=True)
        else:
            text = f"Synthetic {self._role} reply for the test. {world.leak}".strip()
        tin, tout = world.usage
        usage = {"input_tokens": tin, "output_tokens": tout, "total_tokens": tin + tout}
        return GenerateResponse(text=text, profile_id=self._profile_id, usage=usage)

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        raise RequestError("the fake live model makes no embeddings")

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def capabilities(self) -> set[Capability]:
        return {Capability.JSON, Capability.TOOLS, Capability.THINKING}

    def price(self) -> PriceQuote:
        return PriceQuote(input=self._world.per_million_usd, output=self._world.per_million_usd)

    def redact(self, text: str) -> str:
        return text  # the code under test must redact; the fake does nothing for it


# ---------------------------------------------------------------------------------------------------------
# Files: prices, bank copies
# ---------------------------------------------------------------------------------------------------------


def write_prices(
    tmp_path: Path,
    *,
    per_million: float = 1.0,
    credit_usd: float = 0.005,
    status: str = "set",
    name: str = "prices.yaml",
) -> Path:
    """A copy of config/prices.yaml for tests only: every profile costs `per_million` US$ per million tokens, input
    and output alike (conspicuously fake), and 1 credit = `credit_usd`. With the default fake usage of 1000 in and 500
    out one call costs 0.3 credits per US$1 of price."""
    raw = yaml.safe_load(REAL_PRICES.read_text(encoding="utf-8"))
    raw["status"] = status
    raw["credit_usd"] = credit_usd
    raw["source"] = "Test fixture only. Not a real price page."
    raw.pop("region", None)  # a fixture sheet is quoted for no location (ADR-0029 decision 3)
    for profile_id, real in raw["profiles"].items():
        raw["profiles"][profile_id] = {"input": per_million, "output": per_million}
        if "unit_price" in real:  # the search role wants a query unit price (ADR-0029 decision 7): a fake fee
            raw["profiles"][profile_id]["unit_price"] = {"unit": real["unit_price"]["unit"], "per_1k": per_million}
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def bank_case(case_id: str, bank: Path = BANK) -> BankCase:
    return next(case for case in load_bank(bank) if case.id == case_id)


def write_bank(tmp_path: Path, case_id: str, *, new_id: str | None = None, brief: str | None = None) -> Path:
    """A bank directory under `tmp_path` holding one case copied from evals/bank, optionally under another id or with
    another brief text (so every prompt built from it changes)."""
    raw = yaml.safe_load((BANK / f"{case_id}.yaml").read_text(encoding="utf-8"))
    if new_id:
        raw["id"] = new_id
    if brief:
        raw["brief"] = brief
    target = tmp_path / "bank"
    target.mkdir(exist_ok=True)
    (target / f"{raw['id']}.yaml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------------------------------------
# Running the module under test
# ---------------------------------------------------------------------------------------------------------


@dataclass
class Invocation:
    code: int
    out: str
    err: str
    logs: str

    @property
    def everything(self) -> str:
        return "\n".join((self.out, self.err, self.logs))

    def out_lines(self) -> list[str]:
        return [line for line in self.out.splitlines() if line.strip()]

    def err_lines(self) -> list[str]:
        return [line for line in self.err.splitlines() if line.strip()]

    def rows(self) -> list[re.Match[str]]:
        return [m for line in self.out.splitlines() if (m := ROW_RE.match(line))]

    def mode(self) -> re.Match[str] | None:
        return next((m for line in self.out.splitlines() if (m := MODE_RE.match(line))), None)

    def outcome(self) -> re.Match[str] | None:
        return next((m for line in self.out.splitlines() if (m := OUTCOME_RE.match(line))), None)

    def total(self) -> re.Match[str] | None:
        return next((m for line in self.out.splitlines() if (m := TOTAL_RE.match(line))), None)

    def checks(self) -> dict[str, int]:
        return {m["name"]: int(m["n"]) for line in self.out.splitlines() if (m := CHECK_RE.match(line))}


@contextlib.contextmanager
def _capture_logs() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield stream
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


def invoke_main(
    argv: list[str],
    *,
    environ: Mapping[str, str] | None = None,
    world: FakeWorld | None = None,
    safety: bool = True,
) -> Invocation:
    """`tilo_evals.live_e2e.main(argv, ...)` in process, capturing stdout, stderr and logging. `world` supplies the
    fake live provider; `safety` supplies the dev safety screen (the `safety` role has no live adapter yet)."""
    module = live_e2e()
    kwargs: dict[str, Any] = {}
    if world is not None:
        kwargs["live_provider_factory"] = world.factory
    if safety:
        kwargs["safety"] = FakeSafetyProvider()
    if environ is not None:
        kwargs["environ"] = environ
    out, err = io.StringIO(), io.StringIO()
    with _capture_logs() as logs, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(argv, **kwargs)
    return Invocation(code, out.getvalue(), err.getvalue(), logs.getvalue())


def cli_args(
    tmp_path: Path,
    *,
    case: str = "B-007",
    bank: Path = BANK,
    prices: Path | None = None,
    recordings: Path | None = None,
    max_credits: float | None = None,
    mode: str = "live",
    extra: tuple[str, ...] = (),
) -> list[str]:
    args = ["--case", case, "--bank-dir", str(bank), "--prices-file", str(prices or write_prices(tmp_path))]
    args += ["--recordings-dir", str(recordings or tmp_path / "recordings-out")]
    if max_credits is not None:
        args += ["--max-credits", str(max_credits)]
    if mode == "replay":
        args.append("--replay")
    elif mode == "dry-run":
        args.append("--dry-run")
    return [*args, *extra]


def world_for(case_id: str = "B-007", bank: Path = BANK, **fields: Any) -> FakeWorld:
    return FakeWorld(script=bank_case(case_id, bank).director, **fields)


def live_run(
    tmp_path: Path,
    *,
    case: str = "B-007",
    bank: Path = BANK,
    world: FakeWorld | None = None,
    per_million: float = 1.0,
    credit_usd: float = 0.005,
    max_credits: float | None = None,
    record: bool = False,
    recordings: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
) -> tuple[Invocation, FakeWorld, Path]:
    """One CLI run in live mode with the fake provider: the live switch is set only inside a patched environment.
    Returns (invocation, world, recordings dir)."""
    prices = write_prices(tmp_path, per_million=per_million, credit_usd=credit_usd)
    world = world or world_for(case, bank, per_million_usd=per_million, credit_usd=credit_usd)
    recordings = recordings or tmp_path / "recordings-out"
    values = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
    if record:
        values["TILO_RECORD"] = "1"
    values.update(extra_env or {})
    argv = cli_args(
        tmp_path, case=case, bank=bank, prices=prices, recordings=recordings, max_credits=max_credits, extra=extra_args
    )
    with env(**values):
        invocation = invoke_main(argv, world=world)
    return invocation, world, recordings


def replay_run(
    tmp_path: Path,
    recordings: Path,
    *,
    case: str = "B-007",
    bank: Path = BANK,
    per_million: float = 1.0,
    prices: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
) -> tuple[Invocation, FakeWorld]:
    """One CLI `--replay` run: no live switch, and a live provider factory that would be counted if ever used."""
    prices = prices or write_prices(tmp_path, per_million=per_million)
    world = world_for(case, bank, per_million_usd=per_million)
    argv = cli_args(
        tmp_path, case=case, bank=bank, prices=prices, recordings=recordings, mode="replay", extra=extra_args
    )
    with env(**(extra_env or {})):
        invocation = invoke_main(argv, world=world)
    return invocation, world


def recording_files(recordings: Path) -> list[Path]:
    return sorted((recordings / "model-recordings").glob("*/*.json"))


def event_types(events: list[dict[str, Any]]) -> list[str]:
    return [e["type"] for e in events]


def is_subsequence(wanted: list[str], seen: list[str]) -> bool:
    it = iter(seen)
    return all(any(item == candidate for candidate in it) for item in wanted)


def run_direct(
    tmp_path: Path,
    *,
    case: str = "B-007",
    bank: Path = BANK,
    world: FakeWorld | None = None,
    per_million: float = 1.0,
    max_credits: float | None = None,
    record: bool = False,
    recordings: Path | None = None,
) -> tuple[Any, FakeWorld]:
    """`run_live_e2e(...)` called directly (live mode, fake provider) to get the report object with its events."""
    module = live_e2e()
    prices = write_prices(tmp_path, per_million=per_million)
    world = world or world_for(case, bank, per_million_usd=per_million)
    values = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
    if record:
        values["TILO_RECORD"] = "1"
    kwargs: dict[str, Any] = {
        "case_id": case,
        "mode": "live",
        "bank_dir": bank,
        "prices_path": prices,
        "recordings_dir": recordings or tmp_path / "recordings-out",
        "live_provider_factory": world.factory,
        "safety": FakeSafetyProvider(),
    }
    if max_credits is not None:
        kwargs["max_credits"] = max_credits
    with env(**values):
        report = module.run_live_e2e(**kwargs)
    return report, world


def all_text(paths: list[Path]) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in paths)
