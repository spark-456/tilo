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
NAME_ALIASES = {"tilo": ("tillo", "tylo", "teelo")}  # common mishearings of the default name
_GREETINGS = {"hey", "hi", "hello", "ok", "okay", "so", "and", "yo", "well", "right", "alright"}
_FOLLOWUP_LEADS = {
    "tell", "give", "remind", "summarise", "summarize", "repeat", "explain", "show", "say", "go", "continue",
    "and", "what", "why", "how", "who", "when", "where", "which", "can", "could", "would", "should",
    "do", "does", "did", "is", "are", "was", "will", "more",
}  # fmt: skip


def _names(bot_name: str) -> set[str]:
    return {bot_name.lower(), *NAME_ALIASES.get(bot_name.lower(), ())} if bot_name else set()


def _words_after_greeting(sentence: str) -> list[str]:
    words = re.findall(r"[a-z']+", sentence.lower())
    while words and words[0] in _GREETINGS:
        words = words[1:]
    return words


def named_request(sentence: str, bot_name: str) -> bool:
    """Spoken to the assistant by name, question mark or not: the name opens the sentence (after "hey", "okay"...) or
    closes it. "I told Tilo about it" is talk about the assistant, not to it."""
    words, names = _words_after_greeting(sentence), _names(bot_name)
    return bool(words and names and (words[0] in names or words[-1] in names))


def looks_like_followup(text: str) -> bool:
    """A question or request, for the moments right after the assistant spoke when people answer it without its name."""
    words = re.findall(r"[a-z']+", text.lower())
    return bool(words) and (text.rstrip().endswith("?") or (len(words) >= 2 and words[0] in _FOLLOWUP_LEADS))


def addressed(text: str, bot_name: str) -> bool:
    """True if `text` is a question that seems aimed at the assistant.

    Live captions mishear unusual names ("Tilo" -> "Tyler"), so match fuzzily: same first letter and similar spelling.
    A false positive only costs one model call; the model makes the final call on whether to answer.
    """
    if "?" not in text or not bot_name:
        return False
    target = bot_name.lower()
    words = re.findall(r"[a-z']+", text.lower())
    if _names(bot_name) & set(words) or _ASSISTANT_WORDS & set(words):
        return True
    for w in re.findall(r"([a-z']+),", text.lower()):  # vocative: "Tyler, what is..." (a misheard name)
        if 3 <= len(w) <= 8 and w[0] == target[0] and SequenceMatcher(None, w, target).ratio() >= 0.4:
            return True
    return False


def addressed_sentence(text: str, bot_name: str) -> str | None:
    """The first sentence of `text` aimed at the assistant (a question to it, or any sentence that calls it by name)."""
    sents = re.split(r"(?<=[.?!])\s+", text)
    for i, sent in enumerate(sents):
        if addressed(sent, bot_name):
            return sent.strip()
        if named_request(sent, bot_name):
            if len(_words_after_greeting(sent)) == 1 and i + 1 < len(sents):  # "Hey Tilo. Tell me a joke."
                return " ".join(sents[i:]).strip()
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
