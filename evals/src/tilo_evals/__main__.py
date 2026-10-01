"""CLI: `python -m tilo_evals run --pass smoke|full|gate [--group G] [--case ID]... [--results-md PATH]
[--results-json PATH] [--live]` (EFF-07; PRD 19.5, 6.6). `just eval` runs the replay set.

Exit codes: 0 every case that ran passed; 1 at least one case failed; 2 the pass could not run (bad config or
case file, an unknown --case or --group, `--live` refused); 3 the pass stopped at its credit cap with no failure
(partial results).
"""

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .cases import CaseError
from .config import EvalsConfig, EvalsConfigError
from .results import build_hash, merge_results_md, render_json, render_section, summary_text
from .runner import PASS_KINDS, SelectionError, run_pass

EXIT_OK, EXIT_FAILED, EXIT_ERROR, EXIT_PARTIAL = 0, 1, 2, 3


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tilo_evals")
    run = parser.add_subparsers(dest="command", required=True).add_parser("run", help="run an eval pass")
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


def main(argv: list[str] | None = None) -> int:
    return _run(_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
