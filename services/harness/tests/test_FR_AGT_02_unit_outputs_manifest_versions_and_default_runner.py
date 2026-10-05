"""FR-AGT-02 / FR-MEM-06 / FR-CON-10 (ADR-0018 section 5): each stored version also gets a `created` manifest
revision from
`build_manifest`; an output that continues an earlier version is a new version of that artifact; `DefaultUnitRunner`
returns its text as `text/markdown`.

Ambiguity resolved here (ADR-0018 s5 says "one `artifact.created` per stored version", EV-15 says `created` names
version 1): an output with `parent` is version N+1 of the parent's artifact, so the executor announces it with
`artifact.versioned` (`previous_version` the parent's version), never a second `artifact.created`. A `created`
version 2 would be rejected by EV-15. The credits of the unit ride on the unit's first announced item whichever type.
"""

from __future__ import annotations

import asyncio

from agt_output_support import (
    ARTICLE,
    CSV,
    ORG,
    RUN,
    add_tool_call,
    created_ref,
    make_rig,
    outcome,
    run_units,
    sha,
    unit_output,
)
from agt_scripted import ScriptedProvider
from agt_support import contract_errors

NOTE = "Firm Faa reported revenue of 45 million."
CLAIM = {"id": "cl_1", "location": "slide1/cell:B2", "text": NOTE, "source_ids": ["src_a"], "verified": False}


def _with_source(rig):
    ref = add_tool_call(rig, NOTE)
    return unit_output(
        ARTICLE, label="Revenue note", sources=({"id": "src_a", "archive_ref": ref},), claims=(CLAIM,)
    ), ref


def test_FR_AGT_02_a_created_manifest_revision_is_stored_with_each_version(tmp_path) -> None:
    rig = make_rig(tmp_path / "archive")
    output, _ref = _with_source(rig)
    ran = run_units(
        tmp_path,
        {"U1": outcome([output, unit_output(CSV, "text/csv")])},
        skills={"U1": ["web_research"]},
        rig=rig,
    )
    for event in ran.of("artifact.created"):
        ref = event["data"]["artifact"]
        revisions = rig.store.manifest_revisions(rig.scope, ref)
        assert [(r["n"], r["stage"]) for r in revisions] == [(1, "created")], "one `created` revision per version"
        assert contract_errors("manifest", rig.store.manifest(rig.scope, ref)) == []


def test_FR_AGT_02_the_manifest_comes_from_build_manifest_with_the_run_s_events_and_archive(tmp_path) -> None:
    rig = make_rig(tmp_path / "archive")
    output, _ = _with_source(rig)
    ran = run_units(tmp_path, {"U1": outcome([output])}, skills={"U1": ["web_research"]}, rig=rig)
    (created,) = ran.of("artifact.created")
    ref = created["data"]["artifact"]
    manifest = rig.store.manifest(rig.scope, ref)
    (skill,) = ran.of("skill.loaded", actor="A_s0")
    (working,) = ran.of("agent.working")

    assert manifest["artifact"] == ref and manifest["content_sha256"] == sha(ARTICLE)
    assert manifest["parents"] == [] and manifest["authz"] is None
    produced = manifest["produced_by"]
    assert (produced["agent_id"], produced["role"]) == ("A_s0", "specialist")
    assert produced["skill"] == {"id": skill["data"]["skill"], "version": skill["data"]["version"]}, "MF-05"
    assert {skill["id"], working["id"]} <= set(manifest["events"]), "MF-04: the run's events that caused it"
    (source,) = manifest["sources"]
    assert (source["id"], source["kind"], source["ref"]) == ("src_a", "web", "https://example.com/note")
    assert source["fingerprint"] == "sha256:" + sha(NOTE.encode()), "from the archive record, never from the runner"
    assert manifest["claims"] == [CLAIM]
    assert rig.store.head(rig.scope, ref).record["sources"] == [{"id": "src_a", "archive_ref": f"{RUN}/1"}]


def test_FR_AGT_02_a_unit_with_no_skill_has_a_manifest_with_no_skill_and_no_sources(tmp_path) -> None:
    ran = run_units(tmp_path, {"U1": outcome([unit_output()])})
    (created,) = ran.of("artifact.created")
    manifest = ran.rig.store.manifest(ran.rig.scope, created["data"]["artifact"])
    assert manifest["produced_by"]["skill"] is None and manifest["sources"] == [] and manifest["claims"] == []


def _continue_script(extra_kwargs=None):
    def second(unit, context, events):
        parent = created_ref(events, "A_s0")
        return outcome([unit_output(ARTICLE + b"\nRevised.\n", **(extra_kwargs or {}), parent=parent)], credits=0.5)

    return {"U1": outcome([unit_output()]), "U2": second}


def test_FR_AGT_02_an_output_with_a_parent_is_the_next_version_announced_as_versioned_not_created(tmp_path) -> None:
    ran = run_units(tmp_path, _continue_script(), depends={"U2": ["U1"]})
    (first,) = ran.of("artifact.created")
    (second,) = ran.of("artifact.versioned")
    ref1, ref2 = first["data"]["artifact"], second["data"]["artifact"]
    assert ref2 == {"artifact_id": ref1["artifact_id"], "version": 2}
    assert second["data"] == {"artifact": ref2, "previous_version": 1}, "EV-15: created never names version 2"
    assert second["actor"] == "A_s1" and second["target"] == ref1["artifact_id"] and second["credits"] == 0.5
    record = ran.rig.store.head(ran.rig.scope, ref2).record
    assert record["parents"] == [ref1] and record["origin"]["unit"] == "U2"
    assert ran.rig.store.read(ran.rig.scope, ref1) == ARTICLE, "the earlier version is never rewritten (AR-02)"
    assert ran.result.outcomes["U2"].success is True


def test_FR_AGT_02_the_version_of_a_parent_has_a_created_manifest_naming_its_parent(tmp_path) -> None:
    ran = run_units(tmp_path, _continue_script(), depends={"U2": ["U1"]})
    ref1 = created_ref(ran.events, "A_s0")
    (second,) = ran.of("artifact.versioned")
    manifest = ran.rig.store.manifest(ran.rig.scope, second["data"]["artifact"])
    assert manifest["parents"] == [ref1], "MF-02"
    assert [r["stage"] for r in ran.rig.store.manifest_revisions(ran.rig.scope, second["data"]["artifact"])] == [
        "created"
    ]


def test_FR_AGT_02_a_parent_in_another_world_is_not_continued(tmp_path) -> None:
    from tilo_memory.artifacts import NewVersion, Origin, Scope

    rig = make_rig()
    other = rig.store.put(
        Scope(org_id=ORG, world_id="w_other", owner="u_owner"),
        NewVersion(media_type="text/markdown", content=ARTICLE, run_id=RUN, origin=Origin(kind="upload")),
    )
    ran = run_units(tmp_path, {"U1": outcome([unit_output(parent=other.ref)])}, rig=rig)
    assert ran.result.outcomes["U1"].success is False and ran.artifact_events_of("U1") == []


# --- DefaultUnitRunner -----------------------------------------------------------------------------


def _default_runner(text: str):
    from agt_scripted import role_providers
    from tilo_harness.executor import DefaultUnitRunner

    providers = role_providers(specialist=ScriptedProvider(default=text))
    return DefaultUnitRunner(providers), providers


def _context():
    from tilo_harness.executor import UnitContext

    return UnitContext(agent_id="A_s0", skills=())


def test_FR_AGT_02_default_runner_returns_its_text_as_a_markdown_output() -> None:
    from agt_support import build_unit

    runner, _providers = _default_runner("# Findings\n\nThree suppliers quoted a price.\n")
    result = asyncio.run(runner.run(build_unit("U1"), _context()))
    assert result.success is True
    (out,) = result.outputs
    assert out.media_type == "text/markdown", "code picks the media type from the role, never the model (common.schema)"
    assert out.content == b"# Findings\n\nThree suppliers quoted a price.\n" and isinstance(out.content, bytes)
    assert tuple(result.artifact_refs) == (), "it names no ref: the store mints the id"


def test_FR_AGT_02_default_runner_with_an_empty_reply_makes_no_output_and_fails() -> None:
    from agt_support import build_unit

    runner, _providers = _default_runner("")
    result = asyncio.run(runner.run(build_unit("U1"), _context()))
    assert result.success is False and tuple(result.outputs) == ()


def test_FR_AGT_02_default_runner_text_is_stored_and_announced_through_run_plan(tmp_path) -> None:
    runner, _providers = _default_runner("# Findings\n\nThree suppliers quoted a price.\n")
    ran = run_units(tmp_path, {"U1": None}, runner=runner)
    (created,) = ran.of("artifact.created")
    ref = created["data"]["artifact"]
    assert ran.rig.store.read(ran.rig.scope, ref) == b"# Findings\n\nThree suppliers quoted a price.\n"
    assert created["data"]["media_type"] == "text/markdown" and ran.result.outcomes["U1"].success is True


def test_FR_AGT_02_default_runner_reply_with_a_secret_is_stored_redacted(tmp_path) -> None:
    from agt_output_support import SECRET

    runner, _providers = _default_runner(f"Token: {SECRET}\n")
    ran = run_units(tmp_path, {"U1": None}, runner=runner)
    (created,) = ran.of("artifact.created")
    stored = ran.rig.store.read(ran.rig.scope, created["data"]["artifact"])
    assert SECRET.encode() not in stored and SECRET not in str(ran.events)
