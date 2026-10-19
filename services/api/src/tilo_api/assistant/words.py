"""Word rules over the signed-in person's own question (API_PPL_11b.md section 3). The matcher reads only the
question against the fixed lists of `config/assistant.yaml`; it looks nothing up."""

from __future__ import annotations

import re
import unicodedata

from tilo_people.text import clean_line

from tilo_api.assistant.config import AssistantConfig

_TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_QUOTES = {0x2018: "'", 0x2019: "'", 0x02BC: "'"}
MAX_KEY = 2000


def question_key(text: str) -> str:
    """NFKC, `clean_line`, curly apostrophes to ', casefold, whitespace collapsed, cut to 2000 characters."""
    folded = clean_line(unicodedata.normalize("NFKC", text)).translate(_QUOTES).casefold()
    return " ".join(folded.split())[:MAX_KEY]


def tokens(key: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(key))


def _stem(token: str) -> str:
    return token.split("'", 1)[0]


def words(key: str, config: AssistantConfig) -> tuple[str, ...]:
    """The tokens cut at their apostrophe, with the leading fillers dropped."""
    stems = [_stem(t) for t in tokens(key)]
    fillers = config.words["fillers"]
    start = 0
    while start < len(stems) and stems[start] in fillers:
        start += 1
    return tuple(stems[start:])


def about_someone_else(key: str, config: AssistantConfig) -> bool:
    """A possessive of a word outside `self_possessives`, or a third-person word."""
    own, other = config.words["self_possessives"], config.words["third_person"]
    for token in tokens(key):
        stem = _stem(token)
        if stem in other or (token.endswith("'s") and stem not in own):
            return True
    return False
