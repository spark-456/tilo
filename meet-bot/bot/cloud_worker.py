"""One guest browser per request, with transient capture files and provider-only voice."""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tilo_contracts import Transcript

from .config import Config
from .events import remove_meet_links
from .providers import reset_call_counter
from .session import LiveSession
from .voice_meter import meter_from_env


class CapturedTranscript(dict):
    """Reason travels in an HTTP header; the body remains the existing Transcript contract."""

    def __init__(self, transcript, reason):
        super().__init__(transcript)
        self.reason = reason


def transcript_from_items(meeting_id: str, items) -> dict:
    """Assign evidence ids in speech-start order; capture order breaks timestamp ties."""

    def clean(text, limit):
        text = re.sub(r"[\x00-\x1f\x7f]", " ", remove_meet_links(text))
        return " ".join(text.split())[:limit]

    utterances = []
    # Overlapping speakers can settle in a different order from when they began.
    for item in sorted(items, key=lambda item: item.t):
        text = clean(item.text, 4000)
        if text:
            utterances.append(
                {
                    "id": f"u{len(utterances) + 1:04d}",
                    "speaker": clean(item.speaker, 80) or "Speaker",
                    "t_ms": max(0, round(item.t * 1000)),
                    "text": text,
                }
            )
    return Transcript(v="1.0", meeting_id=meeting_id, utterances=utterances).model_dump(mode="json")


@contextmanager
def quiet_capture():
    # Cloud logs are operational only. Session modules can log untrusted participant text at any level.
    loggers = [
        logging.getLogger(name)
        for name in list(logging.root.manager.loggerDict)
        if name.startswith(("bot.", "tilo_providers"))
    ]
    states = [(logger, logger.disabled) for logger in loggers]

    class ContentFilter(logging.Filter):
        def filter(self, record):
            return not record.name.startswith(("bot.", "tilo_providers"))

    boundary = ContentFilter("tilo-content-boundary")
    handlers = set(logging.root.handlers)
    if logging.lastResort is not None:
        handlers.add(logging.lastResort)
    for logger in loggers:
        handlers.update(logger.handlers)
    added = [handler for handler in handlers if not any(f.name == boundary.name for f in handler.filters)]
    for handler in added:
        handler.addFilter(boundary)
    for logger, _ in states:
        logger.disabled = True
    try:
        yield
    finally:
        # A synchronous SDK executor may finish after browser cancellation. Image logs must
        # remain private across captures; local tools/tests recover their original handlers.
        if os.environ.get("TILO_CLOUD_CAPTURE") != "1":
            for handler in added:
                handler.removeFilter(boundary)
        for logger, disabled in states:
            logger.disabled = disabled


async def attend_meeting(meeting_id: str, join_url: str, claim: str | None = None) -> dict:
    reset_call_counter()
    # ADR-0042 (BQ-M2-4): the Live voice's SEC-16 hook, or None (the Live voice then stays unbuilt and the local voice
    # speaks). Only with LIVE=1, TILO_API_URL and the attend's claim; the claim goes nowhere else.
    meter = meter_from_env(meeting_id, claim, os.environ)
    with quiet_capture(), TemporaryDirectory(prefix="tilo-meet-") as directory:
        root = Path(directory)
        agenda = root / "agenda.md"
        agenda.write_text("# Meeting\n\nDuration: 45 min\n\n1. Discussion and decisions (45 min)\n", encoding="utf-8")
        cfg = replace(
            Config.from_env(),
            guest=True,
            bot_email="",
            bot_display_name="Tilo notetaker",
            agenda_path=agenda,
            out_dir=root / "out",
            debug_dir=root / "debug",
            context_dir=root / "context",
            profile_dir=root / "unused",
            max_meeting_minutes=45,
            meeting_minutes=45,
            auto_admit=False,
            required=[],
            admit_allowed=[],
            record_audio=False,
            save_caption_snapshots=False,
            hybrid=False,
            stt="captions",
            reply_mode="both",
            context_urls=[],
        )
        extra = {"voice_meter": meter} if meter is not None else {}  # off: the session is built exactly as before
        session = LiveSession(
            cfg, "join", join_url, agenda, 45, False, [], False, False, [], "captions", "both", **extra
        )
        session.events.echo = False
        await session.run()
        return CapturedTranscript(
            transcript_from_items(meeting_id, session.store.items),
            "left_on_request" if getattr(session, "leave_requested", False) else "completed",
        )
