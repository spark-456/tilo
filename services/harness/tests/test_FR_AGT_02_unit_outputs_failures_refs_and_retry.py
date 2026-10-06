"""FR-AGT-02 / FR-MEM-06 (ADR-0018 section 5 and 6): what makes a unit fail instead of announcing an item.

- A put or manifest failure fails the unit and no `artifact.*` event, handoff or envelope is written for it (HR-1,
  HR-2: nothing appears in the world for an item the store did not commit and the manifest did not cover); the unit
  still retires, its dependents are skipped, the other units go on.
- `UnitOutcome.artifact_refs` (versions that already exist) are accepted only if the store holds them in the run's
  scope; a ref of another world, another owner or nothing at all fails the unit and is never enveloped (AR-03).
- A corrupt blob under an idempotency key raises `ArtifactCorrupt` for ever (AR-01, AR-05), so the executor starts a
  new attempt (a new key), bounded by `config/agents.yaml` `retries.max_attempts` (PRD 8.3, 3).
"""

from __future__ import annotations

import pytest
from agt_output_support import (
    ARTICLE,
    CSV,
    OWNER,
    RUN,
    SECRET,
    FakeSafety,
    created_ref,
    make_rig,
    outcome,
    run_units,
    seed_corrupt,
    sha,
    unit_output,
)

OK = {"id": "cl_1", "location": "slide1/cell:B2", "text": "A plain claim.", "source_ids": [], "verified": False}


BAD_CASES = (
    "empty_content",
    "over_the_2_mb_text_cap",
    "content_is_text_not_bytes",
    "media_type_not_one_of_the_nine",
    "a_unit_never_makes_a_file",
    "eleven_outputs_over_the_cap_of_ten",
    "parent_the_store_does_not_hold",
    "source_not_in_the_raw_archive",
    "claim_cites_a_source_the_manifest_lacks",
    "secret_in_a_claim_MF_06",
    "valid_then_empty",
)


def _bad_outputs():
    """One list of outputs per way a put or the manifest refuses it (AR-04, AR-03, AR-05, MF-01, MF-06)."""
    leak = {**OK, "text": f"The key is {SECRET}."}
    return {
        "empty_content": [unit_output(b"")],
        "over_the_2_mb_text_cap": [unit_output(b"x" * 2_000_001)],
        "content_is_text_not_bytes": [unit_output("not bytes")],
        "media_type_not_one_of_the_nine": [unit_output(ARTICLE, "text/html")],
        "a_unit_never_makes_a_file": [unit_output(b"%PDF-1.7", "application/pdf")],
        "eleven_outputs_over_the_cap_of_ten": [unit_output(ARTICLE + bytes([i])) for i in range(11)],
        "parent_the_store_does_not_hold": [unit_output(parent={"artifact_id": "art_nope", "version": 1})],
        "source_not_in_the_raw_archive": [unit_output(sources=({"id": "src_a", "archive_ref": f"{RUN}/99"},))],
        "claim_cites_a_source_the_manifest_lacks": [unit_output(claims=({**OK, "source_ids": ["src_nope"]},))],
        "secret_in_a_claim_MF_06": [unit_output(claims=(leak,))],
        "valid_then_empty": [unit_output(ARTICLE), unit_output(CSV, "text/csv"), unit_output(b"")],
    }


@pytest.mark.parametrize("case", BAD_CASES)
def test_FR_AGT_02_a_put_or_manifest_failure_fails_the_unit_with_no_artifact_event_and_no_handoff(
    tmp_path, case
) -> None:
    ran = run_units(
        tmp_path,
        {
            # built inside the runner: a UnitOutput that refuses its own bad content fails the unit the same way
            "U1": lambda unit, context, events: outcome(_bad_outputs()[case]),
            "U2": outcome([unit_output(CSV, "text/csv")]),
            "U3": outcome(()),
        },
        depends={"U3": ["U1"]},
        with_archive=True,
    )
    assert ran.result.outcomes["U1"].success is False
    assert ran.artifact_events_of("U1") == [], "no artifact event for an item that was not fully committed"
    assert ran.of("agent.handoff", actor="A_s0") == [] and ran.of("agent.retired") != []
    retired = [e for e in ran.of("agent.retired") if e["target"] == "A_s0"]
    assert len(retired) == 1, "the failed unit still retires"
    assert "U3" in ran.result.skipped, "a unit whose dependency failed is skipped"
    assert len(ran.artifact_events_of("U2")) == 1 and ran.result.outcomes["U2"].success is True, "other units go on"
    assert SECRET not in str(ran.events)


def test_FR_AGT_02_a_store_backend_error_fails_that_unit_only(tmp_path) -> None:
    rig = make_rig(fail_unit="U1")
    ran = run_units(tmp_path, {"U1": outcome([unit_output()]), "U2": outcome([unit_output(CSV, "text/csv")])}, rig=rig)
    assert ran.result.outcomes["U1"].success is False and ran.artifact_events_of("U1") == []
    assert ran.result.outcomes["U2"].success is True and len(ran.artifact_events_of("U2")) == 1


def test_FR_AGT_02_a_failed_unit_that_stored_some_outputs_announces_none(tmp_path) -> None:
    """A version stored but never announced is invisible: worlds and lenses are event-driven (ADR-0018 s6)."""
    ran = run_units(tmp_path, {"U1": outcome(_bad_outputs()["valid_then_empty"])})
    assert ran.of("artifact.created", "artifact.versioned") == []
    assert len(ran.of("agent.working")) == 1, "the unit did start; only its result was refused"


def _existing_ref_script(extra):
    def second(unit, context, events):
        return outcome((), refs=extra(events))

    return {"U1": outcome([unit_output()]), "U2": second}


def test_FR_AGT_02_an_existing_ref_held_in_the_run_scope_is_handed_over_without_a_second_created(tmp_path) -> None:
    ran = run_units(tmp_path, _existing_ref_script(lambda ev: [created_ref(ev, "A_s0")]), depends={"U2": ["U1"]})
    (made,) = ran.of("artifact.created")
    assert made["actor"] == "A_s0", "only U1 made an item"
    handoff = next(e for e in ran.of("agent.handoff") if e["data"]["envelope"]["from"] == "A_s1")
    assert handoff["data"]["envelope"]["artifact_refs"] == [made["data"]["artifact"]]
    assert ran.result.outcomes["U2"].success is True


def _foreign_scopes():
    from tilo_memory.artifacts import Scope

    return {
        "another_world": Scope(org_id="org_demo", world_id="w_other", owner=OWNER),
        "another_owner": Scope(org_id="org_demo", world_id="w_unit_out", owner="u_mallory"),
        "another_org": Scope(org_id="org_rival", world_id="w_unit_out", owner=OWNER),
    }


@pytest.mark.parametrize("where", ["another_world", "another_owner", "another_org"])
def test_FR_AGT_02_a_ref_held_only_in_another_scope_is_rejected_and_reads_as_absent(tmp_path, where) -> None:
    from tilo_memory.artifacts import NewVersion, Origin

    rig = make_rig()
    foreign = rig.store.put(
        _foreign_scopes()[where],
        NewVersion(media_type="text/markdown", content=ARTICLE, run_id=RUN, origin=Origin(kind="upload")),
    )
    ran = run_units(tmp_path, {"U1": outcome((), refs=[foreign.ref])}, rig=rig)
    assert ran.result.outcomes["U1"].success is False, "AR-03: another scope's version is not this run's to hand over"
    assert ran.of("agent.handoff") == [] and ran.artifact_events_of("U1") == []
    assert foreign.ref["artifact_id"] not in str(ran.events), "the event stream does not even name it"


def test_FR_AGT_02_a_ref_the_store_never_held_is_rejected(tmp_path) -> None:
    ghost = {"artifact_id": "art_ghost", "version": 1}
    ran = run_units(tmp_path, {"U1": outcome((), refs=[ghost]), "U2": outcome(())})
    assert ran.result.outcomes["U1"].success is False and ran.of("agent.handoff", actor="A_s0") == []
    assert "art_ghost" not in str(ran.events) and ran.result.outcomes["U2"].success is True


def test_FR_AGT_02_one_foreign_ref_among_good_outputs_fails_the_whole_unit(tmp_path) -> None:
    ran = run_units(
        tmp_path,
        {"U1": outcome([unit_output()], refs=[{"artifact_id": "art_ghost", "version": 1}])},
    )
    assert ran.result.outcomes["U1"].success is False
    assert ran.artifact_events_of("U1") == [], "no event for the good output either"


def test_FR_AGT_02_a_corrupt_blob_under_the_idempotency_key_starts_a_new_attempt(tmp_path) -> None:
    rig = make_rig()
    seed_corrupt(rig, "U1", "A_s0", range(0, 2))  # the keys of attempts 0 and 1 hold bad blobs, older than GRACE
    ran = run_units(tmp_path, {"U1": outcome([unit_output()])}, rig=rig)
    assert ran.result.outcomes["U1"].success is True, "ArtifactCorrupt never clears under a key: use a new attempt"
    (event,) = ran.of("artifact.created")
    record = rig.store.head(rig.scope, event["data"]["artifact"]).record
    assert record["idempotency_key"] == f"{RUN}:U1:2:0", "the first attempt number free of a corrupt blob"
    assert rig.store.read(rig.scope, event["data"]["artifact"]) == ARTICLE
    assert event["data"]["content_sha256"] == sha(ARTICLE)


def test_FR_AGT_02_a_corrupt_blob_that_never_clears_fails_the_unit_after_max_attempts_and_writes_nothing(
    tmp_path,
) -> None:
    rig = make_rig()
    seed_corrupt(rig, "U1", "A_s0", range(0, 10))  # every attempt the executor could try is corrupt
    ran = run_units(tmp_path, {"U1": outcome([unit_output()]), "U2": outcome(())}, rig=rig)
    assert ran.result.outcomes["U1"].success is False
    assert ran.artifact_events_of("U1") == [] and ran.of("agent.handoff", actor="A_s0") == []
    assert ran.result.outcomes["U2"].success is True, "bounded by retries.max_attempts (3), then the unit fails"


def test_FR_AGT_02_a_corrupt_blob_raises_an_alert_to_the_store_sink_not_a_world_event(tmp_path) -> None:
    rig = make_rig()
    seed_corrupt(rig, "U1", "A_s0", range(0, 2))
    run_units(tmp_path, {"U1": outcome([unit_output()])}, rig=rig)
    assert rig.alerts and all(a["type"] == "alert.raised" for a in rig.alerts), (
        "the store reports a corrupt version through its own alert sink (AR-01); the executor adds nothing to it"
    )


def test_FR_AGT_02_the_screener_never_sees_bytes_of_a_unit_that_failed_before_its_put(tmp_path) -> None:
    safety = FakeSafety()
    run_units(tmp_path, {"U1": outcome([unit_output(b"")])}, rig=make_rig(safety=safety))
    assert safety.calls == [], "caps and kinds are checked before any screening or hashing (AR-04)"
