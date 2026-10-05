"""Shared helpers for the PL-02 live Vertex smoke tests (ticket PL-LIVE-vertex-smoke).

Nothing here talks to a network. The Google Gen AI SDK is faked at the `sys.modules` boundary (same
technique as `_fake_genai_sdk.py`), so the real adapter and the real router run, but `genai.Client(...)`
returns an in-memory fake that records every constructor call and every `generate_content` call.

API pinned for the implementer: `API_PL_LIVE_vertex_smoke.md` in this directory.
"""

from __future__ import annotations

import contextlib
import importlib
import importlib.abc
import io
import logging
import os
import re
import sys
import tempfile
import time
import types as pytypes
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest import mock

import yaml
from _fake_genai_sdk import FakeAPIError, FakeCandidate, FakeGenerateContentConfig, FakeGenerateContentResponse

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_MODELS = REPO_ROOT / "config" / "models.yaml"
REAL_PRICES = REPO_ROOT / "config" / "prices.yaml"
SMOKE_MODULE = "tilo_providers.vertex_smoke"
SMOKE_SOURCE = REPO_ROOT / "packages" / "providers" / "src" / "tilo_providers" / "vertex_smoke.py"
SMOKE_SCRIPT = REPO_ROOT / "packages" / "providers" / "scripts" / "live_vertex_smoke.py"

ROLES = ("director", "lead", "specialist", "verifier", "writer", "narrator", "autopilot")
PROJECT = "demo-smoke-project"  # a made-up id; the real one comes from the user's own environment
ENV_KEYS_CLEARED = (
    "LIVE",
    "TILO_RECORD",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_LOCATION",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_VERTEX_BASE_URL",
    "TILO_MODELS_FILE",
    "K_SERVICE",
    "CLOUD_RUN_JOB",
)

# Row and total lines pinned in API_PL_LIVE_vertex_smoke.md.
ROW_RE = re.compile(
    r"^role=(?P<role>\w+) profile=(?P<profile>\S+) latency_ms=(?P<latency>\d+(?:\.\d+)?) "
    r"tokens_in=(?P<tin>\d+) tokens_out=(?P<tout>\d+) credits=(?P<credits>\d+\.\d{4})"
    r"(?: fallback_from=(?P<fallback_from>\S+))?$"
)
TOTAL_RE = re.compile(r"^total credits=(?P<credits>\d+\.\d{4}) ceiling=(?P<ceiling>\d+\.\d{4})$")
FAIL_RE = re.compile(r"^FAIL role=(?P<role>\w+) reason=(?P<code>[a-z_]+): (?P<message>.+) Fix: (?P<fix>.+)$")


def fake_secret(kind: str) -> str:
    """Fake credentials, assembled at runtime so no secret-shaped literal sits in the source."""
    if kind == "access_token":  # the shape of a Google OAuth access token
        return "ya" + "29." + "FakeTokenAbc123_" + "def456-ghi789" * 2
    if kind == "bearer":
        return "Bearer " + "fakeBearer" + "Value0123456789"
    if kind == "api_key":  # the shape of a Google API key
        return "AI" + "za" + "Fake" + "KeyValue0123456789abcdefghijklmn"
    raise ValueError(kind)


# ---------------------------------------------------------------------------------------------------------
# Fake Google Gen AI SDK for Vertex
# ---------------------------------------------------------------------------------------------------------


class DefaultCredentialsError(Exception):
    """Stands in for google.auth.exceptions.DefaultCredentialsError (no Application Default Credentials)."""


class FakeThinkingConfig:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


@dataclass
class FakeUsage:
    prompt_token_count: int
    candidates_token_count: int | None
    total_token_count: int
    thoughts_token_count: int | None = None


@dataclass
class FakeVertexSdk:
    """Records every `genai.Client(...)` construction and every `models.generate_content(...)` call."""

    usage: tuple[int, int | None] = (20, 30)  # (prompt, candidate tokens) per call; None: Vertex left the count out
    thoughts: int | None = None
    text: str = "synthetic reply"
    delay_s: float = 0.0
    errors_by_model: dict[str, Exception] = field(default_factory=dict)
    client_error: Exception | None = None
    client_inits: list[dict[str, Any]] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def _client(self, **kwargs: Any) -> Any:
        self.client_inits.append(kwargs)
        if self.client_error is not None:
            raise self.client_error
        return pytypes.SimpleNamespace(models=_FakeModels(self))

    @contextlib.contextmanager
    def installed(self) -> Iterator[FakeVertexSdk]:
        genai_pkg = pytypes.ModuleType("google.genai")
        types_mod = pytypes.ModuleType("google.genai.types")
        errors_mod = pytypes.ModuleType("google.genai.errors")
        types_mod.GenerateContentConfig = FakeGenerateContentConfig  # type: ignore[attr-defined]
        types_mod.ThinkingConfig = FakeThinkingConfig  # type: ignore[attr-defined]
        errors_mod.APIError = FakeAPIError  # type: ignore[attr-defined]
        genai_pkg.types = types_mod  # type: ignore[attr-defined]
        genai_pkg.errors = errors_mod  # type: ignore[attr-defined]
        genai_pkg.Client = self._client  # type: ignore[attr-defined]
        modules = {"google.genai": genai_pkg, "google.genai.types": types_mod, "google.genai.errors": errors_mod}
        with mock.patch.dict(sys.modules, modules):
            yield self

    def models_called(self) -> list[str]:
        return [call["model"] for call in self.calls]


class _FakeModels:
    def __init__(self, sdk: FakeVertexSdk) -> None:
        self._sdk = sdk

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> FakeGenerateContentResponse:
        sdk = self._sdk
        sdk.calls.append({"model": model, "contents": contents, "config": config})
        if sdk.delay_s:
            time.sleep(sdk.delay_s)
        error = sdk.errors_by_model.get(model)
        if error is not None:
            raise error
        tokens_in, tokens_out = sdk.usage
        total = tokens_in + (tokens_out or 0) + (sdk.thoughts or 0)
        usage = FakeUsage(tokens_in, tokens_out, total, sdk.thoughts)
        return FakeGenerateContentResponse(
            text=sdk.text,
            usage_metadata=usage,  # type: ignore[arg-type]
            candidates=[FakeCandidate(finish_reason="STOP")],
        )

    def count_tokens(self, **_kwargs: Any) -> Any:  # the router counts locally; a remote count is a bug here
        raise AssertionError("the smoke must not make extra (billable or network) count_tokens requests")


def config_thinking_level(config: Any) -> str | None:
    """The thinking level the adapter put on a captured GenerateContentConfig, lower-cased; None if absent.
    Accepts a ThinkingConfig-like object or a plain dict, and a string or an enum value."""
    thinking = getattr(config, "thinking_config", None)
    if thinking is None:
        return None
    level = (
        thinking.get("thinking_level") if isinstance(thinking, Mapping) else getattr(thinking, "thinking_level", None)
    )
    if level is None:
        return None
    return str(getattr(level, "value", level)).lower()


# ---------------------------------------------------------------------------------------------------------
# Environment, imports, output
# ---------------------------------------------------------------------------------------------------------


@contextlib.contextmanager
def env(**overrides: str) -> Iterator[None]:
    """A clean process environment (no live switch, no keys) plus `overrides`; restored on exit.
    This is the only place a test ever sets the live switch, and only inside its own patched environ."""
    with mock.patch.dict(os.environ, {}, clear=False):
        for key in ENV_KEYS_CLEARED:
            os.environ.pop(key, None)
        # No gcloud config here: the smoke looks at gcloud's well-known ADC file, which tests must not read from home.
        os.environ["CLOUDSDK_CONFIG"] = str(Path(tempfile.gettempdir()) / "tilo-test-no-gcloud-config")
        os.environ.update(overrides)
        yield


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


_BLOCKED_PREFIXES = ("google.genai", "google.auth", "google.cloud", "google.oauth2", "vertexai")
_BLOCKED_EXACT = ("tilo_providers.google_adapter",)


class ImportBlocker(importlib.abc.MetaPathFinder):
    """Raises (and records) when the Vertex client, the credential libraries or the Google adapter are imported."""

    def __init__(self) -> None:
        self.hits: list[str] = []

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> None:
        if fullname in _BLOCKED_EXACT or fullname.startswith(_BLOCKED_PREFIXES):
            self.hits.append(fullname)
            raise ImportError(f"PL_LIVE test: {fullname!r} imported when it must not be")
        return None


@contextlib.contextmanager
def vertex_imports_blocked() -> Iterator[ImportBlocker]:
    """No Vertex client, credential library or Google adapter may be imported inside this block. Modules the
    suite already imported are hidden for the duration, so a module-level import in new code is caught too."""
    blocker = ImportBlocker()
    with mock.patch.dict(sys.modules):
        for name in list(sys.modules):
            if name in _BLOCKED_EXACT or name.startswith(_BLOCKED_PREFIXES) or name == SMOKE_MODULE:
                del sys.modules[name]
        sys.meta_path.insert(0, blocker)
        try:
            yield blocker
        finally:
            sys.meta_path.remove(blocker)


def smoke() -> Any:
    """The module under test. Imported inside each test so a missing module fails that test, not collection."""
    return importlib.import_module(SMOKE_MODULE)


@dataclass
class Invocation:
    code: int
    out: str
    err: str
    logs: str

    @property
    def everything(self) -> str:
        return "\n".join((self.out, self.err, self.logs))

    def err_lines(self) -> list[str]:
        return [line for line in self.err.splitlines() if line.strip()]

    def rows(self) -> list[re.Match[str]]:
        return [m for line in self.out.splitlines() if (m := ROW_RE.match(line))]

    def total(self) -> re.Match[str] | None:
        return next((m for line in self.out.splitlines() if (m := TOTAL_RE.match(line))), None)


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


def invoke_main(argv: list[str], *, environ: Mapping[str, str] | None = None) -> Invocation:
    """Runs `tilo_providers.vertex_smoke.main(argv)` in-process, capturing stdout, stderr and logging."""
    module = smoke()
    out, err = io.StringIO(), io.StringIO()
    with _capture_logs() as logs, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = module.main(argv, environ=environ) if environ is not None else module.main(argv)
    return Invocation(code, out.getvalue(), err.getvalue(), logs.getvalue())


def cli_args(
    models: Path, prices: Path, fixtures: Path, *extra: str, credits: float | None = 50.0, replay: bool = False
) -> list[str]:
    args = ["--models-file", str(models), "--prices-file", str(prices), "--fixtures-dir", str(fixtures)]
    if credits is not None:
        args += ["--max-credits", str(credits)]
    if replay:
        args.append("--replay")
    return [*args, *extra]


# ---------------------------------------------------------------------------------------------------------
# Config fixtures
# ---------------------------------------------------------------------------------------------------------


def real_config() -> Any:
    from tilo_providers.config import load_providers_config  # noqa: PLC0415

    return load_providers_config(REAL_MODELS, REAL_PRICES)


def used_profiles(config: Any, roles: tuple[str, ...] = ROLES) -> list[str]:
    from tilo_providers.config import profiles_used_by  # noqa: PLC0415

    return sorted({p for role in roles for p in profiles_used_by(config.roles[role])})


def write_prices(
    tmp_path: Path,
    *,
    scale: float = 1.0,
    uniform: tuple[float, float] | None = None,
    name: str = "prices.set.yaml",
) -> Path:
    """A status-set copy of config/prices.yaml for tests only. The numbers are conspicuously fake fixtures
    (never real prices): flash-38 10/20, flash-37 5/10, lite-31 2/4 per million tokens, times `scale`,
    or `uniform` (input, output) for every profile."""
    raw = yaml.safe_load(REAL_PRICES.read_text(encoding="utf-8"))
    per_profile = {"flash-38": (10.0, 20.0), "flash-37": (5.0, 10.0), "lite-31": (2.0, 4.0)}
    raw["status"] = "set"
    raw["effective_date"] = "2026-10-01"
    raw["source"] = "Test fixture only. Not a real price page."
    for profile_id in raw["profiles"]:
        price_in, price_out = uniform or per_profile.get(profile_id, (1.0, 1.0))
        scaled = (price_in, price_out) if uniform else (price_in * scale, price_out * scale)
        raw["profiles"][profile_id] = {"input": scaled[0], "output": scaled[1]}
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def expected_credits(config: Any, profile_id: str, tokens_in: int, tokens_out: int) -> float:
    """credits = usd / 0.005 (PRD 14.1), usd from the prices file's per-million-token prices (PL-06)."""
    quote = config.price(profile_id)
    return ((tokens_in * quote.input + tokens_out * quote.output) / 1e6) / 0.005


def write_custom_models(tmp_path: Path) -> tuple[Path, Path, dict[str, dict[str, str]]]:
    """A models file whose profile ids and model ids differ from config/models.yaml, to prove the
    role-to-profile mapping comes from whichever config file is given. Returns (models, prices, role map)."""
    profiles = {
        "px": {"provider": "google", "model": "gemini-x-1", "context": 100000, "caps": ["json", "thinking"]},
        "py": {"provider": "google", "model": "gemini-y-1", "context": 100000, "caps": ["json"]},
        "pz": {"provider": "google", "model": "gemini-z-1", "context": 100000, "caps": ["json", "thinking"]},
    }
    mapping = {
        "director": ("py", "pz"),
        "lead": ("pz", "px"),
        "specialist": ("px", "py"),
        "verifier": ("py", "px"),
        "writer": ("pz", "py"),
        "narrator": ("px", "pz"),
        "autopilot": ("py", "pz"),
    }
    roles = {role: {"primary": p, "fallback": f} for role, (p, f) in mapping.items()}
    models = {"example": True, "profiles": profiles, "roles": roles, "rules": {"deny": ["*-preview*"]}}
    models_path = tmp_path / "models.custom.yaml"
    models_path.write_text(yaml.safe_dump(models, sort_keys=False), encoding="utf-8")
    prices = {
        "status": "set",
        "effective_date": "2026-10-01",
        "source": "Test fixture only. Not a real price page.",
        "currency": "USD",
        "credit_usd": 0.005,
        "profiles": {pid: {"input": 1.0, "output": 2.0} for pid in profiles},
    }
    prices_path = tmp_path / "prices.custom.yaml"
    prices_path.write_text(yaml.safe_dump(prices, sort_keys=False), encoding="utf-8")
    plan = {role: {"primary": p, "fallback": f} for role, (p, f) in mapping.items()}
    return models_path, prices_path, plan


def live_run(
    tmp_path: Path,
    *,
    sdk: FakeVertexSdk | None = None,
    prices: Path | None = None,
    models: Path = REAL_MODELS,
    extra_env: Mapping[str, str] | None = None,
    extra_args: tuple[str, ...] = (),
    credits: float | None = 50.0,
    fixtures: Path | None = None,
) -> tuple[Invocation, FakeVertexSdk, Path]:
    """One full run through `main` with the fake SDK, the made-up project and the live switch set inside a
    patched environ only. Returns (invocation, sdk, fixtures dir)."""
    sdk = sdk or FakeVertexSdk()
    prices = prices or write_prices(tmp_path)
    fixtures = fixtures or (tmp_path / "fixtures")
    base_env = {"LIVE": "1", "GOOGLE_CLOUD_PROJECT": PROJECT}
    base_env.update(extra_env or {})
    with env(**base_env), sdk.installed():
        invocation = invoke_main(cli_args(models, prices, fixtures, *extra_args, credits=credits))
    return invocation, sdk, fixtures
