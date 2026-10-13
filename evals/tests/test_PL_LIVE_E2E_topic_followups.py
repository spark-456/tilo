"""#594: pasted topics and terminal reports, using only fake input and recorded observations."""

import shutil
import subprocess
from dataclasses import replace
from types import SimpleNamespace

import pytest
from _live_e2e_lib import REPO_ROOT, bank_case
from test_PL_LIVE_E2E_topic_run import reader
from tilo_evals import live_topic
from tilo_evals.bank_checks import terminal_honest
from tilo_evals.bank_run import Observation


def test_PL_LIVE_E2E_multiline_topic_keeps_paragraphs_until_explicit_end():
    read, _ = reader(["First paragraph.", "", "Second paragraph.", "/end", "n"])
    assert live_topic._typed(read) == "First paragraph.\n\nSecond paragraph."
    assert read("later answer") == "n"


def test_PL_LIVE_E2E_topic_eof_preserves_paragraphs():
    read, _ = reader(["First paragraph.", "", "Second paragraph."])
    assert live_topic._typed(read) == "First paragraph.\n\nSecond paragraph."


def test_PL_LIVE_E2E_stop_line_cleans_terminal_controls(monkeypatch, capsys):
    report = SimpleNamespace(outcome_class="refused", reason="failure\x1b[2J\u202e detail", findings=[], work=[])
    monkeypatch.setattr(live_topic, "run_topic", lambda *_args, **_kwargs: report)
    monkeypatch.setattr(live_topic.e2e, "_print_report", lambda _report: None)
    assert live_topic.main(["--topic", "An offline test."]) == 1
    error = capsys.readouterr().err
    assert "failure" in error and "detail" in error
    assert "\x1b" not in error and "\u202e" not in error


@pytest.mark.parametrize("defect", ["no_reason", "budget", "completed", "sent"])
def test_PL_LIVE_E2E_declined_report_requires_evidence(defect):
    case = replace(bank_case("B-007"), expect={"outcome": "declined"})
    obs = Observation(case, outcome="declined", reason="declined by the person")
    assert terminal_honest(obs) == []
    if defect == "no_reason":
        obs.reason = " "
    elif defect == "sent":
        obs.sent_total = 1
    else:
        obs.events = [{"type": "budget.granted" if defect == "budget" else "world.completed"}]
    assert terminal_honest(obs), "declining an approach cannot claim started/completed work or omit its reason"


@pytest.mark.parametrize("quote", ["'", "\u2018", "\u2019", "\u201a", "\u201b"])
def test_PL_LIVE_E2E_live_run_file_refuses_single_quote_paths(quote):
    command = shutil.which("just")
    assert command is not None, "the recipe regression requires the repository's task runner"
    result = subprocess.run(
        [command, "--justfile", str(REPO_ROOT / "justfile"), "--dry-run", "live-run-file", f"topic{quote}.txt"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode != 0
    assert "rename a path that holds a single quote" in result.stderr
    assert "--topic-file" not in result.stdout
