"""FR-MEM-10 atomic and idempotent import (PRD 9.3 single writer, 13.2 append-only stores; EV-10 one writer per world;
FR-HIL-07 an identical resend is a no-op, FR-AGT-10 a restart gets the same version back):

Order of an import, which these tests pin because it is what makes it all-or-nothing as far as append-only stores allow:
  1. validate everything (bundle, hashes, chain, secrets, the whole event stream against the importer's layout with a
     dry run of EV-01 to EV-15) before the first write: a refusal writes nothing, in any store;
  2. artifact versions and their manifests (rolled back, by the store's own delete, if any of them fails);
  3. the raw-archive lines, verbatim (an existing prefix of the same chain is completed, a differing line refuses);
  4. the events, last, through `writer.append` (identical resends are no-ops), so an artifact event is never written
     for a version that is not stored (HR-1, ADR-0018: `artifact.created` only after the store committed).
So an outage in step 2 or 3 leaves no event and no readable artifact, and an outage in step 4 (an append-only stream
cannot be un-written) leaves a prefix of the replay that a retry of the same import completes without a duplicate.
Importing the same bundle again into the same world is a no-op (`already_imported`). A different version, archive
chain or event already in the world refuses the import and changes nothing.
Fails now: `ModuleNotFoundError: No module named 'tilo_harness.run_bundle'`.
"""

from __future__ import annotations

import json

import pytest
from bundle_support import (
    DEST_ORG,
    ORG,
    RUN,
    FailingArchiveStore,
    FailingBlobs,
    assert_nothing_imported,
    assert_replayed_identically,
    build_source_run,
    do_export,
    do_import,
    edited,
    flaky_event_store,
    jsonl,
    lines_of,
    make_dest,
    rb,
    refused_and_nothing_written,
    sha,
    unpack,
)

pytestmark = pytest.mark.usefixtures("block_network")


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


# --- step 1: validate first -----------------------------------------------------------------------------------------


def _set(index, **changes):
    def mutate(items):
        items[index] |= changes

    return mutate


def _created_twice(items):
    items[14]["data"]["artifact"]["artifact_id"] = items[6]["data"]["artifact"]["artifact_id"]  # a second `created`


def _skips_a_version(items):
    items[13]["data"]["previous_version"] = 5


def _duplicate_id(items):
    items[12]["id"] = items[0]["id"]


# What each breaks. Event indexes of the source run: 5 agent.working, 6 and 14 artifact.created, 13 artifact.versioned,
# 17 artifact.rolled_back, every earlier event is valid, so the refusal is found late in the stream.
INVALID_EVENTS = {
    "EV-12_actor_not_in_layout": _set(14, actor="A_nobody"),
    "EV-15_versioned_skips_a_version": _skips_a_version,
    "EV-15_created_twice": _created_twice,
    "EV-01_unregistered_type": _set(9, type="agent.teleported"),
    "EV-11_cause_never_happened": _set(17, cause="01JB5VQ0000000000000009999"),
    "EV-10_duplicate_id": _duplicate_id,
    "schema_negative_credits": _set(8, credits=-3),
    "schema_unknown_field": _set(5, surprise=True),
}


@pytest.mark.parametrize("case", sorted(INVALID_EVENTS))
def test_FR_MEM_10_a_bad_event_late_in_the_stream_leaves_every_store_untouched(src, tmp_path, case) -> None:
    def edit(entries):
        items = [json.loads(x) for x in lines_of(entries["events.jsonl"])]
        INVALID_EVENTS[case](items)
        entries["events.jsonl"] = jsonl(items)

    forged = edited(do_export(src), edit, index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, forged)
    assert_nothing_imported(dest)  # no artifact, no archive line, no early event: the whole stream was checked first


# --- steps 2 and 3: outages roll back what is rollbackable and write no event ---------------------------------------


@pytest.mark.parametrize("fail_on", [1, 3, 5])
def test_FR_MEM_10_a_blob_backend_outage_rolls_every_artifact_back_writes_no_event_and_a_retry_completes(
    src, tmp_path, fail_on
) -> None:
    from tilo_memory.artifacts import MemoryBlobBackend

    dest = make_dest(tmp_path, src.layout, blobs=FailingBlobs(MemoryBlobBackend(), fail_on=fail_on))
    bundle = do_export(src)
    with pytest.raises((OSError, rb().BundleError)):
        do_import(dest, bundle)
    assert dest.stream() == [] and all(dest.view(s) == [] for s in dest.view_scopes()), "no event was written"
    assert dest.meta.inner.paths() == [] and dest.blobs.inner.keys() == [], "no artifact is left, readable or not"
    assert dest.archive_files() == [], "the archive is written only after every artifact is stored"
    do_import(dest, bundle)  # the outage is over: the same import, the same world
    assert_replayed_identically(src, dest)


@pytest.mark.parametrize("fail_on", [1, 2, 3])
def test_FR_MEM_10_an_archive_outage_rolls_the_artifacts_back_writes_no_event_and_a_retry_completes(
    src, tmp_path, fail_on
) -> None:
    dest = make_dest(tmp_path, src.layout, archive_wrapper=lambda inner: FailingArchiveStore(inner, fail_on=fail_on))
    bundle = do_export(src)
    with pytest.raises((OSError, rb().BundleError)):
        do_import(dest, bundle)
    assert dest.stream() == [] and all(dest.view(s) == [] for s in dest.view_scopes()), "no event was written"
    assert dest.meta.inner.paths() == [] and dest.blobs.inner.keys() == [], "every artifact was rolled back"
    do_import(dest, bundle)  # a prefix of the same chain is completed, never rewritten or duplicated
    assert_replayed_identically(src, dest)
    assert len(dest.archive_lines()) == 3


@pytest.mark.parametrize("fail_seq", [1, 6, 18])
def test_FR_MEM_10_an_event_store_outage_leaves_a_prefix_a_retry_completes_without_duplicates(
    src, tmp_path, fail_seq
) -> None:
    store = flaky_event_store(fail_seq)
    dest = make_dest(tmp_path, src.layout, events_store=store)
    bundle = do_export(src)
    with pytest.raises((OSError, rb().BundleError)):
        do_import(dest, bundle)
    assert len(dest.stream()) == fail_seq - 1, "a prefix of the replay: an append-only stream cannot be un-written"
    store.fail = None
    result = do_import(dest, bundle)
    assert [e["seq"] for e in dest.stream()] == list(range(1, 19)), "no event twice, none missing"
    assert_replayed_identically(src, dest)
    assert result.events == 18


# --- idempotent re-import -------------------------------------------------------------------------------------------


def test_FR_MEM_10_importing_the_same_bundle_again_is_a_no_op(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    bundle = do_export(src)
    first = do_import(dest, bundle)
    assert first.already_imported is False
    before = dest.snapshot()
    creates = (len(dest.meta.called("create")), len(dest.blobs.called("create")))
    for _ in range(2):
        again = do_import(dest, bundle)
        assert again.already_imported is True
        assert (again.run_id, again.events, again.versions, again.manifest_revisions, again.archive_records) == (
            first.run_id,
            first.events,
            first.versions,
            first.manifest_revisions,
            first.archive_records,
        )
    assert dest.snapshot() == before
    assert (len(dest.meta.called("create")), len(dest.blobs.called("create"))) == creates, "nothing was written"
    assert_replayed_identically(src, dest)


def test_FR_MEM_10_two_worlds_of_one_org_import_the_same_run_independently(src, tmp_path) -> None:
    """The raw archive is keyed by org and run, so the second world finds the same chain already there and shares it
    (identical lines, none appended twice); events and artifacts are each world's own."""
    one = make_dest(tmp_path, src.layout, org=ORG, world="w_replay_one")
    two = make_dest(tmp_path, src.layout, org=ORG, world="w_replay_two")  # the same archive directory
    assert one.archive_root == two.archive_root
    bundle = do_export(src)
    do_import(one, bundle)
    do_import(two, bundle)
    assert one.archive_lines() == two.archive_lines() == src.archive_lines()
    assert_replayed_identically(src, one)
    assert_replayed_identically(src, two)
    assert one.stream() != two.stream(), "each world has its own world_id on its events"


# --- conflicts: a different version, chain or event is never overwritten or merged ----------------------------------


def test_FR_MEM_10_a_different_version_already_in_the_scope_refuses_the_import_and_stays_intact(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    entries = unpack(do_export(src))
    ref = src.refs()[0]
    base = f"artifacts/{ref['artifact_id']}/v{ref['version']:06d}"
    other = b"# A different brief that already lives here\n"
    record = json.loads(entries[f"{base}/record.json"])
    record["content_sha256"], record["size_bytes"] = sha(other), len(other)
    dest.artifacts.import_version(dest.scope, record, other)
    before = dest.snapshot()
    with pytest.raises(rb().BundleRefused):
        do_import(dest, do_export(src))
    assert dest.snapshot() == before
    assert dest.artifacts.read(dest.scope, ref) == other


def test_FR_MEM_10_a_different_archive_chain_for_the_run_refuses_the_import_and_stays_intact(src, tmp_path) -> None:
    from tilo_archive import RunArchive

    dest = make_dest(tmp_path, src.layout)
    existing = RunArchive(dest.archive_store, org_id=dest.org, run_id=RUN, redactor=lambda payload: payload)
    existing.append("tool_call", {"tool": "fetch", "content": "Something else was read in this org and run."})
    refused_and_nothing_written(dest, do_export(src))
    assert len(dest.archive_lines()) == 1, "the chain that was there is untouched"
    assert dest.stream() == [] and dest.meta.inner.paths() == [] and dest.blobs.inner.keys() == []


def test_FR_MEM_10_the_same_archive_chain_already_in_the_org_is_not_appended_again(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    for line in src.archive_lines():
        dest.archive_store.append_line(dest.org, RUN, line)
    do_import(dest, do_export(src))
    assert dest.archive_lines() == src.archive_lines()
    assert_replayed_identically(src, dest)


def test_FR_MEM_10_a_bundle_with_an_altered_event_is_refused_in_a_world_that_holds_the_original_run(
    src, tmp_path
) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    before = dest.snapshot()

    def edit(entries):
        items = [json.loads(x) for x in lines_of(entries["events.jsonl"])]
        items[2]["summary"] = "A different story."
        entries["events.jsonl"] = jsonl(items)

    forged = edited(do_export(src), edit, index=True, count=True)
    with pytest.raises(rb().BundleRefused):
        do_import(dest, forged)  # the same id with other content is EV-10, never an overwrite
    assert dest.snapshot() == before


def test_FR_MEM_10_the_importer_s_org_directory_is_where_the_archive_goes(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout)
    do_import(dest, do_export(src))
    assert dest.archive_files() == [f"{DEST_ORG}/{RUN}.jsonl"] and ORG != DEST_ORG
    assert [json.loads(x)["seq"] for x in dest.archive_lines()] == [1, 2, 3]
