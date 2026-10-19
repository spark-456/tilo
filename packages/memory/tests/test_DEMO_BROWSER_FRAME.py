"""DEMO-BROWSER-FRAME: browser frames use the contract's PNG-only origin."""

import pytest
from _artifact_testlib import SAMPLE, make_rig
from tilo_memory.artifacts import ArtifactRefused


def test_DEMO_BROWSER_FRAME_stores_owner_scoped_masked_png_without_a_key():
    rig = make_rig("memory", None)
    frame = SAMPLE["image/png"]
    stored = rig.store.with_new_id(lambda: "art_bs01JB7A0000000000000000BRW1_1").put(
        rig.scope, rig.new(frame, media_type="image/png", kind="browser", key=None)
    )
    assert stored.record["origin"] == {"kind": "browser", "unit": "U1", "agent": "A_s1"}
    assert stored.record["idempotency_key"] is None
    assert rig.store.read(rig.scope, stored.ref) == frame


def test_DEMO_BROWSER_FRAME_refuses_non_png_or_archive_sources():
    rig = make_rig("memory", None)
    with pytest.raises(ArtifactRefused):
        rig.put(b"text", media_type="text/plain", kind="browser", key=None)
    with pytest.raises(ArtifactRefused):
        rig.put(
            SAMPLE["image/png"],
            media_type="image/png",
            kind="browser",
            key=None,
            sources=({"id": "x", "archive_ref": "a"},),
        )
