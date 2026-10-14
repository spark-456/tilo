"""FR-MTG-15: pure addressing and same-speaker attention; no I/O or model."""

import math
import re
from dataclasses import dataclass

from .people import looks_like_followup


@dataclass(frozen=True)
class WakeSettings:
    aliases: tuple[str, ...] = ("tilo", "tillo", "tylo", "teelo")
    attention_s: float = 30

    def __post_init__(self) -> None:
        if not math.isfinite(self.attention_s) or not 0 < self.attention_s <= 300:
            raise ValueError("invalid_attention_window")
        if not self.aliases or any(not re.fullmatch(r"[a-z]+", alias) for alias in self.aliases):
            raise ValueError("invalid_wake_aliases")


@dataclass(frozen=True)
class Attention:
    speaker: str = ""
    at: float = -math.inf


@dataclass(frozen=True)
class WakeResult:
    allowed: bool
    attention: Attention


def wake_gate(
    text: str, speaker: str, now: float, attention: Attention, settings: WakeSettings, *, typed_to_bot: bool = False
) -> WakeResult:
    if not text.strip() or not math.isfinite(now) or now < 0:
        return WakeResult(False, attention)
    named = False
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        words = re.findall(r"[a-z']+", sentence.lower())
        while words and words[0] in ("hey", "hi", "hello", "ok", "okay", "so"):
            words.pop(0)
        named |= bool(words and (words[0] in settings.aliases or words[-1] in settings.aliases))
    same_speaker = bool(speaker and speaker != "?" and speaker == attention.speaker)
    following = same_speaker and 0 < now - attention.at <= settings.attention_s and looks_like_followup(text)
    allowed = typed_to_bot or named or following
    return WakeResult(allowed, Attention(speaker, now) if allowed else attention)
