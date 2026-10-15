"""FR-MEM-10 after the import: the event rules (EV-10 to EV-15) and the artifact-store rules (AR-01 to AR-08)
hold in the importer's world exactly as in a world that made the run itself (PRD 13.4 rollback, 13.5 FR-MEM-06,
15.1 retention):

- The imported stream passes a fresh `EventValidator` and `WorldState` event by event, EV-15 included, and the writer
  that replayed it knows what the world recorded: it accepts the next version and refuses a skipped one.
- The store keeps its rules for imported versions: reads re-hash (AR-01), the next version is the highest plus one
  (AR-02), a restore of an imported version is a new identical version (FR-MEM-06), a version of another scope reads as
  absent (AR-03), a unit's idempotency key still returns its imported version (AR-05, FR-AGT-10), manifest revisions
  append after the imported ones (AR-06), and every imported version is purgeable under the importer's owner, and only
  the importer's (AR-08, FR-MEM-09).
Fails now: `ModuleNotFoundError: No module named 'tilo_harness.run_bundle'`.

"""

from __future__ import annotations

import pytest
from bundle_support import (
    ARTICLE,
    OWNER,
    RUN,
    assert_replayed_identically,
    build_source_run,
    do_export,
    do_import,
    make_dest,
    sha,
)
from conftest import agent_idle_kwargs
from tilo_harness.validator import EventRejected, EventValidator, WorldState

pytestmark = pytest.mark.usefixtures("block_network")

ULID = "01JB5VQ0000000000000000777"


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


def _imported(src, tmp_path):
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    return dest


def test_FR_MEM_10_the_imported_stream_passes_the_validator_from_scratch(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    validator = EventValidator.from_repo()
    state = WorldState(imported.layout)
    state.world_id = imported.world
    for event in imported.stream():
        assert validator.problems(event, state) == [], f"seq {event['seq']}"
        state.observe(event)
    assert state.last_seq == 24  # WORLD-LIVE: the run also records its buildings and posts (6 events)
    assert state.versions[src.art_ids["brief"]] == 3


def test_FR_MEM_10_the_writer_knows_what_the_world_recorded_and_continues_it(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    brief = src.art_ids["brief"]
    assert imported.writer.recorded_version(brief) == 3
    with pytest.raises(EventRejected) as skipped:  # EV-15: the next version is the highest recorded plus one
        imported.writer.emit(
            type="artifact.versioned",
            actor="A_s0",
            target=brief,
            level="L1",
            district="D1",
            summary="A version that was never stored.",
            data={"artifact": {"artifact_id": brief, "version": 6}, "previous_version": 3},
        )
    assert all(p.startswith("EV-15") for p in skipped.value.problems)
    from tilo_memory.artifacts import NewVersion, Origin

    ref3 = {"artifact_id": brief, "version": 3}
    fourth = imported.artifacts.put(
        imported.scope,
        NewVersion(
            media_type="text/markdown",
            content=b"# Market brief v4\n",
            run_id=RUN,
            origin=Origin(kind="unit", unit="U7", agent="A_s0"),
            idempotency_key=f"{RUN}:U7:1:0",
            parent=ref3,
        ),
    )
    assert fourth.ref == {"artifact_id": brief, "version": 4}, "AR-02: highest imported version plus one"
    event = imported.writer.emit(
        type="artifact.versioned",
        actor="A_s0",
        target=brief,
        level="L1",
        district="D1",
        summary="The market brief has a new version.",
        data={"artifact": fourth.ref, "previous_version": 3},
    )
    assert event["seq"] == 25, "the stream continues where the run ended"
    imported.writer.emit(**agent_idle_kwargs("A_s0", "A_s0", level="L1", district="D1"))
    assert imported.writer.recorded_version(brief) == 4


def test_FR_MEM_10_a_second_created_of_an_imported_artifact_is_still_refused(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    brief = src.art_ids["brief"]
    with pytest.raises(EventRejected):
        imported.writer.emit(
            type="artifact.created",
            actor="A_s0",
            target=brief,
            level="L1",
            district="D1",
            summary="Made again.",
            data={
                "artifact": {"artifact_id": brief, "version": 1},
                "content_sha256": sha(ARTICLE),
                "media_type": "text/markdown",
                "size_bytes": len(ARTICLE),
            },
        )


def test_FR_MEM_10_reads_re_hash_imported_bytes_and_a_changed_byte_is_corrupt(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    from tilo_memory.artifacts import ArtifactCorrupt

    ref = {"artifact_id": src.art_ids["brief"], "version": 2}
    assert imported.artifacts.read(imported.scope, ref) == src.read(ref)
    (key,) = [k for k in imported.blobs.inner.keys() if k.endswith(f"{ref['artifact_id']}/v000002")]
    imported.blobs.inner.delete(key)
    imported.blobs.inner.create(key, b"changed")
    with pytest.raises(ArtifactCorrupt):
        imported.artifacts.read(imported.scope, ref)


def test_FR_MEM_10_restoring_an_imported_version_makes_a_new_identical_version(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    from tilo_memory.artifacts import Origin

    brief = src.art_ids["brief"]
    ref1 = {"artifact_id": brief, "version": 1}
    restored = imported.artifacts.restore(imported.scope, ref1, by=Origin(kind="restore"))
    assert restored.ref == {"artifact_id": brief, "version": 4}
    assert imported.artifacts.read(imported.scope, restored.ref) == imported.artifacts.read(imported.scope, ref1)
    assert restored.record["content_sha256"] == sha(src.read(ref1)) and restored.record["parents"] == [ref1]


def test_FR_MEM_10_a_units_idempotency_key_still_returns_its_imported_version(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    """ASSUMPTION (PRD 13.5 is silent): the record's idempotency key is kept on import, so a restarted unit of the same
    run in the importer's world finds its version (AR-05, FR-AGT-10) instead of making a second one."""
    from tilo_memory.artifacts import NewVersion, Origin

    ref = {"artifact_id": src.art_ids["brief"], "version": 1}
    record = src.rig.store.head(src.scope, ref).record
    again = imported.artifacts.put(
        imported.scope,
        NewVersion(
            media_type="text/markdown",
            content=b"different bytes on a restart\n",
            run_id=RUN,
            origin=Origin(kind="unit", unit=record["origin"]["unit"], agent=record["origin"]["agent"]),
            idempotency_key=record["idempotency_key"],
        ),
    )
    assert again.ref == ref and imported.artifacts.read(imported.scope, ref) == src.read(ref)
    assert [v.version for v in imported.artifacts.versions(imported.scope, ref["artifact_id"])] == [1, 2, 3]


def test_FR_MEM_10_manifest_revisions_append_after_the_imported_ones(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    ref = {"artifact_id": src.art_ids["brief"], "version": 2}
    before = imported.artifacts.manifest_revisions(imported.scope, ref)
    assert [(r["n"], r["stage"]) for r in before] == [(1, "created")]
    manifest = imported.artifacts.manifest(imported.scope, ref)
    assert imported.artifacts.add_manifest(imported.scope, ref, manifest, stage="reviewed", cause=ULID) == 2
    assert [r["n"] for r in imported.artifacts.manifest_revisions(imported.scope, ref)] == [1, 2]


def test_FR_MEM_10_imported_versions_belong_to_the_importer_s_owner_for_retention_and_erasure(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    records = imported.artifacts.retention().records()
    assert len(records) == 5 and {r.entity for r in records} == {"artifact"}
    assert {r.user_id for r in records} == {imported.owner} and imported.owner != OWNER
    assert all(r.record_id.startswith(f"orgs/{imported.org}/worlds/{imported.world}/") for r in records)
    source_before = len(src.rig.store.retention().records())
    for record in records:
        imported.artifacts.retention().delete(record.record_id)
    assert imported.meta.inner.paths() == [] and imported.blobs.inner.keys() == [], "erasure leaves nothing behind"
    assert len(src.rig.store.retention().records()) == source_before, "the source's own versions are untouched"


def test_FR_MEM_10_the_whole_replay_is_identical_again_in_the_scope_that_just_took_it(src, tmp_path) -> None:
    imported = _imported(src, tmp_path)
    assert_replayed_identically(src, imported)
