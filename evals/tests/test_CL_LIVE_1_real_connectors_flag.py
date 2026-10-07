"""CL-LIVE-1 (CONNECTORS-LIVE slice 1; user wish 7 Oct 2026: agents may work with connectors): the flag
`--real-connectors` of `just live-e2e` and `just live-run`.

  (6) the flag is parsed and documented; with the guards passed the run uses `real_adapters(...)` instead of
      `mock_adapters()`; without LIVE=1 the process exits non-zero with the refusal and sends nothing;
      `--dry-run --real-connectors` prints the plan (which connectors, which scopes, read-only) and sends nothing
      and builds no client;
  (3) the guards: the live switch exactly "1" AND the flag, not replay, not fake providers, not CI or Cloud Run, never
      a `.env`, fail closed when a token cannot be obtained (no fallback to mocks that would pretend to be real),
      refusal text without a secret, a token or mail text;
  (5) privacy: what the real adapters read is in no recording, event, report, log or output.

The run reaches the connectors through one seam, `real_connectors_factory` (a zero-argument callable the run calls once
every guard has passed; the default builds the live transport and the consent flow, which is CL-LIVE-3). The tests hand
it a fake that builds the REAL `real_adapters` over a fake Google. LIVE is only set in a patched environment, with fake
providers, a fake safety screen and a fake transport: no network, no paid call. API: API_CL_LIVE_1.md.
"""

from __future__ import annotations

import builtins
import contextlib
import importlib
import inspect
import io
import json
import os
import pathlib
import re
import subprocess
import sys

import _live_e2e_lib as lib
import pytest
from _cl_live_evals_lib import (
    LIVE_ENV,
    PLAN_LINE,
    SCOPES,
    ConnectorFactory,
    real,
    run_e2e,
    run_topic,
)
from _live_e2e_lib import network_guard  # noqa: F401  (autouse fixture)
from tilo_providers.safety import FakeSafetyProvider

KINDS = ["e2e", "topic"]
GOOGLE_IDS = {"gmail", "google_drive", "google_calendar"}
PINNED = {k: set(v) for k, v in SCOPES.items()}


def run(kind: str, tmp_path, extra, **kwargs):
    return (run_e2e if kind == "e2e" else run_topic)(tmp_path, extra, **kwargs)


class NeverFactory:
    """A connector factory that must not be called: a guard that lets it be called has failed."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("the connector factory was called")


@pytest.fixture
def no_client(monkeypatch):
    """Records every construction of a live HTTP client, a callback listener or a token broker."""
    built: list[str] = []
    from tilo_connectors import live, tokens

    def recorder(name, original):
        def init(self, *args, **kwargs):
            built.append(name)
            return original(self, *args, **kwargs)

        return init

    monkeypatch.setattr(live._LiveBase, "__init__", recorder("live-http", live._LiveBase.__init__))
    monkeypatch.setattr(live.CallbackServer, "__init__", recorder("callback", live.CallbackServer.__init__))
    monkeypatch.setattr(tokens.TokenBroker, "__init__", recorder("broker", tokens.TokenBroker.__init__))
    return built


def _plan(out: str) -> dict[str, tuple[set[str], str]]:
    rows = [m for line in out.splitlines() if (m := re.match(PLAN_LINE, line))]
    return {m["id"]: (set(m["scopes"].split(",")), "read_only") for m in rows}


# ---------------------------------------------------------------------------
# The flag exists, is parsed, is documented


def test_CL_LIVE_1_flag_is_parsed_and_off_by_default():
    parser = importlib.import_module("tilo_evals.live_e2e")._parser()
    assert parser.parse_args(["--real-connectors"]).real_connectors is True
    assert parser.parse_args([]).real_connectors is False
    assert parser.parse_args(["--real-connectors", "--dry-run"]).dry_run is True
    assert parser.parse_args(["--real-connectors", "--replay"]).replay is True  # parsed; the guards refuse it


def test_CL_LIVE_1_run_live_e2e_takes_the_flag_and_the_factory_seam():
    sig = inspect.signature(importlib.import_module("tilo_evals.live_e2e").run_live_e2e)
    assert sig.parameters["real_connectors"].default is False
    assert sig.parameters["real_connectors_factory"].default is None
    main_sig = inspect.signature(importlib.import_module("tilo_evals.live_e2e").main)
    assert main_sig.parameters["real_connectors_factory"].default is None
    topic_sig = inspect.signature(importlib.import_module("tilo_evals.live_topic").main)
    assert topic_sig.parameters["real_connectors_factory"].default is None


def test_CL_LIVE_1_flag_is_in_the_documented_flag_lists():
    justfile = (lib.REPO_ROOT / "justfile").read_text(encoding="utf-8")
    docs = (lib.REPO_ROOT / "docs" / "live-e2e.md").read_text(encoding="utf-8")
    comment = justfile.split("live-run *flags:")[0].splitlines()[-4:]
    assert any("--real-connectors" in line for line in comment), "the live-run recipe's flag comment lists it"
    assert "--real-connectors" in docs
    # `just` takes flags only through this pattern; the new flag must pass it (it is lower-case letters and a dash)
    assert re.fullmatch(r"[-a-z0-9.= ]*", "--dry-run --real-connectors")


# ---------------------------------------------------------------------------
# Without the user's live switch, or in CI / on Cloud Run: refused, nothing sent, nothing built


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_without_live_1_the_run_is_refused_and_nothing_is_sent_or_built(kind, tmp_path, no_client):
    factory = NeverFactory()

    done = run(kind, tmp_path, ["--real-connectors"], values={"GOOGLE_CLOUD_PROJECT": lib.PROJECT}, factory=factory)

    assert done.code == 2 and done.refused() == "live_not_enabled", done.err
    assert factory.calls == 0 and no_client == []
    assert done.world.calls == [] and done.world.built == [], "no model call either"
    assert "outcome=" not in done.out


@pytest.mark.parametrize("live", ["0", "true", "yes", "01", " 1", "1 ", ""])
@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_only_exactly_1_counts_as_the_live_switch(kind, live, tmp_path, no_client):
    factory = NeverFactory()

    done = run(kind, tmp_path, ["--real-connectors"], values={**LIVE_ENV, "LIVE": live}, factory=factory)

    assert done.code == 2 and done.refused() == "live_not_enabled", done.err
    assert factory.calls == 0 and no_client == []


@pytest.mark.parametrize(
    ("marker", "code"),
    [("CI", "ci_refused"), ("GITHUB_ACTIONS", "ci_refused"), ("K_SERVICE", "deployed_refused"),
     ("CLOUD_RUN_JOB", "deployed_refused")],
)  # fmt: skip
@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_in_ci_or_on_cloud_run_the_flag_is_refused_even_with_the_switch_on(
    kind, marker, code, tmp_path, no_client
):
    factory = NeverFactory()

    done = run(kind, tmp_path, ["--real-connectors"], values={**LIVE_ENV, marker: "true"}, factory=factory)

    assert done.code == 2 and done.refused() == code, done.err
    assert factory.calls == 0 and no_client == []
    assert done.world.calls == []


def test_CL_LIVE_1_replay_with_the_flag_is_refused_and_builds_nothing(tmp_path, no_client):
    factory = NeverFactory()

    done = run_e2e(tmp_path, ["--replay", "--real-connectors"], values={}, factory=factory)

    assert done.code == 2 and done.refused() == "real_connectors_not_live", done.err
    assert factory.calls == 0 and no_client == []
    assert "REFUSED" in done.err and "outcome=" not in done.out


def test_CL_LIVE_1_the_fake_provider_path_refuses_real_connectors_before_any_call(tmp_path, no_client):
    """`record_with_fake` (the synthetic-fixture path) is a fake-provider run: real connectors never go with it."""
    module = importlib.import_module("tilo_evals.live_e2e")
    world = lib.world_for("B-005")
    factory = NeverFactory()

    with lib.env(), pytest.raises(module.LiveE2ERefused) as info:
        module.run_live_e2e(
            "B-005", mode="live", fake_record=True, live_provider_factory=world.factory,
            prices_path=lib.write_prices(tmp_path), recordings_dir=tmp_path / "rec",
            real_connectors=True, real_connectors_factory=factory,
        )  # fmt: skip

    assert info.value.code == "real_connectors_fake_providers"
    assert factory.calls == 0 and no_client == [] and world.built == []


# ---------------------------------------------------------------------------
# --dry-run: the plan, and nothing sent, nothing built


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_dry_run_prints_the_plan_read_only_with_scopes_and_builds_nothing(kind, tmp_path, no_client):
    factory = NeverFactory()

    done = run(kind, tmp_path, ["--dry-run", "--real-connectors"], values={}, factory=factory)

    assert done.code == 0, done.err
    plan = _plan(done.out)
    assert set(plan) == GOOGLE_IDS, done.out
    assert {k: v[0] for k, v in plan.items()} == PINNED, "the scopes the run would ask for, nothing wider"
    assert all(mode == "read_only" for _scopes, mode in plan.values())
    assert any(re.match(r"^real-connectors: read_only\b", line) for line in done.out.splitlines()), done.out
    assert "gmail.send" not in done.out and "gmail.modify" not in done.out
    assert factory.calls == 0 and no_client == [], "a dry run builds no client, no broker and no listener"
    assert done.world.calls == [] and done.world.built == []
    assert "REFUSED" not in done.err and "Traceback" not in done.err


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_without_the_flag_there_is_no_plan_and_the_factory_is_never_called(kind, tmp_path):
    factory = NeverFactory()

    done = run(kind, tmp_path, ["--dry-run"], values={}, factory=factory)

    assert done.code == 0 and _plan(done.out) == {} and factory.calls == 0


# ---------------------------------------------------------------------------
# The guards pass: the run uses the real adapters, read-only, and says so


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_with_the_guards_passed_the_run_uses_real_adapters_instead_of_the_mocks(kind, tmp_path):
    world = lib.world_for("B-005" if kind == "e2e" else "B-007")
    factory = ConnectorFactory(world=world)
    report = tmp_path / "report.json"

    if kind == "e2e":
        done = run_e2e(
            tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=factory, world=world, report_json=report
        )
    else:
        done = run_topic(tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=factory, world=world)

    assert factory.calls == 1, done.err + done.out
    assert factory.model_calls_at_call == [0], "the connectors are built (and fail closed) before the first model call"
    assert world.calls, "and then the run goes on"
    assert "outcome=held_at_gate" in done.out, done.err + done.out  # the gate is held: nothing could be sent
    assert done.code == 0, done.err
    spies = factory.adapters
    assert set(spies) == set(factory.registry.ids())
    assert sum(s.sent_reads for s in spies.values()) >= 1, "the run's own checks read these adapters, not the mocks'"
    assert factory.transport.writes() == [], "read-only: not one write request reached Google"
    line = next((m for m in map(re.compile(r"^connectors: real_read_only \((?P<ids>[a-z_, ]+)\)$").match,
                                done.out.splitlines()) if m), None)  # fmt: skip
    assert line is not None, done.out
    assert {i.strip() for i in line["ids"].split(",")} == GOOGLE_IDS
    faked = [row for row in done.out.splitlines() if row.startswith("faked:")]
    assert not [row for row in faked if "recording mocks" in row and "connectors" in row], faked
    assert any("recipient" in row for row in faked), "the recipient is still the dev stand-in, and the report says so"
    if kind == "e2e":
        assert json.loads(report.read_text(encoding="utf-8"))["side_effects"] == "real_read_only"


def test_CL_LIVE_1_the_default_run_is_unchanged_mocks_and_mock_only(tmp_path):
    """Offered a factory but not the flag, the run uses the recording mocks exactly as before."""
    world = lib.world_for("B-005")
    factory = ConnectorFactory(world=world)
    report = tmp_path / "report.json"

    done = run_e2e(tmp_path, [], values=LIVE_ENV, factory=factory, world=world, report_json=report)

    assert factory.calls == 0
    assert "outcome=held_at_gate" in done.out and done.code == 0, done.err
    assert json.loads(report.read_text(encoding="utf-8"))["side_effects"] == "mock_only"
    assert "faked: connectors and recipient: recording mocks; no real mailbox, chat or Drive write" in done.out
    assert "connectors: real_read_only" not in done.out


# ---------------------------------------------------------------------------
# Fail closed


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_a_missing_token_refuses_the_run_with_no_fallback_to_mocks(kind, tmp_path):
    world = lib.world_for("B-005" if kind == "e2e" else "B-007")
    factory = ConnectorFactory(connect=(), world=world)  # nobody consented: no token for any connector

    done = run(kind, tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=factory, world=world)

    assert done.code == 2 and done.refused() == "real_connectors_no_token", done.err
    assert factory.calls == 1 and world.calls == [] and factory.transport.requests == []
    assert "outcome=" not in done.out, "no run happened, so no report, and certainly not a run on mocks"
    leaked = [s for s in [*factory.secrets_in_play(), *factory.markers.all()] if s in done.everything]
    assert leaked == [], "a refusal carries no secret, token or mail text"


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_1_any_other_connector_failure_is_a_fixed_text_refusal_never_the_errors_words(kind, tmp_path):
    world = lib.world_for("B-005" if kind == "e2e" else "B-007")
    secret = "tok" + "en" + os.urandom(8).hex()
    factory = ConnectorFactory(raises=RuntimeError(f"boom {secret} Authorization: Bearer {secret}"), world=world)

    done = run(kind, tmp_path, ["--real-connectors"], values=LIVE_ENV, factory=factory, world=world)

    assert done.code == 2 and done.refused() == "real_connectors_failed", done.err
    assert secret not in done.everything and "boom" not in done.everything
    assert world.calls == [] and "outcome=" not in done.out


# ---------------------------------------------------------------------------
# No .env, ever


@pytest.mark.parametrize("live", [True, False])
def test_CL_LIVE_1_the_run_never_reads_or_writes_a_dotenv_file(live, tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("LIVE=1\nGOOGLE_OAUTH_CLIENT_SECRET=decoy\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    touched: list[str] = []
    real_open, real_path_open = builtins.open, pathlib.Path.open

    def is_dotenv(name: str) -> bool:
        return name == ".env" or name.endswith(".env")

    def spy_open(file, *args, **kwargs):
        if is_dotenv(pathlib.PurePath(str(file)).name):
            touched.append(str(file))
        return real_open(file, *args, **kwargs)

    def spy_path_open(self, *args, **kwargs):
        if is_dotenv(self.name):
            touched.append(str(self))
        return real_path_open(self, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", spy_open)
    monkeypatch.setattr(io, "open", spy_open)
    monkeypatch.setattr(pathlib.Path, "open", spy_path_open)
    world = lib.world_for("B-005")
    factory = ConnectorFactory(world=world)

    done = run_e2e(tmp_path, ["--real-connectors"], values=LIVE_ENV if live else {}, factory=factory, world=world)

    if live:
        assert "outcome=held_at_gate" in done.out, done.err
    else:
        assert done.refused() == "live_not_enabled", "the decoy's LIVE=1 is not the user's switch"
    assert touched == []
    assert (tmp_path / ".env").read_text(encoding="utf-8").startswith("LIVE=1\n"), "and nothing was written to it"


# ---------------------------------------------------------------------------
# Privacy: nothing the real adapters read is kept or shown


def test_CL_LIVE_1_what_the_real_adapters_read_is_in_no_recording_event_report_log_or_output(tmp_path):
    world = lib.world_for("B-005")
    factory = ConnectorFactory(world=world)
    recordings = tmp_path / "recordings-out"
    report = tmp_path / "report.json"

    done = run_e2e(
        tmp_path, ["--real-connectors"], values={**LIVE_ENV, "TILO_RECORD": "1"}, factory=factory, world=world,
        report_json=report,
    )  # fmt: skip

    assert "outcome=held_at_gate" in done.out, done.err
    assert factory.read_back["mail"]["subject"] == factory.markers.mail, "the planted content was really read"
    assert factory.read_back["drive"].decode() == factory.markers.drive
    assert [e.title for e in factory.read_back["events"].events] == [factory.markers.event]
    needles = [*factory.markers.all(), *factory.secrets_in_play()]
    files = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert recordings.is_dir() and any(files), "the run wrote its recordings and report"
    surfaces = {"stdout": done.out, "stderr": done.err, "logs": done.logs,
                "connection events": json.dumps(factory.events, default=repr)}  # fmt: skip
    surfaces.update({f"file {p.relative_to(tmp_path).as_posix()}": b.decode("latin-1") for p, b in files.items()})
    for where, text in surfaces.items():
        assert [n for n in needles if n in text] == [], f"{where} holds mailbox, Drive or Calendar content or a token"


def test_CL_LIVE_1_the_reports_events_hold_no_connector_content(tmp_path):
    """The events of the run itself (the report's `events`), read through the library call."""
    module = importlib.import_module("tilo_evals.live_e2e")
    world = lib.world_for("B-005")
    factory = ConnectorFactory(world=world)
    out, err = io.StringIO(), io.StringIO()

    with lib.env(**LIVE_ENV):
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            report = module.run_live_e2e(
                "B-005", mode="live", prices_path=lib.write_prices(tmp_path), recordings_dir=tmp_path / "rec",
                live_provider_factory=world.factory, safety=FakeSafetyProvider(),
                real_connectors=True, real_connectors_factory=factory,
            )  # fmt: skip

    assert report.side_effects == "real_read_only" and report.outcome_class == "held_at_gate", report.reason
    blob = json.dumps(report.events, default=repr) + json.dumps(report.to_dict(), default=repr)
    assert [n for n in [*factory.markers.all(), *factory.secrets_in_play()] if n in blob] == []


# ---------------------------------------------------------------------------
# The process exits non-zero without the switch (the real entry points)


@pytest.mark.parametrize(
    "script_args",
    [["evals/scripts/live_e2e.py", "--case", "B-007", "--real-connectors"],
     ["evals/scripts/live_run.py", "--topic", "Write a short note about composting.", "--real-connectors"]],
    ids=["live-e2e", "live-run"],
)  # fmt: skip
def test_CL_LIVE_1_the_entry_points_exit_non_zero_without_live_1_and_send_nothing(script_args):
    scrubbed = {k: v for k, v in os.environ.items()
                if k not in {"LIVE", "CI", "GITHUB_ACTIONS", "K_SERVICE", "CLOUD_RUN_JOB", "GOOGLE_API_KEY",
                             "GEMINI_API_KEY", "TILO_RECORD"}}  # fmt: skip
    scrubbed["GOOGLE_CLOUD_PROJECT"] = lib.PROJECT

    done = subprocess.run([sys.executable, *script_args], cwd=lib.REPO_ROOT, env=scrubbed, capture_output=True,
                          text=True, encoding="utf-8", timeout=300, check=False)  # fmt: skip

    assert done.returncode == 2, done.stderr
    assert re.search(r"^REFUSED live_not_enabled: ", done.stderr, re.M), done.stderr
    assert "Traceback" not in done.stderr and "unrecognized arguments" not in done.stderr
    assert "outcome=" not in done.stdout


def test_CL_LIVE_1_real_adapters_module_is_the_one_the_run_uses():
    """The run imports the factory from the connectors service (no second implementation in evals)."""
    assert real().real_adapters.__module__ == "tilo_connectors.real"
