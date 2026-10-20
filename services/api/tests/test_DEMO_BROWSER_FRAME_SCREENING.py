"""DEMO-BROWSER: the owner sees the frames their run's browser recorded, also when the safety screen gave no verdict.

Live world w_1R0J8CGNDT3864C7Q0W3QG0YE5 (20 Oct 17:03): the browser read en.wikipedia.org and recorded two frames,
both stored `unscreened`. Model Armor's sanitizeUserPrompt answers `invocationResult: FAILURE` with no filter
results for an IMAGE byte item, so no frame can ever be `clean`, and the frame route (clean only) answered 404 for
every frame: the World's Browser panel stayed empty. AR-07 ties the screening state to leaving Tilo (an unscreened
item leaves only as T3, with a person) and AR-11 keeps a frame inside Tilo for its owner, so the owner's own,
recorded, masked frame is served when it has no verdict; a `flagged` frame is never served.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from tilo_api.deps import Principal, Store, WorldRecord

FRAME = "art_bs0J957QN1179VEB67S0TDNESK4E_1"


def _artifacts(screening: str):
    record = {
        "run_id": "r_demo",
        "origin": {"kind": "browser"},
        "screening": screening,
        "size_bytes": 3,
        "media_type": "image/png",
    }
    return lambda: SimpleNamespace(
        head=lambda scope, ref: SimpleNamespace(record=record, ref=ref), read=lambda scope, ref: b"PNG"
    )


def _store():
    store = Store()
    store.worlds["w_demo"] = WorldRecord(owner="u_demo", districts={}, run_id="r_demo")
    store.events["w_demo"] = [{"type": "browser.acted", "data": {"frame": {"artifact_id": FRAME, "version": 1}}}]
    return store


def test_DEMO_BROWSER_an_owners_frame_with_no_verdict_is_shown():
    from tilo_api.browser_frames import get_browser_frame

    owner = Principal("u_demo", "owner", world_id="w_demo")
    assert get_browser_frame("w_demo", FRAME, owner, _store(), _artifacts("unscreened")).body == b"PNG"


def test_DEMO_BROWSER_a_flagged_frame_is_never_shown():
    from tilo_api.browser_frames import get_browser_frame

    owner = Principal("u_demo", "owner", world_id="w_demo")
    with pytest.raises(HTTPException) as refused:
        get_browser_frame("w_demo", FRAME, owner, _store(), _artifacts("flagged"))
    assert refused.value.status_code == 404


def test_DEMO_BROWSER_another_persons_frame_is_still_not_shown_whatever_its_screening():
    from tilo_api.browser_frames import get_browser_frame

    for screening in ("clean", "unscreened"):
        with pytest.raises(HTTPException):
            get_browser_frame("w_demo", FRAME, Principal("u_other", "owner"), _store(), _artifacts(screening))
