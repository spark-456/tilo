from __future__ import annotations

from pathlib import Path

import pytest
from _browser_lib import FakeWeb, doc, password_box, textbox
from tilo_browser.skill_recording import JsonlRecordingStore, RecordedEvent, RecordingSession


def test_SKILL_REPLAY_recording_requires_worker_check_and_masks_secure_fields(make_rig, tmp_path: Path) -> None:
    store = JsonlRecordingStore(tmp_path)
    web = FakeWeb()
    web.add("https://ledgerly.example/search", title="Search", tree=doc(textbox("query", "Search products")))
    rig = make_rig(web, allow=("ledgerly.example",))
    rig.worker.navigate("https://ledgerly.example/search")
    session = RecordingSession(store, rig.worker, owner="owner_1", recording_id="recording_1")
    safe = session.record(
        kind="type",
        url="https://ledgerly.example/search",
        target="Search products",
        selector="#query",
        value="Growth",
    )
    assert safe.value == "Growth"
    assert store.read("owner_1", "recording_1") == [safe]

    secret = "pw-" + "A7kP9xQ2mN4b"
    forged = RecordedEvent(2, "type", "https://ledgerly.example/search", "Password", "#query", secret)
    with pytest.raises(ValueError, match="unverified"):
        store.append("owner_1", "recording_1", forged)

    login = FakeWeb()
    login.add(
        "https://ledgerly.example/login",
        title="Sign in",
        text="Password",
        tree=doc(password_box("password"), title="Sign in"),
    )
    rig = make_rig(login, allow=("ledgerly.example",))
    rig.worker.navigate("https://ledgerly.example/login")
    session = RecordingSession(store, rig.worker, owner="owner_1", recording_id="recording_2")
    masked = session.record(
        kind="type",
        url="https://ledgerly.example/login",
        target="Password",
        selector="#password",
        value=secret,
    )
    persisted = (tmp_path / "owner_1" / "recording_2.jsonl").read_text(encoding="utf-8")
    assert masked.value is None and masked.selector is None
    assert secret not in persisted
