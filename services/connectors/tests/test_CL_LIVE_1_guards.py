"""CL-LIVE-1: `real_adapters` REFUSES unless the user's live switch LIVE is exactly "1"; refuses under replay, a
dry run, fake providers and CI; refuses (fails closed) when a token cannot be obtained, with no fallback to a mock
that would pretend to be real; never reads or writes a `.env`; and every refusal message carries no secret, token
or mail text.

LIVE is only ever put in an injected mapping here, never in the process environment. API: API_CL_LIVE_1.md.
"""

from __future__ import annotations

import builtins
import io
import pathlib
import traceback

import pytest
import yaml
from _cl_live_lib import (
    CONNECTORS_YAML,
    LIVE_ENV,
    REAL_PY,
    leaks,
    make_real_env,
    process_environ_snapshot,
    real,
)
from _cl_live_lib import clean_process_env as clean_process_env  # autouse fixture
from _cl_live_lib import socket_guard as socket_guard  # autouse fixture
from _oauth_lib import DRIVE_READONLY, OWNER


def _assert_nothing_went_out(g) -> None:
    assert g.transport.requests == [], "a refusal sends nothing to Google"
    assert g.spy.asked == [], "a refusal does not even ask the broker for a token"


def _assert_clean(g, exc: BaseException) -> None:
    """The refusal carries no token, client secret or mail text, in its message, repr, code or traceback."""
    text = "\n".join([str(exc), repr(exc), str(getattr(exc, "code", "")), "".join(traceback.format_exception(exc))])
    found = leaks(text, [*g.issued_secrets(), *g.markers.all()])
    assert not found, "a refusal must not echo secrets or content"


# ---------------------------------------------------------------------------
# The live switch


@pytest.mark.parametrize("live", [None, "", "0", "true", "TRUE", "yes", "01", " 1", "1 ", "2", "on"])
def test_CL_LIVE_1_refuses_unless_live_is_exactly_1(live):
    g = make_real_env()
    environ = {} if live is None else {"LIVE": live}

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(environ=environ)

    assert info.value.code == "live_not_enabled"
    _assert_nothing_went_out(g)
    _assert_clean(g, info.value)


def test_CL_LIVE_1_live_exactly_1_builds_the_adapters_and_changes_no_process_state():
    g = make_real_env()
    before = process_environ_snapshot()

    adapters = g.build(environ={"LIVE": "1"})

    assert set(adapters) == set(g.registry.ids())
    assert process_environ_snapshot() == before, "the factory never sets LIVE or anything else in the process"


def test_CL_LIVE_1_the_switch_is_read_from_the_given_mapping_not_assumed_from_the_process(monkeypatch):
    """With no `environ` the process environment decides. A test (or a person) that has no switch gets a refusal."""
    g = make_real_env()
    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(environ=None)
    assert info.value.code == "live_not_enabled"
    monkeypatch.setenv("LIVE", "1")  # the one place a test sets it in the process: the fake path, fake transport
    assert set(g.build(environ=None)) == set(g.registry.ids())


# ---------------------------------------------------------------------------
# CI, Cloud Run, replay, dry run, fake providers, replay transport


@pytest.mark.parametrize("marker", ["CI", "GITHUB_ACTIONS"])
@pytest.mark.parametrize("where", ["given", "process"])
def test_CL_LIVE_1_refuses_in_ci_even_with_the_switch_on(marker, where, monkeypatch):
    g = make_real_env()
    environ = dict(LIVE_ENV)
    if where == "given":
        environ[marker] = "true"
    else:  # the caller's mapping must not hide a process-level marker
        monkeypatch.setenv(marker, "true")

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(environ=environ)

    assert info.value.code == "ci_refused"
    _assert_nothing_went_out(g)
    _assert_clean(g, info.value)


@pytest.mark.parametrize("marker", ["K_SERVICE", "CLOUD_RUN_JOB"])
def test_CL_LIVE_1_refuses_when_deployed_even_with_the_switch_on(marker):
    g = make_real_env()

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(environ={**LIVE_ENV, marker: ""})  # presence is enough, as for the live model gate

    assert info.value.code == "deployed_refused"
    _assert_nothing_went_out(g)


@pytest.mark.parametrize("mode", ["replay", "dry-run", "record", ""])
def test_CL_LIVE_1_refuses_outside_a_live_run_mode(mode):
    g = make_real_env()

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(mode=mode)

    assert info.value.code == "not_live_mode"
    _assert_nothing_went_out(g)


def test_CL_LIVE_1_refuses_under_fake_providers():
    g = make_real_env()

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(providers_fake=True)

    assert info.value.code == "fake_providers"
    _assert_nothing_went_out(g)


def test_CL_LIVE_1_refuses_a_replay_transport_that_would_pass_for_google():
    """A recorded transport behind a 'real' factory would be a mock that pretends to be real."""
    from tilo_connectors.recording import ReplayTransport

    g = make_real_env()
    replay = ReplayTransport({"format": "tilo.http-recording/1", "connector": "gmail", "interactions": []})

    with pytest.raises(real().RealConnectorsRefused) as info:
        real().real_adapters(g.spy, g.registry, replay, user_id=OWNER, environ=dict(LIVE_ENV), clock=g.env.clock)

    assert info.value.code == "replay_transport"
    _assert_nothing_went_out(g)


# ---------------------------------------------------------------------------
# Fail closed when a token cannot be obtained


def test_CL_LIVE_1_refuses_when_no_connector_is_connected_and_never_falls_back_to_a_mock():
    g = make_real_env(connect=())

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build()

    assert info.value.code == "no_token"
    assert g.transport.requests == []
    _assert_clean(g, info.value)


@pytest.mark.parametrize("missing", ["gmail", "google_drive", "google_calendar"])
def test_CL_LIVE_1_refuses_when_any_one_google_connector_has_no_token(missing):
    g = make_real_env(connect=[c for c in ("gmail", "google_drive", "google_calendar") if c != missing])

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build()

    assert info.value.code == "no_token"
    assert g.transport.requests == [], "the check is a token, not a Google call"
    _assert_clean(g, info.value)


def test_CL_LIVE_1_refuses_an_expired_connection():
    g = make_real_env()
    g.env.clock.advance(60 * 60 * 24)  # past the access token's lifetime, with a refresh that Google now rejects
    g.env.google.refresh_mode = "invalid_grant"

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build()

    assert info.value.code == "no_token"
    _assert_clean(g, info.value)


def test_CL_LIVE_1_refuses_a_grant_that_lacks_the_minimum_read_scope():
    """A token that cannot read is a token that cannot be used: refused up front, not at the first agent step."""
    g = make_real_env(connect=("google_drive", "google_calendar"))
    g.env.connect(OWNER, "gmail", [DRIVE_READONLY])  # a Gmail grant that holds no Gmail scope at all

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build()

    assert info.value.code == "no_token"
    assert g.transport.requests == []
    _assert_clean(g, info.value)


# ---------------------------------------------------------------------------
# No .env, ever


def test_CL_LIVE_1_never_reads_or_writes_a_dotenv_file(tmp_path, monkeypatch):
    """A decoy `.env` that says LIVE=1 sits in the working directory: it changes nothing, and nothing opens it."""
    (tmp_path / ".env").write_text("LIVE=1\nTOKEN=decoy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    touched: list[str] = []
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def spy_open(file, *args, **kwargs):
        if pathlib.PurePath(str(file)).name.startswith(".env"):
            touched.append(str(file))
        return real_open(file, *args, **kwargs)

    def spy_path_open(self, *args, **kwargs):
        if self.name.startswith(".env"):
            touched.append(str(self))
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    g = make_real_env()

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(environ={})  # the decoy says LIVE=1; the factory must not have read it
    g.build()  # and the pass path reads none either

    assert info.value.code == "live_not_enabled"
    assert touched == []
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "LIVE=1\nTOKEN=decoy\n", "and it wrote nothing to it"


def test_CL_LIVE_1_real_module_has_no_dotenv_code_path():
    assert REAL_PY.is_file()
    source = REAL_PY.read_text(encoding="utf-8")
    assert "dotenv" not in source.lower()
    assert ".env" not in source


# ---------------------------------------------------------------------------
# No scope widening in code (the config is checked, not trusted)


def _registry_with(tmp_path, edit):
    from tilo_connectors.registry import load_registry

    entries = yaml.safe_load(CONNECTORS_YAML.read_text(encoding="utf-8"))
    edit({e["id"]: e for e in entries})
    path = tmp_path / "connectors.yaml"
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    return load_registry(path)


@pytest.mark.parametrize(
    ("connector", "capability", "wider"),
    [
        ("gmail", "read", "https://www.googleapis.com/auth/gmail.modify"),
        ("gmail", "write", "https://mail.google.com/"),
        ("gmail", "search", "https://www.googleapis.com/auth/gmail.send"),
        ("google_drive", "read", "https://www.googleapis.com/auth/drive"),
        ("google_drive", "write", "https://www.googleapis.com/auth/drive.readonly"),
        ("google_calendar", "read", "https://www.googleapis.com/auth/calendar.events"),
        ("google_calendar", "read", "https://www.googleapis.com/auth/calendar"),
    ],
)
def test_CL_LIVE_1_refuses_a_registry_that_widens_a_scope_beyond_the_pinned_minimum(
    tmp_path, connector, capability, wider
):
    g = make_real_env()

    def widen(by_id):
        by_id[connector]["scopes"][capability] = [*by_id[connector]["scopes"].get(capability, []), wider]

    registry = _registry_with(tmp_path, widen)

    with pytest.raises(real().RealConnectorsRefused) as info:
        g.build(registry=registry)

    assert info.value.code == "scope_widened"
    _assert_nothing_went_out(g)
    assert wider not in str(info.value), "it names the connector, never echoes config values as a secret"
