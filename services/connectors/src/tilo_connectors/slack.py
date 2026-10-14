"""PREP-SLACK-1 / FR-UX-17: inert, separately validated Slack declaration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .registry import load_registry

NEEDS_APP = "Needs the workspace owner's Slack app"
DEFAULT_CONFIG = Path(__file__).resolve().parents[4] / "config" / "slack.yaml"


def load_slack_declaration(path: str | os.PathLike[str] = DEFAULT_CONFIG) -> dict[str, Any]:
    return load_registry(path).get("slack")


def slack_status(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    env = os.environ if environ is None else environ
    configured = env.get("SLACK_OAUTH_CLIENT_ID") and env.get("SLACK_OAUTH_CLIENT_SECRET")
    return {
        "connector": "slack",
        "state": "ready_to_connect" if configured else "needs_app",
        "message": "Ready: connect your Slack workspace" if configured else NEEDS_APP,
    }
