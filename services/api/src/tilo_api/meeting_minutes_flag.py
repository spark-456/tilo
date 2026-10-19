"""Default-off minutes activation in the existing process FlagStore before route registration."""

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from tilo_metering.flags import FlagStore

FLAG = "meeting.minutes.enabled"
ENV = "TILO_MEETING_MINUTES_ENABLED"
DEFAULT_PATH = Path(__file__).resolve().parents[4] / "config/meeting.yaml"


def configure_minutes_flag(
    flags: FlagStore, *, path: Path = DEFAULT_PATH, env: Mapping[str, str] | None = None
) -> None:
    """No client, provider or replacement store. Bad config/override revokes only this flag."""
    enabled = False
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        meeting = raw["meeting"]
        minutes = meeting.get("minutes", {})
        value = minutes.get("enabled", False)
        if not isinstance(meeting, dict) or not isinstance(minutes, dict) or type(value) is not bool:
            raise ValueError("invalid minutes flag")
        values = os.environ if env is None else env
        enabled = values[ENV] == "1" if ENV in values else value
    except (OSError, UnicodeError, yaml.YAMLError, KeyError, TypeError, AttributeError, ValueError):
        enabled = False
    flags.set(FLAG, enabled, reason="minutes startup configuration")
