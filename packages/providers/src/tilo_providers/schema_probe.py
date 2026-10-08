"""tilo_providers.schema_probe — which part of a Director request does Vertex AI refuse? (PL-02, EFF-01).

One tiny capped call per request variant on the Director role's primary profile, straight through the Google adapter on
user ADC. First, when the caller passes the real Director brief request (`director=`), the `director_*` variants:
`director_exact` replays it (the adapter's own config: system prompt, JSON mode, sanitized schema, no thinking config;
short task text, small output cap); if Google rejects it, one variant per suspicious field removed runs, so a single
run pins the 400 on a field; if Google accepts it, they are skipped and `director_exact_real_cap` tries the role's
real output cap (quoted first: over the default ceiling it is not sent). Each variant edits a copy of what
`GoogleModelProvider._config_kwargs` builds, never a hand copy. Then the older variants: (a) no schema, (b) JSON mode
only, (c) the sanitized schema, (d) the raw schema, plus three thinking-config variants. One status line per variant
(ok / ok_truncated / rejected with the HTTP status / another failure code / skipped_*), then the cost. Prints no prompt
and no schema; for a 400 it prints the server's scrubbed, capped reason (`vertex_smoke`), check it before pasting.
Every call is quoted before it is made and skipped if the quote would take the total over the ceiling. Same gate as
`vertex_smoke`: refused unless the live switch is exactly "1", checked first; `--dry-run` (alias `--replay`) prints the
plan and sends nothing. The schema and the Director request are passed in by the caller, so this package does not
import the planner. Prices come only from the prices file (PL-06); no model id is named here."""

from __future__ import annotations

import argparse
import copy
import os
import sys
from collections.abc import Callable, Mapping
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
DEFAULT_MAX_CREDITS = 2.0  # ceiling: the older seven cost about 0.1 credit, an accepted director call about 0.4
ROUTER_DEFAULT_OUT = 1024  # the Router's own default when neither the request nor the role names a cap (BQ-63)
ACCEPTED = frozenset({"ok", "ok_truncated", "blocked"})  # Google took the request; a 400 is "rejected"

Edit = Callable[[dict[str, Any]], dict[str, Any]]


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


# --- the exact Director request and its one-field-removed variants (PL-02 follow-up 3) ----------------------------


def _each_schema(node: Any, change: Callable[[dict[str, Any]], dict[str, Any]]) -> Any:
    """`change` applied to every sub-schema, innermost first; property names are never read as keywords."""
    if not isinstance(node, dict):
        return node
    out = dict(node)
    for key in ("properties", "$defs"):
        if isinstance(out.get(key), dict):
            out[key] = {name: _each_schema(sub, change) for name, sub in out[key].items()}
    if isinstance(out.get("anyOf"), list):
        out["anyOf"] = [_each_schema(branch, change) for branch in out["anyOf"]]
    if "items" in out:
        out["items"] = _each_schema(out["items"], change)
    return change(out)


def _drop_empty(node: dict[str, Any]) -> dict[str, Any]:
    """The property that used to be an untyped `{}` (the Director's `out_of_scope`, now sent as a typed list) removed,
    and any property still schema-less, also from `required`."""
    properties = node.get("properties")
    if isinstance(properties, dict) and (empty := {n for n, s in properties.items() if s == {} or n == "out_of_scope"}):
        node["properties"] = {n: s for n, s in properties.items() if n not in empty}
        if isinstance(node.get("required"), list):
            node["required"] = [n for n in node["required"] if n not in empty]
    return node


def _no_null_branch(node: dict[str, Any]) -> dict[str, Any]:
    """`nullable: true` (what the sanitizer sends for `anyOf: [X, {"type": "null"}]`) removed, and any leftover null
    `anyOf` branch collapsed to X."""
    node = {k: v for k, v in node.items() if k != "nullable"}
    branches = node.get("anyOf")
    if isinstance(branches, list):
        kept = [branch for branch in branches if branch != {"type": "null"}]
        if len(kept) == 1 < len(branches) and isinstance(kept[0], dict):
            return {**{k: v for k, v in node.items() if k != "anyOf"}, **kept[0]}
    return node


def _without(*keywords: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    return lambda node: {k: v for k, v in node.items() if k not in keywords}


def _schema_edit(change: Callable[[dict[str, Any]], dict[str, Any]]) -> Edit:
    def edit(kwargs: dict[str, Any]) -> dict[str, Any]:
        if isinstance(kwargs.get("response_json_schema"), dict):
            kwargs["response_json_schema"] = _each_schema(copy.deepcopy(kwargs["response_json_schema"]), change)
        return kwargs

    return edit


def _pop(field: str) -> Edit:
    return lambda kwargs: {k: v for k, v in kwargs.items() if k != field}


def _system_without_role(kwargs: dict[str, Any]) -> dict[str, Any]:
    """The SDK sends a string system instruction with role "user"; a `Content` without a role goes out without one."""
    if isinstance(kwargs.get("system_instruction"), str):
        from tilo_providers.google_adapter import _genai_module  # noqa: PLC0415  # dry runs never load the SDK

        types_mod = _genai_module("google.genai.types")
        part = types_mod.Part(text=kwargs["system_instruction"])
        kwargs = {**kwargs, "system_instruction": types_mod.Content(parts=[part])}
    return kwargs


@dataclass(frozen=True)
class DirectorVariant:
    name: str
    change: str  # what differs from `director_exact`, for the plan line (never prompt or schema text)
    edit: Edit | None = None
    real_cap: bool = False


DIRECTOR_VARIANTS = (
    DirectorVariant("director_exact", "none (short task text, small output cap)"),
    DirectorVariant("director_no_system", "system_instruction removed", _pop("system_instruction")),
    DirectorVariant("director_system_no_role", "system_instruction sent without role", _system_without_role),
    DirectorVariant("director_no_schema", "response_json_schema removed, JSON mode kept", _pop("response_json_schema")),
    DirectorVariant("director_schema_no_empty", "untyped {} properties removed", _schema_edit(_drop_empty)),
    DirectorVariant("director_schema_no_null_anyof", "anyOf [X, null] sent as X", _schema_edit(_no_null_branch)),
    DirectorVariant(
        "director_schema_no_titles", "title and description removed", _schema_edit(_without("title", "description"))
    ),
    DirectorVariant(
        "director_schema_no_item_bounds",
        "minItems and maxItems removed",
        _schema_edit(_without("minItems", "maxItems")),
    ),
    DirectorVariant("director_exact_real_cap", "the role's real output cap", real_cap=True),
)
DIRECTOR_VARIANT_NAMES = tuple(v.name for v in DIRECTOR_VARIANTS)


def _dependent_status(variant: DirectorVariant, exact: str) -> str | None:
    """None when `variant` runs, given the exact replay's status; else why it is skipped."""
    if exact == "skipped_ceiling":
        return "skipped_ceiling"
    if exact not in ACCEPTED and exact != "rejected":  # auth, quota, ...: no field can be blamed
        return "skipped_exact_failed"
    if variant.real_cap:  # the cap matters only once the small-cap replay is accepted
        return None if exact in ACCEPTED else "skipped_exact_rejected"
    return None if exact == "rejected" else "skipped_exact_accepted"


@dataclass
class ProbeRow:
    variant: str
    status: str  # ok | ok_truncated | blocked | skipped_* | a `vertex_smoke` failure code
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


def _director_plan_line(variant: DirectorVariant, cap: int) -> str:
    return f'variant={variant.name} base=director_exact change="{variant.change}" max_output_tokens={cap}'


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


def _provider(
    raw: bool, profile: Any, profile_id: str, project: str, location: str, client: Any, edit: Edit | None = None
) -> Any:
    from tilo_providers.google_adapter import GoogleModelProvider  # noqa: PLC0415  # dry runs never load the adapter

    class _Probe(GoogleModelProvider):
        def _schema_for_send(self, schema: dict[str, Any]) -> dict[str, Any]:
            # raw: variant (d), what the adapter sent before the fix
            return copy.deepcopy(schema) if raw else super()._schema_for_send(schema)

        def _thinking_for_send(self, level: str) -> str:
            return level if raw else super()._thinking_for_send(level)  # raw: minimal stays minimal

        def _config_kwargs(self, request: GenerateRequest) -> dict[str, Any]:
            kwargs = super()._config_kwargs(request)  # the real send's fields; a director variant edits a copy
            return edit(dict(kwargs)) if edit is not None else kwargs

    return _Probe(profile, profile_id, project, location, client=client)


def run_schema_probe(
    schema: dict[str, Any],
    *,
    director: GenerateRequest | None = None,  # the real Director brief request (`tilo_planning.brief.brief_request`)
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
    # The Router's rule (BQ-63): the request's own cap, else the role's, else its default.
    real_cap = (director.max_output_tokens if director else None) or config.roles[PROBE_ROLE].max_output_tokens
    real_cap = real_cap or ROUTER_DEFAULT_OUT
    directors = DIRECTOR_VARIANTS if director is not None else ()
    header = (
        f"probe role={PROBE_ROLE} profile={profile_id} max_output_tokens={max_output_tokens} "
        f"ceiling={max_total_credits:.4f}"
    )
    if dry_run:
        print(header, file=out)
        for dv in directors:
            print(f"{_director_plan_line(dv, real_cap if dv.real_cap else max_output_tokens)} (dry-run)", file=out)
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

    def attempt(name: str, request: GenerateRequest, est_in: int, raw: bool = False, edit: Edit | None = None) -> None:
        nonlocal total
        cap = request.max_output_tokens or 0
        upper = config.credits((est_in * quote.input + cap * quote.output) / 1e6)  # quoted before the call
        if total + upper > max_total_credits:
            row = ProbeRow(name, "skipped_ceiling")
        else:
            row = _send(_provider(raw, profile, profile_id, project, location, client, edit), request)
            row.variant = name
            if row.status in ACCEPTED and row.tokens_in == 0:
                row.tokens_in = est_in  # a truncated reply reports no input count: the estimate stands in
            row.credits = config.credits((row.tokens_in * quote.input + row.tokens_out * quote.output) / 1e6)
        total += row.credits
        rows.append(row)
        print(_row_line(row), file=out)

    if director is not None:
        from tilo_providers.router import _input_text  # noqa: PLC0415  # what the Router measures for a request

        exact = "skipped_ceiling"
        for dv in DIRECTOR_VARIANTS:
            skip = None if dv.name == "director_exact" else _dependent_status(dv, exact)
            if skip is not None:
                rows.append(ProbeRow(dv.name, skip))
                print(_row_line(rows[-1]), file=out)
                continue
            request = director.model_copy(update={"max_output_tokens": real_cap if dv.real_cap else max_output_tokens})
            attempt(dv.name, request, len(_input_text(request, request.prompt)) // 3 + 1, edit=dv.edit)
            if dv.name == "director_exact":
                exact = rows[-1].status
    for variant in VARIANTS:
        request = GenerateRequest(
            prompt=PROBE_PROMPT,
            max_output_tokens=max_output_tokens,
            json_mode=variant.json_mode,
            response_schema=schema if variant.schema else None,
            thinking_level=variant.thinking,
        )
        est_in = (len(PROBE_PROMPT) + (len(repr(schema)) if variant.schema else 0)) // 3 + 1  # tokens, a guess
        attempt(variant.name, request, est_in, raw=variant.unmapped)
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
    director: GenerateRequest | None = None,
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
            director=director,
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
