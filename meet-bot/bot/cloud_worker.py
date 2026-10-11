"""One guest browser per request, with transient capture files and provider-only voice."""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tilo_contracts import Transcript

from .config import Config
from .events import remove_meet_links
from .providers import reset_call_counter
from .session import LiveSession


class CapturedTranscript(dict):
    """Reason travels in an HTTP header; the body remains the existing Transcript contract."""

    def __init__(self, transcript, reason):
        super().__init__(transcript)
        self.reason = reason


def transcript_from_items(meeting_id: str, items) -> dict:
    def clean(text, limit):
        text = re.sub(r"[\x00-\x1f\x7f]", " ", remove_meet_links(text))
        return " ".join(text.split())[:limit]

    utterances = []
    for item in items:
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


async def attend_meeting(meeting_id: str, join_url: str) -> dict:
    # Cloud logs are operational only. Session modules can log untrusted participant text at any level.
    for name in logging.root.manager.loggerDict:
        if name.startswith(("bot.", "tilo_providers")):
            logging.getLogger(name).disabled = True
    reset_call_counter()
    with TemporaryDirectory(prefix="tilo-meet-") as directory:
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
        session = LiveSession(cfg, "join", join_url, agenda, 45, False, [], False, False, [], "captions", "both")
        session.events.echo = False
        await session.run()
        return CapturedTranscript(
            transcript_from_items(meeting_id, session.store.items),
            "left_on_request" if getattr(session, "leave_requested", False) else "completed",
        )
