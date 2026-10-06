"""FR-MEM-10 (PRD 13.5 "Export and re-import a run; replay is identical", Should; PRD 13.4 "any run can be exported as a
bundle (events, archive, artifacts, manifest) for incident review"; 13.3 exports carry a provenance manifest):

Given a finished run (events, artifact versions with manifests, raw-archive records), When it is exported and the bundle
is imported into a fresh world with no network, Then replaying the imported run gives the identical event stream and
the identical artifact bytes and hashes. Only identity is the importer's: the world id on the events, and the org,
world and owner on the artifact records. See API_FR_MEM_10.md for the interface and bundle layout these tests pin.

`tilo_harness.run_bundle` does not exist yet, so every test fails with `ModuleNotFoundError: No module named
'tilo_harness.run_bundle'`. That is the right failure.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from agt_output_support import TEXT_TYPES
from bundle_support import (
    ARCHIVE,
    BUNDLE_JSON,
    DEST_ORG,
    DEST_OWNER,
    DEST_WORLD,
    EVENTS,
    EXPORTED_AT,
    ORG,
    OWNER,
    RUN,
    WORLD,
    assert_replayed_identically,
    build_plain_run,
    build_random_run,
    build_source_run,
    do_export,
    do_import,
    lines_of,
    make_dest,
    names,
    revisions_of,
    sha,
    unpack,
)
from hypothesis import HealthCheck, Phase, given, settings
from hypothesis import strategies as st

pytestmark = pytest.mark.usefixtures("block_network")  # EFF-01: no network, no paid call


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


def _iso(moment) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{moment.microsecond // 1000:03d}Z"


# --- the round trip ---------------------------------------------------------------------------------------------------


def test_FR_MEM_10_export_then_import_replays_an_identical_run(src, tmp_path) -> None:
    bundle = do_export(src)
    dest = make_dest(tmp_path, src.layout)
    result = do_import(dest, bundle)
    assert_replayed_identically(src, dest)
    assert (result.run_id, result.org_id, result.world_id) == (RUN, DEST_ORG, DEST_WORLD)
    assert (result.events, result.versions, result.manifest_revisions, result.archive_records) == (18, 5, 4, 3)
    assert result.already_imported is False


@pytest.mark.parametrize(
    ("org", "world", "owner"),
    [(ORG, "w_replay_a", DEST_OWNER), ("org_elsewhere", "w_replay_b", "u_reviewer"), (ORG, "w_replay_c", OWNER)],
)
def test_FR_MEM_10_the_run_replays_identically_in_any_importer_scope(src, tmp_path, org, world, owner) -> None:
    """Same org other world, another org, and even the source owner in a new world: replay is identical in each."""
    dest = make_dest(tmp_path, src.layout, org=org, world=world, owner=owner)
    do_import(dest, do_export(src))
    assert_replayed_identically(src, dest)


def test_FR_MEM_10_a_run_with_no_artifacts_and_no_archive_round_trips(tmp_path) -> None:
    plain = build_plain_run(tmp_path / "plain")
    bundle = do_export(plain, archive=None)
    entries = unpack(bundle)
    assert names(entries, "/record.json") == [] and lines_of(entries[ARCHIVE]) == []
    dest = make_dest(tmp_path, plain.layout)
    result = do_import(dest, bundle)
    assert dest.stream() == [dict(e, world_id=dest.world) for e in plain.events]
    assert (result.versions, result.archive_records, result.events) == (0, 0, len(plain.events))
    assert dest.meta.inner.paths() == [] and dest.archive_files() == []


def test_FR_MEM_10_exporting_the_imported_run_again_carries_the_same_bytes(src, tmp_path) -> None:
    """Export, import, export: the second bundle holds the identical artifact bytes, manifests, archive and events
    (but for the importer's world id); its records differ from the first only in identity."""
    from tilo_archive import RunArchive

    first = unpack(do_export(src))
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    archive = RunArchive(dest.archive_store, org_id=dest.org, run_id=RUN, redactor=lambda payload: payload)
    second = unpack(
        do_export(
            src,
            events=dest.stream(),
            artifacts=dest.artifacts,
            scope=dest.scope,
            archive=archive,
            redact=dest.redactor,
        )
    )
    assert sorted(first) == sorted(second)
    for name in first:
        if name.endswith(("/content", "/manifests.json")) or name == ARCHIVE:
            assert first[name] == second[name], f"{name} is identical after a round trip"
    assert [json.loads(x) | {"world_id": 0} for x in lines_of(first[EVENTS])] == [
        json.loads(x) | {"world_id": 0} for x in lines_of(second[EVENTS])
    ]
    for name in names(first, "/record.json"):
        a, b = json.loads(first[name]), json.loads(second[name])
        for key in ("org_id", "world_id", "owner", "screened_at"):
            a.pop(key), b.pop(key)
        assert a == b, f"{name} differs only in identity"


# --- export: deterministic, read-only ---------------------------------------------------------------------------------


def _source_snapshot(src) -> dict:
    meta, blobs = src.rig.meta, src.rig.blobs
    return {
        "events": json.dumps(src.ran.events, sort_keys=True),
        "meta": {p: json.dumps(meta.get(p), sort_keys=True) for p in meta.paths()},
        "blobs": {k: bytes(blobs.read(k)) for k in blobs.keys()},
        "archive": src.archive_lines(),
    }


def test_FR_MEM_10_export_is_deterministic_and_changes_nothing_in_the_source(src) -> None:
    before = _source_snapshot(src)
    first, second = do_export(src), do_export(src)
    assert first == second, "the same run exports to the same bytes"
    assert _source_snapshot(src) == before, "an export is read-only: no manifest revision, event or record is added"
    later = unpack(do_export(src, clock=lambda: EXPORTED_AT.replace(hour=9)))
    now = unpack(first)
    assert {n for n in now if now[n] != later[n]} == {BUNDLE_JSON}, "only the export time differs"


def test_FR_MEM_10_the_bundle_has_the_pinned_closed_layout_and_a_hash_index(src) -> None:
    entries = unpack(do_export(src))
    meta = json.loads(entries[BUNDLE_JSON])
    assert (meta["format"], meta["version"], meta["run_id"]) == ("tilo.run-bundle", "1.0", RUN)
    assert meta["exported_at"] == _iso(EXPORTED_AT)
    assert meta["counts"] == {"events": 18, "archive_records": 3, "versions": 5, "manifest_revisions": 4}
    head = src.rig.archive.head()
    assert (meta["archive_head"]["seq"], meta["archive_head"]["hash"]) == (head[0], head[1])
    expected = {BUNDLE_JSON, EVENTS, ARCHIVE}
    for ref in src.refs():
        base = f"artifacts/{ref['artifact_id']}/v{ref['version']:06d}"
        expected |= {f"{base}/record.json", f"{base}/content", f"{base}/manifests.json"}
    assert set(entries) == expected, "a closed set of entries: nothing else rides along"
    assert meta["entries"] == {n: sha(d) for n, d in entries.items() if n != BUNDLE_JSON}, "SHA-256 of every entry"


def test_FR_MEM_10_the_entries_carry_the_run_exactly_as_stored_but_without_sources(src) -> None:
    entries = unpack(do_export(src))
    assert [json.loads(x) for x in lines_of(entries[EVENTS])] == src.events
    assert lines_of(entries[ARCHIVE]) == src.archive_lines()
    for ref in src.refs():
        base = f"artifacts/{ref['artifact_id']}/v{ref['version']:06d}"
        want = src.rig.store.head(src.scope, ref).record
        assert json.loads(entries[f"{base}/record.json"]) == dict(want, sources=[]), "AR-06: sources never leave Tilo"
        assert entries[f"{base}/content"] == src.read(ref)
        assert json.loads(entries[f"{base}/manifests.json"]) == revisions_of(src.rig.store, src.scope, ref)
    brief = src.rig.store.head(src.scope, {"artifact_id": src.art_ids["brief"], "version": 1}).record
    assert brief["sources"], "the source record does have a source: the bundle dropped it"
    assert b"archive_ref" not in b"".join(entries[n] for n in names(entries, "/record.json"))


def test_FR_MEM_10_only_versions_the_world_recorded_are_exported(tmp_path) -> None:
    run = build_source_run(tmp_path / "run")
    brief = {"artifact_id": run.art_ids["brief"], "version": 3}
    from tilo_memory.artifacts import NewVersion, Origin

    extra = run.rig.store.put(
        run.scope,
        NewVersion(
            media_type="text/markdown",
            content=b"never announced\n",
            run_id=RUN,
            origin=Origin(kind="unit", unit="U9", agent="A_s0"),
            idempotency_key=f"{RUN}:U9:1:0",
            parent=brief,
        ),
    )
    entries = unpack(do_export(run))
    assert extra.version == 4
    assert f"artifacts/{run.art_ids['brief']}/v000004/record.json" not in entries
    assert len(names(entries, "/record.json")) == 5, (
        "the world recorded five versions; the sixth was never announced (EV-15)"
    )


# --- property: any run replays identically ---------------------------------------------------------------------------

NO_SHRINK = (Phase.explicit, Phase.reuse, Phase.generate)  # a run of the executor is slow: report, do not shrink
OUTPUT = st.tuples(
    st.sampled_from(TEXT_TYPES),
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz ABC\n,.", min_size=1, max_size=40).filter(lambda t: t.strip()),
)
UNITS = st.lists(st.lists(OUTPUT, max_size=3), min_size=1, max_size=3)


@settings(max_examples=8, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture], phases=NO_SHRINK)
@given(units=UNITS, world=st.sampled_from(["w_a", "w_replay_zz"]), same_org=st.booleans())
def test_FR_MEM_10_property_any_run_exports_and_replays_identically(units, world, same_org) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        run = build_random_run(root / "src", [[(m, t.encode()) for m, t in outputs] for outputs in units])
        dest = make_dest(root, run.layout, world=world, org=ORG if same_org else DEST_ORG)
        bundle = do_export(run)
        assert bundle == do_export(run), "deterministic"
        do_import(dest, bundle)
        assert_replayed_identically(run, dest)
        assert WORLD not in json.dumps(dest.stream()), "the source world id appears nowhere in the imported stream"
