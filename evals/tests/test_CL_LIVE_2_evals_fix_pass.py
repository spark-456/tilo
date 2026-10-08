"""CL-LIVE-2 fix pass (security review): input typed or pasted before a write card never answers it, the flags of the
factory's gate must equal the run's, the card repeats recipient and destination above the prompt, and unused approvals
do not outlive a hold or the run. Fake Google, fake providers, no network. API: connectors/tests/API_CL_LIVE_2.md.
"""

from __future__ import annotations

import contextlib
import io
from collections.abc import Sequence
from typing import Any

import _live_e2e_lib as lib
import pytest
from _cl_live2_evals_lib import YES_ANSWERS, WriteFactory
from _cl_live_evals_lib import LIVE_ENV, run_topic
from _live_e2e_lib import network_guard  # noqa: F401  (autouse fixture)
from tilo_providers.safety import FakeSafetyProvider

FLAGS = ["--real-connectors", "--allow-writes"]
PASTE = ["Write a short note.", "", *["yes"] * 12]  # the topic, its blank line, then whatever followed in the buffer


class Terminal:
    """A scripted terminal: `buffered` is what is already in the input buffer; `drain` discards it (as the OS flush
    does) and then the person types `typed_after`."""

    def __init__(self, buffered: list[str], typed_after: Sequence[str] = (), *, can_drain: bool = True) -> None:
        self.queue, self.after, self.can_drain, self.drains = list(buffered), list(typed_after), can_drain, 0

    def read(self, _prompt: str) -> str:
        if not self.queue:
            raise EOFError
        return self.queue.pop(0)

    def drain(self) -> bool:
        self.drains += 1
        if not self.can_drain:
            return False
        self.queue[:] = self.after
        return True


def main(
    tmp_path, terminal: Terminal | None, factory, world, *extra: str, drain: Any = "terminal"
) -> tuple[int, str, str]:
    from tilo_evals import live_topic

    kwargs: dict[str, Any] = {}
    if drain is not None and terminal is not None:
        kwargs["drain"] = terminal.drain if drain == "terminal" else drain
    out, err = io.StringIO(), io.StringIO()
    argv = ["--topic-stdin", "--auto-answer", "--prices-file", str(lib.write_prices(tmp_path)), *FLAGS, *extra]
    with lib.env(**LIVE_ENV), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = live_topic.main(
            argv, live_provider_factory=world.factory, safety=FakeSafetyProvider(), read=terminal.read,
            tty=lambda: True, real_connectors_factory=factory, **kwargs,
        )  # fmt: skip
    return code, out.getvalue(), err.getvalue()


def test_CL_LIVE_2_pasted_lines_queued_before_the_card_never_approve_a_write(tmp_path):
    world = lib.world_for("B-007")
    factory, terminal = WriteFactory(world=world), Terminal(PASTE)

    code, out, err = main(tmp_path, terminal, factory, world)

    assert terminal.drains >= 1 and "outcome=held_at_gate" in out and code == 0, err + out
    assert "approved by a typed yes" not in out and factory.transport.uploads() == []
    assert "gate google_drive save_file: held" in out


def test_CL_LIVE_2_a_yes_typed_after_the_buffer_is_discarded_still_approves_once(tmp_path):
    world = lib.world_for("B-007")
    buffered = ["Write a short note.", "", "", "y", "ok", "yes", "yes"]  # the paste, plus the early typing
    factory, terminal = WriteFactory(world=world), Terminal(buffered, ["yes"])

    code, out, err = main(tmp_path, terminal, factory, world)

    assert code == 0 and "outcome=completed" in out, err + out
    assert "gate google_drive save_file: approved by a typed yes" in out and len(factory.transport.uploads()) == 1


def test_CL_LIVE_2_a_drain_that_cannot_run_holds_the_write(tmp_path):
    world = lib.world_for("B-007")
    for drain in ("terminal", lambda: (_ for _ in ()).throw(OSError("no console"))):
        factory = WriteFactory(world=world)
        terminal = Terminal(["Write a short note.", "", "", "y", "ok", "yes"], can_drain=False)

        code, out, err = main(tmp_path, terminal, factory, world, drain=drain)

        assert "outcome=held_at_gate" in out and factory.transport.uploads() == [], (drain, err + out)
        assert "approved by a typed yes" not in out and "discard" in out


def test_CL_LIVE_2_the_default_drain_fails_closed_when_stdin_is_not_a_console(monkeypatch):
    from tilo_evals import live_topic

    class Piped:
        def isatty(self) -> bool:
            return False

        def fileno(self) -> int:
            raise OSError("not a file")

    monkeypatch.setattr("sys.stdin", Piped())
    assert live_topic.drain_stdin() is False
    flushed: list[int] = []
    monkeypatch.setattr(live_topic, "_flush_input", lambda: flushed.append(1))
    assert live_topic.drain_stdin() is False and flushed == [], "a stdin that is not a tty is never flushed as one"

    class Console(Piped):
        def isatty(self) -> bool:
            return True

    monkeypatch.setattr("sys.stdin", Console())
    assert live_topic.drain_stdin() is True and flushed == [1]

    def boom() -> None:
        raise OSError("api unavailable")

    monkeypatch.setattr(live_topic, "_flush_input", boom)
    assert live_topic.drain_stdin() is False


def test_CL_LIVE_2_a_factory_whose_gate_flags_differ_from_the_run_is_refused(tmp_path):
    world = lib.world_for("B-007")
    factory = WriteFactory(world=world, allow_send=True)  # built with send, run without --allow-send

    done = run_topic(tmp_path, FLAGS, values=LIVE_ENV, factory=factory, world=world, answers=YES_ANSWERS)

    assert done.code == 2 and done.refused() == "real_connectors_failed", done.err
    assert world.calls == [] and factory.transport.uploads() == []

    other = WriteFactory(world=world)  # built without send, run with --allow-send
    done = run_topic(tmp_path, [*FLAGS, "--allow-send"], values=LIVE_ENV, factory=other, world=world,
                     answers=YES_ANSWERS)  # fmt: skip
    assert done.code == 2 and done.refused() == "real_connectors_failed" and world.calls == [], done.err


def _person(events: list, gate, said: str = "yes"):
    from tilo_evals.live_topic import TerminalPerson

    def read(prompt: str) -> str:
        events.append(("read", prompt))
        return said

    person = TerminalPerson(read=read, write=lambda t: events.append(("write", t)), tty=lambda: True,
                            drain=lambda: True)  # fmt: skip
    person.bind_write_gate(gate)
    return person


def _gate(body: str):
    from tilo_connectors.real_writes import WriteFlags, WriteGate

    gate = WriteGate(WriteFlags(True))
    gate.bind(lambda _w, _ref, _kind: {"kind": "email", "subject": "Hello", "body_text": body}, lambda t: t)
    return gate


CARD = {"world_id": "w_1", "gate": {"recipients": ["buyer@example.net"], "risk_tier": "T3",
        "action": {"type": "create_draft", "connector": "gmail", "destination": "thread-dev-1",
                   "item": {"artifact_id": "art_1", "version": 1}}}}  # fmt: skip


def test_CL_LIVE_2_the_card_repeats_recipient_and_destination_right_above_the_prompt():
    events: list = []
    person = _person(events, _gate("\n" * 290 + "x" * 10))

    assert person.gate(CARD) is True

    at = max(i for i, (kind, _t) in enumerate(events) if kind == "read")
    above = events[at - 1]
    assert above[0] == "write" and "buyer@example.net" in above[1] and "no thread: a new message" in above[1]
    shown = "\n".join(t for kind, t in events if kind == "write")
    assert shown.count("\n") < 40, "blank runs in the preview are collapsed"


def test_CL_LIVE_2_a_hold_drops_the_unused_approval_of_that_card():
    gate, events = _gate("hello"), []
    review = gate.review(CARD)
    assert gate.approve(review, said="yes", interactive=True) and gate.open_approvals == 1

    assert _person(events, gate, said="no").gate(CARD) is False

    assert gate.open_approvals == 0


def test_CL_LIVE_2_approvals_left_unused_are_dropped_at_the_end_of_the_run(tmp_path):
    from tilo_connectors.real import write_gate_of
    from tilo_connectors.real_writes import Review

    class Seeded(WriteFactory):
        gate: Any = None

        def __call__(self):
            built = super().__call__()
            self.gate = write_gate_of(built)
            stale = Review(True, "", "gmail", "create_draft", (), "x", "", "", 0, "d" * 64)
            assert self.gate.approve(stale, said="yes", interactive=True) and self.gate.open_approvals == 1
            return built

    world = lib.world_for("B-007")
    factory = Seeded(world=world)

    done = run_topic(tmp_path, FLAGS, values=LIVE_ENV, factory=factory, world=world, answers=YES_ANSWERS)

    assert done.code == 0 and len(factory.transport.uploads()) == 1, done.err
    assert factory.gate.open_approvals == 0


@pytest.mark.parametrize("doc", ["docs/live-e2e.md", "services/connectors/tests/API_CL_LIVE_2.md"])
def test_CL_LIVE_2_the_docs_state_the_buffer_rule_and_the_no_default_factory_fact(doc):
    text = (lib.REPO_ROOT / doc).read_text(encoding="utf-8")
    assert "input buffer" in text
    if doc == "docs/live-e2e.md":
        assert "real_connectors_no_token" in text and "until CL-LIVE-3" in text
        assert "never in a recording or report" not in text and "TILO_RECORD" in text.split("typed approval")[-1]


def test_CL_LIVE_2_a_person_without_a_drain_seam_never_counts_the_buffer_as_discarded():
    from tilo_evals.live_topic import TerminalPerson

    assert TerminalPerson(drain=None)._flushed() is False
    assert TerminalPerson(drain=lambda: False)._flushed() is False
    assert TerminalPerson(drain=lambda: True)._flushed() is True
