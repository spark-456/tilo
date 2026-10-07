"""Live meeting-host smoke check (FR-MTG-09, ADR-0024): sign in as the meeting bot, create one event with a Meet link.

Needs LIVE=1 in the environment (only the user sets it), the GOOGLE_OAUTH_* variables and the meeting bot's own
Google account (a test account that nothing else uses). Your browser opens Google's consent page: sign in AS THE
BOT, not as yourself. The script then creates one event on the bot's calendar starting in --start-in-min minutes
and invites ADDRESS (your own test address). It prints the conference status and the event id, never the Meet
link, and never writes tokens to disk. All the work is in tilo_connectors.live.run_host_smoke.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from tilo_connectors.live import LiveNotEnabled, SmokeError, run_host_smoke


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    **run_options: Any,
) -> int:
    parser = argparse.ArgumentParser(prog="live_meeting_host_smoke", description=__doc__.strip().split("\n")[0])
    parser.add_argument("--invite", metavar="ADDRESS", required=True, help="your own test address to invite")
    parser.add_argument("--start-in-min", metavar="MINUTES", type=int, default=30, help="the event starts in this long")
    parser.add_argument("--timeout", metavar="SECONDS", type=float, default=300.0, help="how long to wait for sign-in")
    args = parser.parse_args(argv)
    out = sys.stdout if out is None else out
    options = {"invite": args.invite, "start_in_min": args.start_in_min, "callback_timeout_s": args.timeout}
    try:
        run_host_smoke(environ=environ, out=out, **options, **run_options)
    except (LiveNotEnabled, SmokeError) as error:
        out.write(f"Smoke check stopped: {error}\n")
        out.flush()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
