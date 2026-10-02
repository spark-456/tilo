"""FR-CON-04 / FR-CON-05 with EFF-01 and SEC-14: the adapters replay recorded Google HTTP traffic with
no network, and recordings hold no token or real address. API_FR_CON_04_05.md "Record and replay".
"""

from __future__ import annotations

import json
import pathlib
import re
import socket

import pytest
from _gapi_lib import GMAIL_API, FakeGoogleApis, drive_file_decl
from _oauth_lib import (
    DRIVE_FILE,
    GMAIL_COMPOSE,
    GMAIL_READONLY,
    GMAIL_SEND,
    OWNER,
    fake_secret,
    gmail_decl,
    leaks,
    make_env,
)

RECORDINGS = pathlib.Path(__file__).resolve().parent / "fixtures" / "http"
SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "id_token",
    "client_secret",
    "code",
    "code_verifier",
    "token",
    "assertion",
    "password",
}
SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "set-cookie", "x-goog-api-key"}
ALLOWED_DOMAINS = {"example.com", "example.net", "example.org"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _recordings() -> list[pathlib.Path]:
    found = sorted(RECORDINGS.glob("*.json"))
    assert found, "services/connectors/tests/fixtures/http/ holds the replay fixtures"
    return found


@pytest.fixture()
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("a replay opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)


def _connected_env():
    env = make_env()
    env.connect(OWNER, "gmail", [GMAIL_READONLY, GMAIL_COMPOSE, GMAIL_SEND])
    env.connect(OWNER, "google_drive", [DRIVE_FILE])
    return env


def _adapters_over(transport, env=None):
    from tilo_connectors.adapters import DriveAdapter, GmailAdapter, InMemoryPicks

    env = env or _connected_env()
    sleeps: list[float] = []
    picks = InMemoryPicks()
    common = {
        "broker": env.broker,
        "transport": transport,
        "artifacts": None,
        "owner_of": lambda world_id: OWNER,
        "clock": env.clock,
        "emit": env.emitted.append,
        "sleep": sleeps.append,
    }
    return (
        GmailAdapter(declaration=gmail_decl(), **common),
        DriveAdapter(declaration=drive_file_decl(), picks=picks, **common),
        picks,
        env,
    )


def _walk(value, path=()):
    if isinstance(value, dict):
        for k, v in value.items():
            yield path + (k,), k, v
            yield from _walk(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _walk(v, path + (i,))


# ---------------------------------------------------------------------------
# The committed recordings


@pytest.mark.parametrize("path", _recordings(), ids=lambda p: p.name)
def test_FR_CON_04_recordings_follow_the_pinned_format(path):
    from tilo_connectors.recording import RECORDING_FORMAT

    assert RECORDING_FORMAT == "tilo.http-recording/1"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["format"] == RECORDING_FORMAT
    assert data["connector"] in {"gmail", "google_drive"}
    assert data["interactions"]
    for it in data["interactions"]:
        assert set(it) == {"request", "response"}
        assert {"method", "url", "params", "headers", "json"} <= set(it["request"])
        assert "?" not in it["request"]["url"]
        assert {"status", "headers", "json", "content_b64"} <= set(it["response"])
        assert all(k == k.lower() for k in it["request"]["headers"]) and all(
            k == k.lower() for k in it["response"]["headers"]
        )


@pytest.mark.parametrize("path", _recordings(), ids=lambda p: p.name)
def test_FR_CON_04_recordings_contain_no_tokens_and_no_real_addresses(path):
    from tilo_connectors.recording import REDACTED

    assert REDACTED == "REDACTED"
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    for it in data["interactions"]:
        for side in ("request", "response"):
            for name, value in it[side]["headers"].items():
                if name in SECRET_HEADERS:
                    assert value == "REDACTED", f"{path.name}: header {name} is not scrubbed"
        for name, value in it["request"]["params"].items():
            if name in {"access_token", "key", "oauth_token", "token", "code"}:
                assert value == "REDACTED"
    for _, key, value in _walk(data):
        if key in SECRET_KEYS:
            assert value == "REDACTED", f"{path.name}: {key} is not scrubbed"
    assert not re.search(r"Bearer\s+(?!REDACTED)\S", text), "a bearer token is in a recording"
    assert not re.search(r"ya29\.|1//0", text), "a Google token shape is in a recording"
    for domain in EMAIL.findall(text):
        low = domain.lower()
        assert any(low == d or low.endswith("." + d) for d in ALLOWED_DOMAINS), f"{path.name}: address at {domain}"


# ---------------------------------------------------------------------------
# Replay through the adapters


def test_FR_CON_04_gmail_reads_replay_from_the_recording_without_any_network(no_network):
    from tilo_connectors.recording import ReplayTransport

    replay = ReplayTransport(RECORDINGS / "gmail_read.json")
    gmail, _, _, _ = _adapters_over(replay)

    found = gmail.search_threads(OWNER, "from:supplier@example.com")
    msg = gmail.get_message(OWNER, "msg_supplier_1")
    labels = gmail.list_labels(OWNER)

    assert [t["id"] for t in found["threads"]] == ["thr_supplier_1"]
    assert msg["thread_id"] == "thr_supplier_1"
    assert "supplier@example.com" in msg["from"]
    assert msg["to"] == ["owner@example.com"]
    assert msg["subject"] == "Delivery date for order 4471"
    assert msg["message_id"] == "<order4471.1@mail.example.com>"
    assert "confirm the delivery date for order 4471" in msg["body_text"]
    assert msg["attachments"] == [{"filename": "terms.pdf", "mime_type": "application/pdf", "size": 1234}]
    assert msg["untrusted"] is True
    assert {"id": "Label_7", "name": "Suppliers", "type": "user"} in labels
    assert replay.unused() == []


def test_FR_CON_05_drive_reads_replay_from_the_recording_without_any_network(no_network):
    from tilo_connectors.recording import ReplayTransport

    replay = ReplayTransport(RECORDINGS / "drive_read.json")
    _, drive, picks, _ = _adapters_over(replay)
    picks.add(OWNER, ["file_picked_1"])

    meta = drive.get_metadata(OWNER, "file_picked_1")
    data = drive.download(OWNER, "file_picked_1")

    assert meta["name"] == "Q3 figures.txt" and meta["size"] == len(data)
    assert data == b"Quarterly figures, picked by the user.\n"


def test_FR_CON_04_a_request_that_was_not_recorded_is_a_replay_miss_not_a_network_call(no_network):
    from tilo_connectors.recording import ReplayMiss, ReplayTransport

    replay = ReplayTransport(RECORDINGS / "gmail_read.json")
    with pytest.raises(ReplayMiss):
        replay.request(
            "GET", f"{GMAIL_API}/messages/msg_unknown", params={"format": "full"}, headers={"authorization": "Bearer x"}
        )


def test_FR_CON_04_each_recorded_interaction_is_served_once():
    from tilo_connectors.recording import ReplayMiss, ReplayTransport

    replay = ReplayTransport(RECORDINGS / "gmail_read.json")
    auth = {"authorization": "Bearer " + fake_secret("at")}
    first = replay.request("GET", f"{GMAIL_API}/labels", headers=auth)
    assert first.status_code == 200 and first.json()["labels"]
    with pytest.raises(ReplayMiss):
        replay.request("GET", f"{GMAIL_API}/labels", headers=auth)


def test_FR_CON_04_replay_refuses_a_request_without_a_bearer_token():
    from tilo_connectors.recording import ReplayMiss, ReplayTransport

    replay = ReplayTransport(RECORDINGS / "gmail_read.json")
    with pytest.raises(ReplayMiss):
        replay.request("GET", f"{GMAIL_API}/labels", headers={})


def test_FR_CON_04_replay_matches_recorded_params_and_allows_extra_live_ones():
    from tilo_connectors.recording import ReplayMiss, ReplayTransport

    replay = ReplayTransport(RECORDINGS / "gmail_read.json")
    auth = {"authorization": "Bearer " + fake_secret("at")}
    with pytest.raises(ReplayMiss):
        replay.request("GET", f"{GMAIL_API}/threads", params={"q": "from:someone@example.org"}, headers=auth)
    hit = replay.request(
        "GET", f"{GMAIL_API}/threads", params={"q": "from:supplier@example.com", "maxResults": 20}, headers=auth
    )
    assert hit.json()["threads"][0]["id"] == "thr_supplier_1"


def test_FR_CON_05_replay_serves_binary_content_and_prefers_the_most_specific_match():
    """The media request carries alt=media; the metadata interactions (no params) come first in the
    file but match it less specifically, so the content interaction is served."""
    from tilo_connectors.recording import ReplayTransport

    replay = ReplayTransport(json.loads((RECORDINGS / "drive_read.json").read_text(encoding="utf-8")))
    auth = {"authorization": "Bearer " + fake_secret("at")}
    url = "https://www.googleapis.com/drive/v3/files/file_picked_1"

    media = replay.request("GET", url, params={"alt": "media"}, headers=auth)
    meta = replay.request("GET", url, params={"fields": "id,name,size"}, headers=auth)

    assert media.content == b"Quarterly figures, picked by the user.\n"
    assert media.headers["content-type"] == "text/plain"
    assert meta.json()["name"] == "Q3 figures.txt"


# ---------------------------------------------------------------------------
# Recording: scrubbed at the source


def test_FR_CON_04_a_recording_transport_scrubs_every_secret_and_replays_back(tmp_path):
    from tilo_connectors.recording import RecordingTransport, ReplayTransport

    env = _connected_env()
    apis = FakeGoogleApis(env.google)
    seeded = apis.seed_message(thread_id="thr_supplier_1", subject="Delivery date")
    recorder = RecordingTransport(apis, connector="gmail")
    gmail, _, _, _ = _adapters_over(recorder, env)

    live = [gmail.search_threads(OWNER, "delivery"), gmail.get_message(OWNER, seeded["id"]), gmail.list_labels(OWNER)]
    path = tmp_path / "recorded.json"
    recorder.save(path)
    text = path.read_text(encoding="utf-8")

    assert leaks(text, list(env.google.issued_access) + list(env.google.live_refresh)) == []
    assert json.loads(text) == recorder.recording()
    assert recorder.recording()["format"] == "tilo.http-recording/1"
    replay = ReplayTransport(path)
    replayed_gmail, _, _, _ = _adapters_over(replay)
    again = [
        replayed_gmail.search_threads(OWNER, "delivery"),
        replayed_gmail.get_message(OWNER, seeded["id"]),
        replayed_gmail.list_labels(OWNER),
    ]
    assert again == live
    assert replay.unused() == []


def test_FR_CON_04_scrub_interaction_redacts_every_pinned_field():
    from tilo_connectors.recording import scrub_interaction

    secrets_ = {
        name: fake_secret(name)
        for name in ("bearer", "cookie", "apikey", "param", "at", "rt", "idt", "cs", "code", "cv", "tok", "asr", "pw")
    }
    interaction = {
        "request": {
            "method": "POST",
            "url": "https://oauth2.googleapis.com/token",
            "params": {"access_token": secrets_["param"], "key": secrets_["apikey"], "alt": "json"},
            "headers": {
                "authorization": "Bearer " + secrets_["bearer"],
                "cookie": secrets_["cookie"],
                "x-goog-api-key": secrets_["apikey"],
                "accept": "application/json",
            },
            "json": {
                "code": secrets_["code"],
                "code_verifier": secrets_["cv"],
                "client_secret": secrets_["cs"],
                "nested": [{"password": secrets_["pw"]}],
            },
        },
        "response": {
            "status": 200,
            "headers": {"set-cookie": secrets_["cookie"], "content-type": "application/json"},
            "json": {
                "access_token": secrets_["at"],
                "refresh_token": secrets_["rt"],
                "id_token": secrets_["idt"],
                "token": secrets_["tok"],
                "assertion": secrets_["asr"],
                "scope": GMAIL_READONLY,
            },
            "content_b64": None,
        },
    }
    original = json.dumps(interaction)

    scrubbed = scrub_interaction(interaction)

    assert json.dumps(interaction) == original, "scrub_interaction returns a copy"
    assert leaks(json.dumps(scrubbed), list(secrets_.values())) == []
    assert scrubbed["request"]["headers"]["authorization"] == "REDACTED"
    assert scrubbed["request"]["headers"]["accept"] == "application/json"
    assert scrubbed["request"]["params"]["alt"] == "json"
    assert scrubbed["response"]["json"]["scope"] == GMAIL_READONLY
    assert scrubbed["request"]["json"]["nested"][0]["password"] == "REDACTED"


def test_FR_CON_04_recording_transport_returns_the_inner_response_unchanged():
    from tilo_connectors.recording import RecordingTransport

    env = _connected_env()
    apis = FakeGoogleApis(env.google)
    recorder = RecordingTransport(apis, connector="gmail")
    token = env.google.issued_access[0]

    response = recorder.request("GET", f"{GMAIL_API}/labels", headers={"authorization": f"Bearer {token}"})

    assert response.status_code == 200 and response.json()["labels"]
    (interaction,) = recorder.recording()["interactions"]
    assert interaction["request"]["headers"]["authorization"] == "REDACTED"
    assert interaction["response"]["json"] == response.json()
