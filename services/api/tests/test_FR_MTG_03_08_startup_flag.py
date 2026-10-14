"""Minutes activation uses the existing process flags before routes are installed."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from tilo_metering.flags import InMemoryFlagStore

FLAG = "meeting.minutes.enabled"
ENV = "TILO_MEETING_MINUTES_ENABLED"
ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "configured, override, expected",
    [
        (False, None, False),
        (True, None, True),
        (False, "1", True),
        (True, "0", False),
        (True, "true", False),
        (True, " 1", False),
        (True, "", False),
        (False, "01", False),
    ],
)
def test_FR_MTG_03_08_strict_startup_override_preserves_same_store(tmp_path, configured, override, expected):
    from tilo_api.meeting_minutes_flag import configure_minutes_flag

    path = tmp_path / "meeting.yaml"
    path.write_text(yaml.safe_dump({"meeting": {"minutes": {"enabled": configured}}}), encoding="utf-8")
    flags = InMemoryFlagStore()
    for name in ["replay_only", "claims_frozen"]:
        flags.set(name, True, reason="existing treasury guard")
    histories = {name: flags.history(name) for name in ["replay_only", "claims_frozen"]}
    flags.set(FLAG, True, reason="previous value")
    prior = flags.history(FLAG)
    configure_minutes_flag(flags, path=path, env={} if override is None else {ENV: override})
    assert flags.get(FLAG) is expected
    assert flags.history(FLAG)[: len(prior)] == prior
    for name, history in histories.items():
        assert flags.get(name) is True and flags.history(name) == history


@pytest.mark.parametrize(
    "content",
    [
        None,
        "meeting: [",
        "[]",
        "meeting: null",
        "meeting: {minutes: []}",
        'meeting: {minutes: {enabled: "false"}}',
        "meeting: {minutes: {enabled: 1}}",
        "meeting: {minutes: {enabled: null}}",
    ],
)
def test_FR_MTG_03_08_invalid_config_fails_closed_even_with_env_on(tmp_path, content):
    from tilo_api.meeting_minutes_flag import configure_minutes_flag

    path = tmp_path / "meeting.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    flags = InMemoryFlagStore()
    flags.set(FLAG, True, reason="must be revoked on malformed startup config")
    configure_minutes_flag(flags, path=path, env={ENV: "1"})
    assert flags.get(FLAG) is False


def test_FR_MTG_03_08_checked_in_default_false():
    config = yaml.safe_load((ROOT / "config/meeting.yaml").read_text(encoding="utf-8"))
    assert config["meeting"]["minutes"]["enabled"] is False


@pytest.mark.parametrize("override, enabled", [(None, False), ("0", False), ("1", True), ("true", False)])
def test_FR_MTG_03_08_real_process_flag_precedes_route_and_openapi_install(override, enabled):
    env = dict(os.environ)
    env.pop(ENV, None)
    env.pop("LIVE", None)
    if override is not None:
        env[ENV] = override
    script = """
import json
from tilo_api import app, deps
from starlette.routing import Match
paths = []
for action in ['analyze-minutes', 'draft-followup']:
    path = '/v1/meetings/mt_offline/' + action
    scope = {'type': 'http', 'path': path, 'root_path': '', 'method': 'POST', 'app': app}
    if any(route.matches(scope)[0] == Match.FULL for route in app.routes):
        paths.append(path)
print('MINUTES_RESULT=' + json.dumps({
    'flag': deps.get_flag_store().get('meeting.minutes.enabled'),
    'routes': paths, 'openapi': list(app.openapi()['paths']),
}))
"""
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=ROOT, env=env, capture_output=True, text=True, timeout=45, check=False
    )
    assert result.returncode == 0, result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("MINUTES_RESULT="))
    state = json.loads(line.partition("=")[2])
    assert state["flag"] is enabled
    for collection in [state["routes"], state["openapi"]]:
        for action in ["analyze-minutes", "draft-followup"]:
            assert any(path.endswith("/" + action) for path in collection) is enabled
