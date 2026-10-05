"""tilo_providers.vertex_smoke — live Vertex AI smoke (PL-02, EFF-01; PRD 6.4, 6.5, 6.6, 14.1).

One tiny, capped call per role through the normal `Router`, so the first live call proves the whole path: config ->
router -> record-replay -> Google adapter (ADC). Refuses unless the live switch is exactly "1" (checked first, before
any config read or Google import); stops at the first failed role; spend is bounded by a credit ceiling enforced as the
router's budget. Prices come only from the prices file (PL-06). Names no model or profile id: the role-to-profile
mapping is whatever the models file says. Replay (`--replay`) serves the recordings of an earlier recorded run."""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from tilo_providers.config import (
    ProviderConfigError,
    ProvidersConfig,
    load_providers_config,
    profiles_used_by,
    resolve_models_path,
)
from tilo_providers.interfaces import GenerateRequest
from tilo_providers.replay import _AUTHORIZATION_LIKE_RE  # the recordings' own Authorization/Bearer scrub
from tilo_providers.router import BudgetExceededError, Router

SMOKE_ROLES = ("director", "lead", "specialist", "verifier", "writer", "narrator", "autopilot")
SMOKE_PROMPT = "Reply with one short sentence about a calm harbour town at sunrise, in plain words."  # fixed, synthetic
THINKING_MINIMUM = (
    None  # no thinking level: Vertex answers 400 to "minimal" for the director profile (live, 5 Oct 2026)
)
MAX_REASON_CHARS = 200  # the longest server reason printed for a "rejected" request
DEFAULT_MAX_OUTPUT_TOKENS = 64
HARD_MAX_OUTPUT_TOKENS = 256
DEFAULT_MAX_TOTAL_CREDITS = 2.0  # US$0.01 at 1 credit = US$0.005 (PRD 14.1)
HARD_MAX_TOTAL_CREDITS = 100.0  # US$0.50; orchestrator decision: the pinned live-run helper uses a 50 credit ceiling
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass
class RoleRow:  # one served call
    role: str
    profile_id: str
    fallback_from: str | None  # the primary's id when a fallback served it
    latency_ms: float
    tokens_in: int
    tokens_out: int
    credits: float


@dataclass
class SmokeReport:
    rows: list[RoleRow]
    total_credits: float
    ceiling_credits: float
    max_output_tokens: int
    mode: Literal["live", "replay"]


class SmokeRefused(Exception):  # a precondition failed; nothing was sent
    def __init__(self, code: str, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.code, self.missing = code, list(missing or [])


class SmokeFailed(Exception):  # a role failed; the rows before it are in `report`
    def __init__(self, role: str, code: str, message: str, fix: str, report: SmokeReport) -> None:
        super().__init__(message)
        self.role, self.code, self.fix, self.report = role, code, fix, report


# code -> (one-line message, one-line fix). Server text is never printed: it can echo credentials (PRD 16.1 rule 4),
# except the adapter's already-redacted reason for "rejected", scrubbed again and capped (see `_reason`).
_FAILURES = {
    "rejected": ("Google rejected a request setting", "the reason is shown above; adjust the role or profile settings"),
    "quota": ("every candidate hit its quota", "request more Vertex AI quota in the Cloud console, or retry later"),
    "permission": ("the call was denied", "grant roles/aiplatform.user on the project to the account used for ADC"),
    "api_disabled": ("the Vertex AI API is not enabled", "enable aiplatform.googleapis.com on the project"),
    "location": ("the model was not found at this location", "check GOOGLE_LOCATION (unset means global)"),
    "auth": ("no usable Application Default Credentials", "run gcloud auth application-default login"),
    "ceiling": ("the credit ceiling would be exceeded", "raise --max-credits (up to the hard limit) or lower the cap"),
    "replay_miss": ("no recording for this request", "record one with TILO_RECORD=1 on a live run first"),
    "unknown": ("the call failed", "re-run once; if it repeats, check the project, location and credentials"),
}


def _chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    while error is not None and error not in chain:
        chain.append(error)
        error = error.__cause__  # type: ignore[assignment]
    return chain


def classify(error: BaseException) -> str:
    """Failure code from a RouterError's `__cause__` chain: status code and text of each link, and class names."""
    if isinstance(error, BudgetExceededError):
        return "ceiling"
    names = {type(link).__name__ for link in _chain(error)}
    statuses = {code for code in (getattr(link, "code", None) for link in _chain(error)) if isinstance(code, int)}
    text = " ".join(str(link) for link in _chain(error)).lower()
    if "ReplayMissError" in names:
        return "replay_miss"
    if 400 in statuses:  # before the text checks: a 400's own words ("is disabled", "not_found") never decide its code
        return "rejected"
    if "DefaultCredentialsError" in names or "default credentials" in text or 401 in statuses:
        return "auth"
    if "service_disabled" in text or "has not been used" in text or "is disabled" in text:
        return "api_disabled"
    if 403 in statuses or "permission_denied" in text:
        return "permission"
    if 404 in statuses or "not_found" in text:
        return "location"
    if 429 in statuses or "QuotaError" in names or "resource_exhausted" in text:
        return "quota"
    if "RequestError" in names:
        return "rejected"
    return "unknown"


# A labelled value (a token, key, secret, signature ...) in any common shape: plain, quoted, or escaped JSON.
_SECRET_RE = re.compile(
    r"(?i)ya29\.[\w.\-]+|AIza[\w\-]{35,}"
    r"|[\w\-]*(?:token|key|secret|password|credential|signature|sig)s?\\*\"?(?:\s*[:=]\s*|\s+is\s+)\\*\"?[^\s\"\\,;&}]+"
)


def scrubbed_server_text(error: BaseException) -> str:
    """The adapter's redacted server text for a rejected request, made safe to print but not yet capped: one line, no
    control or format characters (so none can hide a label or drive the terminal), scrubbed again. A caller that
    scrubs more (a project id, a path) does that, then caps with `MAX_REASON_CHARS` (scrub before cap)."""
    said = next((str(link) for link in _chain(error) if type(link).__name__ == "_RedactedAPIError"), "")
    said = "".join(c for c in " ".join(said.split()) if unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs"))
    return _SECRET_RE.sub("[redacted]", _AUTHORIZATION_LIKE_RE.sub("[redacted]", said))


def _reason(error: BaseException) -> str:
    return scrubbed_server_text(error)[:MAX_REASON_CHARS]


def _check_caps(max_output_tokens: int, max_total_credits: float) -> None:
    if not 1 <= max_output_tokens <= HARD_MAX_OUTPUT_TOKENS:
        raise SmokeRefused("cap_out_of_range", f"--max-output-tokens must be 1..{HARD_MAX_OUTPUT_TOKENS}")
    if not 0 < max_total_credits <= HARD_MAX_TOTAL_CREDITS:
        raise SmokeRefused("cap_out_of_range", f"--max-credits must be above 0 and at most {HARD_MAX_TOTAL_CREDITS}")


def _load(
    models_path: Path | str | None, prices_path: Path | str | None, environ: Mapping[str, str]
) -> ProvidersConfig:
    models = Path(models_path) if models_path else resolve_models_path(env=environ)
    prices = Path(prices_path) if prices_path else _REPO_ROOT / "config" / "prices.yaml"
    try:
        config = load_providers_config(models, prices)
    except ProviderConfigError as error:
        raise SmokeRefused("config_invalid", f"the models or prices file did not load: {error}") from None
    absent = [role for role in SMOKE_ROLES if role not in config.roles]
    if absent:
        raise SmokeRefused("config_invalid", f"the models file has no role {absent[0]!r}")
    return config


def _check_prices(config: ProvidersConfig) -> None:
    if config.prices.status == "set":
        return
    used = sorted({p for role in SMOKE_ROLES for p in profiles_used_by(config.roles[role])})
    missing = ["status", "effective_date", "source", *(f"{p}.{side}" for p in used for side in ("input", "output"))]
    raise SmokeRefused(
        "prices_unset",
        "config/prices.yaml is unset: confirm these values from the provider's price page, then set status to set",
        missing,
    )


def run_vertex_smoke(
    *,
    environ: Mapping[str, str] | None = None,
    models_path: Path | str | None = None,
    prices_path: Path | str | None = None,
    fixtures_dir: Path | str | None = None,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_total_credits: float = DEFAULT_MAX_TOTAL_CREDITS,
    replay: bool = False,
) -> SmokeReport:
    environ = os.environ if environ is None else environ
    if replay:  # never goes live: the router reads os.environ, so both views must be off
        if environ.get("LIVE") == "1" or os.environ.get("LIVE") == "1":
            raise SmokeRefused("replay_with_live", "--replay never runs with the live switch on")
    elif environ.get("LIVE") != "1":  # first and only thing looked at
        raise SmokeRefused("live_not_enabled", "set LIVE to exactly 1 to make real (paid) calls; nothing was sent")
    _check_caps(max_output_tokens, max_total_credits)
    config = _load(models_path, prices_path, environ)
    if not replay:  # the router and the SDK read os.environ, so these checks look there (and in `environ` for keys)
        for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
            if environ.get(name) or os.environ.get(name):
                raise SmokeRefused("api_key_present", f"{name} is set; remove it, the smoke uses ADC only")
        if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
            raise SmokeRefused("missing_project", "GOOGLE_CLOUD_PROJECT is not set")
    _check_prices(config)
    if not replay:  # still before any client exists; imported late so replay and refusals never load the adapter
        from tilo_providers.google_adapter import GoogleSettingsError, validate_google_settings  # noqa: PLC0415

        try:
            validate_google_settings(
                os.environ["GOOGLE_CLOUD_PROJECT"], os.environ.get("GOOGLE_LOCATION", "global"), os.environ
            )
        except GoogleSettingsError as error:
            raise SmokeRefused(error.code, str(error)) from None

    report = SmokeReport([], 0.0, float(max_total_credits), max_output_tokens, "replay" if replay else "live")
    router = Router(config, fixtures_dir=Path(fixtures_dir) if fixtures_dir else _REPO_ROOT / "fixtures")
    for role in SMOKE_ROLES:
        primary = config.roles[role].primary
        request = GenerateRequest(
            prompt=SMOKE_PROMPT, max_output_tokens=max_output_tokens, thinking_level=THINKING_MINIMUM
        )

        def fail(code: str, role: str = role, message: str | None = None) -> SmokeFailed:
            text, fix = _FAILURES[code]
            return SmokeFailed(role, code, message or text, fix, report)

        try:
            result = router.generate(role, request, budget=max(report.ceiling_credits - report.total_credits, 0.0))
        except Exception as error:
            code = classify(error)
            reason = _reason(error) if code == "rejected" else ""
            raise fail(code, message=f"{_FAILURES[code][0]}: {reason}" if reason else None) from None
        served = next((a for a in reversed(result.attempts) if a.outcome == "ok"), None)
        usage = result.response.usage if result.response else None
        if served is None or not usage or "input_tokens" not in usage or "output_tokens" not in usage:
            raise fail("unknown", message="the reply was blocked or carried no token usage")
        quote = config.price(served.profile_id)
        credits = config.credits((usage["input_tokens"] * quote.input + usage["output_tokens"] * quote.output) / 1e6)
        fallback_from = primary if served.profile_id != primary else None
        row = RoleRow(role, served.profile_id, fallback_from, served.latency_ms, *_tokens(usage), credits)
        report.rows.append(row)
        report.total_credits += credits
    return report


def _tokens(usage: Mapping[str, int]) -> tuple[int, int]:
    return usage["input_tokens"], usage["output_tokens"]


def _print_report(report: SmokeReport) -> None:
    for row in report.rows:
        tail = f" fallback_from={row.fallback_from}" if row.fallback_from else ""
        print(
            f"role={row.role} profile={row.profile_id} latency_ms={row.latency_ms:.1f} tokens_in={row.tokens_in} "
            f"tokens_out={row.tokens_out} credits={row.credits:.4f}{tail}"
        )
    print(f"total credits={report.total_credits:.4f} ceiling={report.ceiling_credits:.4f}")


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="live_vertex_smoke", description=__doc__.split("\n\n")[0])
    parser.add_argument("--max-output-tokens", type=int, default=DEFAULT_MAX_OUTPUT_TOKENS)
    parser.add_argument("--max-credits", type=float, default=DEFAULT_MAX_TOTAL_CREDITS)
    parser.add_argument("--replay", action="store_true", help="serve recordings; never goes live")
    parser.add_argument("--models-file", type=Path)
    parser.add_argument("--prices-file", type=Path)
    parser.add_argument("--fixtures-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        report = run_vertex_smoke(
            environ=environ,
            models_path=args.models_file,
            prices_path=args.prices_file,
            fixtures_dir=args.fixtures_dir,
            max_output_tokens=args.max_output_tokens,
            max_total_credits=args.max_credits,
            replay=args.replay,
        )
    except SmokeRefused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        for key in refusal.missing:
            print(f"  confirm {key}", file=sys.stderr)
        return 2
    except SmokeFailed as failure:
        _print_report(failure.report)
        print(f"FAIL role={failure.role} reason={failure.code}: {failure} Fix: {failure.fix}", file=sys.stderr)
        return 1
    _print_report(report)
    return 0
