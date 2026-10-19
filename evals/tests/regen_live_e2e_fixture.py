"""Regenerates the committed PL-LIVE-E2E fixture `evals/bank/live/B-007/` (issues #340, #367): `uv run python
evals/tests/regen_live_e2e_fixture.py`.

It records the fake run (the Director scripted from the case, a synthetic reply for every other role) through the REAL
code (`tilo_evals.live_e2e.record_with_fake`, the Router, the record-and-replay layer), so the recording's keys are
exactly the keys the current prompts and config produce. Run it after a prompt, template or `config/connectors.yaml`
change and commit the result; the replay tests (`test_PL_LIVE_E2E_22`, `_30`, `_32`) then show whether a prompt changed
by accident. It makes no paid call and no network call, and it needs no environment variable: `record_with_fake` takes
only an injected fake provider and never reads the live switch (the CLI path keeps refusing without the user's own).
Not collected by pytest (no `test_` prefix). Reads no secret, writes only under the fixture folder.
"""

from __future__ import annotations

import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _live_e2e_lib import COMMITTED_RECORDINGS, REAL_PRICES, world_for  # noqa: E402
from tilo_evals.live_e2e import record_with_fake  # noqa: E402
from tilo_providers.safety import FakeSafetyProvider  # noqa: E402

CASE = "B-007"
FIXED_TODAY = date(2026, 10, 9)  # the date the prompts state (INTAKE-QUALITY-1); the recording stores it in `TODAY`


def main(target: Path | None = None) -> int:
    target = target or COMMITTED_RECORDINGS / CASE
    shutil.rmtree(target, ignore_errors=True)
    world = world_for(CASE, per_million_usd=0.75, delay_s=0.0)  # the fake's usage is fixed: 1000 in, 500 out per call
    report = record_with_fake(
        CASE,
        fake_factory=world.factory,
        recordings_dir=target,
        prices_path=REAL_PRICES,
        safety=FakeSafetyProvider(),
        today=FIXED_TODAY,
    )
    sys.stdout.write(f"outcome={report.outcome_class} events={report.event_count} written to {target.as_posix()}\n")
    return 0 if report.outcome_class == report.expected else 1


if __name__ == "__main__":
    raise SystemExit(main())
