"""The live scenario generator (issue #272 (b), GEN-07..GEN-10; PRD 6.6 EFF-01, 14 metering, 16.3, 19.3; interface:
`evals/tests/API_GEN_07_10.md`).

`python -m tilo_evals generate --n N` asks the `generator` role (config/models.yaml, through the provider layer; this
module names no model) for N new briefs, treats each as untrusted input (shape, length, language, near-duplicate, safety
screen), runs every kept brief once through the real pipeline exactly as `live_e2e` does, and writes it as a bank case
holding the Director's own redacted replies, so `python -m tilo_evals bank --bank <folder>` replays it offline later.
One `autorater` call per kept case scores plan fit and question usefulness; those scores are reported apart, labelled
live, and never count toward GEN-03. The whole run shares one Router budget (PL-03): nothing over the cap is ever sent.
Only the user runs it: it refuses without `LIVE=1`, in CI and when deployed, before any provider, screen or file.
"""

from __future__ import annotations

import datetime
import json
import math
import os
import re
import tempfile
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import jsonschema
import yaml
from tilo_providers.config import ProviderConfigError, ProvidersConfig
from tilo_providers.interfaces import GenerateRequest, ModelProvider, SafetyProvider
from tilo_providers.prompts import load_prompt, neutralise_marker
from tilo_providers.safety import build_safety_provider

from .bank import BANK_SCHEMA_PATH, BankCase
from .bank_checks import Finding, check_case, hard_findings
from .bank_run import DEFAULT_CAP
from .config import CappedError, read_yaml
from .live_e2e import (
    _PROMPT_TOKENS,
    _REPO,
    Estimate,
    LiveE2ERefused,
    Row,
    _estimate_chars,
    _execute,
    _gate,
    _load_config,
    _Meter,
    _MeteredRouter,
    _Providers,
    _scrub_known,
    _stage,
    _vertex,
)

GENERATOR_ROLE, AUTORATER_ROLE = "generator", "autorater"
MAX_BRIEF, MAX_TITLE, DUPLICATE_JACCARD = 4000, 120, 0.8  # the bank schema's own limits; word-set Jaccard of a copy
DEFAULT_SETTINGS = _REPO / "evals" / "generator.yaml"
SETTINGS_SCHEMA = _REPO / "evals" / "generator.schema.json"
KEPT_CLASSES = frozenset({"completed", "held_at_gate", "refused", "needs_answers"})  # the bank's four outcome classes
_GEN_OUT = (500, 500)  # output cap of the generator call: per brief, plus a base (thinking tokens count against it)
_RATER_OUT, _RATER_CHARS = 200, 6000
SCOPE = (
    "Claim scope: each case is one unseen, model-written brief run once through the real pipeline on the live "
    "models, so a pass means the pipeline stayed valid and honest on that brief, nothing more. Plan quality is only "
    "what the autorater section below says, from a single model's judgement. Neither is a statement that Tilo "
    "handles any scenario."
)
SCORES_NOTE = (
    "These scores come from a live model judging each plan against its brief. They are not counted as passes, and "
    "they never change the structural results above, the outcome classes, the written cases or the exit code."
)


class GenerateRefused(Exception):
    """A gate or argument refusal; nothing was sent and nothing was written."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(" ".join(message.split()))
        self.code = code


@dataclass(frozen=True)
class Rejection:
    index: int  # position in the model's list
    reason: str  # invalid | length | language | duplicate | safety (or, for an unfinished run, its outcome class)
    detail: str = ""


@dataclass
class GeneratedCase:
    id: str
    path: Path
    outcome_class: str
    findings: list[Finding] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # the domain, then the shapes


@dataclass
class GenerateReport:
    requested: int
    date: str
    cap_credits: float
    cap_inr: float
    inr_per_usd: float
    estimate: Estimate
    credit_usd: float = 0.005
    total_credits: float = 0.0
    stopped_at_cap: bool = False
    reply_unusable: bool = False  # the generator's reply held no usable list of briefs (not a cap stop)
    cases: list[GeneratedCase] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)  # briefs that failed validation, never run
    unfinished: list[Rejection] = field(default_factory=list)  # kept briefs whose run did not reach a bank class
    live_scores: dict[str, dict[str, float]] = field(default_factory=dict)
    hard_findings: list[Finding] = field(default_factory=list)  # of the generated runs only; scores never feed it
    rows: list[Row] = field(default_factory=list)


class _CapturingRouter(_MeteredRouter):
    """Notes the last reply of each Director request kind: what the run saw is what the case file will script."""

    replies: dict[str, Any]

    def generate(self, role_id: str, request: GenerateRequest, **kwargs: Any) -> Any:
        result = super().generate(role_id, request, **kwargs)
        if role_id == "director" and result.response is not None and result.response.text:
            kind = {"intake": "brief"}.get(_stage(role_id, request), _stage(role_id, request))
            try:
                reply = json.loads(result.response.text)
            except ValueError:
                return result
            self.replies[kind] = reply if isinstance(reply, dict) else None
        return result


# --- settings, cap and estimate ---------------------------------------------------------------------------------


def _settings(path: Path | None, max_inr: float | None) -> tuple[float, float]:
    """(max_inr, inr_per_usd) from the settings file, checked against its schema; `max_inr` overrides the file's."""
    file = Path(path) if path else DEFAULT_SETTINGS
    try:
        raw = read_yaml(file, CappedError)
        jsonschema.Draft202012Validator(json.loads(SETTINGS_SCHEMA.read_text(encoding="utf-8"))).validate(raw)
    except (CappedError, jsonschema.ValidationError) as error:
        raise GenerateRefused("settings_invalid", f"the generator settings did not load: {error}") from None
    cap = float(raw["max_inr"] if max_inr is None else max_inr)
    if not (math.isfinite(cap) and cap > 0 and math.isfinite(raw["inr_per_usd"])):
        raise GenerateRefused("cap_out_of_range", "--max-inr and the settings' rates must be finite and above 0")
    return cap, float(raw["inr_per_usd"])


def _estimate(config: ProvidersConfig, n: int) -> Estimate:
    """Before any call: one generator call, N runs of a short or a maximum-length brief, N autorater calls."""

    def credits(role: str, tokens_in: int, tokens_out: int) -> float:
        quote = config.price(config.roles[role].primary)
        return config.credits((tokens_in * quote.input + tokens_out * quote.output) / 1e6)

    short, long_ = _estimate_chars(config, 400), _estimate_chars(config, MAX_BRIEF)
    low = credits(GENERATOR_ROLE, _PROMPT_TOKENS, 150 * n) + credits(AUTORATER_ROLE, 800, 30) * n
    high = credits(GENERATOR_ROLE, _PROMPT_TOKENS, _GEN_OUT[0] * n + _GEN_OUT[1])
    high += credits(AUTORATER_ROLE, _PROMPT_TOKENS + _RATER_CHARS // 3, _RATER_OUT) * n
    return Estimate(low + n * short.credits_low, high + n * long_.credits_high)


# --- the brief list: what exists, what the model sent, what is kept -------------------------------------------------


def _existing(bank_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    """Every case file of the bank and of earlier generations (raw mappings: brief, domain, shapes)."""
    found = []
    for path in sorted([*bank_dir.glob("*.yaml"), *out_dir.glob("*/*.yaml")]):
        try:
            raw = read_yaml(path, CappedError)
        except CappedError:
            continue
        if isinstance(raw, dict):
            found.append(raw)
    return found


def _next_number(out_dir: Path) -> int:
    numbers = [int(m[1]) for p in out_dir.glob("*/G-*.yaml") if (m := re.fullmatch(r"G-(\d+)", p.stem))]
    return max(numbers, default=0) + 1


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"\w+", text.lower()))


def _near(a: frozenset[str], b: frozenset[str]) -> bool:
    return len(a & b) / len(a | b) >= DUPLICATE_JACCARD if a | b else False


def _screened(safety: SafetyProvider, text: str) -> bool:
    """True when the screen passes the text; a screen that raised cannot vouch for it, so fail closed (PRD 16.3)."""
    try:
        return not safety.check(text)["flagged"]
    except Exception:  # noqa: BLE001 - any failure of the screen is a refusal, never a pass
        return False


def _entry(raw: Any, matrix: tuple[list[str], list[str]]) -> tuple[dict[str, Any] | None, Rejection | None]:
    """The cleaned entry, or why it is invalid, too long or not text (checked in that order)."""
    domains, shapes = matrix
    if not isinstance(raw, dict):
        return None, Rejection(0, "invalid", "not an object")
    title, brief, shape = raw.get("title"), raw.get("brief"), raw.get("shapes")
    shapes_ok = isinstance(shape, list) and bool(shape) and all(isinstance(s, str) and s in shapes for s in shape)
    if not (isinstance(title, str) and title.strip() and isinstance(brief, str) and shapes_ok):
        return None, Rejection(0, "invalid", "missing or unknown title, brief, domain or shapes")
    if raw.get("domain") not in domains:
        return None, Rejection(0, "invalid", "missing or unknown title, brief, domain or shapes")
    text = brief.strip()
    if not text or len(text) > MAX_BRIEF:
        return None, Rejection(0, "length", f"{len(text)} characters (1 to {MAX_BRIEF} allowed)")
    odd = any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in f"{title}{text}")
    if odd or not any(c.isalpha() for c in text):
        return None, Rejection(0, "language", "no letters, or a control character")
    cleaned = {"title": " ".join(title.split())[:MAX_TITLE], "domain": raw["domain"], "brief": text}
    return {**cleaned, "shapes": list(dict.fromkeys(shape or []))}, None


def _validated(
    entries: list[Any],
    n: int,
    existing: list[dict[str, Any]],
    safety: SafetyProvider,
    matrix: tuple[list[str], list[str]],
) -> tuple[list[tuple[int, dict[str, Any]]], list[Rejection]]:
    """At most `n` kept entries as (position, entry), in order, and every rejection before the n-th was kept."""
    seen = [_words(str(e.get("brief", ""))) for e in existing]
    kept: list[tuple[int, dict[str, Any]]] = []
    rejected: list[Rejection] = []
    for index, raw in enumerate(entries):
        if len(kept) >= n:
            break
        entry, why = _entry(raw, matrix)
        if entry is not None:
            words = _words(entry["brief"])
            if any(_near(words, old) for old in seen):
                entry, why = None, Rejection(0, "duplicate", "a near copy of an existing or earlier brief")
            elif not _screened(safety, entry["brief"]):
                entry, why = None, Rejection(0, "safety", "flagged by the safety screen, or the screen could not run")
        if entry is None and why is not None:
            rejected.append(replace(why, index=index))
        elif entry is not None:
            kept.append((index, entry))
            seen.append(_words(entry["brief"]))
    return kept, rejected


def _briefs_from(text: str | None) -> list[Any] | None:
    """The model's `briefs` list from its reply (untrusted: any JSON object inside the text), or None."""
    body = text or ""
    try:
        reply = json.loads(body[body.find("{") : body.rfind("}") + 1])
    except ValueError:
        return None
    briefs = reply.get("briefs") if isinstance(reply, dict) else None
    return briefs if isinstance(briefs, list) and briefs else None


def _coverage(existing: list[dict[str, Any]], matrix: tuple[list[str], list[str]]) -> str:
    """Tags only, never text: for each domain, how many cases carry each shape."""
    count = Counter((e.get("domain"), s) for e in existing for s in e.get("shapes") or [] if isinstance(s, str))
    lines = []
    for domain in matrix[0]:
        tags = [f"{shape} {count[(domain, shape)]}" for shape in matrix[1] if count[(domain, shape)]]
        lines.append(f"- {domain}: {', '.join(tags) or 'none yet'}")
    return "\n".join(lines)


# --- the case file ----------------------------------------------------------------------------------------------


class _Dumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:
        return True  # the bank loader refuses aliases


def _write_case(folder: Path, case: BankCase, director: dict[str, Any], grant: float) -> Path:
    doc: dict[str, Any] = {
        "id": case.id,
        "title": case.title,
        "domain": case.domain,
        "shapes": list(case.shapes),
        "brief": case.brief,
        "director": director,
        "expect": {"outcome": case.outcome},
        "notes": "Generated live by `tilo_evals generate`; replays offline. Not part of the frozen bank.",
    }
    if grant != DEFAULT_CAP:
        doc["approve"] = {"cap": grant}  # the cap the live run was granted, so the replay is granted the same
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{case.id}.yaml"
    path.write_bytes(yaml.dump(doc, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120).encode("utf-8"))
    return path


def _score(router: _MeteredRouter, brief: str, director: dict[str, Any]) -> dict[str, float] | None:
    """The autorater's two scores for one case, or None (a failing role, a cap stop or an unusable reply)."""
    plan = director.get("plan") or {}
    run = json.dumps(
        {
            "reading": director.get("brief"),
            "units": [{k: u.get(k) for k in ("id", "title", "role", "depends_on")} for u in plan.get("units", [])],
        },
        sort_keys=True,
    )[:_RATER_CHARS]
    prompt = load_prompt(
        AUTORATER_ROLE,
        "plan_fit.md",
        {"brief": neutralise_marker(brief, "BRIEF"), "run": neutralise_marker(run, "RUN")},
    )
    request = GenerateRequest(prompt=prompt, max_output_tokens=_RATER_OUT, json_mode=True, thinking_level="minimal")
    try:
        text = router.generate(AUTORATER_ROLE, request).response.text or ""  # type: ignore[union-attr]
        reply = json.loads(text[text.find("{") : text.rfind("}") + 1])
        scores = {k: reply[k] for k in ("plan_fit", "question_usefulness")}
    except Exception:  # noqa: BLE001 - an unscored case, never a failed run
        return None
    ok = all(isinstance(v, int | float) and not isinstance(v, bool) and 0 <= v <= 1 for v in scores.values())
    return {k: float(v) for k, v in scores.items()} if ok else None


# --- the run ----------------------------------------------------------------------------------------------------


def run_generate(
    n: int,
    *,
    mode: Literal["live", "dry-run"] = "live",
    max_inr: float | None = None,
    environ: Mapping[str, str] | None = None,
    bank_dir: Path | None = None,
    out_dir: Path | None = None,
    settings_path: Path | None = None,
    models_path: Path | None = None,
    prices_path: Path | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,
    today: datetime.date | None = None,
    announce: Callable[[Estimate, float], None] | None = None,
) -> GenerateReport:
    env = os.environ if environ is None else environ
    live = mode == "live"
    try:
        _gate(mode, env, None)  # first of all: before any file, provider or screen
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise GenerateRefused("bad_arguments", "--n must be a whole number of at least 1")
        cap_inr, rate = _settings(settings_path, max_inr)
        config = _load_config(models_path, prices_path, env, (GENERATOR_ROLE, AUTORATER_ROLE))
        factory = (live_provider_factory or _vertex(config)) if live else None
    except LiveE2ERefused as refusal:
        raise GenerateRefused(refusal.code, str(refusal)) from None
    cap, estimate = config.credits(cap_inr / rate), _estimate(config, n)
    day = (today or datetime.datetime.now(datetime.UTC).date()).isoformat()
    report = GenerateReport(n, day, cap, cap_inr, rate, estimate, credit_usd=config.prices.credit_usd)
    if not live:
        if announce is not None:
            announce(estimate, cap)
        return report  # a dry run builds no provider, calls no screen and writes nothing
    with tempfile.TemporaryDirectory() as scratch:  # recordings are never kept: the case file is the record
        try:
            screen = safety or build_safety_provider(config, fixtures_dir=scratch)
        except ProviderConfigError as error:  # the stock `safety` role is the dev fake, refused when live (FR-INT-02)
            raise GenerateRefused("safety_unavailable", f"no safety screen for generated briefs: {error}") from None
        if announce is not None:
            announce(estimate, cap)  # before any model call
        _live(report, n, config, env, Path(scratch), factory, screen, bank_dir, out_dir)
    return report


def _live(
    report: GenerateReport,
    n: int,
    config: ProvidersConfig,
    env: Mapping[str, str],
    scratch: Path,
    factory: Callable[[str, str], ModelProvider] | None,
    screen: SafetyProvider,
    bank_dir: Path | None,
    out_dir: Path | None,
) -> None:
    bank, out = Path(bank_dir or _REPO / "evals" / "bank"), Path(out_dir or _REPO / "evals" / "generated")
    schema = json.loads(BANK_SCHEMA_PATH.read_text(encoding="utf-8"))["properties"]
    matrix = (schema["domain"]["enum"], schema["shapes"]["items"]["enum"])
    existing = _existing(bank, out)
    meter = _Meter(config, report.cap_credits)
    router = _CapturingRouter(config, meter, _Providers(config, meter, scratch, factory))
    router.replies = {}
    prompt = load_prompt(
        GENERATOR_ROLE,
        "briefs.md",
        {
            "n": str(n),
            "domains": ", ".join(matrix[0]),
            "shapes": ", ".join(matrix[1]),
            "coverage": _coverage(existing, matrix),
        },
    )
    request = GenerateRequest(
        prompt=prompt, max_output_tokens=_GEN_OUT[0] * n + _GEN_OUT[1], json_mode=True, thinking_level="low"
    )
    try:
        entries = _briefs_from(router.generate(GENERATOR_ROLE, request).response.text)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 - a cap stop or a failing role: the reply is unusable, never a crash
        entries = None
    kept: list[tuple[int, dict[str, Any]]] = []
    if entries is None:
        report.reply_unusable = not meter.stop
    else:
        kept, report.rejected = _validated(entries, n, existing, screen, matrix)
    grant, number, runs = min(DEFAULT_CAP, report.cap_credits), _next_number(out), {}
    for index, entry in kept:
        meter.failure = None
        case = BankCase(
            id=f"G-{number:03d}",
            title=entry["title"],
            domain=entry["domain"],
            shapes=tuple(entry["shapes"]),
            brief=entry["brief"],
            director={},
            expect={"outcome": "completed"},
            path=Path("."),
            approve={"cap": grant},
        )
        router.replies.clear()
        obs, outcome, reason, _, _ = _execute(case, router, meter, screen, env, live=True, cap=grant, narrate=False)
        if outcome == "rejected" and obs.outcome == "refused":  # a Director that stopped honestly: the pipeline said so
            outcome = "refused"
        if outcome not in KEPT_CLASSES:
            said = _scrub_known(" ".join((reason or "").split()), env)[:200]
            report.unfinished.append(Rejection(index, outcome, said))
            if meter.stop:
                break
            continue
        director = {k: router.replies.get(k) for k in ("brief", "approaches", "plan")}
        obs.case = replace(obs.case, director=director, expect={"outcome": outcome})
        found = check_case(obs)
        path = _write_case(out / report.date, obs.case, director, grant)
        report.cases.append(GeneratedCase(case.id, path, outcome, found, [case.domain, *case.shapes]))
        report.hard_findings += hard_findings(found)
        runs[case.id], number = (case.brief, director), number + 1
        if meter.stop:
            break
    for made in report.cases:  # last, so a cap that runs out costs the scores and never a case
        if not meter.stop and (scores := _score(router, *runs[made.id])) is not None:
            report.live_scores[made.id] = scores
        meter.failure = None
    report.stopped_at_cap = bool(meter.stop and meter.stop[0] == "stopped_at_cap")
    report.total_credits, report.rows = meter.total, list(meter.rows.values())


def exit_code(report: GenerateReport) -> int:
    """0 ran with at least one case and no hard finding; 1 a hard check failed or no case was written; 3 the cap."""
    if report.stopped_at_cap:
        return 3
    return 0 if report.cases and not report.hard_findings else 1


# --- the report -------------------------------------------------------------------------------------------------


def render_report(report: GenerateReport) -> str:
    kept, hard = len(report.cases), report.hard_findings
    clean = sum(1 for c in report.cases if not hard_findings(c.findings))
    lines = ["# Generated scenario cases", "", SCOPE, ""]
    lines += [f"**{kept} of {report.requested} requested briefs were kept, run live and written** ({report.date}).", ""]
    if report.reply_unusable:
        lines += ["The generator's reply held no usable list of briefs, so nothing was run.", ""]
    if report.stopped_at_cap:
        lines += ["**The run stopped at its credit cap**: nothing over the cap was sent; later work was not done.", ""]
    if kept:
        pct = f" ({clean / kept:.0%})" if kept else ""
        lines += [f"{clean} of {kept} kept cases pass every hard check{pct}.", ""]
    lines += ["## Outcome classes", ""]
    outcomes = Counter(c.outcome_class for c in report.cases)
    lines += [f"- {name}: {count}" for name, count in sorted(outcomes.items())] or ["- none"]
    lines += ["", "## Failures by cause (hard checks)", ""]
    lines += [f"- {c}: {k}" for c, k in Counter(f.check for f in hard).most_common()] or ["- none"]
    lines += [f"- {c.id} [{f.check}]: {f.detail}" for c in report.cases for f in c.findings if f.hard]
    lines += ["", "## Briefs not kept", ""]
    causes = Counter(r.reason for r in report.rejected)
    lines += [f"- rejected, {why}: {count}" for why, count in sorted(causes.items())]
    lines += [f"- rejected brief {r.index + 1}, {r.reason}: {r.detail}" for r in report.rejected]
    lines += [f"- run not finished, brief {r.index + 1}, {r.reason}: {r.detail}" for r in report.unfinished]
    lines += [] if report.rejected or report.unfinished else ["- none"]
    lines += ["", "## Cost", ""]
    lines += [f"- credits used: {report.total_credits:.4f} of a cap of {report.cap_credits:.4f}"]
    lines += [
        f"- cap: INR {report.cap_inr:g} at {report.inr_per_usd:g} INR per US dollar, US${report.credit_usd:g} a credit"
    ]
    by_role: dict[str, list[float]] = {}
    for row in report.rows:
        by_role.setdefault(row.role, [0.0, 0.0])
        by_role[row.role][0] += row.calls
        by_role[row.role][1] += row.credits
    lines += [
        f"- {role}: {int(calls)} calls, {credits:.4f} credits" for role, (calls, credits) in sorted(by_role.items())
    ]
    lines += ["", "## Cases", ""]
    lines += [f"- {c.id}: {c.outcome_class} ({', '.join(c.tags)})" for c in report.cases] or ["- none"]
    scored = {c.id: report.live_scores[c.id] for c in report.cases if c.id in report.live_scores}
    lines += ["", f"## Autorater scores (live, N={len(scored)}, {report.date})", "", SCORES_NOTE, ""]
    if scored:
        lines += ["| Case | plan_fit | question_usefulness |", "| --- | --- | --- |"]
        lines += [f"| {i} | {s['plan_fit']:.2f} | {s['question_usefulness']:.2f} |" for i, s in scored.items()]
    unscored = [c.id for c in report.cases if c.id not in scored]
    lines += ["", f"Not scored: {', '.join(unscored)}." if unscored else "Every kept case was scored.", ""]
    return "\n".join(lines)
