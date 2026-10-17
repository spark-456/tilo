"""FR-MEM-06 AR-04 (kinds and caps, checked before hashing) and AR-07 (redactor before put, screening only from the
verdict on the stored bytes). Sources: contracts/artifact.rules.md AR-04 and AR-07,
docs/adr/0018-artifact-output-and-store.md sections 1 and 7 (BQ-257: 2,000,000 text/JSON, 50,000,000 file, 10
outputs per unit, 200,000,000 per world; BQ-258), PRD 16.1, 16.3 item 2. API: API_FR_MEM_06.md.
`tilo_memory.artifacts` does not exist yet, so these fail at import."""

from __future__ import annotations

from datetime import timedelta

import pytest
from _artifact_testlib import (
    ALL_TYPES,
    ARTICLE,
    FILE_TYPES,
    MAX_FILE,
    MAX_TEXT,
    MAX_WORLD,
    OTHER_WORLD,
    SAMPLE,
    SECRET,
    TEXT_TYPES,
    Clock,
    FakeSafety,
    Redactor,
    Sized,
    SizeOnlyBlobs,
    iso,
    make_rig,
    scope_of,
    sha,
)
from tilo_memory.artifacts import ArtifactRefused, NewVersion, Origin


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


@pytest.fixture
def big(tmp_path):
    """A store over size-only blobs: for caps that would need 50 MB or 200 MB of real bytes."""
    return make_rig("custom", tmp_path, blobs=SizeOnlyBlobs())


def _text_of(media_type: str, size: int) -> bytes:
    """Valid-looking text/CSV/JSON of exactly `size` bytes."""
    if media_type == "application/json":
        return b'"' + b"a" * (size - 2) + b'"'
    return b"a" * size


def _nothing_stored(rig) -> None:
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


# --- AR-04: kinds ---------------------------------------------------------------------------------


@pytest.mark.parametrize("media_type", TEXT_TYPES)
def test_FR_MEM_06_AR_04_a_unit_output_may_be_markdown_csv_or_json(rig, media_type):
    stored = rig.put(SAMPLE[media_type], media_type=media_type)
    assert stored.record["media_type"] == media_type
    assert rig.store.read(rig.scope, stored.ref) == SAMPLE[media_type]


@pytest.mark.parametrize("media_type", FILE_TYPES)
def test_FR_MEM_06_AR_04_a_unit_output_is_never_a_file_and_is_refused_before_hashing(rig, media_type):
    with pytest.raises(ArtifactRefused):
        rig.put(SAMPLE[media_type], media_type=media_type)
    assert rig.hasher.calls == 0, "kinds are checked before hashing"
    _nothing_stored(rig)


@pytest.mark.parametrize("media_type", FILE_TYPES)
def test_FR_MEM_06_AR_04_render_makes_files(rig, media_type):
    stored = rig.render(SAMPLE[media_type], media_type)
    assert stored.record["origin"] == {"kind": "render", "unit": "U3", "agent": None}
    assert stored.record["idempotency_key"].startswith("r_run1:U3:")
    assert rig.store.read(rig.scope, stored.ref) == SAMPLE[media_type]


@pytest.mark.parametrize("media_type", TEXT_TYPES)
def test_FR_MEM_06_AR_04_render_never_makes_text_and_is_refused_before_hashing(rig, media_type):
    with pytest.raises(ArtifactRefused):
        rig.render(SAMPLE[media_type], media_type)
    assert rig.hasher.calls == 0
    _nothing_stored(rig)


@pytest.mark.parametrize("media_type", ALL_TYPES)
def test_FR_MEM_06_AR_04_an_upload_may_be_any_of_the_nine_media_types(rig, media_type):
    stored = rig.upload(SAMPLE[media_type], media_type)
    assert stored.record["media_type"] == media_type and stored.record["origin"]["kind"] == "upload"
    assert stored.record["origin"] == {"kind": "upload", "unit": None, "agent": None}
    assert rig.store.read(rig.scope, stored.ref) == SAMPLE[media_type]


@pytest.mark.parametrize(
    "media_type",
    [
        "image/svg+xml",
        "application/octet-stream",
        "text/plain",
        "TEXT/MARKDOWN",
        "text/markdown; charset=utf-8",
        "",
    ],
)
def test_FR_MEM_06_AR_04_the_media_type_enum_is_closed_for_every_origin(rig, media_type):
    with pytest.raises(ArtifactRefused):
        rig.upload(b"<b>x</b>", media_type)
    with pytest.raises(ArtifactRefused):
        rig.put(b"<b>x</b>", media_type=media_type)
    assert rig.hasher.calls == 0
    _nothing_stored(rig)


# --- AR-04: size ----------------------------------------------------------------------------------


@pytest.mark.parametrize("media_type", ALL_TYPES)
def test_FR_MEM_06_AR_04_empty_content_is_refused_before_hashing(rig, media_type):
    with pytest.raises(ArtifactRefused):
        rig.upload(b"", media_type)
    assert rig.hasher.calls == 0
    _nothing_stored(rig)


@pytest.mark.parametrize("media_type", TEXT_TYPES)
@pytest.mark.parametrize("blank", [b" ", b"\n", b"  \n\t \r\n"])
def test_FR_MEM_06_AR_04_whitespace_only_text_is_refused_before_hashing(rig, media_type, blank):
    with pytest.raises(ArtifactRefused):
        rig.put(blank, media_type=media_type)
    with pytest.raises(ArtifactRefused):
        rig.upload(blank, media_type)
    assert rig.hasher.calls == 0
    _nothing_stored(rig)


@pytest.mark.parametrize("media_type", TEXT_TYPES)
def test_FR_MEM_06_AR_04_text_and_json_are_at_most_2_000_000_bytes(rig, media_type):
    ok = rig.put(_text_of(media_type, MAX_TEXT), media_type=media_type)
    assert ok.record["size_bytes"] == MAX_TEXT == 2_000_000
    hashed = rig.hasher.calls
    with pytest.raises(ArtifactRefused):
        rig.put(_text_of(media_type, MAX_TEXT + 1), media_type=media_type)
    with pytest.raises(ArtifactRefused):
        rig.upload(_text_of(media_type, MAX_TEXT + 1), media_type)
    assert rig.hasher.calls == hashed, "an over-cap put is refused before hashing"
    assert len(rig.blobs.inner.keys()) == 1


def test_FR_MEM_06_AR_04_a_file_is_at_most_50_000_000_bytes(big):
    ok = big.upload(Sized(MAX_FILE), "application/pdf")
    assert ok.record["size_bytes"] == MAX_FILE == 50_000_000
    hashed = big.hasher.calls
    with pytest.raises(ArtifactRefused):
        big.upload(Sized(MAX_FILE + 1), "application/pdf")
    with pytest.raises(ArtifactRefused):
        big.render(Sized(MAX_FILE + 1), "image/png")
    assert big.hasher.calls == hashed
    assert len(big.blobs.inner.keys()) == 1


def test_FR_MEM_06_AR_04_FR_AGT_13_a_unit_has_at_most_ten_outputs_the_eleventh_index_is_refused(rig):
    made = [rig.put(f"output {i}".encode(), attempt=1, index=i) for i in range(10)]
    assert len({m.artifact_id for m in made}) == 10
    hashed = rig.hasher.calls
    with pytest.raises(ArtifactRefused):
        rig.put(b"output 10", attempt=1, index=10)
    assert rig.hasher.calls == hashed
    assert len(rig.blobs.inner.keys()) == 10


def test_FR_MEM_06_AR_04_a_world_holds_at_most_200_000_000_bytes_in_total(big):
    for _ in range(4):
        big.upload(Sized(MAX_FILE), "application/pdf")
    assert sum(v.record["size_bytes"] for v in _all(big)) == MAX_WORLD == 200_000_000, "exactly the cap is allowed"
    hashed = big.hasher.calls
    with pytest.raises(ArtifactRefused):
        big.upload(Sized(1), "image/png")
    with pytest.raises(ArtifactRefused):
        big.put(b"x")
    assert big.hasher.calls == hashed, "the world cap is checked before hashing too"
    assert len(big.blobs.inner.keys()) == 4

    other = scope_of(world=OTHER_WORLD)  # the cap is per world: another world is not affected
    assert big.upload(Sized(MAX_FILE), "application/pdf", scope=other).record["world_id"] == OTHER_WORLD


def test_FR_MEM_06_AR_04_a_restore_counts_toward_the_world_total(big):
    first = big.upload(Sized(MAX_FILE), "application/pdf")
    for _ in range(3):
        big.upload(Sized(MAX_FILE), "application/pdf")
    keys = big.blobs.inner.keys()
    with pytest.raises(ArtifactRefused):  # ASSUMPTION: the copy is stored bytes, so the cap applies (AR-04 "every put")
        big.restore(first.ref)
    assert big.blobs.inner.keys() == keys


def _all(rig):
    out = []
    for artifact_id in sorted({k.split("/")[5] for k in rig.blobs.inner.keys()}):
        out.extend(rig.store.versions(rig.scope, artifact_id))
    return out


# --- AR-07: the redactor runs before put ----------------------------------------------------------


_WITH_SECRET = {
    "text/markdown": f"The key is {SECRET} and the rest is fine.".encode(),
    "text/csv": f"name,value\nkey,{SECRET}\n".encode(),
    "application/json": ('{"key": "' + SECRET + '", "n": 1}').encode(),
}


@pytest.mark.parametrize("media_type", TEXT_TYPES)
def test_FR_MEM_06_AR_07_the_stored_bytes_are_the_redactors_output_and_redacted_is_true(rig, media_type):
    original = _WITH_SECRET[media_type]
    stored = rig.put(original, media_type=media_type)
    expected = original.replace(SECRET.encode(), b"[REDACTED]")
    assert rig.redactor.calls == [original.decode()], "the redactor runs once, on the text the unit produced"
    assert rig.store.read(rig.scope, stored.ref) == expected
    assert SECRET.encode() not in b"".join(rig.blobs.inner.read(k) for k in rig.blobs.inner.keys())
    assert SECRET not in repr(stored.record)
    assert stored.record["redacted"] is True
    assert stored.record["size_bytes"] == len(expected)
    assert stored.record["content_sha256"] == sha(expected), "the hash is of the stored (redacted) bytes"


@pytest.mark.parametrize("media_type", TEXT_TYPES)
def test_FR_MEM_06_AR_07_redacted_is_false_when_the_redactor_changed_nothing(rig, media_type):
    stored = rig.put(SAMPLE[media_type], media_type=media_type)
    assert rig.redactor.calls == [SAMPLE[media_type].decode()]
    assert stored.record["redacted"] is False
    assert rig.store.read(rig.scope, stored.ref) == SAMPLE[media_type]


@pytest.mark.parametrize("media_type", FILE_TYPES)
def test_FR_MEM_06_AR_07_files_are_not_redacted_and_redacted_is_false(rig, media_type):
    content = b"%file% " + SECRET.encode()
    stored = rig.upload(content, media_type)
    assert rig.redactor.calls == [], "the redactor does not read files"
    assert stored.record["redacted"] is False
    assert rig.store.read(rig.scope, stored.ref) == content


def test_FR_MEM_06_AR_07_a_redactor_error_fails_the_put_and_stores_nothing(rig):
    rig.redactor.error = RuntimeError(f"cannot redact {SECRET}")
    with pytest.raises(ArtifactRefused) as info:
        rig.put(_WITH_SECRET["text/markdown"], attempt=1)
    assert SECRET not in str(info.value) and SECRET not in repr(info.value.__cause__)
    _nothing_stored(rig)
    assert rig.safety.calls == [], "nothing unredacted reaches the screener either"

    rig.redactor.error = None  # the same key still works once the redactor does: nothing was used up
    again = rig.put(_WITH_SECRET["text/markdown"], attempt=1)
    assert again.version == 1 and again.record["redacted"] is True


# --- AR-07: screening comes only from the verdict on the stored bytes -----------------------------


def test_FR_MEM_06_AR_07_clean_comes_from_the_verdict_on_the_exact_stored_text(rig):
    stored = rig.put(_WITH_SECRET["text/markdown"])
    stored_text = rig.store.read(rig.scope, stored.ref).decode()
    assert rig.safety.calls == [{"text": stored_text, "content": None, "mime_type": None}]
    assert SECRET not in rig.safety.calls[0]["text"], "the screener sees the redacted bytes, not the unit's raw output"
    assert stored.record["screening"] == "clean"
    assert stored.record["screened_at"] == iso(rig.clock.reads[0])


@pytest.mark.parametrize("media_type", FILE_TYPES)
def test_FR_MEM_06_AR_07_a_file_is_screened_as_the_exact_stored_bytes_with_its_media_type(rig, media_type):
    stored = rig.upload(SAMPLE[media_type], media_type)
    assert rig.safety.calls == [{"text": "", "content": SAMPLE[media_type], "mime_type": media_type}]
    assert stored.record["screening"] == "clean"


def test_FR_MEM_06_AR_07_a_flagged_verdict_is_recorded_as_flagged_with_its_time(tmp_path):
    rig = make_rig("memory", tmp_path, safety=FakeSafety(flagged=True))
    stored = rig.put(ARTICLE)
    assert stored.record["screening"] == "flagged"
    assert stored.record["screened_at"] == iso(rig.clock.reads[0])
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE, (
        "flagged content is stored; the policy engine stops it leaving"
    )


@pytest.mark.parametrize(
    "safety",
    [
        pytest.param(FakeSafety(error=RuntimeError("provider down")), id="provider-error"),
        pytest.param(FakeSafety(error=TimeoutError("deadline")), id="timeout"),
        pytest.param(FakeSafety(error=ValueError("cannot screen this media type")), id="unsupported-media-type"),
        pytest.param(FakeSafety(result=None), id="verdict-is-none"),
        pytest.param(FakeSafety(result={}), id="verdict-has-no-flagged"),
        pytest.param(FakeSafety(result="clean"), id="verdict-is-not-a-dict"),
        pytest.param(FakeSafety(result={"flagged": None}), id="flagged-is-not-a-bool"),
        pytest.param(None, id="no-screener-at-all"),
    ],
)
def test_FR_MEM_06_AR_07_a_missing_verdict_is_unscreened_with_no_time_and_never_clean(tmp_path, safety):
    rig = make_rig("memory", tmp_path, safety=safety)
    stored = rig.put(ARTICLE)
    assert stored.record["screening"] == "unscreened"
    assert stored.record["screened_at"] is None
    assert rig.store.read(rig.scope, stored.ref) == ARTICLE, "the put still succeeds; only `clean` versions leave Tilo"


def test_FR_MEM_06_AR_07_screened_at_is_never_after_created_at(tmp_path):
    rig = make_rig("memory", tmp_path, clock=Clock(tick=timedelta(seconds=1)))
    for i in range(3):
        record = rig.put(f"draft {i}".encode()).record
        assert record["screened_at"] is not None and record["screened_at"] <= record["created_at"]


def test_FR_MEM_06_AR_07_a_unit_cannot_name_its_own_screening_hash_or_redaction(rig):
    base = {"media_type": "text/markdown", "content": ARTICLE, "run_id": "r_run1", "origin": Origin(kind="upload")}
    for forbidden in ("screening", "screened_at", "redacted", "content_sha256", "size_bytes", "version", "owner"):
        with pytest.raises(TypeError):
            NewVersion(**base, **{forbidden: "clean"})  # type: ignore[arg-type]


def test_FR_MEM_06_AR_07_the_redactor_is_called_before_the_screener_and_before_anything_is_stored(tmp_path):
    order: list[str] = []

    class Spy(Redactor):
        def __call__(self, text: str) -> str:
            order.append("redact")
            return super().__call__(text)

    class SpySafety(FakeSafety):
        def check(self, text, **kw):
            order.append("screen")
            return super().check(text, **kw)

    rig = make_rig("memory", tmp_path, redactor=Spy(), safety=SpySafety())
    rig.meta.calls.clear()
    rig.blobs.calls.clear()
    rig.put(ARTICLE)
    assert order == ["redact", "screen"]
    assert rig.blobs.called("create") and rig.meta.called("create")
