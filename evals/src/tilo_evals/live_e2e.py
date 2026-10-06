"""`just live-e2e`: one held-out bank case through the real pipeline, on real models only when the user says so
(issue #340, PL-LIVE-E2E; PRD 6.4 PL-02/PL-03, 6.6 EFF-01, 9.4 HR-1, 16.1 rule 4; interface: API_PL_LIVE_E2E.md).

The real `tilo-api` routes, planner, executor, policy engine and outbox run in process (intake, questions, approaches,
approve, plan, run with Leads, Writers and the Verifier, Narrator, delivery or an honest stop). Every model call goes
through the provider layer's `Router` by role; this module names no model and builds no Google client of its own. The
live provider (ADC only) is wrapped in `RecordReplayProvider`: with the user's `LIVE=1` it calls out, with
`TILO_RECORD=1` it also saves each reply (redacted, LF), and `--replay` and `--dry-run` never build a live provider.
Spend is bounded by the Router's budget (PL-03): nothing over the cap is ever sent. A provider's own error text is
never stored or printed, because it can echo a credential; the one exception is a rejected request (HTTP 400), whose
adapter-redacted reason is scrubbed again, cut to one line and 200 characters, as `vertex_smoke` does. Any other
status prints its code only.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Request
from tilo_harness.outputs import UnitOutput
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config, resolve_models_path
from tilo_providers.errors import ProviderError, QuotaError, RequestError
from tilo_providers.interfaces import Capability, GenerateRequest, GenerateResponse, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.replay import RecordReplayProvider, ReplayMissError, recording_key, redact_strings
from tilo_providers.router import BudgetExceededError, Router
from tilo_providers.safety import FakeSafetyProvider
from tilo_providers.vertex_smoke import MAX_REASON_CHARS, classify, scrubbed_server_text

from . import e2e_stand_ins
from .bank import BankCase, BankError, load_bank
from .bank_checks import CHECKS, Finding, check_case, terminal_honest
from .bank_run import Observation, drive

DEFAULT_MAX_CREDITS = 40.0  # credits (PRD 14.1); what a credit is worth in dollars is read from the prices file
HARD_MAX_CREDITS = 200.0
STAGES = ("intake", "approaches", "plan", "run", "narrate")
OUTCOME_CLASSES = frozenset(
    {"completed", "held_at_gate", "needs_answers", "refused", "failed", "stopped_at_cap", "replay_miss", "rejected"}
)
SAFETY_NOTE = (
    "trusted_bank_input (by design; Model Armor is the safety role's live adapter, FR-INT-02, #450)"  # BQ-LE2E-5
)
SYNTHETIC_MARKER = "SYNTHETIC"  # a file beside `model-recordings/`: a fake provider wrote them (BQ-LE2E-9)
FAKED = (  # what a run never does for real, printed with every report (HR-1: say what is not real)
    "safety screen: trusted bank input only, by design (Model Armor is the safety role's live adapter, "
    "FR-INT-02, #450)",
    "connectors and recipient: recording mocks; no real mailbox, chat or Drive write",
    "Verifier verdict: recorded in the unit's summary, not acted on",
    "must-ask judgement: a fixed 'nothing to ask' stand-in, no model call; the deterministic rules still ask",
)
PLANNING_NOTE = "planning credits come from this meter: the planning events carry 0 (#327)"
SCOPE_NOTE = "claim scope: structural pass rate (GEN-11), not output quality"

_REPO = Path(__file__).resolve().parents[3]
_OWNER = "u_live_e2e"
_UNIT_TIMEOUT_S = {"live": 600.0, "replay": 120.0}
_OUT = {
    "writer": 1024,
    "specialist": 1024,
    "verifier": 300,
    "lead": 400,
    "narrator": 600,
}  # output caps of our own calls
_DEFAULT_OUT = 1024  # the Router's default when neither the request nor the role gives one (BQ-63)
_DIRECTOR_OUT = 4096  # the Director's floor when its role sets no cap: thinking tokens count against it (BQ-LE2E-9)
_PROMPT_TOKENS, _UNITS, _DIRECTOR_RETRIES, _MAX_BEATS = 1500, (3, 8), 3, 8  # estimate assumptions; Narrator beats
_ROLE: ContextVar[str] = ContextVar("live_e2e_role")
_PERSONAL = re.compile(
    "|".join(
        (
            r"[\w.+-]+@[\w-]+\.[\w.-]+",  # an email address
            r"\+\d[\d ()-]{7,}\d|\(\d{2,4}\)[ -]?\d{3,4}[ -]?\d{3,4}|\b\d{3}[ -]\d{3}[ -]\d{4}\b",  # a phone number
            r"ya29\.[\w.-]+|AIza[\w-]{20,}|sk-[\w-]{16,}|(?i:bearer)\s+[\w.-]{10,}",  # a token or key
        )
    )
)


class LiveE2ERefused(Exception):
    """A precondition failed; nothing was sent."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(" ".join(message.split()))
        self.code = code


class TrustedInputRefused(ProviderError):
    """The trusted-bank-input screen refused a text: it never states the text itself."""


@dataclass
class Row:
    stage: str
    role: str
    profile: str
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    credits: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class Estimate:
    credits_low: float
    credits_high: float


@dataclass(frozen=True)
class StoryLine:
    text: str
    event_ids: list[str]


@dataclass
class LiveE2EReport:
    case_id: str
    mode: str
    cap_credits: float
    estimate: Estimate
    safety: str = SAFETY_NOTE
    outcome_class: str | None = None  # None: a dry run, nothing ran
    reason: str | None = None
    rows: list[Row] = field(default_factory=list)
    total_credits: float = 0.0
    events: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    checks_run: list[str] = field(default_factory=list)
    questions: int = 0
    answered: dict[str, str | None] = field(default_factory=dict)
    story_lines: list[StoryLine] = field(default_factory=list)
    side_effects: str = (
        "mock_only"  # the delivery and the gated send go to recording mocks, never a real mailbox or Drive
    )
    expected: str | None = None
    recordings: str | None = None  # replay only: "synthetic" (a fake provider wrote them) or "unmarked"
    story_note: str | None = None  # why the Narrator left no Story, as a code only

    @property
    def event_count(self) -> int:
        return len(self.events)

    def to_dict(self) -> dict[str, Any]:
        checks = {name: [f.detail for f in self.findings if f.check == name] for name in self.checks_run}
        return {
            "case_id": self.case_id, "mode": self.mode, "outcome_class": self.outcome_class, "reason": self.reason,
            "safety": self.safety, "cap_credits": self.cap_credits, "total_credits": self.total_credits,
            "event_count": self.event_count, "rows": [dataclasses.asdict(r) for r in self.rows], "checks": checks,
            "questions": self.questions, "answered": self.answered, "estimate": dataclasses.asdict(self.estimate),
            "story_lines": [dataclasses.asdict(s) for s in self.story_lines], "side_effects": self.side_effects,
            "faked": list(FAKED), "recordings": self.recordings, "story_note": self.story_note,
        }  # fmt: skip


def default_recordings_dir(case_id: str) -> Path:
    return _REPO / "evals" / "bank" / "live" / case_id  # never a folder called `recordings/`: gitignored


# --- the gate (EFF-01) ---------------------------------------------------------------------------------------------


def _gate(mode: str, env: Mapping[str, str], max_credits: float | None) -> None:
    """The refusals that need no file, in the order the interface pins; the live switch is looked at first of all."""
    live = mode == "live"
    if live and env.get("LIVE") != "1":
        raise LiveE2ERefused("live_not_enabled", "set LIVE to exactly 1 to make real (paid) calls; nothing was sent")
    if mode == "replay" and "1" in (env.get("LIVE"), os.environ.get("LIVE")):
        raise LiveE2ERefused("replay_with_live", "--replay never runs with the live switch on")
    both = (
        env,
        os.environ,
    )  # the live decision itself reads os.environ, so a caller's own environ never hides a marker
    if live and any(e.get("CI") or e.get("GITHUB_ACTIONS") for e in both):
        raise LiveE2ERefused("ci_refused", "a live run is refused in CI (CI or GITHUB_ACTIONS is set)")
    if live and any("K_SERVICE" in e or "CLOUD_RUN_JOB" in e for e in both):
        raise LiveE2ERefused(
            "deployed_refused", "a live run is refused when deployed (K_SERVICE or CLOUD_RUN_JOB is set)"
        )
    if max_credits is not None and not (math.isfinite(max_credits) and 0 < max_credits <= HARD_MAX_CREDITS):
        raise LiveE2ERefused("cap_out_of_range", f"--max-credits must be above 0 and at most {HARD_MAX_CREDITS:g}")
    if live:
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            if env.get(name) or os.environ.get(name):
                raise LiveE2ERefused("api_key_present", f"{name} is set; remove it, a live run uses ADC only")
        if not env.get("GOOGLE_CLOUD_PROJECT"):
            raise LiveE2ERefused("missing_project", "GOOGLE_CLOUD_PROJECT is not set")


def _load_config(
    models_path: Path | None, prices_path: Path | None, env: Mapping[str, str], extra_roles: tuple[str, ...] = ()
) -> ProvidersConfig:
    models = Path(models_path) if models_path else resolve_models_path(env=env)
    prices = Path(prices_path) if prices_path else _REPO / "config" / "prices.yaml"
    try:
        config = load_providers_config(models, prices)
    except ProviderConfigError as error:
        raise LiveE2ERefused("config_invalid", f"the models or prices file did not load: {error}") from None
    if config.prices.status != "set":
        raise LiveE2ERefused("prices_unset", "config/prices.yaml is unset: confirm the prices, then set status to set")
    needed = ("director", "lead", "specialist", "verifier", "writer", "narrator", *extra_roles)
    absent = [r for r in needed if r not in config.roles]
    if absent:
        raise LiveE2ERefused("config_invalid", f"the models file has no role {absent[0]!r}")
    return config


def _load_case(case_id: str, bank_dir: Path | None) -> BankCase:
    try:
        cases = load_bank(bank_dir if bank_dir else _REPO / "evals" / "bank")
    except BankError as error:
        raise LiveE2ERefused("config_invalid", f"the bank did not load: {error}") from None
    case = next((c for c in cases if c.id == case_id), None)
    if case is None:
        raise LiveE2ERefused("unknown_case", f"no bank case {case_id!r}")
    return case


# --- the estimate (before any call): the case, the role caps and the prices file only -----------------------------


def _output_cap(config: ProvidersConfig, role: str) -> int:
    """The output cap a call of `role` is sent with when its request names none: our own call's cap, else the role's
    configured one, else the Director's floor (the Router's 1024 includes thinking tokens and can cut a plan short)."""
    return (
        _OUT.get(role)
        or config.roles[role].max_output_tokens
        or (_DIRECTOR_OUT if role == "director" else _DEFAULT_OUT)
    )


def _estimate(config: ProvidersConfig, case: BankCase) -> Estimate:
    return _estimate_chars(config, len(case.brief) + sum(len(f["text"]) for f in case.files))


def _estimate_chars(config: ProvidersConfig, chars: int) -> Estimate:
    """One run of a brief with `chars` characters of input (the generator reuses it for each brief it will run)."""
    base = _PROMPT_TOKENS + chars // 3

    def credits(role: str, calls: int, tokens_in: int, tokens_out: int) -> float:
        quote = config.price(config.roles[role].primary)
        return calls * config.credits((tokens_in * quote.input + tokens_out * quote.output) / 1e6)

    def out(role: str) -> int:
        return _output_cap(config, role)

    low = credits("director", 3, base, 400) + credits("writer", _UNITS[0], base, 250)
    low += credits("lead", 1, base, 100) + credits("narrator", 1, base, 200)
    high = credits("director", 3 + _DIRECTOR_RETRIES, base + 1000, out("director"))
    high += credits("writer", _UNITS[1], base + 1500, out("writer")) + credits("lead", 3, base + 1500, out("lead"))
    high += credits("narrator", 1, base + 1500, out("narrator"))
    return Estimate(low, high)


# --- the meter: every call counted in exactly one row ---------------------------------------------------------------


class _Meter:
    def __init__(self, config: ProvidersConfig, cap: float) -> None:
        self.config, self.cap = config, cap
        self.rows: dict[tuple[str, str, str], Row] = {}
        self.stop: tuple[str, str, str, str] | None = (
            None  # (outcome class, role, detail, stage): the first thing that ended the run
        )
        self.failure: tuple[str, BaseException] | None = None  # (role, error): the first call the Router gave up on
        self.lock = threading.RLock()  # one model call at a time, so the cap is checked against what was really spent

    def cost(self, profile: str, tokens_in: int, tokens_out: int) -> float:
        quote = self.config.price(profile)
        return self.config.credits((tokens_in * quote.input + tokens_out * quote.output) / 1e6)

    @property
    def total(self) -> float:
        return math.fsum(row.credits for row in self.rows.values())

    def left(self) -> float:
        return max(self.cap - self.total, 0.0)

    def tokens(self, response: GenerateResponse, request: GenerateRequest) -> tuple[int, int]:
        usage = response.usage or {}
        if isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
            return usage["input_tokens"], usage["output_tokens"]
        return len(f"{request.system or ''} {request.prompt}".split()), len((response.text or "").split())  # no usage

    def add(self, role: str, request: GenerateRequest, response: GenerateResponse, latency_ms: float) -> None:
        tokens_in, tokens_out = self.tokens(response, request)
        with self.lock:
            key = (_stage(role, request), role, response.profile_id)
            row = self.rows.setdefault(key, Row(*key))
            row.calls, row.tokens_in, row.tokens_out = (
                row.calls + 1,
                row.tokens_in + tokens_in,
                row.tokens_out + tokens_out,
            )
            row.credits += self.cost(response.profile_id, tokens_in, tokens_out)
            row.latency_ms += latency_ms

    def add_unreturned(
        self, role: str, profile: str, request: GenerateRequest, tokens_in: int, latency_ms: float
    ) -> None:
        """A call that raised after it may have been billed (a blocked reply, a timeout): charged at the Router's own
        pre-call quote, the input and the full output cap, because the provider reported no usage for it."""
        with self.lock:
            key = (_stage(role, request), role, profile)
            row = self.rows.setdefault(key, Row(*key))
            tokens_out = request.max_output_tokens or 0
            row.calls += 1
            row.tokens_in, row.tokens_out = row.tokens_in + tokens_in, row.tokens_out + tokens_out
            row.credits += self.cost(profile, tokens_in, tokens_out)
            row.latency_ms += latency_ms

    def stopped(self, kind: str, role: str, detail: str = "", stage: str = "") -> None:
        with self.lock:
            self.stop = self.stop or (kind, role, detail, stage)

    def failed(self, role: str, error: BaseException) -> None:
        with self.lock:
            self.failure = self.failure or (role, error)


def _stage(role: str, request: GenerateRequest) -> str:
    if role == "narrator":
        return "narrate"
    if role == "director":
        properties = (request.response_schema or {}).get("properties", {})
        return "approaches" if "approaches" in properties else "plan" if "units" in properties else "intake"
    return "run"


class _Redacting(ModelProvider):
    """The live provider with every reply redacted BEFORE the run uses it, so what is recorded is what the run saw."""

    def __init__(self, inner: ModelProvider) -> None:
        self._inner = inner

    def redact(self, text: str) -> str:
        return _PERSONAL.sub("[redacted]", redact_strings(text, self._inner))

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        return GenerateResponse.model_validate(redact_strings(self._inner.generate(request).model_dump(), self))

    def stream(self, request: GenerateRequest) -> Iterator[GenerateResponse]:
        yield self.generate(request)

    def embed(self, request: Any) -> Any:
        return self._inner.embed(request)

    def count_tokens(self, text: str) -> int:
        return self._inner.count_tokens(text)

    def capabilities(self) -> set[Capability]:
        return self._inner.capabilities()

    def price(self) -> Any:
        return self._inner.price()


class _Metered(_Redacting):
    """Counts every served call, replayed or live, and notes a replay miss (with the key that would satisfy it)."""

    def __init__(self, inner: ModelProvider, role: str, profile: str, meter: _Meter) -> None:
        super().__init__(inner)
        self._role, self._profile, self._meter = role, profile, meter

    def generate(self, request: GenerateRequest) -> GenerateResponse:
        started = time.perf_counter()
        try:
            response = self._inner.generate(request)
        except ReplayMissError:
            key = recording_key(self._role, self._profile, request)
            self._meter.stopped("replay_miss", self._role, key, _stage(self._role, request))
            raise
        except (RequestError, QuotaError):  # refused before any generation: never billed
            raise
        except Exception:
            # Anything else may have been billed after it was sent (a blocked candidate, a timeout): count it.
            tokens_in = len(f"{request.system or ''} {request.prompt}".split())
            elapsed = (time.perf_counter() - started) * 1000
            self._meter.add_unreturned(self._role, self._profile, request, tokens_in, elapsed)
            raise
        self._meter.add(self._role, request, response, (time.perf_counter() - started) * 1000)
        return response


class _FakeRecorder(RecordReplayProvider):
    """Records every reply of an injected fake, whatever the environment says: it never reads the live switch or the
    record flag, so the fake path (`record_with_fake`) cannot be turned into a paid call by the environment."""

    def _is_live(self) -> bool:
        return True

    def _is_record(self) -> bool:
        return True


def _require_fake(provider: object) -> None:
    """A provider handed to the fake path must call itself a fake and must not be a network adapter (EFF-01)."""
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415
    from tilo_providers.openai_compat_adapter import OpenAICompatModelProvider  # noqa: PLC0415

    network = isinstance(provider, GoogleModelProvider | OpenAICompatModelProvider)
    if (
        network
        or not isinstance(provider, ModelProvider)
        or getattr(type(provider), "SYNTHETIC_FAKE", False) is not True
    ):
        raise LiveE2ERefused("not_a_fake_provider", "the fake record path takes only an injected fake provider")


class _Providers:
    """(role, profile) -> the provider the Router uses: `RecordReplayProvider` around the live one, built lazily."""

    def __init__(
        self,
        config: ProvidersConfig,
        meter: _Meter,
        recordings: Path,
        live: Callable[[str, str], ModelProvider] | None,
        *,
        fake_record: bool = False,
    ) -> None:
        self._config, self._meter, self._recordings, self._live = config, meter, recordings, live
        self._wrap = _FakeRecorder if fake_record else RecordReplayProvider
        self._made: dict[tuple[str, str], ModelProvider] = {}

    def __call__(self, role: str, profile: str) -> ModelProvider:
        if (role, profile) not in self._made:

            def live_factory() -> ModelProvider:
                if self._live is None:
                    raise RuntimeError("a replay never goes live")
                return _Redacting(self._live(role, profile))

            caps = {Capability(c) for c in self._config.profiles[profile].caps}
            recorded = self._wrap(role, profile, live_factory, self._recordings, caps)
            self._made[(role, profile)] = _Metered(recorded, role, profile, self._meter)
        return self._made[(role, profile)]


class _MeteredRouter(Router):
    """The one door for every model call: nothing is sent that the budget left cannot cover (PL-03)."""

    def __init__(self, config: ProvidersConfig, meter: _Meter, providers: _Providers) -> None:
        super().__init__(config, provider_for_profile=lambda profile: providers(_ROLE.get(), profile))
        self.meter, self._cfg = meter, config

    def generate(self, role_id: str, request: GenerateRequest, *, budget: float | None = None, **kwargs: Any) -> Any:
        if request.max_output_tokens is None:  # the Router's own default of 1024 would cut a Director plan short
            request = request.model_copy(update={"max_output_tokens": _output_cap(self._cfg, role_id)})
        with self.meter.lock:
            left = self.meter.left()
            token = _ROLE.set(role_id)
            try:
                return super().generate(
                    role_id, request, budget=left if budget is None else min(budget, left), **kwargs
                )
            except BudgetExceededError:
                self.meter.stopped("stopped_at_cap", role_id)
                raise
            except Exception as error:
                if role_id != "narrator":  # a Narrator that fails leaves no Story; it never ends the run (see `_story`)
                    self.meter.failed(role_id, error)
                raise
            finally:
                _ROLE.reset(token)


# --- the screen a live run uses (BQ-LE2E-5) -----------------------------------------------------------------------


def _sha(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()  # the bank's own newline rule


class TrustedBankInputScreen(SafetyProvider):
    """TRUSTED-BANK-INPUT: allows a text only if it is byte-identical (after CRLF to LF, as the bank digest does) to the
    brief, an attached file, the file names or the scripted answers of the committed bank case being run, whose own file
    hash it re-checks on every call; refuses everything else with a clear error. Nothing untrusted can reach a live
    model through it. It is NOT a general safety provider (Model Armor is the safety role's live adapter, FR-INT-02,
    #450), is never registered in the factory and is used only by `just live-e2e`. A trusted text still gets the fake
    screen's injection-marker scan."""

    def __init__(self, case: BankCase) -> None:
        self._path, self._file = case.path, _sha(case.path.read_text(encoding="utf-8"))
        answers = sorted(a for a in (case.answers or {}).values() if a)
        names = "\n".join(f["name"] for f in case.files)
        self._allowed = {_sha(t) for t in (case.brief, names, *(f["text"] for f in case.files), *answers) if t}
        self._answers: tuple[str, ...] = tuple(answers)
        self.refused: list[str] = []

    def _refuse(self, why: str) -> TrustedInputRefused:
        self.refused.append(why)
        return TrustedInputRefused(why)

    def _check(self, text: str, *, content: bytes | None, mime_type: str | None) -> Any:
        if content is not None:
            raise self._refuse("trusted bank input: a native file is not a bank case input; nothing was sent")
        if _sha(self._path.read_text(encoding="utf-8")) != self._file:
            raise self._refuse("trusted bank input: the case file changed since the run began; nothing was sent")
        answers = tuple(sorted(text.replace("\r\n", "\n").split("\n")))
        if _sha(text) not in self._allowed and not (self._answers and answers == self._answers):
            raise self._refuse(
                f"trusted bank input: a text of {len(text)} characters is not the committed case's own input, "
                "and a live run sends nothing else to a model"
            )
        return FakeSafetyProvider()._check(text, content=None, mime_type=None)


# --- the run's own seams: everything but the model-backed unit runner and the writer is tilo-api's ----------------


class _Writer:
    """The single writer's `append(world_id, event)` over the in-memory store (the dev writer refuses when live)."""

    def __init__(self, store: Any) -> None:
        self._store, self._lock = store, threading.Lock()

    def append(self, world_id: str, event: dict) -> dict:
        from tilo_api import deps, events  # noqa: PLC0415
        from tilo_harness.validator import repo_validator  # noqa: PLC0415

        world = self._store.worlds.get(world_id)
        if world is None or event.get("vis") is None:
            raise deps.EventRejected("an event needs a known world and the `vis` that says who may see it")
        with self._lock:
            committed = self._store.events.setdefault(world_id, [])
            existing = next((e for e in committed if e.get("id") == event.get("id")), None)
            seq = existing["seq"] if existing else max((e["seq"] for e in committed), default=0) + 1
            null_trace = dict.fromkeys(
                ("model_role", "profile", "tokens_in", "tokens_out", "tool", "latency_ms", "archive_ref")
            )
            stamped = {
                "v": "1.0", "seq": seq, "ts": existing["ts"] if existing else event.get("ts") or events.now(),
                "world_id": world_id, "run_id": world.run_id, "level": None, "district": None, "item": None,
                "severity": "info", "credits": 0, "cause": None, "authz": None, "data": {},
                "trace": null_trace, **event,
            }  # fmt: skip
            stamped.update(v="1.0", seq=seq, world_id=world_id, run_id=world.run_id)
            if existing is not None:
                if stamped == existing:
                    return existing
                raise deps.EventRejected(f"id {event.get('id')!r} already committed differently")
            if problems := repo_validator().problems(stamped):
                raise deps.EventRejected("; ".join(problems[:3]))
            committed.append(stamped)
            return stamped


class _UnitRunner:
    """One model call per unit by the unit's role (prompts/<role>/unit.md), fed the work of the units it waits for; one
    Lead review per district milestone (the district's last unit). A Verifier's verdict is recorded, not acted on."""

    def __init__(self, router: Router, meter: _Meter) -> None:
        self._router, self._meter = router, meter
        self._brief: dict[str, Any] = {}
        self._units: list[dict[str, Any]] = []
        self._work: dict[str, str] = {}

    def capture(self, brief: dict[str, Any], plan: dict[str, Any]) -> None:
        self._brief, self._units = brief, list(plan.get("units", []))

    def _ask(self, role: str, prompt: str) -> tuple[str, float]:
        request = GenerateRequest(prompt=prompt, max_output_tokens=_OUT.get(role), thinking_level="minimal")
        response = self._router.generate(role, request).response
        text = ((response.text if response else None) or "").strip()
        if not response or not text:
            raise ProviderError("the model returned no text")
        tokens_in, tokens_out = self._meter.tokens(response, request)
        return text, self._meter.cost(response.profile_id, tokens_in, tokens_out)

    def _request(self) -> dict[str, str]:
        brief = self._brief
        return {
            "goal": _safe(str(brief.get("goal") or "")), "audience": _safe(str(brief.get("audience") or "not stated")),
            "constraints": _safe("; ".join(map(str, brief.get("constraints") or [])) or "none"),
        }  # fmt: skip

    async def run(self, unit: Any, context: Any) -> Any:
        from tilo_api.runs import MeteredOutcome  # noqa: PLC0415

        earlier = [f"[{d}] {self._work[d]}" for d in unit["depends_on"] if d in self._work]
        variables = {
            "title": _safe(unit["title"]), "unit_type": unit["unit_type"],
            "inputs": _safe("\n\n".join(earlier) or "(none)"),
            "skills": "\n\n".join(skill.body for skill in context.skills), **self._request(),
        }  # fmt: skip
        text, credits = await asyncio.to_thread(
            self._ask, unit["role"], load_prompt(unit["role"], "unit.md", variables)
        )
        self._work[unit["id"]] = text
        summary = f"Finished {unit['title']}."
        if unit["role"] == "verifier":
            summary += f" Verdict: {text.splitlines()[0][:80]}"
        district = unit["district"]
        if not any(unit["id"] in u["depends_on"] and u["district"] == district for u in self._units):  # the milestone
            work = "\n\n".join(
                f"[{u['id']}] {u['title']}: {self._work[u['id']]}"
                for u in self._units
                if u["id"] in self._work and u["district"] == district
            )
            prompt = load_prompt("lead", "review.md", {"district": district, "work": _safe(work), **self._request()})
            review, spent = await asyncio.to_thread(self._ask, "lead", prompt)
            summary, credits = f"{summary} Lead review: {review[:200]}", credits + spent
        item = UnitOutput(media_type="text/markdown", content=text.encode("utf-8"))  # the executor stores it (ADR-0018)
        return MeteredOutcome(success=True, summary=summary, outputs=(item,), credits=credits)


def _safe(text: str) -> str:
    """Model-written or user text goes into a prompt as data: none of our block markers can be closed from inside."""
    for marker in ("REQUEST", "EARLIER", "WORK", "BEATS"):
        text = neutralise_marker(text, marker)
    return text


class _ClearModel:
    """The must-ask judge (FR-AGT-05) as a fixed stand-in: no model call, every unit judged clear. Only the
    deterministic rules (a failed unit, a step above T1) can ask a person. Named in `FAKED`."""

    def generate(self, request: Any) -> GenerateResponse:
        return GenerateResponse(text='{"ask": false}', profile_id="live-e2e-clear")


def _app(router: _MeteredRouter, safety: SafetyProvider, runner: _UnitRunner) -> FastAPI:
    from tilo_api import deps, dev_run, runs  # noqa: PLC0415
    from tilo_api.cards import build_router  # noqa: PLC0415
    from tilo_api.dispatch import router as dispatch_router  # noqa: PLC0415
    from tilo_api.intake import router as intake_router  # noqa: PLC0415
    from tilo_api.redaction import router as redaction_router  # noqa: PLC0415
    from tilo_api.tasks import router as tasks_router  # noqa: PLC0415
    from tilo_planning.compiler import compile_plan  # noqa: PLC0415

    app, store = FastAPI(), deps.Store()
    store.policies["pol_dev_send"] = dev_run.dev_send_policy(
        _OWNER
    )  # L1 "ask each time": the run goes to its gate card
    for api_router in (intake_router, dispatch_router, redaction_router, tasks_router, runs.router):
        app.include_router(api_router)
    app.include_router(build_router(runs.get_card_store, answer_guard=runs.answer_guard))
    adapters, writer = dev_run.mock_adapters(), _Writer(store)  # recording mocks: no real mailbox, chat or Drive

    def compiler() -> Any:
        def compile_and_capture(*, brief: dict, approach: dict, budget_cap: float, context: Any) -> dict:
            plan = compile_plan(brief, approach, budget_cap, context, router=router).plan
            runner.capture(brief, plan)
            return plan

        return compile_and_capture

    def must_ask_providers() -> dict[str, _ClearModel]:
        return {role: _ClearModel() for role in ("specialist", "writer", "verifier")}

    def resolve(**_: Any) -> dict:
        return {"destination": dev_run.DEV_DESTINATION, "recipients": [dev_run.DEV_RECIPIENT], "known_recipients": []}

    def principal(request: Request) -> Any:
        return deps.Principal(user_id=_OWNER, role="owner", world_id=request.path_params.get("world_id"))

    app.dependency_overrides.update(
        {
            deps.get_current_principal: principal, deps.get_store: lambda: store, deps.get_event_writer: lambda: writer,
            deps.get_router: lambda: router, deps.get_safety: lambda: safety, deps.get_plan_compiler: compiler,
            deps.get_unit_runner: lambda: runner, deps.get_action_resolver: lambda: resolve,
            deps.get_connector_adapters: lambda: adapters, deps.get_must_ask_providers: must_ask_providers,
            **e2e_stand_ins.overrides(),  # the artifact store, redactor and raw archive the run needs (ADR-0018 T4)
        }
    )  # fmt: skip
    return app


# --- the Narrator: one call per world; each Story line cites the events of the beat it tells (HR-1) -----------------


def _beats(events: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    size = max(1, math.ceil(len(events) / _MAX_BEATS))
    return [events[i : i + size] for i in range(0, len(events), size)]


def _narrate(router: _MeteredRouter, events: list[dict[str, Any]]) -> list[StoryLine]:
    beats = _beats(events)
    shown = "\n\n".join(
        f"Beat {n}:\n" + "\n".join(f"- {e['summary']}" for e in beat) for n, beat in enumerate(beats, 1)
    )
    request = GenerateRequest(
        prompt=load_prompt("narrator", "story.md", {"beats": _safe(shown)}),
        max_output_tokens=_OUT["narrator"],
        thinking_level="minimal",
    )
    text = (router.generate("narrator", request).response or GenerateResponse(profile_id="none")).text or ""
    lines: list[StoryLine] = []
    for position, line in enumerate(raw.strip() for raw in text.splitlines() if raw.strip()):
        found = re.match(r"(?i)^beat\s+(\d+)\s*[:.-]\s*(.+)$", line)
        index, said = (int(found[1]) - 1, found[2]) if found else (position, line)
        if 0 <= index < len(beats):
            lines.append(StoryLine(said[:300], [e["id"] for e in beats[index]]))
    return lines


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    """Library log lines can carry a provider's error text (PRD 16.1 rule 4): the report is the only output."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


def _vertex(config: ProvidersConfig) -> Callable[[str, str], ModelProvider]:
    from tilo_providers.factory import _build_live_provider  # noqa: PLC0415
    from tilo_providers.google_adapter import GoogleSettingsError, validate_google_settings  # noqa: PLC0415

    try:
        validate_google_settings(
            os.environ["GOOGLE_CLOUD_PROJECT"], os.environ.get("GOOGLE_LOCATION", "global"), os.environ
        )
    except GoogleSettingsError as error:
        raise LiveE2ERefused(error.code, str(error)) from None
    return lambda _role, profile: _build_live_provider(config.profiles[profile], profile)


_PROJECT_PATH = re.compile(r"(?i)projects/[^/\s\"']+")
_ADC_FILE = re.compile(r"[^\s\"']*application_default_credentials\.json")


def _scrub_known(text: str, env: Mapping[str, str]) -> str:
    """What a provider's text may echo about this machine and project: the project id, the ADC file and the gcloud
    folder (from the environment, or by shape), and any email, phone number or token."""
    for name in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_APPLICATION_CREDENTIALS", "CLOUDSDK_CONFIG"):
        for value in (env.get(name), os.environ.get(name)):
            if value and len(value) >= 3:
                text = text.replace(value, "[redacted]")
    return _PERSONAL.sub("[redacted]", _ADC_FILE.sub("[redacted]", _PROJECT_PATH.sub("projects/[redacted]", text)))


def _provider_failure(error: BaseException, env: Mapping[str, str]) -> tuple[str, str]:
    """(code, reason) of a call the Router gave up on. Only a rejected request (HTTP 400) gives a reason: the adapter's
    redacted server text, scrubbed again here, one line, scrubbed before it is capped. Any other status: code only."""
    code = classify(error)
    return code, (_scrub_known(scrubbed_server_text(error), env)[:MAX_REASON_CHARS] if code == "rejected" else "")


def _classify(
    obs: Observation, meter: _Meter, safety: SafetyProvider, env: Mapping[str, str]
) -> tuple[str, str | None]:
    if meter.stop:
        kind, role, detail, stage = meter.stop
        if kind == "replay_miss":
            return kind, (
                f"no recording for stage {stage} (role {role}) with key {detail}: a prompt, brief or config changed"
            )
        return (
            kind,
            f"the run reached its credit cap of {meter.cap:.4f} credits before it could finish ({role} call refused)",
        )
    code, said = _provider_failure(meter.failure[1], env) if meter.failure else ("", "")
    if code == "rejected" and meter.failure:  # a 400 beats the route's generic text (it called the screen unavailable)
        return "rejected", f"the provider rejected a request of the {meter.failure[0]} role" + (
            f": {said}" if said else ""
        )
    if refused := getattr(safety, "refused", None):  # the trusted screen's own words beat the route's generic 503 text
        return "refused", refused[-1]
    outcome, reason = (
        ("failed", obs.crash or "no terminal state within the time budget")
        if obs.crash or obs.timed_out
        else ((obs.outcome or "failed"), obs.reason)
    )
    if code and meter.failure and outcome not in ("completed", "held_at_gate", "needs_answers"):
        reason = f"{reason or 'the run did not finish'}; provider call failed ({meter.failure[0]} role): {code}"
    return outcome, reason


def _story(
    router: _MeteredRouter, events: list[dict[str, Any]], env: Mapping[str, str]
) -> tuple[list[StoryLine], str | None]:
    """The Narrator's Story, or why there is none (a code, never a provider's text): it never ends the run."""
    try:
        return _narrate(router, events), None
    except Exception as error:  # noqa: BLE001
        code, said = _provider_failure(error, env)
        return [], f"the Narrator call failed: {code}" + (f" ({said})" if said else "")


def _mark_recordings(recordings: Path, *, synthetic: bool) -> None:
    """Say who wrote the recordings in this folder, so a replay never passes a fixture off as a real run (HR-1)."""
    marker = recordings / SYNTHETIC_MARKER
    if synthetic:
        recordings.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            "written by a fake provider for tests; not a real model run\n", encoding="utf-8", newline="\n"
        )
    else:
        marker.unlink(missing_ok=True)


def _execute(
    case: BankCase, router: _MeteredRouter, meter: _Meter, screen: SafetyProvider, env: Mapping[str, str],
    *, live: bool, cap: float, narrate: bool = True,
) -> tuple[Observation, str, str | None, list[StoryLine], str | None]:  # fmt: skip
    """One case through the real pipeline on `router`: (observation, outcome class, reason, Story, why no Story).
    The generator calls it once per brief on its own router, so the whole run shares one meter and one cap."""
    approve = {**(case.approve or {}), "cap": min(float((case.approve or {}).get("cap", cap)), cap)}
    obs = Observation(case=dataclasses.replace(case, approve=approve))
    story: list[StoryLine] = []
    note: str | None = None
    app = _app(router, screen, _UnitRunner(router, meter))
    with _quiet():
        try:
            drive(obs.case, obs, _UNIT_TIMEOUT_S["live" if live else "replay"], app)
        except Exception as error:  # noqa: BLE001 - a crash is an observation; the error's text is never kept
            obs.crash = type(error).__name__
        if narrate and obs.events and not meter.stop:
            story, note = _story(router, obs.events, env)
    outcome, reason = _classify(obs, meter, screen, env)
    return obs, outcome, reason, story, note


def run_live_e2e(
    case_id: str = "B-007",
    *,
    mode: Literal["live", "replay", "dry-run"] = "live",
    max_credits: float = DEFAULT_MAX_CREDITS,
    environ: Mapping[str, str] | None = None,
    bank_dir: Path | None = None,
    models_path: Path | None = None,
    prices_path: Path | None = None,
    recordings_dir: Path | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,
    announce: Callable[[Estimate, float], None] | None = None,
    fake_record: bool = False,  # only `record_with_fake` sets this; the command line has no way to
) -> LiveE2EReport:
    env: Mapping[str, str] = {} if fake_record else os.environ if environ is None else environ
    if fake_record and (live_provider_factory is None or mode != "live"):
        raise LiveE2ERefused("not_a_fake_provider", "the fake record path takes only an injected fake provider")
    _gate("dry-run" if fake_record else mode, env, max_credits)  # the fake path has no live decision to gate
    config = _load_config(models_path, prices_path, env)
    case = _load_case(case_id, bank_dir)
    live = mode == "live"
    factory = (live_provider_factory or _vertex(config)) if live else None
    refused: list[LiveE2ERefused] = []
    if fake_record and factory is not None:
        built = factory

        def factory(role: str, profile: str) -> ModelProvider:  # noqa: F811 - checked before its first call
            provider = built(role, profile)
            try:
                _require_fake(provider)
            except LiveE2ERefused as refusal:
                refused.append(refusal)
                raise
            return provider

    estimate = _estimate(config, case)
    if announce is not None:
        announce(estimate, max_credits)  # before any model call
    screen = safety or TrustedBankInputScreen(case)
    report = LiveE2EReport(case_id, mode, max_credits, estimate, expected=case.outcome)
    report.safety = SAFETY_NOTE if isinstance(screen, TrustedBankInputScreen) else f"injected ({type(screen).__name__})"
    if mode == "dry-run":
        return report
    meter = _Meter(config, max_credits)
    recordings = Path(recordings_dir) if recordings_dir else default_recordings_dir(case_id)
    if live and not fake_record and os.environ.get("TILO_RECORD") == "1":
        _mark_recordings(recordings, synthetic=live_provider_factory is not None)  # only a test injects a provider
    providers = _Providers(config, meter, recordings, factory, fake_record=fake_record)
    router = _MeteredRouter(config, meter, providers)
    obs, report.outcome_class, report.reason, report.story_lines, report.story_note = _execute(
        case, router, meter, screen, env, live=live, cap=max_credits
    )
    if report.reason:  # a last line of defence: nothing printed names the project, an ADC path or a token
        report.reason = _scrub_known(" ".join(report.reason.split()), env)
    if refused:
        raise refused[0]
    if fake_record:
        _mark_recordings(recordings, synthetic=True)
    if not live:
        report.recordings = "synthetic" if (recordings / SYNTHETIC_MARKER).is_file() else "unmarked"
    stopped = report.outcome_class in ("stopped_at_cap", "replay_miss")
    found = check_case(obs)
    report.findings = [f for f in found if not (stopped and f.check == terminal_honest.__name__)]
    report.checks_run = [c.__name__ for c in CHECKS if not (stopped and c is terminal_honest)]
    report.rows, report.total_credits = list(meter.rows.values()), meter.total
    report.events, report.questions, report.answered = obs.events, obs.questions, obs.answered
    return report


def record_with_fake(
    case_id: str = "B-007",
    *,
    fake_factory: Callable[[str, str], ModelProvider] | None,
    recordings_dir: Path,
    prices_path: Path | None = None,
    bank_dir: Path | None = None,
    models_path: Path | None = None,
    max_credits: float = DEFAULT_MAX_CREDITS,
    safety: SafetyProvider | None = None,
) -> LiveE2EReport:
    """Re-record the synthetic fixture (issue #367) through an injected fake: the real Router, record-and-replay layer
    and pipeline, with every reply from `fake_factory`. Programmatic only: no flag or environment variable reaches it,
    it reads neither the live switch nor the record flag, and it refuses (`not_a_fake_provider`, before the provider's
    first call) anything that is a network adapter or does not call itself a fake (`SYNTHETIC_FAKE = True`)."""
    return run_live_e2e(
        case_id, mode="live", max_credits=max_credits, bank_dir=bank_dir, models_path=models_path,
        prices_path=prices_path, recordings_dir=recordings_dir, live_provider_factory=fake_factory, safety=safety,
        fake_record=True,
    )  # fmt: skip


# --- the command ---------------------------------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="live_e2e", description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--case", default="B-007", help="the bank case to run (default B-007)")
    parser.add_argument(
        "--max-credits", type=float, default=DEFAULT_MAX_CREDITS, help=f"cap, at most {HARD_MAX_CREDITS:g}"
    )
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--replay", action="store_true", help="serve the recordings; never goes live, free")
    kind.add_argument("--dry-run", action="store_true", help="print the estimate and stop; no call")
    for name in ("bank-dir", "models-file", "prices-file", "recordings-dir", "report-json"):
        parser.add_argument(f"--{name}", type=Path)
    return parser


def _exit_code(report: LiveE2EReport) -> int:
    if report.outcome_class == "stopped_at_cap":
        return 3
    hard = [f for f in report.findings if f.hard]
    return 0 if report.outcome_class == report.expected and not hard else 1


def _print_report(report: LiveE2EReport) -> None:
    print(f"mode={report.mode} case={report.case_id}")
    print(f"safety: {report.safety}")
    for item in FAKED:
        print(f"faked: {item}")
    if report.recordings == "synthetic":
        print("recordings: SYNTHETIC fixture written by a fake provider; this replay is not a real model run")
    elif report.recordings:
        print("recordings: not marked synthetic; they stand for what an earlier recorded run returned")
    for r in report.rows:
        print(
            f"stage={r.stage} role={r.role} profile={r.profile} calls={r.calls} tokens_in={r.tokens_in} "
            f"tokens_out={r.tokens_out} credits={r.credits:.4f} latency_ms={r.latency_ms:.1f}"
        )
    print(f"outcome={report.outcome_class} events={report.event_count}")
    for name in report.checks_run:
        print(f"check={name} findings={sum(1 for f in report.findings if f.check == name)}")
    print(f"total credits={report.total_credits:.4f} cap={report.cap_credits:.4f}")
    print(f"note: {PLANNING_NOTE}")
    print(f"note: {SCOPE_NOTE}")
    if report.story_note:
        print(f"story: none ({report.story_note})")
    for line in report.story_lines:
        print(f"story: {line.text}")


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,
) -> int:
    args = _parser().parse_args(argv)
    mode: Literal["live", "replay", "dry-run"] = "replay" if args.replay else "dry-run" if args.dry_run else "live"

    def announce(estimate: Estimate, cap: float) -> None:
        print(
            f"estimate credits_low={estimate.credits_low:.4f} credits_high={estimate.credits_high:.4f} cap={cap:.4f}",
            flush=True,
        )

    try:
        report = run_live_e2e(
            args.case, mode=mode, max_credits=args.max_credits, environ=environ, bank_dir=args.bank_dir,
            models_path=args.models_file, prices_path=args.prices_file, recordings_dir=args.recordings_dir,
            live_provider_factory=live_provider_factory, safety=safety, announce=announce,
        )  # fmt: skip
    except LiveE2ERefused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        return 2
    if mode == "dry-run":
        return 0
    _print_report(report)
    if args.report_json:
        data = {**report.to_dict(), "event_types": [e["type"] for e in report.events]}
        args.report_json.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    code = _exit_code(report)
    if code:
        why = " ".join((report.reason or "the outcome is not the case's, or a hard check failed").split())
        print(f"STOP {report.outcome_class}: {why}", file=sys.stderr)
    return code
