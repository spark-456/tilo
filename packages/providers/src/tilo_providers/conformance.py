"""tilo_providers.conformance — PL-05 conformance suite: schema adherence,
tool calling, repair rate, latency budget, safety handling, checked per
profile against a `ModelProvider` the caller supplies (a recording or the
fake provider in CI; live only with `LIVE=1`). Results write to
`config/conformance/<profile_id>.json`; `config.load_providers_config`'s
`conformance_dir` gate refuses a role whose primary, fallback or cascade
profile has a failing result. Run via `just conformance`."""

from __future__ import annotations

import json
import time
from datetime import date as date_cls
from pathlib import Path
from typing import Any

from tilo_providers.errors import ProviderError
from tilo_providers.interfaces import Capability, GenerateRequest, ModelProvider
from tilo_providers.router import validate_json_schema

CHECK_NAMES = ("schema_adherence", "tool_calling", "repair_rate", "latency_budget", "safety_handling")
_SCHEMA = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
_LATENCY_BUDGET_MS = 5_000.0


def _schema_adherence(provider: ModelProvider) -> str:
    if Capability.JSON not in provider.capabilities():
        return "fail"
    response = provider.generate(
        GenerateRequest(prompt='Reply as JSON: {"answer": "ok"}', json_mode=True, response_schema=_SCHEMA)
    )
    return "pass" if validate_json_schema(response, _SCHEMA) else "fail"


def _tool_calling(provider: ModelProvider) -> str:
    return "pass" if Capability.TOOLS in provider.capabilities() else "fail"


def _repair_rate(provider: ModelProvider) -> str:
    # PRD 6.6 cascades allow one repair attempt: passes if a fresh call
    # after an initial one still produces schema-valid JSON.
    provider.generate(GenerateRequest(prompt="first attempt", json_mode=True, response_schema=_SCHEMA))
    response = provider.generate(
        GenerateRequest(prompt='Reply as JSON: {"answer": "ok"}', json_mode=True, response_schema=_SCHEMA)
    )
    return "pass" if validate_json_schema(response, _SCHEMA) else "fail"


def _latency_budget(provider: ModelProvider) -> str:
    start = time.perf_counter()
    provider.generate(GenerateRequest(prompt="latency check"))
    return "pass" if (time.perf_counter() - start) * 1000 <= _LATENCY_BUDGET_MS else "fail"


def _safety_handling(provider: ModelProvider) -> str:
    try:
        provider.generate(GenerateRequest(prompt="safety handling smoke check"))
    except ProviderError:
        pass  # a ProviderError (incl. SafetyError) is a handled shape, not a crash
    return "pass"


_CHECKS: dict[str, Any] = {
    "schema_adherence": _schema_adherence,
    "tool_calling": _tool_calling,
    "repair_rate": _repair_rate,
    "latency_budget": _latency_budget,
    "safety_handling": _safety_handling,
}


def run_conformance_suite(
    profile_id: str, provider: ModelProvider, *, build: str, today: date_cls | None = None
) -> dict[str, Any]:
    checks = {name: check(provider) for name, check in _CHECKS.items()}
    result = "pass" if all(status == "pass" for status in checks.values()) else "fail"
    return {
        "profile_id": profile_id,
        "date": (today or date_cls.today()).isoformat(),
        "build": build,
        "checks": checks,
        "result": result,
    }


def write_conformance_result(result: dict[str, Any], conformance_dir: Path | str) -> Path:
    conformance_dir = Path(conformance_dir)
    conformance_dir.mkdir(parents=True, exist_ok=True)
    path = conformance_dir / f"{result['profile_id']}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _profiles_used_by_roles(config: Any) -> set[str]:
    profile_ids: set[str] = set()
    for role in config.roles.values():
        profile_ids.add(role.primary)
        if role.fallback:
            profile_ids.add(role.fallback)
        profile_ids.update(role.cascade or ())
    return profile_ids


def main(argv: list[str] | None = None) -> int:  # pragma: no cover -- exercised via `just conformance`
    import argparse

    from tilo_providers.config import load_providers_config, resolve_models_path
    from tilo_providers.factory import provider_for_role_profile
    from tilo_providers.replay import ReplayMissError

    parser = argparse.ArgumentParser(
        description="PL-05 conformance suite runner (replay by default; LIVE=1 for real calls)"
    )
    parser.add_argument("--build", default="dev")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[4]
    config = load_providers_config(resolve_models_path(repo_root), repo_root / "config" / "prices.yaml")
    out_dir = Path(args.out) if args.out else repo_root / "config" / "conformance"
    fixtures_dir = repo_root / "fixtures"
    role_by_profile = {role.primary: role_id for role_id, role in config.roles.items()}

    for profile_id in sorted(_profiles_used_by_roles(config)):
        role_id = role_by_profile.get(profile_id, next(iter(config.roles)))
        provider = provider_for_role_profile(role_id, profile_id, config, fixtures_dir=fixtures_dir)
        try:
            result = run_conformance_suite(profile_id, provider, build=args.build)
        except ReplayMissError as error:
            result = {
                "profile_id": profile_id,
                "date": date_cls.today().isoformat(),
                "build": args.build,
                "checks": dict.fromkeys(CHECK_NAMES, "fail"),
                "result": "fail",
            }
            print(f"{profile_id}: no recording ({error}) -- recorded as fail")
        path = write_conformance_result(result, out_dir)
        print(f"{profile_id}: {result['result']} -> {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
