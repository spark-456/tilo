"""Start-up refusals of the bot (FR-MTG-11, EFF-01). Standard library only: the host CLI runs without Tilo's packages.

- A fake transcript never reaches a real meeting. `start` and `join` put the bot in a real call, so they refuse the dev
  fakes (canned answers, a sine tone for a voice) unless the user set the live switch: without it `bot/providers.py`
  reads `config/*.dev.yaml`. `run-mock` and the offline tests keep the fakes; they never open a call.
- The bot never records provider traffic. `TILO_RECORD` would write what outside participants said into the tracked
  `fixtures/` tree, so the bot refuses to start with it set, on the host and in the container."""

from __future__ import annotations

import os

FILE_OVERRIDES = ("TILO_MODELS_FILE", "TILO_SPEECH_FILE", "TILO_VOICE_FILE")


class BotRefused(RuntimeError):
    """A start-up refusal; the message says what to change."""


def is_live() -> bool:
    return os.environ.get("LIVE") == "1"  # the same single definition as the provider layer: only the user sets it


def recording_refusal() -> str | None:
    if os.environ.get("TILO_RECORD", "").strip():
        return (
            "the bot refuses to start with TILO_RECORD set: recording would write what people in a meeting said into "
            "the repository's fixtures. Unset TILO_RECORD."
        )
    return None


def fakes_refusal() -> str | None:
    """Why `start`/`join` must not run on the dev fakes, or None when the providers are the real ones."""
    if not is_live():
        return (
            "start and join refuse the dev fakes: without LIVE=1 the bot answers with canned text and speaks a test "
            "tone, and a fake transcript never reaches a real meeting. Only you set LIVE=1 (README, Providers); use "
            "run-mock to try the bot offline."
        )
    # Only a hint, case-insensitive; the check that counts is what the files resolve to (`providers.start_up_check`).
    dev = [n for n in FILE_OVERRIDES if ".dev." in os.environ.get(n, "").lower()]
    if dev:
        return f"start and join refuse a dev config file ({', '.join(dev)}): a fake transcript never reaches a meeting."
    return None
