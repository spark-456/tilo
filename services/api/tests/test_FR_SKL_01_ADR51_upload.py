"""S2 (FR-SKL-01, TS-03, TS-11, TS-20; ADR-0034 decision 3, ADR-0051 decision A, BQ-SMB-5): teach by uploading a
recording or a file.

Pinned interface:
  * `POST /v1/skills/captures/media` (multipart, one `file`): the type is read from the bytes only (WebM, MP4, PDF, PNG,
    JPEG, plain text; the file name and declared type are ignored, anything else is 415 `unsupported_type`). It is
    stored by the ADR-0018 store in the owner's Desk world as an `upload` (a video `unscreened`) and answers 201
    `{artifact: {artifact_id, version}, media_type, size_bytes, readable, reason, limits}`. Over `max_file_bytes` is 413
    `file_too_large` (nothing stored). Over `max_read_bytes` it is stored and answered `readable: false, reason:
    too_long_to_read`. A video with an audio track when the role's profile has no `audio_input` price is 422
    `audio_not_supported` before anything is stored. The per-person write limit counts every attempt (SEC-10).
  * `POST /v1/skills/captures` takes `method` describe | upload | record; upload and record need `artifact` (a pinned
    ref in the owner's Desk world) and take optional `text`; describe takes `text` and never an artifact. The model
    reads the file as one media part (or a text file as a delimited document). `too_long_to_read` and
    `audio_not_supported` are 422 with no model call; any ref the owner cannot read is the one 404. Every
    `skill.captured` event and every captured step carries the pinned artifact. A record is video only.
  * config/skills.yaml `capture` holds max_steps 20, max_recording_seconds 300, max_file_bytes 50000000 and
    max_read_bytes 10485760.
"""

from __future__ import annotations

import io
import json

import pytest
from _api_lib import validate_event
from _ppl11a_lib import conforms
from _skills4_lib import CLEAR, ORG, PRIYA, PRIYA_DESK, SAM, plan

WEBM = b"\x1a\x45\xdf\xa3\x93\x42\x82\x84webm" + b"\x00" * 60
WEBM_AUDIO = WEBM + b"\x86\x86A_OPUS" + b"\x00" * 20
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"mdat" + b"\x00" * 40
MP4_AUDIO = MP4 + b"hdlr" + b"\x00" * 8 + b"soun" + b"\x00" * 8
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
TEXT = b"Every Monday I open the supplier list, copy the new prices and mail them to my buyer.\n"
MEDIA = "/v1/skills/captures/media"
CAPTURE = "/v1/skills/captures"


def _pdf() -> bytes:
    from pypdf import PdfWriter  # noqa: PLC0415

    writer, out = PdfWriter(), io.BytesIO()
    writer.add_blank_page(width=100, height=100)
    writer.write(out)
    return out.getvalue()


def _upload(skills4, data, *, name="clip.bin", kind="application/octet-stream", user=PRIYA, art="art_cap01"):
    skills4.rig._ids = [art]
    skills4.rig.as_user(user)
    return skills4.rig.client.post(MEDIA, files={"file": (name, data, kind)})


def _limits(monkeypatch, **changes):
    from tilo_api import skills_media  # noqa: PLC0415

    monkeypatch.setattr(skills_media, "load_capture_limits", lambda: skills_media.CaptureLimits(**{**_BASE, **changes}))


_BASE = {"max_steps": 20, "max_recording_seconds": 300, "max_file_bytes": 50_000_000, "max_read_bytes": 10_485_760}


def test_FR_SKL_01_S2_the_shipped_capture_limits_are_config(repo_root):
    from tilo_api import skills_media  # noqa: PLC0415

    assert skills_media.load_capture_limits() == skills_media.CaptureLimits(**_BASE)


@pytest.mark.parametrize(
    ("data", "media"),
    [
        (WEBM, "video/webm"),
        (MP4, "video/mp4"),
        (PNG, "image/png"),
        (JPEG, "image/jpeg"),
        (TEXT, "text/markdown"),
    ],
)
def test_FR_SKL_01_S2_the_type_comes_from_the_bytes_and_the_file_is_stored_in_the_desk_world(skills4, data, media):
    response = _upload(skills4, data, name="evil.exe", kind="application/x-msdownload")  # name and type are ignored
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["media_type"] == media and body["size_bytes"] == len(data) and body["readable"] is True
    assert body["reason"] is None and body["artifact"] == {"artifact_id": "art_cap01", "version": 1}
    assert body["limits"] == {"max_recording_seconds": 300, "max_steps": 20}
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    stored = skills4.rig.artifacts.head(Scope(ORG, PRIYA_DESK, PRIYA), body["artifact"])
    assert stored.record["origin"]["kind"] == "upload" and stored.record["media_type"] == media
    if media.startswith("video/"):
        assert stored.record["screening"] == "unscreened"


def test_FR_SKL_01_S2_a_pdf_is_accepted_by_its_bytes(skills4):
    response = _upload(skills4, _pdf(), name="notes.txt", kind="text/plain")
    assert response.status_code == 201 and response.json()["media_type"] == "application/pdf"


@pytest.mark.parametrize(
    "data",
    [
        b"MZ\x90\x00" + b"\x00" * 30,
        b"\x00\x01\x02binary",
        b"GIF89a" + bytes([1, 0, 1, 0, 128, 0, 0]),
        b"",
        b"   \n\t ",
        b"PK\x03\x04zip",
    ],
)
def test_FR_SKL_01_S2_anything_else_is_415_and_nothing_is_stored(skills4, data):
    response = _upload(skills4, data, name="clip.webm", kind="video/webm")
    assert response.status_code in (415, 422)
    assert response.json() in ({"detail": "unsupported_type"}, {"detail": "empty_file"})
    assert skills4.rig.meta.paths("") == []


def test_FR_SKL_01_S2_a_file_over_the_stored_cap_is_413_and_one_over_the_read_cap_is_stored_but_not_read(
    skills4, monkeypatch
):
    _limits(monkeypatch, max_file_bytes=200, max_read_bytes=100)
    big = _upload(skills4, WEBM + b"\x00" * 300)
    assert big.status_code == 413 and big.json() == {"detail": "file_too_large"}
    huge = _upload(skills4, WEBM + b"\x00" * 20000)  # refused from the declared length, before the form is read
    assert huge.status_code == 413 and huge.json() == {"detail": "file_too_large"}
    assert skills4.rig.meta.paths("") == []
    long_file = _upload(skills4, WEBM + b"\x00" * 100)
    body = long_file.json()
    assert long_file.status_code == 201 and body["readable"] is False and body["reason"] == "too_long_to_read"
    capture = skills4.rig.post(CAPTURE, {"method": "upload", "artifact": body["artifact"]})
    assert capture.status_code == 422 and capture.json() == {"detail": "too_long_to_read"}
    assert skills4.model.calls == []  # no model call for a file the model would not be sent


@pytest.mark.parametrize(("data", "label"), [(WEBM_AUDIO, "webm"), (MP4_AUDIO, "mp4")])
def test_FR_SKL_01_S2_a_recording_with_sound_is_refused_unless_the_role_has_an_audio_price(
    skills4, monkeypatch, data, label
):
    from tilo_api import skills_media  # noqa: PLC0415

    monkeypatch.setattr(skills_media, "audio_priced", lambda: False)
    refused = _upload(skills4, data)
    assert refused.status_code == 422 and refused.json() == {"detail": "audio_not_supported"}, label
    assert skills4.rig.meta.paths("") == [] and skills4.model.calls == []
    monkeypatch.setattr(skills_media, "audio_priced", lambda: True)
    assert _upload(skills4, data).status_code == 201
    monkeypatch.setattr(skills_media, "audio_priced", lambda: False)
    silent = _upload(skills4, MP4 if label == "mp4" else WEBM, art="art_cap02")
    assert silent.status_code == 201  # no audio track: nothing to price


def test_FR_SKL_01_S2_a_stored_recording_with_sound_is_checked_again_before_the_model_call(skills4, monkeypatch):
    from tilo_api import skills_media  # noqa: PLC0415

    stored = _upload(skills4, WEBM_AUDIO).json()["artifact"]  # priced: accepted
    monkeypatch.setattr(skills_media, "audio_priced", lambda: False)
    response = skills4.rig.post(CAPTURE, {"method": "record", "artifact": stored})
    assert response.status_code == 422 and response.json() == {"detail": "audio_not_supported"}
    assert skills4.model.calls == []


@pytest.mark.parametrize(("data", "method"), [(WEBM, "record"), (MP4, "upload"), (PNG, "upload")])
def test_FR_SKL_01_S2_a_capture_from_a_file_sends_one_media_part_and_pins_the_artifact(skills4, data, method):
    artifact = _upload(skills4, data).json()["artifact"]
    skills4.model.captures[CLEAR] = ["Open the supplier list", "Copy the prices", "Mail them to the buyer"]
    skills4.model.last_description = CLEAR
    response = skills4.rig.post(CAPTURE, {"method": method, "artifact": artifact, "text": CLEAR})
    assert response.status_code == 201, response.text
    call = skills4.model.calls[-1]
    assert [p.mime_type for p in call.parts] == [skills4.rig.artifacts.head(_scope(), artifact).record["media_type"]]
    draft = skills4.store.get(ORG, response.json()["capture_id"])
    assert draft["method"] == method and conforms("taught_skill.schema.json", draft)
    assert [c["artifact"] for c in draft["captured"]] == [artifact] * 3
    events = [e for e in skills4.events() if e["type"] == "skill.captured"]
    assert len(events) == 3 and all(e["data"]["artifact"] == artifact and e["data"]["method"] == method for e in events)
    for event in events:
        validate_event(event)
        assert "supplier" not in json.dumps(event)
    assert events[0]["trace"]["model_role"] == "skill_capture" and events[0]["trace"]["tokens_in"] == 400


def _scope():
    from tilo_memory.artifacts import Scope  # noqa: PLC0415

    return Scope(ORG, PRIYA_DESK, PRIYA)


def test_FR_SKL_01_S2_a_recording_can_be_taught_with_no_words_and_a_text_file_is_delimited_data(skills4):
    skills4.model.captures[CLEAR] = ["Open the list", "Copy the prices", "Mail them"]
    skills4.model.last_description = CLEAR
    video = _upload(skills4, WEBM).json()["artifact"]
    assert skills4.rig.post(CAPTURE, {"method": "record", "artifact": video}).status_code == 201
    assert "<<<DESCRIPTION" in skills4.model.calls[-1].prompt
    note = _upload(skills4, TEXT, art="art_cap02").json()["artifact"]
    assert skills4.rig.post(CAPTURE, {"method": "upload", "artifact": note}).status_code == 201
    prompt = skills4.model.calls[-1].prompt
    assert "<<<DOCUMENT" in prompt and TEXT.decode().strip() in prompt and not skills4.model.calls[-1].parts


def test_FR_SKL_01_S2_the_body_is_closed_about_method_and_artifact(skills4):
    artifact = _upload(skills4, WEBM).json()["artifact"]
    for body in (
        {"method": "upload", "text": CLEAR},  # upload needs a file
        {"method": "record", "text": CLEAR},
        {"method": "describe", "text": CLEAR, "artifact": artifact},  # describe never takes one
        {"method": "guided", "artifact": artifact},
        {"method": "record", "artifact": {**artifact, "extra": 1}},
        {"method": "record", "artifact": {"artifact_id": "art_x", "version": 0}},
    ):
        assert skills4.rig.post(CAPTURE, body).status_code == 422, body
    pdf = _upload(skills4, _pdf(), art="art_cap03").json()["artifact"]
    assert skills4.rig.post(CAPTURE, {"method": "record", "artifact": pdf}).status_code == 422  # a record is video
    assert skills4.model.calls == []


def test_FR_SKL_01_S2_another_persons_or_a_missing_artifact_is_the_one_404(skills4):
    artifact = _upload(skills4, WEBM).json()["artifact"]
    skills4.rig.as_user(SAM)
    foreign = skills4.rig.post(CAPTURE, {"method": "record", "artifact": artifact})
    missing = skills4.rig.post(CAPTURE, {"method": "record", "artifact": {"artifact_id": "art_nope", "version": 1}})
    assert foreign.status_code == 404 and foreign.json() == missing.json() == {"detail": "not_found"}
    assert skills4.model.calls == []


def test_FR_SKL_01_S2_the_draft_from_a_file_goes_on_to_tilos_version(skills4):
    artifact = _upload(skills4, WEBM).json()["artifact"]
    skills4.model.captures[CLEAR] = ["Read the new mail", "Save a summary", "Email me the summary"]
    skills4.model.last_description = CLEAR
    capture_id = skills4.rig.post(CAPTURE, {"method": "record", "artifact": artifact}).json()["capture_id"]
    skills4.model.override["version"] = json.dumps(
        {
            "steps": plan(("Read the new mail", "gmail", "read_email", "read")),
            "question": None,
        }
    )
    body = skills4.version(capture_id)
    assert body.status_code == 200, body.text
    assert skills4.store.get(ORG, capture_id)["method"] == "record"


def test_FR_SKL_01_S2_the_write_limit_counts_every_upload_attempt(skills4):
    statuses = [_upload(skills4, b"\x00\x01").status_code for _ in range(61)]
    assert statuses[-1] == 429 and statuses.count(429) == 1 and set(statuses[:-1]) <= {415, 422}


def test_FR_SKL_01_S2_one_file_in_the_form_is_the_rule(skills4):
    skills4.rig.as_user(PRIYA)
    two = skills4.rig.client.post(MEDIA, files=[("file", ("a", WEBM)), ("file", ("b", WEBM))])
    other_name = skills4.rig.client.post(MEDIA, files={"upload": ("a", WEBM)})
    extra = skills4.rig.client.post(MEDIA, files={"file": ("a", WEBM)}, data={"note": "x"})
    assert [r.status_code for r in (two, other_name, extra)] == [422, 422, 422]
    assert skills4.rig.meta.paths("") == []


def test_FR_SKL_01_S2_an_upload_makes_no_model_call_and_needs_a_signed_in_person(skills4):
    assert _upload(skills4, WEBM).status_code == 201 and skills4.model.calls == []
    assert skills4.rig.router_calls == []


def test_FR_SKL_01_S2_the_media_route_is_closed_to_replay_only(skills4):
    from tilo_metering.flags import InMemoryFlagStore  # noqa: PLC0415

    flags = InMemoryFlagStore()
    flags.set("replay_only", True, reason="test")
    skills4.rig.app.dependency_overrides[skills4.rig.deps.get_flag_store] = lambda: flags
    response = _upload(skills4, WEBM)
    assert response.status_code == 503 and skills4.rig.meta.paths("") == []
