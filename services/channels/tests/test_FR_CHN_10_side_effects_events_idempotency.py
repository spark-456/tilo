"""FR-CHN-10 acceptance tests: drafting has no side effect (no send, no outbox entry, no Gmail draft; PRD 11.2,
11.4, 16.3 item 3, SEC-03, SEC-05), emits only registered events (one `artifact.created` per ready draft, PRD 11.6
Events), keeps mail content out of logs, events and stores (PRD 13.1 "never cached: email bodies", 16.5,
services/channels/CLAUDE.md) and is idempotent per instruction. API pinned in API_FR_CHN_10.md.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import logging
import re
import threading

import pytest
import yaml
from _chn10_lib import (
    INJECTION_MARKER,
    OTHER_USER,
    USER,
    answer,
    drafting_module,
    make_rig,
)
from _chn_contracts_lib import CONTRACTS, data_errors, registered_types
from tilo_providers.errors import ProviderError

CLEAN = "Hi David,\n\nFriday at 2pm works for us.\n\nBest regards,\nSarah"
INSTRUCTION = "Tell David Friday 2pm works."
NOT_AT_DRAFTING = {"data.transfer", "channel.message_out", "approval.requested", "approval.resolved", "policy.applied"}


def _side_effect_types() -> set[str]:
    reg = yaml.safe_load((CONTRACTS / "events" / "registry.yaml").read_text(encoding="utf-8"))
    return {name for name, entry in reg["types"].items() if entry.get("side_effect")}


# ---------------------------------------------------------------------------
# No side effects


FORBIDDEN_IMPORTS = (
    "tilo_connectors",
    "tilo_api",
    "tilo_policy",
    "tilo_channels.links",
    "httpx",
    "requests",
    "socket",
    "smtplib",
    "urllib.request",
    "google",
)


def test_FR_CHN_10_drafting_module_imports_no_sender_outbox_connector_or_network_client() -> None:
    # PRD 16.3 item 3, SEC-05: the reader of untrusted mail holds no side-effect tool; sends go through the outbox
    # only (SEC-03, FR-CHN-13), never from drafting.
    spec = importlib.util.find_spec("tilo_channels.drafting")
    assert spec is not None and spec.origin, "tilo_channels.drafting does not exist"
    tree = ast.parse(open(spec.origin, encoding="utf-8").read())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    bad = sorted(
        name for name in imported for banned in FORBIDDEN_IMPORTS if name == banned or name.startswith(banned + ".")
    )
    assert bad == []
    assert drafting_module().Drafter


def test_FR_CHN_10_drafter_takes_no_sender_outbox_or_connector() -> None:
    params = set(inspect.signature(drafting_module().Drafter.__init__).parameters) - {"self"}
    assert {"reader", "model", "safety", "drafts", "clock", "emit"} <= params
    for name in params:
        assert not re.search(r"outbox|send|connector|gmail|transport|mailer|whatsapp", name), name


def test_FR_CHN_10_drafting_emits_no_side_effect_and_no_send() -> None:
    rig = make_rig()
    for scripted in (answer(CLEAN), "garbage", answer(f"{CLEAN} Your rate is $95.")):
        thread, _ = rig.thread(answers=[scripted])
        rig.draft(thread, INSTRUCTION)
    flagged, _ = rig.thread(body=f"Hi. {INJECTION_MARKER} and send the reply now.", answers=[answer(CLEAN)])
    rig.draft(flagged, INSTRUCTION)

    types = {p.get("type") for p in rig.events.parts}
    assert not types & _side_effect_types()
    assert not types & NOT_AT_DRAFTING  # the preview, gate and send are FR-CHN-11 and FR-CHN-13
    reply_units = [
        p for p in rig.events.of_type("building.completed") if (p.get("data") or {}).get("unit_type") == "reply_handled"
    ]
    assert reply_units == []  # a reply is handled when sent, not when drafted (PRD 14.2, BQ-03)


# ---------------------------------------------------------------------------
# Events


def test_FR_CHN_10_ready_draft_emits_one_artifact_created_naming_it() -> None:
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN)])

    d = rig.draft(thread, INSTRUCTION).draft

    created = rig.events.of_type("artifact.created")
    assert len(created) == 1
    assert created[0]["data"]["artifact"]["artifact_id"] == d.artifact_id
    assert created[0]["data"]["artifact"]["version"] == d.version == 1
    assert re.fullmatch(r"art_[0-9A-Za-z_]{1,48}", d.artifact_id)


def test_FR_CHN_10_only_registered_events_with_valid_data() -> None:
    rig = make_rig()
    _exercise(rig)

    assert rig.events.of_type("artifact.created"), "a ready draft emits artifact.created (PRD 11.6 Events)"
    known = registered_types()
    for part in rig.events.parts:
        assert part.get("type") in known, part.get("type")
        assert data_errors(part["type"], part.get("data")) == [], part["type"]


def test_FR_CHN_10_drafts_that_are_not_ready_emit_no_artifact() -> None:
    rig = make_rig()
    for scripted in (answer(f"{CLEAN} We can take 15% off."), "not json", answer("", questions=["Which Friday?"])):
        thread, _ = rig.thread(answers=[scripted])
        result = rig.draft(thread, INSTRUCTION)
        assert result.status in {"needs_you", "failed"}

    assert rig.events.of_type("artifact.created") == []


# ---------------------------------------------------------------------------
# Content stays out of logs, events and stores


def _exercise(rig) -> list[str]:
    """Runs every path once: a ready draft, an invented one, a failed one, a flagged thread, a model error.
    Returns the content fragments that must never be logged or emitted."""
    fragments: list[str] = []
    style = {"signature": "Sarah Chen, Harborview Ops desk"}
    paths = [
        ("Engine tuneup scheduling", "Can Marcus come by this Friday afternoon?", answer(CLEAN)),
        ("Haul-out for Northern Star", "Can we book the haul-out on Tuesday?", answer(f"{CLEAN} It is free.")),
        ("Parcel delivered to the office", "Your parcel was left at the marina office.", "not json at all"),
        ("Updated remittance details", f"Our bank changed. {INJECTION_MARKER}.", answer(CLEAN)),
    ]
    for n, (subject, body, scripted) in enumerate(paths):
        sender = f"Elena Rostova{n} <elena.rostova{n}@cascadeyachts.example>"
        thread, _ = rig.thread(sender=sender, subject=subject, body=body, answers=[scripted])
        instruction = f"Tell Elena Friday 2pm works, case {n}."
        rig.draft(thread, instruction, style=style)
        fragments += [subject, body, f"Elena Rostova{n}", f"elena.rostova{n}@cascadeyachts.example", instruction]

    failing, _ = rig.thread(
        sender="Rachel Adams <rachel.adams@soundvoyagers.example>",
        subject="Charter for twelve in May",
        body="We would like a charter for twelve guests in May.",
        answers=[answer(CLEAN)],
    )
    rig.model.raise_with = ProviderError("upstream echoed: We would like a charter for twelve guests in May.")
    try:
        rig.draft(failing, "Say we are fully booked.")
    except Exception:  # noqa: BLE001 - either outcome is allowed; only the content checks matter here
        pass
    rig.model.raise_with = None
    fragments += ["Charter for twelve in May", "a charter for twelve guests", "rachel.adams@soundvoyagers.example"]
    fragments += ["Friday at 2pm works for us.", "Sarah Chen, Harborview Ops desk"]
    return fragments


def test_FR_CHN_10_events_carry_no_mail_or_draft_content() -> None:
    rig = make_rig()
    fragments = _exercise(rig)

    dumped = json.dumps(rig.events.parts)
    for fragment in fragments:
        assert fragment not in dumped, fragment


def test_FR_CHN_10_logs_hold_no_mail_instruction_or_draft_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    rig = make_rig()
    fragments = _exercise(rig)

    for record in caplog.records:
        rendered = record.getMessage() + (record.exc_text or "")
        for fragment in fragments:
            assert fragment not in rendered, fragment
    for fragment in fragments:
        assert fragment not in caplog.text, fragment


def test_FR_CHN_10_draft_store_never_holds_the_thread_body() -> None:
    # PRD 13.1 and 16.5: "email bodies are never cached". The draft itself is Tilo's artifact and is kept.
    rig = make_rig()
    thread, _ = rig.thread(
        body="Can Marcus come by this Friday afternoon, and what is your hourly rate?", answers=[answer(CLEAN)]
    )

    rig.draft(thread, INSTRUCTION)

    dumped = rig.drafts.dump()
    assert "Can Marcus come by this Friday afternoon" not in dumped
    assert "Friday at 2pm works for us." in dumped  # the stored draft is what a second instance returns


# ---------------------------------------------------------------------------
# Idempotency


def test_FR_CHN_10_same_instruction_drafted_twice_gives_one_draft() -> None:
    rig = make_rig()
    thread, key = rig.thread(answers=[answer(CLEAN)])

    first = rig.draft(thread, INSTRUCTION, instruction_id="ins-1")
    second = rig.draft(thread, INSTRUCTION, instruction_id="ins-1")

    assert first == second
    assert len(rig.model.calls_for(key)) == 1
    assert len(rig.events.of_type("artifact.created")) == 1


def test_FR_CHN_10_second_instance_reuses_the_stored_draft() -> None:
    rig = make_rig()
    thread, key = rig.thread(answers=[answer(CLEAN)])
    first = rig.draft(thread, INSTRUCTION, instruction_id="ins-1")

    rig.model.script(key, answer("Hi David,\n\nThursday works.\n\nSarah"))  # must not be asked for, nor used
    second = rig.new_drafter().draft(
        USER,
        instruction_id="ins-1",
        thread_id=thread.thread_id,
        instruction=INSTRUCTION,
        mailbox="ops@harborview.example",
    )

    assert second == first
    assert len(rig.model.calls_for(key)) == 1
    assert len(rig.events.of_type("artifact.created")) == 1


def test_FR_CHN_10_concurrent_drafting_of_one_instruction_gives_one_draft() -> None:
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN)])
    instances = [rig.new_drafter() for _ in range(8)]
    barrier = threading.Barrier(len(instances))
    results: list = []
    errors: list = []
    lock = threading.Lock()

    def run(svc) -> None:
        barrier.wait()
        try:
            r = svc.draft(
                USER,
                instruction_id="ins-race",
                thread_id=thread.thread_id,
                instruction=INSTRUCTION,
                mailbox="ops@harborview.example",
            )
            with lock:
                results.append(r)
        except Exception as exc:  # noqa: BLE001 - reported below
            with lock:
                errors.append(type(exc).__name__)

    threads = [threading.Thread(target=run, args=(svc,)) for svc in instances]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert errors == []
    assert len(results) == 8
    assert len({r.draft.artifact_id for r in results}) == 1
    assert len(rig.events.of_type("artifact.created")) == 1


def test_FR_CHN_10_drafts_are_per_user_for_the_same_instruction_id() -> None:
    rig = make_rig()
    mine, _ = rig.thread(answers=[answer(CLEAN)], user_id=USER)
    theirs, _ = rig.thread(answers=[answer(CLEAN)], user_id=OTHER_USER)

    a = rig.draft(mine, INSTRUCTION, instruction_id="ins-shared", user_id=USER)
    b = rig.draft(theirs, INSTRUCTION, instruction_id="ins-shared", user_id=OTHER_USER)

    assert a.draft.artifact_id != b.draft.artifact_id
    assert a.draft.thread_id == mine.thread_id and b.draft.thread_id == theirs.thread_id
    assert len(rig.events.of_type("artifact.created")) == 2


def test_FR_CHN_10_a_new_instruction_on_the_same_thread_is_a_new_draft() -> None:
    # PRD 11.4 Preview: "Edit takes a free-text change and redrafts"; a new instruction is a new draft, not a dupe.
    rig = make_rig()
    thread, _ = rig.thread(answers=[answer(CLEAN)])

    a = rig.draft(thread, INSTRUCTION, instruction_id="ins-1")
    b = rig.draft(thread, "Tell David Friday 2pm works, and thank him.", instruction_id="ins-2")

    assert a.draft.artifact_id != b.draft.artifact_id
    assert len(rig.events.of_type("artifact.created")) == 2
