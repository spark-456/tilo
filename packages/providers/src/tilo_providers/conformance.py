"""tilo_providers.conformance — PL-05 checks per profile on a recording or fake in CI (live only with `LIVE=1`);
writes `config/conformance/<profile_id>.json` (BQ-64). Run via `just conformance`."""

from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Any

from tilo_providers.errors import ProviderError, SafetyError
from tilo_providers.interfaces import Capability, GenerateRequest, ModelProvider
from tilo_providers.prompts import load_prompt
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import schema_error

_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


def _json_ok(provider: ModelProvider, prompt: str = 'Reply as JSON: {"answer": "ok"}') -> bool:
    request = GenerateRequest(prompt=prompt, json_mode=True, response_schema=_SCHEMA)
    return Capability.JSON in provider.capabilities() and schema_error(provider.generate(request), _SCHEMA) is None


def _latency_ok(provider: ModelProvider) -> bool:
    start = time.perf_counter()
    provider.generate(GenerateRequest(prompt="latency check"))
    return time.perf_counter() - start <= 5.0  # latency budget: 5 s per call


_CHECKS = {
    "schema_adherence": _json_ok,
    "tool_calling": lambda provider: Capability.TOOLS in provider.capabilities(),
    "repair_rate": lambda provider: _json_ok(provider, "first attempt") | _json_ok(provider),  # both calls run
    "latency_budget": _latency_ok,
    # any answer to the unsafe probe fails; only its SafetyError passes (caught in _status)
    "safety_handling": lambda p: not p.generate(GenerateRequest(prompt=load_prompt("conformance", "safety_probe.md"))),
}


def _status(name: str, provider: ModelProvider) -> str:
    try:
        return "pass" if _CHECKS[name](provider) else "fail"
    except SafetyError:  # only the unsafe probe passes by being blocked
        return "pass" if name == "safety_handling" else "fail"
    except (ProviderError, ReplayMissError):  # any other provider error or a missing recording fails
        return "fail"


def run_conformance_suite(profile_id: str, provider: ModelProvider, *, build: str, today: date | None = None) -> dict:
    if getattr(provider, "dev_only", False):  # CL-INT-5: a dev fake never produces a result a role could use
        raise ValueError(f"PL-05: profile {profile_id!r} is a dev-only fake; it is never run through conformance")
    checks = {name: _status(name, provider) for name in _CHECKS}
    result = "pass" if all(status == "pass" for status in checks.values()) else "fail"
    day = (today or date.today()).isoformat()
    return {"profile_id": profile_id, "date": day, "build": build, "checks": checks, "result": result}


def write_conformance_result(result: dict[str, Any], conformance_dir: Path | str) -> Path:
    path = Path(conformance_dir) / f"{result['profile_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


# Sibling interfaces (SafetyProvider, EvalProvider): PL-05 is for ModelProviders only.
NON_MODEL_PROVIDERS = frozenset({"model_armor", "vertex_eval"})


def main() -> int:  # pragma: no cover -- exercised via `just conformance`
    from tilo_providers.config import DEV_ONLY_MODELS, load_providers_config, profiles_used_by, resolve_models_path
    from tilo_providers.factory import build_provider

    root = Path(__file__).resolve().parents[4]
    config = load_providers_config(resolve_models_path(root), root / "config" / "prices.yaml")
    role_by_profile = {p: r for r, role in reversed(config.roles.items()) for p in profiles_used_by(role)}
    for profile_id, role_id in sorted(role_by_profile.items()):
        if config.profiles[profile_id].model in DEV_ONLY_MODELS:
            print(f"{profile_id}: skipped (dev-only fake, never conforms)")
            continue
        if config.profiles[profile_id].provider in NON_MODEL_PROVIDERS:
            print(f"{profile_id}: skipped (not a ModelProvider; PL-05 does not apply)")
            continue
        provider = build_provider(role_id, config, fixtures_dir=root / "fixtures", profile_id=profile_id)
        result = run_conformance_suite(profile_id, provider, build="dev")
        print(f"{profile_id}: {result['result']} -> {write_conformance_result(result, root / 'config/conformance')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
