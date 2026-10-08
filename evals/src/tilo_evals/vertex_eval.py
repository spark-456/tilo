"""`python -m tilo_evals vertex-eval export|run` (VERTEX-EVAL-1, ADR-0033; docs/design/VERTEX-EVAL-1.md).

`export` pairs two bank-format folders of recorded Director output by case id and writes a redacted local pairs file;
it is free. `run` sends each pair to the `eval_judge` role (a pairwise comparison, then plan groundedness) and writes a
report that leads with counts. The gate comes first: the live path needs the user's live switch (`live_e2e._gate`),
`--fake` and `--dry-run` need none and are refused or free. Every call is charged its quote and the run stops before a
case that would pass the cap. Nothing here is an EV row. Exit codes: 0 done; 1 an unusable judgement or a provider
failure; 2 refused or bad input (nothing sent); 3 stopped at the credit cap.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema
import yaml
from tilo_providers.config import ProviderConfigError, ProvidersConfig, load_providers_config, resolve_models_path
from tilo_providers.evaluation import EVAL_ROLE, build_eval_provider
from tilo_providers.interfaces import EvalItem, EvalProvider, EvalRequest
from tilo_providers.prompts import neutralise_marker
from tilo_providers.replay import _AUTHORIZATION_LIKE_RE
from tilo_providers.vertex_smoke import _SECRET_RE, classify

from .bank import BankCase, BankError, load_bank
from .config import CappedError, read_yaml
from .results import build_hash


class Refused(Exception):
    """A precondition failed; nothing was sent. `code` is the word printed after REFUSED."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(" ".join(message.split()))
        self.code = code


HARD_MAX_CREDITS = 19.0  # a code constant: the settings file cannot raise it (a run costs under 20 credits)
_REPO = Path(__file__).resolve().parents[3]
_SETTINGS, _SCHEMA = _REPO / "evals" / "vertex_eval.yaml", _REPO / "evals" / "vertex_eval.schema.json"
_PROMPTS = _REPO / "prompts" / "eval_judge"
_PAIRS_DEFAULT, _REPORT_DEFAULT = "evals/vertex-eval/pairs.local.yaml", "evals/vertex-eval/report.local.md"
TRUNCATED = " [truncated]"
_MAX_FIELD = 100_000  # a longer field is never sent; it also bounds the regex work
_STOP_CODES = frozenset({"auth", "permission", "quota", "api_disabled", "location"})  # vertex_smoke.classify
_LABEL, _ID = re.compile(r"[A-Za-z0-9 ._-]{1,40}"), re.compile(r"[A-Za-z0-9_-]{1,64}")
_LONG_RUN = re.compile(r"[^\s\"']{1001,}")  # no natural text has one; the scrub regexes are quadratic on them
_BLOCK = re.compile(r"<<<([A-Z_]+)\n(.*?)\n\1>>>", re.DOTALL)
_SLOT = re.compile(r"\{(prompt|context|response|baseline_model_response)\}")
_ADD = (
    "add to config/models.yaml: vertex-eval: { provider: vertex_eval, model: <judge model id>, context: <tokens>, "
    "caps: [] } and eval_judge: { primary: vertex-eval, fallback: vertex-eval }, and to config/prices.yaml: "
    "vertex-eval: { input: <USD per 1M>, output: <USD per 1M> }"
)


def _positive(text: str) -> int:
    value = int(text) if text.lstrip("-").isdigit() else 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return value


def add_arguments(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="vertex_command", required=True)
    raw = argparse.RawDescriptionHelpFormatter
    exp = sub.add_parser("export", formatter_class=raw, help="pair two bank-format folders into a pairs file (free)")
    exp.epilog = f"default --out:\n  {_PAIRS_DEFAULT}"
    exp.add_argument("--candidate", type=Path, required=True)
    exp.add_argument("--baseline", type=Path, default=None)
    exp.add_argument("--candidate-label", default="candidate")
    exp.add_argument("--baseline-label", default="baseline")
    exp.add_argument("--max-cases", type=_positive, default=None)
    exp.add_argument("--out", type=Path, default=Path(_PAIRS_DEFAULT))
    run = sub.add_parser("run", formatter_class=raw, help="judge a pairs file (fake by default in dev; live is gated)")
    run.epilog = f"default --report-md:\n  {_REPORT_DEFAULT}\ndefault --pairs:\n  {_PAIRS_DEFAULT}"
    run.add_argument("--pairs", type=Path, default=Path(_PAIRS_DEFAULT))
    mode = run.add_mutually_exclusive_group()
    mode.add_argument(
        "--fake", action="store_true", help="the deterministic dev stand-in; refused with the live switch"
    )
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the estimate and stop; no call")
    run.add_argument("--max-credits", type=float, default=None)
    run.add_argument("--groundedness", choices=("candidate", "both"), default="candidate")
    run.add_argument("--report-md", type=Path, default=Path(_REPORT_DEFAULT))
    run.add_argument("--report-json", type=Path, default=None)
    for command in (exp, run):
        command.add_argument("--settings", type=Path, default=None)
    for name in ("models-file", "prices-file"):
        run.add_argument(f"--{name}", type=Path, default=None)


# --- settings, redaction ----------------------------------------------------------------------------------------


def _settings(path: Path | None) -> dict[str, Any]:
    try:
        raw = read_yaml(Path(path) if path else _SETTINGS, CappedError)
        jsonschema.Draft202012Validator(json.loads(_SCHEMA.read_text(encoding="utf-8"))).validate(raw)
    except (CappedError, jsonschema.ValidationError) as error:
        said = getattr(error, "message", str(error))[:300]
        raise Refused("settings_invalid", f"the vertex-eval settings did not load: {said}") from None
    if raw["max_credits"] > HARD_MAX_CREDITS:
        raise Refused("cap_out_of_range", f"the settings' max_credits is above {HARD_MAX_CREDITS:g}")
    return dict(raw)


def _redact(text: str, env: Mapping[str, str]) -> str:
    """Control and format characters out, then secrets and personal data (design 4.1). The caller caps afterwards."""
    text = "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf", "Co", "Cs"))
    from .live_e2e import _scrub_known  # noqa: PLC0415  (loads the services; the parser does not)

    text = _scrub_known(_LONG_RUN.sub("[redacted]", text), env)
    return _AUTHORIZATION_LIKE_RE.sub("[redacted]", _SECRET_RE.sub("[redacted]", text))


def _clean(text: str, limit: int, env: Mapping[str, str]) -> str:
    """Redact, then cap (scrub before cut, so a cut never leaves part of a secret). Only a window of the text is
    scrubbed, which bounds the regex work; it grows while redaction leaves too little to fill the cap."""
    window = 2 * limit
    while True:
        out = _redact(text[:window], env)
        if len(out) >= limit + 200 or window >= len(text):
            break
        window *= 2
    return out if window >= len(text) and len(out) <= limit else out[:limit] + TRUNCATED


# --- export -----------------------------------------------------------------------------------------------------


def _load_folder(folder: Path) -> dict[str, BankCase]:
    if not folder.is_dir():
        raise Refused("bad_input", "a case folder is missing or is not a folder")
    try:
        cases = load_bank(folder)
    except BankError as error:
        raise Refused("bad_input", f"a case folder did not load: {error}") from None
    if not cases:
        raise Refused("bad_input", "a case folder holds no case")
    return {c.id: c for c in cases}


def _texts(case: BankCase) -> tuple[str, str, str]:
    answers = "".join(
        f"\n- {k}: {'(not answered)' if v is None else v}" for k, v in sorted((case.answers or {}).items())
    )
    prompt = case.brief + (f"\n\nAnswers:{answers}" if answers else "")
    context = "\n\n".join(f"--- {f['name']} ---\n{f['text']}" for f in case.files)
    response = json.dumps(case.director, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return prompt, context, response


def _inputs(case: BankCase) -> str:
    return json.dumps([case.brief, list(case.files), case.answers], sort_keys=True)


def _export(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    settings = _settings(args.settings)
    for label in (args.candidate_label, args.baseline_label):
        if not _LABEL.fullmatch(label):
            raise Refused("bad_label", "a label is 1 to 40 letters, digits, spaces, dots, dashes or underscores")
    cand = _load_folder(args.candidate)
    base = _load_folder(args.baseline) if args.baseline else None
    limit, caps = args.max_cases or settings["max_cases"], settings["field_chars"]
    pairs: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for case_id in sorted(set(cand) | set(base or {})):
        if len(pairs) >= limit:
            break
        a, b = cand.get(case_id), (base or {}).get(case_id)
        reason = ""
        if base is not None and (a is None or b is None):
            reason = "only_in_baseline" if a is None else "only_in_candidate"
        elif any(c is not None and all(v is None for v in c.director.values()) for c in (a, b)):
            reason = "no_output"
        elif b is not None and a is not None and _inputs(a) != _inputs(b):
            reason = "inputs_differ"
        elif a is not None and any(len(t) > _MAX_FIELD for c in (a, b) if c for t in _texts(c)):
            reason = "input_too_large"
        if reason or a is None:
            skipped.append({"id": case_id, "reason": reason})
            continue
        prompt, context, response = _texts(a)
        row = {
            "id": case_id,
            "prompt": _clean(prompt, caps["prompt"], env),
            "context": _clean(context, caps["context"], env),
            "candidate_response": _clean(response, caps["response"], env),
        }
        if b is not None:
            row["baseline_response"] = _clean(_texts(b)[2], caps["response"], env)
        pairs.append(row)
    if not pairs:
        raise Refused("no_pair", "no case could be exported; see the skipped reasons: " + json.dumps(skipped)[:300])
    doc = {
        "candidate_label": args.candidate_label,
        "baseline_label": args.baseline_label if base is not None else None,
        "pairs": pairs,
        "skipped": skipped,
    }
    _write(args.out, yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120))
    print(f"exported {len(pairs)} pairs ({len(skipped)} skipped); pairs file: {Path(args.out).as_posix()}")
    return 0


def _write(path: Path, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(text.encode("utf-8"))  # bytes, so Windows never writes CRLF


# --- run: the pairs file ----------------------------------------------------------------------------------------


@dataclass
class _Case:
    id: str
    prompt: str
    context: str
    cand: str
    base: str | None
    index: int
    truncated: list[str] = field(default_factory=list)


@dataclass
class _Call:
    kind: str  # pairwise | cand | base
    request: EvalRequest
    quote: float


@dataclass
class _Done:
    case: _Case
    shown_as: str | None = None
    choice: str | None = None  # candidate | baseline | tie | error
    grounded: dict[str, str] = field(default_factory=dict)  # side -> "1" | "0" | "error"
    said: dict[str, str] = field(default_factory=dict)  # call kind -> redacted explanation


def _bad(why: str) -> Refused:
    return Refused("pairs_invalid", f"the pairs file is not usable: {why}")


def _load_pairs(
    path: Path, caps: Mapping[str, int], env: Mapping[str, str]
) -> tuple[str, str | None, list[_Case], list[dict[str, str]], str]:
    try:
        sha = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        raise _bad("it cannot be read") from None
    try:
        doc = read_yaml(Path(path), CappedError)
    except CappedError:
        raise _bad("it is not YAML") from None
    rows = doc.get("pairs") if isinstance(doc, dict) else None
    if not isinstance(rows, list) or not rows:
        raise _bad("it needs a non-empty `pairs` list")
    labels = [doc.get("candidate_label", "candidate"), doc.get("baseline_label")]
    if not (isinstance(labels[0], str) and _LABEL.fullmatch(labels[0])) or not (
        labels[1] is None or (isinstance(labels[1], str) and _LABEL.fullmatch(labels[1]))
    ):
        raise _bad("a label is not valid")
    keys = {"id", "prompt", "context", "candidate_response", "baseline_response"}
    cases: list[_Case] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        ok = isinstance(row, dict) and set(row) <= keys and {"id", "prompt", "candidate_response"} <= set(row)
        if not ok or not isinstance(row["id"], str) or not _ID.fullmatch(row["id"]) or row["id"] in seen:
            raise _bad("a row has a missing, odd or repeated id or key")
        texts = {k: row.get(k, "" if k == "context" else None) for k in keys - {"id"}}
        if not all(isinstance(v, str) for k, v in texts.items() if k != "baseline_response") or not (
            texts["baseline_response"] is None or isinstance(texts["baseline_response"], str)
        ):
            raise _bad(f"row {row['id']} has a field that is not text")
        seen.add(row["id"])
        if any(len(v) > _MAX_FIELD for v in texts.values() if v):
            skipped.append({"id": row["id"], "reason": "input_too_large"})
            continue
        case = _Case(row["id"], "", "", "", None, len(cases))
        for name, key, cap in (
            ("prompt", "prompt", "prompt"),
            ("context", "context", "context"),
            ("cand", "candidate_response", "response"),
            ("base", "baseline_response", "response"),
        ):
            if texts[key] is None:
                continue
            value = _clean(texts[key], caps[cap], env)
            if value.endswith(TRUNCATED):
                case.truncated.append(key)
            setattr(case, name, value)
        cases.append(case)
    if not cases:
        raise _bad("every row was too large")
    return labels[0], labels[1], cases, skipped, sha


# --- run: requests and quotes -----------------------------------------------------------------------------------


def _rubric(name: str) -> str:
    return (_PROMPTS / name).read_bytes().decode("utf-8")


def _markers(template: str) -> dict[str, str]:
    return {slot: marker for marker, body in _BLOCK.findall(template) for slot in re.findall(r"\{(\w+)\}", body)}


def _quote(config: ProvidersConfig, profile: str, settings: Mapping[str, Any], template: str, item: EvalItem) -> float:
    """((ceil(B/3) + overhead) * input + assumed_output * output) / 1e6 in credits; B is the UTF-8 size of the rubric
    with the fields filled (a third of a byte per token errs high)."""
    values = {
        "prompt": item.prompt,
        "context": item.context,
        "response": item.response,
        "baseline_model_response": item.baseline_response or "",
    }
    size = len(_SLOT.sub(lambda m: values[m[1]], template).encode("utf-8"))
    price = config.price(profile)
    tokens = math.ceil(size / 3) + settings["overhead_tokens"]
    return config.credits((tokens * price.input + settings["assumed_output_tokens"] * price.output) / 1e6)


def _plan(
    case: _Case,
    metrics: Mapping[str, Any],
    both: bool,
    config: ProvidersConfig,
    profile: str,
    settings: Mapping[str, Any],
) -> list[_Call]:
    def call(kind: str, metric: str, request_kind: str, response: str, baseline: str | None = None) -> _Call:
        template = metrics[metric]["text"]
        marks = _markers(template)
        item = EvalItem(
            id=case.id,
            prompt=neutralise_marker(case.prompt, marks["prompt"]),
            context=neutralise_marker(case.context, marks["context"]),
            response=neutralise_marker(response, marks["response"]),
            baseline_response=None
            if baseline is None
            else neutralise_marker(baseline, marks["baseline_model_response"]),
        )
        request = EvalRequest(metric=metrics[metric]["id"], kind=request_kind, template=template, item=item)  # type: ignore[arg-type]
        return _Call(kind, request, _quote(config, profile, settings, template, item))

    calls: list[_Call] = []
    if case.base is not None:  # even-index cases send the candidate as the response, odd-index cases swap the two
        first, second = (case.base, case.cand) if case.index % 2 else (case.cand, case.base)
        calls.append(call("pairwise", "pairwise", "pairwise", first, second))
    calls.append(call("cand", "groundedness", "pointwise", case.cand))
    if both and case.base is not None:
        calls.append(call("base", "groundedness", "pointwise", case.base))
    return calls


# --- run ---------------------------------------------------------------------------------------------------------


def _load_config(args: argparse.Namespace, env: Mapping[str, str]) -> tuple[ProvidersConfig, str]:
    models = args.models_file or (_REPO / "config" / "models.dev.yaml" if args.fake else resolve_models_path(env=env))
    prices = args.prices_file or _REPO / "config" / "prices.yaml"
    try:
        config = load_providers_config(Path(models), Path(prices))
        if config.prices.status != "set":
            raise ProviderConfigError("the prices file is unset")
        if EVAL_ROLE not in config.roles:
            raise ProviderConfigError(f"the models file has no {EVAL_ROLE!r} role")
        profile = config.roles[EVAL_ROLE].primary
        config.price(profile)
    except ProviderConfigError as error:
        raise Refused("config_invalid", f"{str(error)[:200]}; {_ADD}") from None
    return config, profile


def _run(args: argparse.Namespace, env: Mapping[str, str], injected: EvalProvider | None) -> int:
    live = not (args.fake or args.dry_run)
    if args.fake and "1" in (env.get("LIVE"), os.environ.get("LIVE")):
        raise Refused("fake_with_live", "--fake is refused while LIVE is set: a fake run is never a live one")
    if live:
        from .live_e2e import LiveE2ERefused, _gate  # noqa: PLC0415

        try:
            _gate("live", env, None)  # the live switch is looked at before any file, config or Google import
        except LiveE2ERefused as refusal:
            raise Refused(refusal.code, str(refusal)) from None
    cap = args.max_credits
    if cap is not None and not (math.isfinite(cap) and 0 < cap <= HARD_MAX_CREDITS):
        raise Refused("cap_out_of_range", f"--max-credits must be above 0 and at most {HARD_MAX_CREDITS:g}")
    settings = _settings(args.settings)
    cap = float(settings["max_credits"] if cap is None else cap)
    config, profile = _load_config(args, env)
    metrics = {
        name: {"id": spec["id"], "text": _rubric(spec["template"])} for name, spec in settings["metrics"].items()
    }
    cand_label, base_label, cases, skipped, pairs_sha = _load_pairs(args.pairs, settings["field_chars"], env)
    plans = [_plan(c, metrics, args.groundedness == "both", config, profile, settings) for c in cases]
    costs = [sum(call.quote for call in plan) for plan in plans]
    fit, spent = 0, 0.0
    for cost in costs:
        if spent + cost > cap:
            break
        fit, spent = fit + 1, spent + cost
    if args.dry_run:
        print(f"estimate credits={sum(costs):.4f} cap={cap:.4f}")
        print(f"fit {fit} of {len(cases)} cases")
        return 0
    if fit == 0:
        raise Refused("cap_too_small", f"the cap of {cap:.4f} credits fits no whole case; nothing was sent")
    try:
        provider = injected or build_eval_provider(config, live_permitted=live)
    except ProviderConfigError as error:
        raise Refused("config_invalid", str(error)[:200]) from None
    done: list[_Done] = []
    total, stop = 0.0, ""
    for case, plan, cost in zip(cases, plans, costs, strict=True):
        if total + cost > cap:
            stop = "credit cap"
            break
        record = _Done(case, shown_as=None if case.base is None else "B" if case.index % 2 else "A")
        for call in plan:
            try:
                score = provider.evaluate(call.request)
                said = _clean(score.explanation, 500, env)
                failed = False
            except Exception as error:  # noqa: BLE001  (a provider's own words are never printed, only its code)
                code, said, score, failed = classify(error), "", None, True
                if code in _STOP_CODES:
                    stop = f"provider failure ({code})"
                    break
            total += call.quote
            record.said[call.kind] = said
            if call.kind == "pairwise":
                choice = None if failed or score is None else score.choice
                swapped = bool(case.index % 2)
                record.choice = (
                    "error"
                    if choice is None
                    else "tie"
                    if choice == "tie"
                    else "candidate"
                    if (choice == "candidate") != swapped
                    else "baseline"
                )
            else:
                value = None if failed or score is None else score.score
                record.grounded[call.kind] = "1" if value == 1.0 else "0" if value == 0.0 else "error"
        else:
            done.append(record)
            continue
        break
    errors = sum(d.choice == "error" or "error" in d.grounded.values() for d in done)
    return _finish(
        args,
        config,
        profile,
        (cand_label, base_label),
        cases,
        skipped,
        done,
        total,
        cap,
        stop,
        errors,
        pairs_sha,
        metrics,
    )


# --- report -----------------------------------------------------------------------------------------------------


def _pct(k: int, n: int) -> str:
    return f"{int(100 * k / n + 0.5)}% ({k} of {n})"


def _cell(text: str, limit: int = 120) -> str:
    return " ".join(text.split()).replace("|", "/")[:limit] or "-"


def _finish(
    args: Any,
    config: ProvidersConfig,
    profile: str,
    labels: tuple[str, str | None],
    cases: list[_Case],
    skipped: list[dict[str, str]],
    done: list[_Done],
    total: float,
    cap: float,
    stop: str,
    errors: int,
    pairs_sha: str,
    metrics: Mapping[str, Any],
) -> int:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    fake = bool(args.fake)
    tally = {s: sum(d.choice == s for d in done) for s in ("candidate", "baseline", "tie")}
    judged_pairs = sum(tally.values())
    grounded = {s: [d.grounded[s] for d in done if d.grounded.get(s) in ("0", "1")] for s in ("cand", "base")}
    n, k = len(cases), len(done)
    usd = total * config.prices.credit_usd
    shas = {m["id"]: hashlib.sha256(m["text"].encode("utf-8")).hexdigest() for m in metrics.values()}
    lines = [
        "# Vertex AI plan evaluation",
        "",
        "FAKE: deterministic dev stand-in, not a measurement" if fake else "LIVE: Vertex AI Gen AI evaluation service",
        "",
        f"- Build {build_hash()} at {now}; judge profile `{profile}` (role `{EVAL_ROLE}`)",
        "- Rubrics: " + ", ".join(f"{i} (sha256 {s})" for i, s in shas.items()),
        f"- Pairs file sha256 {pairs_sha}; candidate `{labels[0]}`, baseline `{labels[1] or 'none'}`",
        "",
        f"{'The deterministic stand-in' if fake else 'A single judge model'}'s {'' if fake else 'live '}judgements "
        f"of recorded Director output on {n} pairs. "
        "It is not an EV row, not EV-05, and not a claim about any other case.",
        "",
        f"Judged {k} of {n} cases" + (f" ({n - k} not run: {stop})." if k < n else "."),
    ]
    if judged_pairs:
        c, b, t = tally["candidate"], tally["baseline"], tally["tie"]
        lines += [
            f"Candidate preferred in {c} of {judged_pairs}, baseline in {b} of {judged_pairs}, "
            f"tie in {t} of {judged_pairs}.",
            f"Candidate win rate {_pct(c, judged_pairs)}" + (f"; {_pct(c, c + b)} excluding ties." if c + b else "."),
        ]
    which = "fake judge" if fake else "live judge"
    g = grounded["cand"]
    lines.append(f"Candidate plan groundedness ({which}): grounded in {sum(v == '1' for v in g)} of {len(g)}.")
    if grounded["base"] or args.groundedness == "both":
        h = grounded["base"]
        lines.append(f"Baseline plan groundedness ({which}): grounded in {sum(v == '1' for v in h)} of {len(h)}.")
    lines += [
        "",
        "| case | pairwise | candidate shown as | groundedness | truncated | explanation |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in done:
        ground = d.grounded.get("cand", "-") + (f" (baseline {d.grounded['base']})" if "base" in d.grounded else "")
        said = " ; ".join(_cell(s) for s in d.said.values())
        lines.append(
            f"| {d.case.id} | {d.choice or '-'} | {d.shown_as or '-'} | {ground} "
            f"| {','.join(d.case.truncated) or '-'} | {said} |"
        )
    if errors:
        lines += [
            "",
            "Error rows (kept out of every denominator): "
            + ", ".join(d.case.id for d in done if d.choice == "error" or "error" in d.grounded.values()),
        ]
    if skipped:
        lines += ["", "Skipped: " + ", ".join(f"{s['id']} ({s['reason']})" for s in skipped)]
    lines += [
        "",
        f"Credits: {total:.4f} of {cap:.4f} (US${usd:.4f}); estimated; reconcile against the billing export. "
        f"Stop reason: {stop or 'none'}.",
    ]
    _write(args.report_md, "\n".join(lines) + "\n")
    if args.report_json:
        cases_json = [
            {
                "id": d.case.id,
                "shown_as": d.shown_as,
                "choice": d.choice,
                "groundedness": d.grounded,
                "explanations": d.said,
                "truncated": d.case.truncated,
            }
            for d in done
        ]
        doc = {
            "basis": "fake" if fake else "live_autorater",
            "build": build_hash(),
            "generated_utc": now,
            "judge": {"profile": profile, "role": EVAL_ROLE},
            "labels": {"candidate": labels[0], "baseline": labels[1]},
            "rubrics": shas,
            "pairs_sha256": pairs_sha,
            "judged": k,
            "total": n,
            "stop_reason": stop or None,
            "credits": {"total": round(total, 4), "cap": cap, "usd": round(usd, 4)},
            "cases": cases_json,
            "skipped": skipped,
        }
        _write(args.report_json, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(f"report: {Path(args.report_md).as_posix()}")
    print(f"total credits={total:.4f} cap={cap:.4f}")
    if stop.startswith("provider"):
        print(f"STOP {stop}; see the report", file=sys.stderr)
        return 1
    if stop:
        print("STOP stopped at the credit cap: nothing over the cap was sent; see the report", file=sys.stderr)
    return 1 if errors else 3 if stop else 0


def run_vertex_eval(args: argparse.Namespace, environ: Mapping[str, str] | None, provider: EvalProvider | None) -> int:
    env = dict(os.environ if environ is None else environ)
    try:
        return _export(args, env) if args.vertex_command == "export" else _run(args, env, provider)
    except Refused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        return 2
