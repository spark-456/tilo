"""Teach a skill by uploading a recording or a file (S2: FR-SKL-01; ADR-0034 decision 3, ADR-0051 decision A, BQ-SMB-5;
taught_skill.rules.md TS-03, TS-20).

`POST /v1/skills/captures/media` takes one multipart `file`. The type is read from the bytes only (WebM, MP4, PDF, PNG,
JPEG or plain text); the file name and declared type are never used. The file is stored by the ADR-0018 store in the
owner's Desk world as an `upload` (a video `unscreened`: it cannot be screened). At most `max_read_bytes` is later read
as one media part; a larger file is stored and answered `too_long_to_read`. A video with an audio track is refused when
the role's profile has no `audio_input` price, before anything is stored or sent (TS-20). The file's words are data,
never instructions. This route makes no model call; `POST /v1/skills/captures` does, with the pinned artifact.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import yaml
from fastapi import APIRouter, Depends, Request
from starlette.datastructures import UploadFile
from tilo_memory.artifacts import ArtifactRefused, ArtifactStore, NewVersion, Origin, Scope
from tilo_metering.flags import FlagStore
from tilo_planning.artifacts import new_ulid
from tilo_providers.media import _TYPES as _MAGIC  # noqa: PLC2701 - the one list of magic numbers the providers read
from tilo_providers.media import MediaPart

from tilo_api import deps
from tilo_api.people import _PeopleRoute
from tilo_api.people_events import _DESK_WORLD, WorkEvents, get_work_events
from tilo_api.people_writes import Refusal
from tilo_api.skills_routes import _ROOT, _guarded

logger = logging.getLogger("tilo_api.skills_media")
router = APIRouter(route_class=_PeopleRoute)

_SNIFFED = ("video/webm", "video/mp4", "application/pdf", "image/png", "image/jpeg")
_WEBM_AUDIO = re.compile(rb"A_(?:OPUS|VORBIS|AAC|MPEG|PCM|FLAC|AC3|EAC3|DTS)")
_MP4_AUDIO = re.compile(rb"hdlr.{8}soun", re.DOTALL)
_PLAIN = re.compile(r"[^\x00-\x08\x0b\x0c\x0e-\x1f\x7f]+")
_MAX_PLAIN = 2_000_000  # the store's cap for text
_FORM_SLACK = 8192  # the multipart framing around the one file
_SHIPPED = {"max_steps": 20, "max_recording_seconds": 300, "max_file_bytes": 50_000_000, "max_read_bytes": 10_485_760}


@dataclass(frozen=True)
class CaptureLimits:
    max_steps: int
    max_recording_seconds: int
    max_file_bytes: int
    max_read_bytes: int


def load_capture_limits(root: Path = _ROOT) -> CaptureLimits:
    """`config/skills.yaml` `capture`; a missing or unusable file or value falls back to the shipped number."""
    try:
        raw = yaml.safe_load((root / "skills.yaml").read_text(encoding="utf-8"))["capture"]
    except Exception:
        logger.warning("config/skills.yaml capture not read; using the shipped limits")
        raw = {}
    found = {k: raw[k] if type(raw.get(k)) is int and raw[k] >= 1 else v for k, v in _SHIPPED.items()}
    return CaptureLimits(**found)


def sniff(data: bytes) -> str | None:
    """The media type of the bytes, by magic number only, or None. Plain text is stored as markdown."""
    head = data[:64]
    for mime in _SNIFFED:
        if _MAGIC[mime][1](head):
            return mime
    if 0 < len(data) <= _MAX_PLAIN and data.strip():
        try:
            return "text/markdown" if _PLAIN.fullmatch(data.decode("utf-8")) else None
        except UnicodeDecodeError:
            return None
    return None


def has_audio(media: str, data: bytes) -> bool:
    """Whether a video holds an audio track: a WebM codec id or an MP4 sound handler."""
    if media == "video/webm":
        return _WEBM_AUDIO.search(data[:65536]) is not None
    return media == "video/mp4" and _MP4_AUDIO.search(data) is not None


def audio_priced() -> bool:
    """Whether the capture role's first profile has an `audio_input` price (TS-20), as the Router also requires. With
    no prices set there is nothing to meter, as in the Router."""
    from tilo_api import skills_capture  # noqa: PLC0415 - it imports this module

    try:
        config = deps.providers_config()
        if config.prices.status != "set":
            return True
        return config.prices.profiles[config.roles[skills_capture.CAPTURE_ROLE].primary].audio_input is not None
    except Exception:
        return False


def _check_audio(media: str, data: bytes) -> None:
    if has_audio(media, data) and not audio_priced():
        raise Refusal(422, "audio_not_supported")


def read_capture_file(artifacts: ArtifactStore, scope: Scope, ref: dict[str, Any]) -> tuple[str, bytes]:
    """The owner's stored capture file as (media type, bytes), checked again before a model call: one 404 for anything
    the owner cannot read, `too_long_to_read` over `max_read_bytes`, `audio_not_supported` as at upload."""
    try:
        head = artifacts.head(scope, ref)
        media = None if head is None else head.record["media_type"]
        if head is None or head.record["origin"]["kind"] != "upload":
            raise Refusal(404, "not_found")
        if head.record["size_bytes"] > load_capture_limits().max_read_bytes:
            raise Refusal(422, "too_long_to_read")
        data = artifacts.read(scope, ref)
    except Refusal:
        raise
    except Exception:  # noqa: BLE001 - absent, another person's and unreadable are one answer
        raise Refusal(404, "not_found") from None
    _check_audio(media, data)
    return media, data


def media_part(media: str, data: bytes) -> MediaPart:
    try:
        return MediaPart(mime_type=media, data=data)
    except Exception:  # noqa: BLE001 - a PDF that cannot be read, a bad part: the type only, never the file
        raise Refusal(422, "unreadable_file") from None


@router.post("/v1/skills/captures/media", status_code=201)
async def media_route(
    request: Request,
    principal: Annotated[deps.Principal, Depends(deps.get_current_principal)],
    artifacts: Annotated[ArtifactStore, Depends(deps.get_artifact_store)],
    we: Annotated[WorkEvents, Depends(get_work_events)],
    flags: Annotated[FlagStore, Depends(deps.get_flag_store)],
) -> dict[str, Any]:
    """Store one capture file in the owner's Desk world: 201 with its pinned ref and whether Tilo can read it."""
    deps.refuse_if_replay_only(flags)
    limits = load_capture_limits()
    declared = request.headers.get("content-length", "")
    if not declared.isdigit():
        raise Refusal(411, "length_required")
    if int(declared) > limits.max_file_bytes + _FORM_SLACK:  # before the form is read or spooled
        raise Refusal(413, "file_too_large")
    form = await request.form()
    uploads = form.getlist("file")
    if len(uploads) != 1 or len(form) != 1 or not isinstance(uploads[0], UploadFile):
        raise Refusal(422, "one_file")
    data = await uploads[0].read(limits.max_file_bytes + 1)  # never hold more than the cap in memory
    if len(data) > limits.max_file_bytes:
        raise Refusal(413, "file_too_large")
    media = sniff(data)
    if media is None:
        raise Refusal(415, "unsupported_type")
    _check_audio(media, data)

    def store() -> dict[str, Any]:
        owner = principal.user_id
        world = we.desks.desk_world(deps.ORG_ID, owner)
        if type(world) is not str or _DESK_WORLD.fullmatch(world) is None or we.desks.desk_owner(world) != owner:
            raise ValueError("not the owner's Desk world")
        try:
            new = NewVersion(media, data, "r_cap_" + new_ulid(), Origin(kind="upload"))
            stored = artifacts.put(Scope(deps.ORG_ID, world, owner), new)
        except ArtifactRefused:
            raise Refusal(422, "unsupported_type") from None
        readable = len(data) <= limits.max_read_bytes
        return {
            "artifact": stored.ref,
            "media_type": media,
            "size_bytes": len(data),
            "readable": readable,
            "reason": None if readable else "too_long_to_read",
            "limits": {"max_recording_seconds": limits.max_recording_seconds, "max_steps": limits.max_steps},
        }

    return _guarded(store)
