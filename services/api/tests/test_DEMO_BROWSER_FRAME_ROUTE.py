"""DEMO-BROWSER-FRAME: frames are shown only to the owning world."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from tilo_api.deps import Principal, Store, WorldRecord


class FakeArtifacts:
    def head(self, scope, ref):
        return SimpleNamespace(
            record={
                "run_id": "r_demo",
                "origin": {"kind": "browser"},
                "screening": "clean",
                "size_bytes": 3,
                "media_type": "image/png",
            },
            ref=ref,
        )

    def read(self, scope, ref):
        return b"PNG"


def test_DEMO_BROWSER_FRAME_route_requires_owner_and_recorded_frame():
    from tilo_api.browser_frames import get_browser_frame

    store = Store()
    store.worlds["w_demo"] = WorldRecord(owner="u_demo", districts={}, run_id="r_demo")
    store.events["w_demo"] = [
        {"type": "browser.acted", "data": {"frame": {"artifact_id": "art_bsdemo_1", "version": 1}}}
    ]
    owner = Principal("u_demo", "owner", world_id="w_demo")
    frame = get_browser_frame("w_demo", "art_bsdemo_1", owner, store, lambda: FakeArtifacts())
    assert frame.body == b"PNG"
    assert frame.headers["cache-control"] == "no-store"
    for principal, artifact in [(Principal("u_other", "owner"), "art_bsdemo_1"), (owner, "art_unseen")]:
        with pytest.raises(HTTPException) as denied:
            get_browser_frame("w_demo", artifact, principal, store, lambda: FakeArtifacts())
        assert denied.value.status_code == 404
