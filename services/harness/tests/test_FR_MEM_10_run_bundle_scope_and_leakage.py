"""FR-MEM-10 scope rules (PRD 16.5 per-org and per-world isolation, SEC-07 per-district views,
contracts/artifact.rules.md AR-03, event rules EV-10 to EV-13): importing never reuses the source scope's
identity, never leaks across worlds, and the importer's scope decides.

- Events keep everything but `world_id`, which becomes the importer's world. Artifact records take the importer's
  `org_id`, `world_id` and `owner`; the archive lands under the importer's org. Nothing is written under the source's
  ids, nor under any scope the bundle merely names.
- `import_run(scope=, writer=)`: the scope must be the writer's org and world (the call's own check), else refused.
- A bundle is one run of one world: mixed worlds or runs in the event stream are refused. The importer's world must be
  fresh (empty), because the run's `seq` starts at 1 (EV-10): another event already there refuses the bundle.
- Per-district views are the importing writer's own redaction of the replayed events (never copied from a bundle): a
  `vis` naming a district that the importer's layout does not have is refused (EV-13), so is an actor, target or
  district the layout does not know (EV-12).
- Export refuses what it cannot vouch for: events that are not one whole run of one world from seq 1 with no gap, a
  version the events name but the Scope does not hold (another world's versions read as absent, AR-03), a corrupt
  blob, a broken archive chain. Fails now: `ModuleNotFoundError: No module named 'tilo_harness.run_bundle'`.

"""

from __future__ import annotations

import json

import pytest
from agt_support import build_layout
from bundle_support import (
    DEST_ORG,
    DEST_OWNER,
    DEST_WORLD,
    EVENTS,
    ORG,
    OWNER,
    RUN,
    WORLD,
    assert_nothing_imported,
    assert_replayed_identically,
    build_source_run,
    do_export,
    do_import,
    edited,
    jb,
    jsonl,
    lines_of,
    make_dest,
    refused_and_nothing_written,
    refused_type,
    unpack,
)
from conftest import world_requested_kwargs

pytestmark = pytest.mark.usefixtures("block_network")


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


def _edit_events(change):
    def edit(entries):
        entries[EVENTS] = jsonl([change(json.loads(line)) for line in lines_of(entries[EVENTS])])

    return edit


def _edit_event(index, change):
    def edit(entries):
        items = [json.loads(line) for line in lines_of(entries[EVENTS])]
        items[index] = change(items[index])
        entries[EVENTS] = jsonl(items)

    return edit


# --- identity: the importer's scope decides -------------------------------------------------------------------------


def test_FR_MEM_10_the_import_takes_the_importer_s_org_world_and_owner_and_keeps_nothing_of_the_source(
    src, tmp_path
) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    assert {e["world_id"] for e in dest.stream()} == {DEST_WORLD}
    for path in dest.meta.inner.paths():
        assert path.startswith(f"orgs/{DEST_ORG}/worlds/{DEST_WORLD}/"), path
        record = dest.meta.inner.get(path)
        if "/manifests/" not in path:
            assert (record["org_id"], record["world_id"], record["owner"]) == (DEST_ORG, DEST_WORLD, DEST_OWNER)
    assert all(k.startswith(f"orgs/{DEST_ORG}/worlds/{DEST_WORLD}/") for k in dest.blobs.inner.keys())
    assert dest.archive_files() == [f"{DEST_ORG}/{RUN}.jsonl"], "the archive lands under the importer's org"
    for needle in (ORG, WORLD):
        assert not dest.meta.mentions(needle) and not dest.blobs.mentions(needle), (
            f"{needle} reached the artifact store"
        )
        assert needle not in json.dumps(dest.stream()), f"{needle} is in the imported events"
        assert needle not in "".join(dest.archive_lines())
    assert not dest.meta.mentions(OWNER) and not dest.blobs.mentions(OWNER), "the source owner is not on any record"


def test_FR_MEM_10_the_source_scope_and_the_import_cannot_read_each_other(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    for ref in src.refs():
        assert dest.artifacts.head(src.scope, ref) is None, "a version of another org and world reads as absent (AR-03)"
        assert src.rig.store.head(dest.scope, ref) is None
        assert dest.artifacts.head(dest.scope, ref) is not None


def test_FR_MEM_10_a_record_that_names_another_scope_is_stored_under_the_importer_s_scope_only(src, tmp_path) -> None:
    from tilo_memory.artifacts import Scope

    victim = Scope(org_id="org_victim", world_id="w_victim", owner="u_victim")
    ref = src.refs()[0]
    path = f"artifacts/{ref['artifact_id']}/v{ref['version']:06d}/record.json"

    def edit(entries):
        record = json.loads(entries[path])
        record |= {"org_id": victim.org_id, "world_id": victim.world_id, "owner": victim.owner}
        entries[path] = jb(record)

    forged = edited(do_export(src), edit, index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, forged)
    for needle in ("org_victim", "w_victim", "u_victim"):
        assert not dest.meta.mentions(needle) and not dest.blobs.mentions(needle)
    assert dest.artifacts.head(victim, ref) is None
    assert dest.artifacts.head(dest.scope, ref).record["world_id"] == DEST_WORLD


def test_FR_MEM_10_whatever_world_the_bundle_s_events_name_the_importer_s_world_is_used(src, tmp_path) -> None:
    forged = edited(
        do_export(src), _edit_events(lambda e: e | {"world_id": "w_somewhere_else"}), index=True, count=True
    )
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, forged)
    assert {e["world_id"] for e in dest.stream()} == {DEST_WORLD}
    assert "w_somewhere_else" not in json.dumps(dest.snapshot(), default=str)


# --- the importer's own call: scope, writer, world ------------------------------------------------------------------


@pytest.mark.parametrize(
    "scope_ids",
    [
        (DEST_ORG, "w_not_the_writer", DEST_OWNER),
        ("org_not_the_writer", DEST_WORLD, DEST_OWNER),
        (ORG, WORLD, OWNER),  # the source's own scope: never reused
    ],
)
def test_FR_MEM_10_the_scope_must_be_the_writer_s_org_and_world(src, tmp_path, scope_ids) -> None:
    from tilo_memory.artifacts import Scope

    dest = make_dest(tmp_path, src.layout)
    org, world, owner = scope_ids
    refused_and_nothing_written(dest, do_export(src), scope=Scope(org_id=org, world_id=world, owner=owner))
    assert_nothing_imported(dest)


def test_FR_MEM_10_a_world_that_already_holds_another_event_is_refused_and_left_as_it_was(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    dest.writer.emit(**world_requested_kwargs(target=DEST_WORLD))
    refused_and_nothing_written(dest, do_export(src))
    assert len(dest.stream()) == 1


# --- one run of one world -------------------------------------------------------------------------------------------


def test_FR_MEM_10_events_from_two_worlds_in_one_bundle_are_refused(src, tmp_path) -> None:
    forged = edited(do_export(src), _edit_event(7, lambda e: e | {"world_id": "w_victim"}), index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, forged)
    assert_nothing_imported(dest)


def test_FR_MEM_10_events_of_another_run_in_the_bundle_are_refused(src, tmp_path) -> None:
    one = edited(do_export(src), _edit_event(7, lambda e: e | {"run_id": "r_other_run"}), index=True, count=True)
    every = edited(do_export(src), _edit_events(lambda e: e | {"run_id": "r_other_run"}), index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, one)
    refused_and_nothing_written(dest, every)  # the bundle says RUN, the events say another run
    assert_nothing_imported(dest)


def test_FR_MEM_10_a_district_the_importer_s_layout_does_not_have_is_refused_and_no_view_leaks(src, tmp_path) -> None:
    hidden = edited(do_export(src), _edit_event(7, lambda e: e | {"vis": ["D1", "D9"]}), index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, hidden)  # EV-13: vis names a real district
    assert_nothing_imported(dest)


def test_FR_MEM_10_an_event_the_importer_s_layout_does_not_know_is_refused(src, tmp_path) -> None:
    other = build_layout(
        world_id=DEST_WORLD,
        district_specs=[{"id": "D1", "lead": "A_lead", "specialists": ["A_x0", "A_x1"], "unit_ids": ["U1", "U2"]}],
    )
    dest = make_dest(tmp_path, other)
    refused_and_nothing_written(dest, do_export(src))  # EV-12: A_s0 is not an agent of this layout
    assert_nothing_imported(dest)


def test_FR_MEM_10_the_importer_s_views_are_its_own_redaction_of_the_replayed_events(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    assert_replayed_identically(src, dest)
    assert dest.view("shared") and dest.view("D1")
    for scope in dest.view_scopes():
        assert [e["seq"] for e in dest.view(scope)] == list(range(1, len(dest.view(scope)) + 1)), "a dense view seq"


# --- export refuses what it cannot vouch for ------------------------------------------------------------------------


def _refused_export(src, **kw):
    before = len(src.rig.store.retention().records())
    with pytest.raises(refused_type()):
        do_export(src, **kw)
    assert len(src.rig.store.retention().records()) == before


def test_FR_MEM_10_export_refuses_events_that_are_not_one_whole_run_of_one_world(src) -> None:
    events = [dict(e) for e in src.events]
    _refused_export(src, events=[])
    _refused_export(src, events=events[1:])  # does not start at seq 1
    _refused_export(src, events=events[:4] + events[5:])  # a gap
    _refused_export(src, events=events[:5] + [dict(events[5], world_id="w_victim")] + events[6:])
    _refused_export(src, events=events[:5] + [dict(events[5], run_id="r_other_run")] + events[6:])
    _refused_export(src, events=events[:3] + [events[4], events[3]] + events[5:])  # out of order
    _refused_export(src, run_id="r_other_run")


def test_FR_MEM_10_export_refuses_a_scope_that_does_not_hold_the_versions_the_events_name(src) -> None:
    from tilo_memory.artifacts import Scope

    _refused_export(src, scope=Scope(org_id=ORG, world_id="w_other_world", owner=OWNER))
    _refused_export(src, scope=Scope(org_id="org_other_org", world_id=WORLD, owner=OWNER))
    _refused_export(src, scope=Scope(org_id=ORG, world_id=WORLD, owner="u_somebody_else"))


def test_FR_MEM_10_export_refuses_a_corrupt_blob_and_a_broken_archive_chain(tmp_path) -> None:
    run = build_source_run(tmp_path / "run")
    ref = run.refs()[0]
    run.rig.tamper(ref)  # the stored bytes no longer match their hash (AR-01)
    _refused_export(run)

    run = build_source_run(tmp_path / "run2")
    path = run.archive_dir / ORG / f"{RUN}.jsonl"
    lines = path.read_text(encoding="utf-8").split("\n")
    lines[1] = lines[1].replace("A second page", "Another page")
    path.write_text("\n".join(lines), encoding="utf-8", newline="")
    from tilo_archive import LocalDirStore, RunArchive

    broken = RunArchive(LocalDirStore(run.archive_dir), org_id=ORG, run_id=RUN, redactor=lambda payload: payload)
    _refused_export(run, archive=broken)


def test_FR_MEM_10_export_refuses_an_archive_of_another_run(src, tmp_path) -> None:
    from tilo_archive import LocalDirStore, RunArchive

    other = RunArchive(LocalDirStore(tmp_path / "other"), org_id=ORG, run_id="r_other_run", redactor=lambda p: p)
    other.append("tool_call", {"tool": "fetch", "content": "x"})
    _refused_export(src, archive=other)


def test_FR_MEM_10_no_bytes_leave_the_scope_that_exported(src) -> None:
    entries = unpack(do_export(src))
    blob = b"".join(entries.values())
    for foreign in (b"w_victim", b"org_victim", b"u_victim"):
        assert foreign not in blob
