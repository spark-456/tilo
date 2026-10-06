"""CLI: `python -m tilo_evals metrics [--bank-dir D] [--case ID]... [--results-md P] [--results-json P]` (EV-01..EV-15,
PRD 3.5; exit 0, or 2 when refused in a live or deployed environment or a case file is bad).
`python -m tilo_evals run --pass smoke|full|gate [--group G] [--case ID]... [--results-md PATH]
[--results-json PATH] [--live]` (EFF-07; PRD 19.5, 6.6). `just eval` runs the replay set.

Exit codes: 0 every case that ran passed; 1 at least one case failed; 2 the pass could not run (bad config or
case file, an unknown --case or --group, `--live` refused); 3 the pass stopped at its credit cap with no failure
(partial results).
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from tilo_providers.interfaces import ModelProvider, SafetyProvider

from .cases import CaseError
from .config import EvalsConfig, EvalsConfigError
from .results import build_hash, merge_results_md, render_json, render_section, summary_text
from .runner import PASS_KINDS, SelectionError, run_pass

EXIT_OK, EXIT_FAILED, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 2, 3


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive integer")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tilo_evals")
    commands = parser.add_subparsers(dest="command", required=True)
    bank = commands.add_parser("bank", help="run the generality bank on fakes (issue #272)")
    bank.add_argument("--case", dest="case_ids", action="append", default=[])
    bank.add_argument("--repeat", type=int, default=1)
    bank.add_argument("--bank", dest="bank_dir", default="evals/bank")
    bank.add_argument("--results-md", dest="results_md", default="evals/bank-results.local.md")
    gen = commands.add_parser("generate", help="the live scenario generator; the user's live switch only (issue #272)")
    gen.add_argument("--n", type=int, required=True, help="how many briefs to ask for (at least 1)")
    gen.add_argument("--dry-run", dest="dry_run", action="store_true", help="print the estimate and stop; no call")
    gen.add_argument("--max-inr", dest="max_inr", type=float, default=None, help="cap in rupees (the file's default)")
    gen.add_argument(
        "--date", type=date.fromisoformat, default=None, help="folder name, YYYY-MM-DD (default today UTC)"
    )
    for name in ("settings", "bank-dir", "out-dir", "models-file", "prices-file", "report-md"):
        gen.add_argument(f"--{name}", type=Path, default=None)
    metrics = commands.add_parser("metrics", help="EV-01..EV-15 from a replay pass and the bank on fakes (PRD 3.5)")
    metrics.add_argument("--case", dest="case_ids", action="append", default=[])
    metrics.add_argument("--bank-dir", dest="bank_dir", default="evals/bank")
    metrics.add_argument("--cases-root", dest="cases_root", default="evals/cases")
    metrics.add_argument("--results-md", dest="results_md", default="evals/metrics.local.md")
    metrics.add_argument("--results-json", dest="results_json", default=None)
    metrics.add_argument("--latency-n", dest="latency_n", type=_positive, default=3, help="samples per NFR measure")
    lat = commands.add_parser("latency", help="NFR-02/03/05: Tilo's own latency overhead on fakes (PRD 17.1)")
    lat.add_argument("--n", type=_positive, required=True, help="samples per measure (at least 1)")
    lat.add_argument("--json", action="store_true", help="print the report as one JSON document")
    run = commands.add_parser("run", help="run an eval pass")
    run.add_argument("--pass", dest="pass_kind", choices=PASS_KINDS, required=True)
    run.add_argument("--group", default=None)
    run.add_argument("--case", dest="case_ids", action="append", default=[])
    run.add_argument("--results-md", dest="results_md", default="evals/results.md")
    run.add_argument("--results-json", dest="results_json", default=None)
    run.add_argument("--live", action="store_true")
    return parser


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))  # bytes, so Windows never writes CRLF


def _run(args: argparse.Namespace) -> int:
    if args.live:
        if os.environ.get("LIVE") != "1":
            print(
                "tilo_evals: --live refused; the user sets LIVE=1 in the environment first (EFF-01).", file=sys.stderr
            )
        else:
            print("tilo_evals: --live is not built yet (it needs a packages/providers executor).", file=sys.stderr)
        return EXIT_ERROR
    try:
        config = EvalsConfig.load("config/evals.yaml")
        result = run_pass(pass_kind=args.pass_kind, config=config, group=args.group, case_ids=args.case_ids)
    except (EvalsConfigError, CaseError, SelectionError) as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    section = render_section(result, build_hash=build_hash(), now_utc=now)
    md_path = Path(args.results_md)
    existing = md_path.read_bytes().decode("utf-8", errors="replace") if md_path.is_file() else ""
    _write(md_path, merge_results_md(existing, section, args.pass_kind))
    if args.results_json:
        _write(Path(args.results_json), json.dumps(render_json(result), indent=2, sort_keys=True))
    print(summary_text(result))
    print(f"results: {md_path.as_posix()}")
    return EXIT_FAILED if result.failed else EXIT_PARTIAL if result.stopped_at_cap else EXIT_OK


def _bank(args: argparse.Namespace) -> int:
    from .bank import BankError, bank_digest, load_bank  # noqa: PLC0415 (loads the services; `run` does not)
    from .bank_report import render, run_bank  # noqa: PLC0415
    from .bank_run import BankRefused  # noqa: PLC0415

    try:
        cases = load_bank(args.bank_dir)
        if args.case_ids:
            unknown = sorted(set(args.case_ids) - {c.id for c in cases})
            if unknown:
                raise BankError(f"unknown bank case(s): {', '.join(unknown)}")
            cases = [c for c in cases if c.id in args.case_ids]
        results = run_bank(cases, repeat=args.repeat)
    except (BankError, BankRefused) as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR
    text = render(results, repeat=args.repeat, bank_digest=bank_digest(args.bank_dir))
    _write(Path(args.results_md), text)
    passed = sum(r.passed for r in results)
    print(f"bank: {passed} of {len(results)} cases pass every hard check; results: {Path(args.results_md).as_posix()}")
    return EXIT_OK if passed == len(results) else EXIT_FAILED


def _latency(args: argparse.Namespace) -> int:
    from .latency import LatencyError, LatencyRefused, measure, text_lines  # noqa: PLC0415 (loads the services)

    try:
        report = measure(args.n)
    except (LatencyRefused, LatencyError) as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else "\n".join(text_lines(report)))
    return EXIT_OK


def _metrics(args: argparse.Namespace) -> int:
    """Replays the case set (a full pass under the credit cap), runs the bank on fakes, writes the EV rows."""
    from tilo_metering.costs import load_credit_usd  # noqa: PLC0415 (the loader behind FR-MTR-10's cost_report)
    from tilo_metering.errors import MeteringConfigError  # noqa: PLC0415

    from .bank import BankError, load_bank  # noqa: PLC0415 (loads the services; `run` does not)
    from .bank_report import run_bank  # noqa: PLC0415
    from .bank_run import BankRefused  # noqa: PLC0415
    from .cases import load_cases  # noqa: PLC0415
    from .latency import LatencyError, LatencyRefused, measure  # noqa: PLC0415
    from .metrics import (  # noqa: PLC0415
        bank_measures,
        compute_metrics,
        coverage_from,
        records_from_bank,
        records_from_pass,
    )
    from .metrics_report import render_json as rows_json  # noqa: PLC0415
    from .metrics_report import render_markdown  # noqa: PLC0415
    from .runner import PassResult  # noqa: PLC0415

    try:
        if any(name in os.environ for name in ("LIVE", "K_SERVICE", "CLOUD_RUN_JOB")):  # refuse before anything runs
            raise BankRefused(
                "the metrics report runs on recordings and fakes only: LIVE, K_SERVICE and CLOUD_RUN_JOB must be unset"
            )
        config = EvalsConfig.load("config/evals.yaml")
        credit_usd = load_credit_usd("config/prices.yaml")
        replay, bank = load_cases(root=args.cases_root), load_bank(args.bank_dir)
        replay_ids, bank_ids = {c.id for c in replay}, {c.id for c in bank}
        if unknown := sorted(set(args.case_ids) - replay_ids - bank_ids):
            raise SelectionError(f"unknown case id(s): {', '.join(unknown)}")
        chosen = [i for i in args.case_ids if i in replay_ids]
        replayed = (
            run_pass(pass_kind="full", config=config, cases_root=args.cases_root, case_ids=chosen)
            if chosen or not args.case_ids
            else PassResult("full")
        )
        banked = run_bank([c for c in bank if not args.case_ids or c.id in args.case_ids])
        latency = measure(args.latency_n)  # NFR-02/03/05 (PRD 17.1): local overhead on fakes, a table apart from EV
    except (
        EvalsConfigError,
        CaseError,
        SelectionError,
        BankError,
        BankRefused,
        MeteringConfigError,
        LatencyError,
        LatencyRefused,
    ) as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR
    records = [*records_from_pass(replayed), *records_from_bank(banked)]
    coverage = coverage_from([*(c.measures for c in replay), *(bank_measures(c) for c in bank)], records)
    rows = compute_metrics(records, credit_usd=credit_usd, coverage=coverage)
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    _write(Path(args.results_md), render_markdown(rows, build_hash=build_hash(), now_utc=now, latency=latency))
    if args.results_json:
        _write(Path(args.results_json), json.dumps({**rows_json(rows), "latency": latency}, indent=2, sort_keys=True))
    ids = {s: {r.id for r in rows if r.status == s} for s in ("computed", "no_data", "needs_live_or_pilot")}
    print(
        f"metrics: {len(ids['computed'])} computed, {len(ids['no_data'])} no data, "
        f"{len(ids['needs_live_or_pilot'])} need live or pilot data; report: {Path(args.results_md).as_posix()}"
    )
    return EXIT_OK


def _generate(
    args: argparse.Namespace,
    environ: Mapping[str, str] | None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None,
    safety: SafetyProvider | None,
) -> int:
    from .generator import GenerateRefused, exit_code, render_report, run_generate  # noqa: PLC0415

    def announce(estimate: Any, cap: float) -> None:
        low, high = estimate.credits_low, estimate.credits_high
        print(f"estimate credits_low={low:.4f} credits_high={high:.4f} cap={cap:.4f}", flush=True)

    out = args.out_dir
    try:
        report = run_generate(
            args.n, mode="dry-run" if args.dry_run else "live", max_inr=args.max_inr, environ=environ,
            bank_dir=args.bank_dir, out_dir=out, settings_path=args.settings, models_path=args.models_file,
            prices_path=args.prices_file, live_provider_factory=live_provider_factory, safety=safety,
            today=args.date, announce=announce,
        )  # fmt: skip
    except GenerateRefused as refusal:
        print(f"REFUSED {refusal.code}: {refusal}", file=sys.stderr)
        return EXIT_ERROR
    if args.dry_run:
        return EXIT_OK
    root = out or Path(__file__).resolve().parents[3] / "evals" / "generated"
    path = args.report_md or root / report.date / "report.md"
    _write(path, render_report(report))
    print(f"generated: {len(report.cases)} of {report.requested} kept and written; report: {path.as_posix()}")
    print(f"total credits={report.total_credits:.4f} cap={report.cap_credits:.4f}")
    code = exit_code(report)
    if code == EXIT_PARTIAL:
        print("STOP stopped at the credit cap: nothing over the cap was sent; see the report", file=sys.stderr)
    elif code:
        print("STOP no case was written, or a generated case failed a hard check; see the report", file=sys.stderr)
    return code


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    live_provider_factory: Callable[[str, str], ModelProvider] | None = None,
    safety: SafetyProvider | None = None,
) -> int:
    """`environ`, `live_provider_factory` and `safety` are test seams used by `generate` only."""
    args = _parser().parse_args(argv)
    if args.command == "generate":
        return _generate(args, environ, live_provider_factory, safety)
    if args.command == "metrics":
        return _metrics(args)
    if args.command == "latency":
        return _latency(args)
    return _bank(args) if args.command == "bank" else _run(args)


if __name__ == "__main__":
    sys.exit(main())
