"""FR-MTG-15: pure addressing and attention; no I/O or model.

Owner decision 21 Oct: Meet captions mishear the name, so the gate is generous about being called (closed aliases,
two-word splits such as "tea low", a close first-word match, and "assistant," / "notetaker," said to the bot), and a
question asked right after Tilo spoke is a follow-up from anyone. Ordinary speech that merely mentions Tilo still
does not reach a model in a group call; one-on-one calls are decided by the brain (`Brain.question_in`)."""

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .people import looks_like_followup

_GREETINGS = ("hey", "hi", "hello", "ok", "okay", "so")
# Words a caption might produce that look like the name but are ordinary speech.
_NEAR_MISSES = frozenset(
    {
        "tile",
        "tiles",
        "till",
        "tell",
        "tall",
        "toll",
        "tilt",
        "told",
        "tyler",
        "silo",
        "kilo",
        "halo",
        "hello",
        "polo",
        "solo",
        "tilly",
        "tidal",
        "title",
        "toilet",
        "teal",
        "tilde",
        "tiller",
    }
)
# Said straight to the bot ("Assistant, what is due?", "hey notetaker ..."), never "Assistant manager said".
_ROLE_CALL = re.compile(
    r"^\s*(?:(?:hey|hi|hello|ok|okay)[\s,]+(?:assistant|notetaker|note taker|bot)\b"
    r"|(?:assistant|notetaker|note taker|bot)\s*[,:!?])",
    re.I,
)


@dataclass(frozen=True)
class WakeSettings:
    aliases: tuple[str, ...] = (
        "tilo",
        "tillo",
        "tylo",
        "teelo",
        "tilow",
        "tealo",
        "theelo",
        "deelo",
        "teelow",
        "tealow",
        "tlow",
        "chilo",
    )
    attention_s: float = 30
    after_reply_s: float = 15  # a question this soon after Tilo spoke is for Tilo, whoever asks it

    def __post_init__(self) -> None:
        if not math.isfinite(self.attention_s) or not 0 < self.attention_s <= 300:
            raise ValueError("invalid_attention_window")
        if not math.isfinite(self.after_reply_s) or not 0 <= self.after_reply_s <= 120:
            raise ValueError("invalid_after_reply_window")
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


def _close_to_alias(word: str, aliases: tuple[str, ...]) -> bool:
    if len(word) < 4 or word in _NEAR_MISSES:
        return False
    return any(SequenceMatcher(None, word, alias).ratio() >= 0.8 for alias in aliases)


def calls_tilo(text: str, settings: "WakeSettings") -> bool:
    """True when a sentence opens (or ends) by calling Tilo, allowing for caption mishearings."""
    for sentence in re.split(r"(?<=[.?!])\s+", text):
        if _ROLE_CALL.match(sentence):
            return True
        words = re.findall(r"[a-z']+", sentence.lower())
        while words and words[0] in _GREETINGS:
            words.pop(0)
        if not words:
            continue
        if words[0] in settings.aliases or words[-1] in settings.aliases:
            return True
        if len(words) > 1 and words[0] + words[1] in settings.aliases:  # "tea low", "t low"
            return True
        if _close_to_alias(words[0], settings.aliases):
            return True
    return False


def wake_gate(
    text: str,
    speaker: str,
    now: float,
    attention: Attention,
    settings: WakeSettings,
    *,
    typed_to_bot: bool = False,
    bot_spoke_at: float = -math.inf,
) -> WakeResult:
    if not text.strip() or not math.isfinite(now) or now < 0:
        return WakeResult(False, attention)
    named = calls_tilo(text, settings)
    same_speaker = bool(speaker and speaker != "?" and speaker == attention.speaker)
    following = same_speaker and 0 < now - attention.at <= settings.attention_s and looks_like_followup(text)
    asks = text.rstrip().endswith("?") or looks_like_followup(text)
    after_reply = math.isfinite(bot_spoke_at) and 0 < now - bot_spoke_at <= settings.after_reply_s and asks
    allowed = typed_to_bot or named or following or after_reply
    return WakeResult(allowed, Attention(speaker, now) if allowed else attention)
