"""Pure helpers for names and who has to be present. No browser."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from . import selectors as S

_NAME_JUNK = re.compile(r"devices|Mute |more_vert|More actions|Meeting host|Contributors|\(You\)|Admit|Deny")


def clean_name(text: str) -> str:
    """Participant rows come back with icon/button text glued on ("John RegidevicesMute ..."): keep the name."""
    t = _NAME_JUNK.split(text)[0].strip()
    return "" if t.lower() in S.PARTICIPANT_NOISE else t


def name_match(wanted: str, actual: str) -> bool:
    w, a = wanted.strip().lower(), actual.strip().lower()
    return bool(w) and (w in a or a in w)


def missing_required(required: list[str], present: list[str]) -> list[str]:
    """Required names with nobody matching them in `present`."""
    return [r for r in required if not any(name_match(r, p) for p in present)]


def gate_open(required: list[str], present: list[str]) -> bool:
    """The meeting 'starts' (bot may speak, clock starts) when every required person is here,
    or, if nobody is required, when at least one other person is."""
    if required:
        return not missing_required(required, present)
    return bool(present)


_ASSISTANT_WORDS = {"assistant", "bot", "notetaker"}


def addressed(text: str, bot_name: str) -> bool:
    """True if `text` is a question that seems aimed at the assistant.

    Live captions mishear unusual names ("Tilo" -> "Tyler"), so match fuzzily: same first letter and similar spelling.
    A false positive only costs one model call; the model makes the final call on whether to answer.
    """
    if "?" not in text or not bot_name:
        return False
    target = bot_name.lower()
    words = re.findall(r"[a-z']+", text.lower())
    if target in words or _ASSISTANT_WORDS & set(words):
        return True
    for w in re.findall(r"([a-z']+),", text.lower()):  # vocative: "Tyler, what is..." (a misheard name)
        if 3 <= len(w) <= 8 and w[0] == target[0] and SequenceMatcher(None, w, target).ratio() >= 0.4:
            return True
    return False


def addressed_sentence(text: str, bot_name: str) -> str | None:
    """The first sentence of `text` that is a question aimed at the assistant, or None."""
    for sent in re.split(r"(?<=[.?!])\s+", text):
        if addressed(sent, bot_name):
            return sent.strip()
    return None


def question_of(text: str, bot_name: str, mode: str = "questions") -> str | None:
    """The question in `text` the assistant should consider answering.

    mode "addressed": only sentences aimed at the assistant (name, misheard name, "assistant"/"bot").
    mode "questions": also any other question (captions often garble the name, and a follow-up like "what action
    items do we have?" carries no name). The model then answers only what the meeting information can answer.
    """
    sent = addressed_sentence(text, bot_name)
    if sent or mode != "questions":
        return sent
    questions = [x.strip() for x in re.split(r"(?<=[.?!])\s+", text) if x.strip().endswith("?") and len(x.split()) >= 3]
    return questions[-1] if questions else None
