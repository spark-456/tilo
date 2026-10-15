"""NFR-03 / NFR-22: the overall deadline of the Director's brief in POST /intake, from `config/intake.yaml`.

A 503 from the primary model used to leave an intake running past the web's wait (live, 15 Oct 2026: 122.6 s, answered
201 after the web had shown a failure). The deadline is handed to `Router.generate`, which keeps every attempt inside
it and falls back on the cascade with the time left."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import yaml

_CONFIG = Path(__file__).resolve().parents[4] / "config" / "intake.yaml"
_MAX_SECONDS = 600

# The 503 detail for a deadline that passed: a code the web turns into its own sentence, plus plain words.
INTAKE_DEADLINE_DETAIL = {
    "code": "intake_deadline",
    "message": "Making the plan took too long, so nothing was started. Try again.",
}


class IntakeDeadlineConfigError(Exception):
    """config/intake.yaml is missing or unusable; intake fails loudly rather than run with no limit."""


@dataclass(frozen=True)
class IntakeDeadline:
    seconds: float
    first_attempt_share: float


def _number(doc: dict, key: str) -> float:
    value = doc[key]
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise IntakeDeadlineConfigError(f"{key} must be a number")
    return float(value)


def load_intake_deadline(path: Path | None = None) -> IntakeDeadline:
    try:
        doc = yaml.safe_load((path or _CONFIG).read_text(encoding="utf-8"))
        seconds, share = _number(doc, "deadline_seconds"), _number(doc, "first_attempt_share")
    except IntakeDeadlineConfigError:
        raise
    except (OSError, yaml.YAMLError, KeyError, TypeError) as exc:
        raise IntakeDeadlineConfigError(f"intake.yaml is unusable ({type(exc).__name__})") from exc
    if not 0 < seconds <= _MAX_SECONDS:
        raise IntakeDeadlineConfigError(f"deadline_seconds must be above 0 and at most {_MAX_SECONDS}")
    if not 0 < share < 1:
        raise IntakeDeadlineConfigError("first_attempt_share must be above 0 and below 1")
    return IntakeDeadline(seconds, share)
