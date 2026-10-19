"""CL-LIVE-2 (CONNECTORS-LIVE slice 2): `--allow-writes` / `--allow-send` of `just live-e2e` and `just live-run`. With
`--real-connectors --allow-writes` a gated Drive save (or Gmail draft) executes for real, but only after a person types
`yes` at an interactive terminal on the gate card; nothing else approves it. Fake Google, fake providers, no network.
API: services/connectors/tests/API_CL_LIVE_2.md.
"""

from __future__ import annotations

import importlib
import inspect
import re

import _live_e2e_lib as lib
import pytest
from _cl_live2_evals_lib import YES_ANSWERS, WriteFactory
from _cl_live_evals_lib import LIVE_ENV, run_e2e, run_topic
from _live_e2e_lib import network_guard  # noqa: F401  (autouse fixture)
from tilo_providers.safety import FakeSafetyProvider

KINDS = ["e2e", "topic"]


def run(kind: str, tmp_path, extra, **kwargs):
    return (run_e2e if kind == "e2e" else run_topic)(tmp_path, extra, **kwargs)


class Never:
    calls = 0

    def __call__(self):
        Never.calls += 1
        raise AssertionError("the connector factory was called")


def _world(kind: str):
    return lib.world_for("B-005" if kind == "e2e" else "B-007")


def test_CL_LIVE_2_the_flags_are_parsed_off_by_default_and_documented():
    parser = importlib.import_module("tilo_evals.live_e2e")._parser()
    args = parser.parse_args(["--real-connectors", "--allow-writes", "--allow-send"])
    assert args.allow_writes is True and args.allow_send is True
    assert parser.parse_args([]).allow_writes is False and parser.parse_args([]).allow_send is False
    sig = inspect.signature(importlib.import_module("tilo_evals.live_e2e").run_live_e2e)
    assert sig.parameters["allow_writes"].default is False and sig.parameters["allow_send"].default is False
    justfile = (lib.REPO_ROOT / "justfile").read_text(encoding="utf-8")
    docs = (lib.REPO_ROOT / "docs" / "live-e2e.md").read_text(encoding="utf-8")
    assert "--allow-writes" in justfile.split("live-run *flags:")[0].splitlines()[-4:].__str__()
    assert "--allow-writes" in docs and "--allow-send" in docs and "real_write_gated" in docs
    assert re.fullmatch(r"[-a-z0-9.= ]*", "--real-connectors --allow-writes --allow-send")


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("flags", "code"),
    [
        (["--allow-writes"], "allow_writes_needs_real_connectors"),
        (["--allow-send"], "allow_writes_needs_real_connectors"),
        (["--real-connectors", "--allow-send"], "allow_send_needs_allow_writes"),
    ],
)
def test_CL_LIVE_2_flag_combinations_that_make_no_sense_are_refused_before_any_call(kind, flags, code, tmp_path):
    world, factory = _world(kind), Never()
    Never.calls = 0

    done = run(kind, tmp_path, flags, values=LIVE_ENV, factory=factory, world=world)

    assert done.code == 2 and done.refused() == code, done.err
    assert Never.calls == 0 and world.calls == [] and "outcome=" not in done.out


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_2_the_write_flags_obey_the_live_switch_ci_and_replay(kind, tmp_path):
    flags = ["--real-connectors", "--allow-writes"]
    for values, code in [({}, "live_not_enabled"), ({**LIVE_ENV, "CI": "true"}, "ci_refused"),
                         ({**LIVE_ENV, "K_SERVICE": "svc"}, "deployed_refused")]:  # fmt: skip
        done = run(kind, tmp_path, flags, values=values, factory=Never(), world=_world(kind))
        assert done.code == 2 and done.refused() == code, (values, done.err)
    if kind == "e2e":
        done = run(kind, tmp_path, [*flags, "--replay"], values={}, factory=Never(), world=_world(kind))
        assert done.code == 2 and done.refused() == "real_connectors_not_live", done.err


def test_CL_LIVE_2_a_run_with_no_person_cannot_write(tmp_path):
    """`live-e2e` has no terminal: a bank case's scripted gate is not a person, so writes are refused up front."""
    world, factory = _world("e2e"), WriteFactory(world=_world("e2e"))

    done = run_e2e(tmp_path, ["--real-connectors", "--allow-writes"], values=LIVE_ENV, factory=factory, world=world)

    assert done.code == 2 and done.refused() == "allow_writes_needs_a_person", done.err
    assert factory.transport.writes() == [] and world.calls == []


@pytest.mark.parametrize("kind", KINDS)
def test_CL_LIVE_2_dry_run_prints_which_writes_would_be_gated_and_builds_nothing(kind, tmp_path):
    flags = ["--dry-run", "--real-connectors", "--allow-writes", "--allow-send"]
    done = run(kind, tmp_path, flags, values={}, factory=Never(), world=_world(kind))

    assert done.code == 0, done.err
    assert "real-writes: write_gated_send (dry run: nothing built, nothing sent)" in done.out
    assert "real-write gmail create_draft: typed terminal approval" in done.out
    assert "real-write gmail send_email: typed terminal approval" in done.out
    assert "real-write google_drive save_file: typed terminal approval" in done.out
    gmail = r"^real-connector gmail: scopes=\S+gmail\.readonly,\S+gmail\.compose,\S+gmail\.send mode=write_gated_send$"
    assert re.search(gmail, done.out, re.M)
    assert re.search(r"^real-connector google_calendar: scopes=\S+calendar\.readonly mode=read_only$", done.out, re.M)
    plain = run(kind, tmp_path, ["--dry-run", "--real-connectors", "--allow-writes"], values={}, factory=Never(),
                world=_world(kind))  # fmt: skip
    assert "send_email" not in plain.out and "write_gated (dry run" in plain.out


def test_CL_LIVE_2_a_typed_yes_writes_the_drive_file_once_and_the_report_says_so(tmp_path):
    world = _world("topic")
    factory = WriteFactory(world=world)

    done = run_topic(tmp_path, ["--real-connectors", "--allow-writes"], values=LIVE_ENV, factory=factory, world=world,
                     answers=YES_ANSWERS)  # fmt: skip

    assert done.code == 0 and "outcome=completed" in done.out, done.err + done.out
    assert len(factory.transport.uploads()) == 1, "an approve is exactly one request"
    assert "connectors: real_write_gated (gmail, google_drive, google_calendar)" in done.out
    assert "REAL WRITE (google_drive save_file)" in done.out and "to: " in done.out and "preview:" in done.out
    assert "gate google_drive save_file: approved by a typed yes" in done.out
    assert not [s for s in factory.secrets_in_play() if s in done.everything]


@pytest.mark.parametrize(
    ("answers", "tty", "extra"),
    [
        (("", "y", "ok", "no"), True, []),  # the person says no
        (("", "y", "ok", "y"), True, []),  # `y` is not the typed word `yes`
        (("", "y", "ok", "yes"), False, []),  # piped input, no interactive terminal
        (("", "y", "ok"), True, ["--auto-approve-t1t2"]),  # a flag never approves a real write; the prompt gets EOF
    ],
    ids=["no", "y", "no_tty", "auto_approve_flag"],
)
def test_CL_LIVE_2_nothing_but_a_typed_yes_at_a_terminal_approves_a_real_write(answers, tty, extra, tmp_path):
    from tilo_evals import live_topic

    world = _world("topic")
    factory = WriteFactory(world=world)
    queue = list(answers)

    def read(_prompt: str) -> str:
        if not queue:
            raise EOFError
        return queue.pop(0)

    import contextlib
    import io

    out, err = io.StringIO(), io.StringIO()
    with lib.env(**LIVE_ENV), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = live_topic.main(
            ["--topic", "Write a short note.", "--auto-answer", "--prices-file", str(lib.write_prices(tmp_path)),
             "--real-connectors", "--allow-writes", *extra],
            live_provider_factory=world.factory, safety=FakeSafetyProvider(), read=read, tty=lambda: tty,
            real_connectors_factory=factory,
        )  # fmt: skip

    assert "outcome=held_at_gate" in out.getvalue() and code == 0, err.getvalue()
    assert factory.transport.writes() == [] and factory.transport.uploads() == []
