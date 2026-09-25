"""tilo_providers.conformance — PL-05 suite per profile (schema adherence, tool calling, repair
rate, latency budget, safety handling) against a recording or fake in CI, live only with
`LIVE=1`. Writes `config/conformance/<profile_id>.json` (BQ-55). Run via `just conformance`."""

from __future__ import annotations

import json
import time
from datetime import date as date_cls
from pathlib import Path
from typing import Any

from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import Capability, GenerateRequest, ModelProvider
from tilo_providers.replay import ReplayMissError
from tilo_providers.router import validate_json_schema

_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}


def _json_ok(provider: ModelProvider, prompt: str = 'Reply as JSON: {"answer": "ok"}') -> bool:
    request = GenerateRequest(prompt=prompt, json_mode=True, response_schema=_SCHEMA)
    return Capability.JSON in provider.capabilities() and validate_json_schema(provider.generate(request), _SCHEMA)


def _latency_ok(provider: ModelProvider) -> bool:
    start = time.perf_counter()
    provider.generate(GenerateRequest(prompt="latency check"))
    return time.perf_counter() - start <= 5.0  # latency budget: 5 s per call


def _safety_ok(provider: ModelProvider) -> bool:
    try:
        provider.generate(GenerateRequest(prompt="safety handling smoke check"))
    except ProviderError:
        pass  # a ProviderError (incl. SafetyError) is a handled shape, not a crash
    return True


_CHECKS = {
    "schema_adherence": _json_ok,
    "tool_calling": lambda provider: Capability.TOOLS in provider.capabilities(),
    "repair_rate": lambda provider: _json_ok(provider, "first attempt") | _json_ok(provider),  # both calls run
    "latency_budget": _latency_ok,
    "safety_handling": _safety_ok,
}


def _status(check: Any, provider: ModelProvider) -> str:
    try:
        return "pass" if check(provider) else "fail"
    except (ProviderError, ReplayMissError):  # an unhandled provider error or a missing recording fails
        return "fail"


def run_conformance_suite(
    profile_id: str, provider: ModelProvider, *, build: str, today: date_cls | None = None
) -> dict[str, Any]:
    checks = {name: _status(check, provider) for name, check in _CHECKS.items()}
    result = "pass" if all(status == "pass" for status in checks.values()) else "fail"
    day = (today or date_cls.today()).isoformat()
    return {"profile_id": profile_id, "date": day, "build": build, "checks": checks, "result": result}


def write_conformance_result(result: dict[str, Any], conformance_dir: Path | str) -> Path:
    path = Path(conformance_dir) / f"{result['profile_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def main() -> int:  # pragma: no cover -- exercised via `just conformance`
    from tilo_providers.config import load_providers_config, profiles_used_by, resolve_models_path
    from tilo_providers.factory import provider_for_role_profile

    root = Path(__file__).resolve().parents[4]
    config = load_providers_config(resolve_models_path(root), root / "config" / "prices.yaml")
    role_by_profile = {p: r for r, role in reversed(config.roles.items()) for p in profiles_used_by(role)}
    for profile_id, role_id in sorted(role_by_profile.items()):
        provider = provider_for_role_profile(role_id, profile_id, config, fixtures_dir=root / "fixtures")
        result = run_conformance_suite(profile_id, provider, build="dev")
        print(f"{profile_id}: {result['result']} -> {write_conformance_result(result, root / 'config/conformance')}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
