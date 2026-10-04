"""Live Gmail smoke check (FR-CON-04, PRD 5.4 CP1): sign in with Google, list up to 5 recent messages.

Needs LIVE=1 in the environment (only the user sets it), the GOOGLE_OAUTH_* variables and a test account.
Read-only by default. With --draft ADDRESS it also saves one draft to that address, through the outbox.
It never sends mail and never writes tokens to disk. All the work is in tilo_connectors.live.run_smoke.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from tilo_connectors.live import LiveNotEnabled, SmokeError, run_smoke


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    **run_smoke_options: Any,
) -> int:
    parser = argparse.ArgumentParser(prog="live_gmail_smoke", description=__doc__.strip().split("\n")[0])
    parser.add_argument("--draft", metavar="ADDRESS", help="also save one draft addressed to ADDRESS (never sent)")
    parser.add_argument("--timeout", metavar="SECONDS", type=float, default=300.0, help="how long to wait for sign-in")
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    options = {"draft_to": args.draft, "callback_timeout_s": args.timeout, **run_smoke_options}
    try:
        run_smoke(environ=environ, out=out, **options)
    except (LiveNotEnabled, SmokeError) as error:
        out.write(f"Smoke check stopped: {error}\n")
        out.flush()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
