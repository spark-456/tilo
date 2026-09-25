"""CLI entry point: `python -m tilo_evals run --pass smoke|full|gate ...`
(EFF-07; PRD 19.1, 6.6 "Lean evals"). `main(argv)` is called directly by the
test suite (rather than through subprocess) so a missing module fails as a
clear ImportError instead of an opaque non-zero exit code (P8-06 spec).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from .cases import CaseError
from .config import EvalsConfig, EvalsConfigError
from .results import build_hash, render_results_json, render_results_md
from .runner import run_pass

EXIT_OK = 0
EXIT_ERROR = 2
EXIT_PARTIAL = 3


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tilo_evals")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run an eval pass")
    run_parser.add_argument("--pass", dest="pass_kind", choices=["smoke", "full", "gate"], required=True)
    run_parser.add_argument("--group", default=None)
    run_parser.add_argument("--case", dest="case_ids", action="append", default=[])
    run_parser.add_argument("--results-md", dest="results_md", default="evals/results.md")
    run_parser.add_argument("--results-json", dest="results_json", default=None)
    run_parser.add_argument("--live", action="store_true")

    return parser


def _write_bytes_appending(path: Path, text: str) -> None:
    """Appends text to path without Windows CRLF corruption (contract-
    pitfalls.md: write_bytes(...encode()), never write_text, on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.exists() else b""
    separator = b"\n" if existing else b""
    path.write_bytes(existing + separator + text.encode("utf-8"))


def _cmd_run(args: argparse.Namespace) -> int:
    if args.live:
        if os.environ.get("LIVE") != "1":
            print("tilo_evals: --live refused; set LIVE=1 in the environment first (EFF-01).", file=sys.stderr)
            return EXIT_ERROR
        print(
            "tilo_evals: --live is not built yet (needs packages/providers); LIVE=1 is set, "
            "but there is no live executor to run.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    try:
        config = EvalsConfig.load("config/evals.yaml")
    except EvalsConfigError as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        result = run_pass(
            pass_kind=args.pass_kind,
            config=config,
            group=args.group,
            case_ids=args.case_ids or None,
        )
    except CaseError as exc:
        print(f"tilo_evals: {exc}", file=sys.stderr)
        return EXIT_ERROR

    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    hash_ = build_hash()
    md = render_results_md(pass_result=result, build_hash=hash_, now_utc=now_utc)
    _write_bytes_appending(Path(args.results_md), md)

    if args.results_json:
        payload = render_results_json(pass_result=result)
        Path(args.results_json).write_bytes(json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"))

    return EXIT_PARTIAL if result.stopped_at_cap else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _cmd_run(args)
    parser.print_help()
    return EXIT_ERROR


if __name__ == "__main__":
    sys.exit(main())
