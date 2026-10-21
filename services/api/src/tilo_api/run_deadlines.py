"""RUN-SPEED: per-call deadlines for a run's model calls, from `config/run_deadlines.yaml`.

A deadline is the Router's own PL-03 limit (`Router.generate(deadline=...)`): no attempt starts after it, and a
candidate with a fallback behind it waits only its share of the time left, so a hung primary hands over in time (live,
21 Oct 2026: a plan call waited about 120 s on one attempt before a 5xx). It never changes what is sent, what is
checked or what is charged: a timed-out attempt's answer is dropped, like any failed attempt.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from tilo_providers.router import Deadline

logger = logging.getLogger("tilo_api.run_deadlines")
_CONFIG = Path(__file__).resolve().parents[4] / "config" / "run_deadlines.yaml"
_MAX_SECONDS = 600.0


@dataclass(frozen=True)
class CallDeadline:
    seconds: float
    first_attempt_share: float

    def start(self) -> Deadline:
        """A fresh deadline for one call, counted from now."""
        return Deadline.after(self.seconds, self.first_attempt_share)


@dataclass(frozen=True)
class RunDeadlines:
    plan: CallDeadline
    must_ask: CallDeadline


SHIPPED = RunDeadlines(plan=CallDeadline(180.0, 0.3), must_ask=CallDeadline(45.0, 0.5))


def _call(doc: Any, key: str) -> CallDeadline:
    part = doc[key]
    seconds, share = part["seconds"], part["first_attempt_share"]
    for value in (seconds, share):
        if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
            raise ValueError(f"{key} needs numbers")
    if not 0 < seconds <= _MAX_SECONDS or not 0 < share < 1:
        raise ValueError(f"{key} is out of range")
    return CallDeadline(float(seconds), float(share))


def load_run_deadlines(path: Path | None = None) -> RunDeadlines:
    """The configured limits; a missing or unusable file keeps the shipped numbers (a run is never left without one)."""
    try:
        doc = yaml.safe_load((path or _CONFIG).read_text(encoding="utf-8"))
        return RunDeadlines(plan=_call(doc, "plan"), must_ask=_call(doc, "must_ask"))
    except Exception as exc:  # noqa: BLE001 - the shipped numbers stand in, loudly
        logger.warning("config/run_deadlines.yaml not usable (%s); using the shipped limits", type(exc).__name__)
        return SHIPPED
