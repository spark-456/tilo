"""S2 (FR-SKL-01, TS-03, ADR-0034 decision 3, ADR-0051): a capture recording is stored by the ADR-0018 store as an
`upload`. video/webm and video/mp4 (common 1.7.0) are accepted for an upload only, within the 50,000,000 byte file cap
and the world cap, and are always stored `unscreened` (a video cannot be screened or redacted). A unit, a render and a
fetch never store a video, and the other kinds and caps are unchanged."""

from __future__ import annotations

import pytest
from _artifact_testlib import FakeSafety, make_rig
from tilo_memory.artifacts import ArtifactRefused

WEBM = b"\x1a\x45\xdf\xa3\x93\x42\x82\x84webm" + b"\x00" * 40
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 40


@pytest.mark.parametrize(("media", "content"), [("video/webm", WEBM), ("video/mp4", MP4)])
def test_FR_SKL_01_S2_a_capture_video_upload_is_stored_unscreened_even_with_a_clean_screener(media, content):
    rig = make_rig("memory", None, safety=FakeSafety(flagged=False))
    stored = rig.upload(content, media)
    assert stored.record["media_type"] == media and stored.record["origin"]["kind"] == "upload"
    assert stored.record["screening"] == "unscreened" and stored.record["screened_at"] is None
    assert rig.store.read(rig.scope, stored.ref) == content


@pytest.mark.parametrize("kind", ["unit", "render"])
def test_FR_SKL_01_S2_only_an_upload_may_store_a_video(kind):
    rig = make_rig("memory", None)
    with pytest.raises(ArtifactRefused):
        rig.put(WEBM, media_type="video/webm", kind=kind, **({"agent": None} if kind == "render" else {}))
    assert rig.meta.inner.paths() == []


def test_FR_SKL_01_S2_a_video_over_the_file_cap_is_refused_before_it_is_stored(monkeypatch):
    from tilo_memory import artifacts  # noqa: PLC0415

    rig = make_rig("memory", None)
    monkeypatch.setattr(artifacts, "MAX_FILE", 100)
    with pytest.raises(ArtifactRefused):
        rig.upload(WEBM + b"\x00" * 100, "video/webm")
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_FR_SKL_01_S2_other_media_types_are_still_refused():
    rig = make_rig("memory", None)
    for media in ("video/quicktime", "audio/mpeg", "text/html", "application/octet-stream"):
        with pytest.raises(ArtifactRefused):
            rig.upload(b"abc", media)
