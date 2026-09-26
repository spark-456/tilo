"""SEC-03 (PRD 16.4 SEC-03 row, services/connectors/CLAUDE.md "Local rules"): connector
side-effect methods are callable only from the outbox. Checked twice: (1) at runtime, an
adapter's side-effect method raises without a valid Grant, which only Outbox.dispatch_due()
mints; (2) statically, an ast scan of every tracked .py file under services/ and packages/
finds no call to a side-effect method outside the one outbox module (see API.md "SEC-03 static
check, resolved" for why this suite's own direct calls below are excluded from that scan).
"""

from __future__ import annotations

import subprocess
import textwrap

import pytest
import tilo_connectors
from _connectors_lib import ManualClock, evidence_from_case
from tilo_connectors.fakes import FakeGmail
from tilo_connectors.side_effects import SIDE_EFFECT_METHOD_NAMES, scan_for_side_effect_calls


def test_SEC_03_direct_call_without_a_grant_raises():
    gmail = FakeGmail()
    with pytest.raises(tilo_connectors.MissingGrant):
        gmail.send_reply("thread-supplier-1", None, ["riya@example.com"], "k1", grant=None)


def test_SEC_03_direct_call_with_a_forged_grant_raises():
    gmail = FakeGmail()
    with pytest.raises(tilo_connectors.MissingGrant):
        gmail.send_reply("thread-supplier-1", None, ["riya@example.com"], "k1", grant=object())


def test_SEC_03_dispatch_due_mints_a_grant_the_adapter_accepts(gate_case_factory):
    """The one legitimate path: going through Outbox.dispatch_due() succeeds."""
    case = gate_case_factory(undo_window_s=0)
    gmail = FakeGmail()
    store = tilo_connectors.InMemoryOutboxStore()
    outbox = tilo_connectors.Outbox(store, {"gmail": gmail}, lambda part: None, ManualClock("2026-09-29T09:00:00.000Z"))
    outbox.enqueue(case["entry"], evidence_from_case(case))

    sent = outbox.dispatch_due()

    assert len(sent) == 1
    assert sent[0]["state"] == "sent"
    assert len(gmail.sent) == 1


def test_SEC_03_send_reply_is_a_declared_side_effect_method():
    assert "send_reply" in SIDE_EFFECT_METHOD_NAMES


def test_SEC_03_static_scan_flags_a_call_outside_the_outbox(tmp_path, outbox_module_path):
    offender = tmp_path / "leaky_service.py"
    offender.write_text(
        textwrap.dedent(
            """
            from tilo_connectors.fakes import FakeGmail

            def leak(gmail, grant):
                return gmail.send_reply("thread-1", None, ["a@example.com"], "k1", grant)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    violations = scan_for_side_effect_calls([offender], allowed_path=outbox_module_path)

    assert len(violations) == 1
    v = violations[0]
    assert v.path == offender.resolve()
    assert v.method_name == "send_reply"
    assert v.lineno == 4


def test_SEC_03_static_scan_allows_a_call_inside_the_outbox_module(tmp_path):
    """A call in the file named as `allowed_path` is not flagged, whatever its contents --
    this is the one place SIDE_EFFECT_METHOD_NAMES calls belong."""
    pretend_outbox = tmp_path / "outbox.py"
    pretend_outbox.write_text(
        textwrap.dedent(
            """
            def dispatch(gmail, grant):
                return gmail.send_reply("thread-1", None, ["a@example.com"], "k1", grant)
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    violations = scan_for_side_effect_calls([pretend_outbox], allowed_path=pretend_outbox)

    assert violations == []


def test_SEC_03_static_scan_skips_files_that_do_not_parse(tmp_path, outbox_module_path):
    broken = tmp_path / "broken.py"
    broken.write_text("def f(:\n", encoding="utf-8")

    violations = scan_for_side_effect_calls([broken], allowed_path=outbox_module_path)

    assert violations == []


def test_SEC_03_static_side_effect_calls_only_in_outbox(repo_root, outbox_module_path):
    """The real, whole-repo check (ticket text: "every tracked .py file under services/ and
    packages/"). Excludes test paths -- see API.md "SEC-03 static check, resolved": this
    suite's own direct calls above must live outside the outbox to prove MissingGrant, which a
    real SEC-03 lint would exempt the same way."""
    result = subprocess.run(
        ["git", "ls-files", "--", "services", "packages"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked = [
        (repo_root / line).resolve()
        for line in result.stdout.splitlines()
        if line.endswith(".py")
        and "/tests/" not in line.replace("\\", "/")
        and not line.rsplit("/", 1)[-1].startswith("test_")
    ]
    assert tracked, "expected at least some tracked .py files under services/ and packages/"

    violations = scan_for_side_effect_calls(tracked, allowed_path=outbox_module_path)

    assert violations == [], [f"{v.path}:{v.lineno} calls {v.method_name}()" for v in violations]
