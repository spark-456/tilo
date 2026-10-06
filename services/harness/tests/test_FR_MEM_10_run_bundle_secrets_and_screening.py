"""FR-MEM-10 secrets and screening (PRD 16.2 and FR-MEM-05 "secrets never reach the archive", MF-06 "again before an
export or a run bundle carries one out of Tilo", AR-07 "unscreened is never clean"):

- A secret never enters a bundle: export runs the shared redactor over every string it carries (events, archive
  payloads, manifests, text and JSON bytes) and refuses, producing no bytes, when the redactor would change one. A
  redacted version round-trips as redacted (`redacted` true, the placeholder in its bytes) and the secret never comes
  back anywhere.
- Import scans again, because a bundle is untrusted input: anything the importer's redactor would change refuses the
  whole bundle (never stored, never silently redacted: that would break the hashes). Messages never repeat the secret.
  A redactor error fails closed.
- Screening on import is the importer's: a `clean` claim is judged again on the exact bytes by the importer's screener
  (no screener, an error or an unreadable verdict means `unscreened`), `unscreened` and `flagged` stay as they are and
  the screener is not even asked about them (AR-07: unscreened versions stay unscreened). The fake secret is assembled
  at runtime. Fails now: `ModuleNotFoundError: No module named 'tilo_harness.run_bundle'`.

"""

from __future__ import annotations

import json

import pytest
from bundle_support import (
    ARCHIVE,
    BUNDLE_JSON,
    EVENTS,
    SECRET,
    FailingRedactor,
    FakeSafety,
    GarbledSafety,
    Redactor,
    assert_nothing_imported,
    assert_replayed_identically,
    build_source_run,
    do_export,
    edited,
    jb,
    jsonl,
    lines_of,
    make_dest,
    meta_of,
    names,
    refused_and_nothing_written,
    refused_type,
    sha,
    unpack,
)
from conftest import agent_idle_kwargs

pytestmark = pytest.mark.usefixtures("block_network")


@pytest.fixture(scope="module")
def src(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src"))


@pytest.fixture(scope="module")
def src_secret(tmp_path_factory):
    return build_source_run(tmp_path_factory.mktemp("src_secret"), secret_in_brief=True)


# --- export: a secret never enters a bundle -------------------------------------------------------------------------


def test_FR_MEM_10_a_redacted_version_round_trips_as_redacted_and_the_secret_is_nowhere(src_secret, tmp_path) -> None:
    from bundle_support import do_import

    ref = {"artifact_id": src_secret.art_ids["brief"], "version": 1}
    record = src_secret.rig.store.head(src_secret.scope, ref).record
    assert record["redacted"] is True, "the store redacted the secret when the version was put"
    bundle = do_export(src_secret)
    for name, data in unpack(bundle).items():
        assert SECRET.encode() not in data, f"{name} carries the secret"
    dest = make_dest(tmp_path, src_secret.layout)
    do_import(dest, bundle)
    assert_replayed_identically(src_secret, dest)
    assert dest.artifacts.head(dest.scope, ref).record["redacted"] is True
    assert b"[REDACTED]" in dest.artifacts.read(dest.scope, ref)
    assert SECRET not in json.dumps(dest.snapshot(), default=str)
    assert not dest.meta.mentions(SECRET) and not dest.blobs.mentions(SECRET)


def test_FR_MEM_10_export_refuses_an_archive_record_the_redactor_would_change(tmp_path) -> None:
    run = build_source_run(tmp_path / "run")
    run.rig.archive.append("tool_call", {"tool": "fetch", "content": f"the page said {SECRET}"})
    with pytest.raises(refused_type()) as caught:
        do_export(run)
    assert SECRET not in str(caught.value), "the refusal never repeats the secret"


def test_FR_MEM_10_export_refuses_an_event_the_redactor_would_change(tmp_path) -> None:
    run = build_source_run(tmp_path / "run")
    run.ran.writer.emit(
        **(agent_idle_kwargs("A_s0", "A_s0", level="L1", district="D1") | {"summary": f"leak {SECRET}"})
    )
    run.events = run.ran.events
    with pytest.raises(refused_type()) as caught:
        do_export(run)
    assert SECRET not in str(caught.value)


def test_FR_MEM_10_export_runs_the_redactor_over_every_kind_of_string(src) -> None:
    seen = Redactor()
    do_export(src, redact=seen)
    shown = "\n".join(seen.calls)
    assert "Market brief" in shown and "A_s0" in shown, "event strings and manifest strings were scanned"
    assert "Firm Faa reported revenue" in shown, "archive payloads were scanned"
    assert "Three suppliers quoted a price" in shown, "text and JSON bytes were scanned"


def test_FR_MEM_10_a_failing_redactor_fails_the_export_closed(src) -> None:
    with pytest.raises(refused_type()):
        do_export(src, redact=FailingRedactor())


# --- import: a bundle is untrusted, so it is scanned again ----------------------------------------------------------


def _brief_v1(src) -> str:
    return f"artifacts/{src.art_ids['brief']}/v000001"


def _forge_event_summary(entries):
    items = [json.loads(x) for x in lines_of(entries[EVENTS])]
    items[3]["summary"] = f"Looked up {SECRET}"
    entries[EVENTS] = jsonl(items)


def _forge_archive_with_valid_chain(entries):
    """A secret in an archive record, with the per-record hashes and the chain recomputed, and the head in bundle.json
    updated: only the secret scan can refuse this."""
    from tilo_archive.record import canonical_json, record_hash

    records = [json.loads(x) for x in lines_of(entries[ARCHIVE])]
    records[1]["payload"] = {
        "tool": "fetch",
        "content": f"seen {SECRET}",
        "source": {"kind": "web", "ref": "https://example.com/two"},
    }
    prev = "0" * 64
    for record in records:
        record["prev_hash"] = prev
        record["hash"] = record_hash(record)
        prev = record["hash"]
    entries[ARCHIVE] = ("\n".join(canonical_json(r) for r in records) + "\n").encode()
    meta = meta_of(entries)
    meta["archive_head"] = {"seq": records[-1]["seq"], "hash": prev}
    entries[BUNDLE_JSON] = jb(meta)


def _forge_text_blob_consistently(src):
    """The brief's bytes (version 1 and its exact restore, version 3) carry the secret; records, manifests and
    `artifact.created` agree with the new bytes, so only the secret scan can refuse this."""

    def edit(entries):
        brief = src.art_ids["brief"]
        digest = ""
        for version in (1, 3):
            base = f"artifacts/{brief}/v{version:06d}"
            body = entries[f"{base}/content"] + SECRET.encode()
            digest = sha(body)
            entries[f"{base}/content"] = body
            record = json.loads(entries[f"{base}/record.json"])
            record["content_sha256"], record["size_bytes"] = digest, len(body)
            entries[f"{base}/record.json"] = jb(record)
            revisions = json.loads(entries[f"{base}/manifests.json"])
            for revision in revisions:
                revision["manifest"]["content_sha256"] = digest
            entries[f"{base}/manifests.json"] = jb(revisions)
        items = [json.loads(x) for x in lines_of(entries[EVENTS])]
        for item in items:
            if item["type"] == "artifact.created" and item["data"]["artifact"] == {"artifact_id": brief, "version": 1}:
                item["data"] |= {
                    "content_sha256": digest,
                    "size_bytes": len(entries[f"artifacts/{brief}/v000001/content"]),
                }
        entries[EVENTS] = jsonl(items)

    return edit


def _forge_manifest_claim(src):
    def edit(entries):
        path = f"{_brief_v1(src)}/manifests.json"
        revisions = json.loads(entries[path])
        revisions[0]["manifest"]["claims"][0]["text"] = f"Revenue was {SECRET}"
        entries[path] = jb(revisions)

    return edit


@pytest.mark.parametrize(
    "case", ["event_summary", "archive_record_valid_chain", "text_blob_consistent", "manifest_claim"]
)
def test_FR_MEM_10_a_bundle_carrying_a_secret_is_refused_whole_and_never_repeats_it(src, tmp_path, case) -> None:
    forge = {
        "event_summary": _forge_event_summary,
        "archive_record_valid_chain": _forge_archive_with_valid_chain,
        "text_blob_consistent": _forge_text_blob_consistently(src),
        "manifest_claim": _forge_manifest_claim(src),
    }[case]
    forged = edited(do_export(src), forge, index=True, count=True)
    dest = make_dest(tmp_path, src.layout)
    error = refused_and_nothing_written(dest, forged)
    assert SECRET not in str(error)
    assert_nothing_imported(dest)
    assert not dest.meta.mentions(SECRET) and not dest.blobs.mentions(SECRET)


def test_FR_MEM_10_a_failing_importer_redactor_fails_the_import_closed(src, tmp_path) -> None:
    dest = make_dest(tmp_path, src.layout, redactor=FailingRedactor())
    refused_and_nothing_written(dest, do_export(src))
    assert_nothing_imported(dest)


# --- import: screening is the importer's ----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sources(tmp_path_factory):
    return {
        "clean": build_source_run(tmp_path_factory.mktemp("s_clean")),
        "flagged": build_source_run(tmp_path_factory.mktemp("s_flagged"), safety=FakeSafety(flagged=True)),
        "unscreened": build_source_run(
            tmp_path_factory.mktemp("s_unscreened"), safety=FakeSafety(error=TimeoutError("provider timeout"))
        ),
    }


IMPORTER = {
    "none": lambda: None,
    "clean": lambda: FakeSafety(),
    "flagged": lambda: FakeSafety(flagged=True),
    "error": lambda: FakeSafety(error=TimeoutError("slow")),
    "garbled": lambda: GarbledSafety(),
}
# (source screening, importer screener) -> what the imported version is
EXPECTED = {
    **{("clean", "none"): "unscreened", ("clean", "clean"): "clean", ("clean", "flagged"): "flagged"},
    **{("clean", "error"): "unscreened", ("clean", "garbled"): "unscreened"},
    **{("flagged", name): "flagged" for name in IMPORTER},
    **{("unscreened", name): "unscreened" for name in IMPORTER},
}


@pytest.mark.parametrize(("source", "importer"), sorted(EXPECTED))
def test_FR_MEM_10_screening_after_import_is_the_importer_s_verdict_never_the_bundle_s_claim(
    sources, tmp_path, source, importer
) -> None:
    from bundle_support import do_import

    run = sources[source]
    for ref in run.refs():
        assert run.rig.store.head(run.scope, ref).record["screening"] == source, "the source holds what the test says"
    screener = IMPORTER[importer]()
    dest = make_dest(tmp_path, run.layout, safety=screener)
    do_import(dest, do_export(run))
    want = EXPECTED[(source, importer)]
    for ref in run.refs():
        record = dest.artifacts.head(dest.scope, ref).record
        assert record["screening"] == want, f"{ref}: a {source} version imported with a {importer} screener"
        assert (record["screened_at"] is None) == (want == "unscreened"), "screened_at is null exactly when unscreened"
        assert dest.artifacts.read(dest.scope, ref) == run.read(ref)
    if screener is not None and source != "clean":
        assert screener.calls == [], (
            "no verdict is asked for on a version that is already flagged or unscreened (AR-07)"
        )
    if screener is not None and source == "clean":
        asked = [c["text"] for c in screener.calls]
        assert set(asked) == {run.read(r).decode("utf-8") for r in run.refs()}, "each exact stored text was judged"


def test_FR_MEM_10_a_bundle_cannot_claim_screened_at_for_an_unscreened_version(src, tmp_path) -> None:
    ref = src.refs()[0]
    path = f"artifacts/{ref['artifact_id']}/v{ref['version']:06d}/record.json"

    def edit(entries):
        record = json.loads(entries[path])
        record["screening"] = "unscreened"  # but screened_at stays set: not a state the contract allows
        entries[path] = jb(record)

    dest = make_dest(tmp_path, src.layout)
    refused_and_nothing_written(dest, edited(do_export(src), edit, index=True, count=True))
    assert_nothing_imported(dest)


def test_FR_MEM_10_a_relabelled_clean_claim_is_only_ever_the_importer_s_verdict(sources, tmp_path) -> None:
    """A bundle that relabels flagged versions as clean gets no more than the importer's own verdict on the exact bytes:
    with no screener the versions are unscreened, never clean."""
    from bundle_support import do_import

    run = sources["flagged"]

    def relabel(entries):
        for name in names(entries, "/record.json"):
            record = json.loads(entries[name])
            record["screening"] = "clean"
            entries[name] = jb(record)

    dest = make_dest(tmp_path, run.layout, safety=None)
    do_import(dest, edited(do_export(run), relabel, index=True, count=True))
    for ref in run.refs():
        record = dest.artifacts.head(dest.scope, ref).record
        assert (record["screening"], record["screened_at"]) == ("unscreened", None)
