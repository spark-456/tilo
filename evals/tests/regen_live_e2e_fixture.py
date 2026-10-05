"""Regenerates the committed PL-LIVE-E2E fixture `evals/bank/live/B-007/` (issue #340): `uv run python
evals/tests/regen_live_e2e_fixture.py`.

It records the fake run (the Director scripted from the case, a synthetic reply for every other role) through the REAL
code (`tilo_evals.live_e2e`, the Router, the record-and-replay provider), so the recording's keys are exactly the keys
the current prompts produce. Run it after a prompt or template changes on purpose and commit the result; the replay
tests then show whether a prompt changed by accident. It makes no paid call and no network call: the live switch is
set only inside this process's own patched environment, and the only provider is the fake in `_live_e2e_lib`.
Not collected by pytest (no `test_` prefix). Reads no secret, writes only under the fixture folder.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _live_e2e_lib import COMMITTED_RECORDINGS, PROJECT, REAL_PRICES, env, invoke_main, world_for  # noqa: E402

CASE = "B-007"


def main() -> int:
    target = COMMITTED_RECORDINGS / CASE
    shutil.rmtree(target, ignore_errors=True)
    world = world_for(CASE, per_million_usd=0.75, delay_s=0.0)  # the fake's usage is fixed: 1000 in, 500 out per call
    argv = ["--case", CASE, "--prices-file", str(REAL_PRICES), "--recordings-dir", str(target)]
    with env(LIVE="1", TILO_RECORD="1", GOOGLE_CLOUD_PROJECT=PROJECT):
        result = invoke_main(argv, world=world)
    sys.stdout.write(result.out)
    sys.stderr.write(result.err)
    return result.code


if __name__ == "__main__":
    raise SystemExit(main())
