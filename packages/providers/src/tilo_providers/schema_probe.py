"""tilo_providers.schema_probe — which part of a Director request does Vertex AI refuse? (PL-02, EFF-01).

One tiny capped call per request variant on the Director role's primary profile, straight through the Google adapter on
user ADC: (a) no schema, (b) JSON mode only, (c) the sanitized schema, (d) the raw schema, plus three thinking-config
variants. One status line per variant (ok / ok_truncated / rejected with the HTTP status / another failure code), then
the cost. Prints no prompt and no schema; for a 400 it prints the server's scrubbed, capped reason (`vertex_smoke`),
check it before pasting. Same gate as `vertex_smoke`: refused unless the live switch is exactly "1", checked first;
`--dry-run` (alias `--replay`) prints the plan and sends nothing. The schema is passed in by the caller, so this
package does not import the planner. Prices come only from the prices file (PL-06); no model id is named here."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tilo_providers.errors import OutputTruncatedError, SafetyError
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.vertex_smoke import (
    DEFAULT_MAX_OUTPUT_TOKENS,
    SmokeRefused,
    _chain,
    _check_caps,
    _check_prices,
    _load,
    _reason,
    classify,
)

PROBE_ROLE = "director"
PROBE_PROMPT = "Reply with a JSON object describing a calm harbour town at sunrise, in plain words."  # fixed, synthetic
DEFAULT_MAX_CREDITS = 2.0  # ceiling; the seven calls cost about 0.1 credit in all


@dataclass(frozen=True)
class Variant:
    name: str
    json_mode: bool = False
    schema: str | None = None  # None, "sanitized" (the adapter's normal send) or "raw" (the caller's dict as it is)
    thinking: str | None = None
    unmapped: bool = False  # sent exactly as given: the adapter's schema cut and minimal -> low mapping are bypassed


VARIANTS = (
    Variant("no_schema"),
    Variant("json_mode", json_mode=True),
    Variant("schema_sanitized", schema="sanitized"),
    Variant("schema_raw", schema="raw", unmapped=True),
    Variant("schema_thinking_low", schema="sanitized", thinking="low"),
    # What units, narrator and generator ask for. The adapter now sends low for minimal, so the first one bypasses it
    # (does Vertex still 400 on minimal?) and the second goes through it (does the mapped request work?).
    Variant("json_mode_thinking_minimal_unmapped", json_mode=True, thinking="minimal", unmapped=True),
    Variant("json_mode_thinking_minimal_mapped", json_mode=True, thinking="minimal"),
)
VARIANT_NAMES = tuple(v.name for v in VARIANTS)


@dataclass
class ProbeRow:
    variant: str
    status: str  # ok | ok_truncated | blocked | skipped_ceiling | a `vertex_smoke` failure code
    http: int | None = None
    error: str | None = None
    reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    credits: float = 0.0


def _plan_line(variant: Variant) -> str:
    schema, thinking = variant.schema or "none", variant.thinking or "off"
    if variant.thinking == "minimal":
        thinking += "(sent as minimal)" if variant.unmapped else "(adapter sends low)"
    return f"variant={variant.name} schema={schema} json_mode={variant.json_mode} thinking={thinking}"


def _row_line(row: ProbeRow) -> str:
    parts = [f"variant={row.variant}", f"status={row.status}"]
    if row.http is not None:
        parts.append(f"http={row.http}")
    if row.error:
        parts.append(f"error={row.error}")
    parts += [f"tokens_in={row.tokens_in}", f"tokens_out={row.tokens_out}", f"credits={row.credits:.4f}"]
    if row.reason:
        parts.append(f'reason="{row.reason}"')
    return " ".join(parts)


def _provider(raw: bool, profile: Any, profile_id: str, project: str, location: str, client: Any) -> Any:
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415  # dry runs never load the adapter

    class _Raw(GoogleModelProvider):
        def _schema_for_send(self, schema: dict[str, Any]) -> dict[str, Any]:
            return copy.deepcopy(schema)  # variant (d): what the adapter sent before the fix

        def _thinking_for_send(self, level: str) -> str:
            return level  # minimal stays minimal: tests what Vertex says to it

    return (_Raw if raw else GoogleModelProvider)(profile, profile_id, project, location, client=client)


def run_schema_probe(
    schema: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
    models_path: Path | str | None = None,
    prices_path: Path | str | None = None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS * 2,
    max_total_credits: float = DEFAULT_MAX_CREDITS,
    dry_run: bool = False,
    client: Any = None,  # tests only: a fake `google.genai.Client`
    out: Any = None,
) -> list[ProbeRow]:
    environ = os.environ if environ is None else environ
    out = sys.stdout if out is None else out
    if dry_run:  # never goes live
        if environ.get("LIVE") == "1" or os.environ.get("LIVE") == "1":
            raise SmokeRefused("replay_with_live", "--dry-run never runs with the live switch on")
    elif environ.get("LIVE") != "1":  # first and only thing looked at
        raise SmokeRefused("live_not_enabled", "set LIVE to exactly 1 to make real (paid) calls; nothing was sent")
    _check_caps(max_output_tokens, max_total_credits)
    config = _load(models_path, prices_path, environ)
    profile_id = config.roles[PROBE_ROLE].primary
    profile = config.profiles[profile_id]
    _check_prices(config)
    header = (
        f"probe role={PROBE_ROLE} profile={profile_id} max_output_tokens={max_output_tokens} "
        f"ceiling={max_total_credits:.4f}"
    )
    if dry_run:
        print(header, file=out)
        for variant in VARIANTS:
            print(f"{_plan_line(variant)} (dry-run)", file=out)
        print("dry-run: nothing was sent", file=out)
        return []
    if profile.provider != "google":
        raise SmokeRefused("profile_not_google", "the director's primary profile is not a google profile")
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        if environ.get(name) or os.environ.get(name):
            raise SmokeRefused("api_key_present", f"{name} is set; remove it, the probe uses ADC only")
    project = environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SmokeRefused("missing_project", "GOOGLE_CLOUD_PROJECT is not set")
    location = environ.get("GOOGLE_LOCATION") or os.environ.get("GOOGLE_LOCATION") or "global"
    if client is None:
        from tilo_providers.google_adapter import GoogleSettingsError, validate_google_settings  # noqa: PLC0415

        try:
            validate_google_settings(project, location, os.environ)
        except GoogleSettingsError as error:
            raise SmokeRefused(error.code, str(error)) from None
    quote = config.price(profile_id)
    print(header, file=out)
    rows: list[ProbeRow] = []
    total = 0.0
    for variant in VARIANTS:
        request = GenerateRequest(
            prompt=PROBE_PROMPT,
            max_output_tokens=max_output_tokens,
            json_mode=variant.json_mode,
            response_schema=schema if variant.schema else None,
            thinking_level=variant.thinking,
        )
        est_in = (len(PROBE_PROMPT) + (len(repr(schema)) if variant.schema else 0)) // 3 + 1  # tokens, a guess
        upper = config.credits((est_in * quote.input + max_output_tokens * quote.output) / 1e6)
        if total + upper > max_total_credits:
            row = ProbeRow(variant.name, "skipped_ceiling")
        else:
            row = _send(_provider(variant.unmapped, profile, profile_id, project, location, client), request)
            row.variant = variant.name
            if row.status in ("ok", "ok_truncated", "blocked") and row.tokens_in == 0:
                row.tokens_in = est_in  # a truncated reply reports no input count: the estimate stands in
            row.credits = config.credits((row.tokens_in * quote.input + row.tokens_out * quote.output) / 1e6)
        total += row.credits
        rows.append(row)
        print(_row_line(row), file=out)
    print(f"total credits={total:.4f} ceiling={max_total_credits:.4f}", file=out)
    return rows


def _send(provider: Any, request: GenerateRequest) -> ProbeRow:
    try:
        response = provider.generate(request)
    except OutputTruncatedError as error:  # Google accepted the request; the small cap cut the reply
        return ProbeRow("", "ok_truncated", tokens_out=(error.output_tokens or 0) + (error.thinking_tokens or 0))
    except SafetyError:
        return ProbeRow("", "blocked")
    except Exception as error:
        code = classify(error)
        statuses = [c for c in (getattr(link, "code", None) for link in _chain(error)) if isinstance(c, int)]
        http = statuses[0] if statuses else None
        return ProbeRow(
            "", code, http=http, error=type(error).__name__, reason=_reason(error) if code == "rejected" else ""
        )
    usage = response.usage or {}
    return ProbeRow("", "ok", tokens_in=usage.get("input_tokens", 0), tokens_out=usage.get("output_tokens", 0))


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    schema: dict[str, Any],
    client: Any = None,
) -> int:
    parser = argparse.ArgumentParser(prog="live_vertex_probe_schema", description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS * 2)
    parser.add_argument("--max-credits", type=float, default=DEFAULT_MAX_CREDITS)
    parser.add_argument(
        "--dry-run", "--replay", dest="dry_run", action="store_true", help="print the plan; send nothing"
    )
    parser.add_argument("--models-file", type=Path)
    parser.add_argument("--prices-file", type=Path)
    args = parser.parse_args(argv)
    try:
        run_schema_probe(
            schema,
            environ=environ,
            models_path=args.models_file,
            prices_path=args.prices_file,
            max_output_tokens=args.max_output_tokens,
            max_total_credits=args.max_credits,
            dry_run=args.dry_run,
            client=client,
        )
    except SmokeRefused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        for key in refusal.missing:
            print(f"  confirm {key}", file=sys.stderr)
        return 2
    return 0
