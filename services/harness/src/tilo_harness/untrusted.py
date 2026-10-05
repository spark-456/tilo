"""Untrusted text on its way into a prompt template (PRD 16.3 item 1).

Templates fence untrusted data in `<<<NAME ... NAME>>>` blocks. `neutralise` makes sure no text can open,
close or forge a block, whatever the block's name:

- only the first `limit` characters are kept, before anything else looks at the text;
- the text is NFKC-normalised, so no full-width or small-form look-alike of `<` or `>` survives;
- format characters (soft hyphen, zero-width, bidi and tag characters), control characters except newline
  and tab, surrogates and private-use characters are removed;
- `<` and `>` become single angle quotes, so no template marker can be spelled in the result.

NFKC cost stays linear (`nfkc`, UAX #15 stream-safe format): canonical reordering is quadratic on a long run
of non-starters in the DECOMPOSED text, and a character can decompose into non-starters without being one
(U+0F73, U+FF9E), or expand 18 times (U+FDFA). So run length and decomposed length are counted per character
from its NFKD (`_profile`, cached) in one pass; a character that would make a run longer than `MAX_MARK_RUN`
is dropped, and the text is cut before the character that would take its decomposed length past `limit`.
`has_long_mark_run` uses the same count, so a caller can refuse such text before it normalises anything, and
an optional `Budget` bounds the characters normalised across many calls.
"""

from __future__ import annotations

import functools
import unicodedata

_ANGLES = str.maketrans({"<": "‹", ">": "›"})
_DROP = {"Cf", "Cc", "Cs", "Co", "Cn"}
_KEEP = {"\n", "\t"}
_LINE_BREAKS = {"Zl", "Zp"}
MAX_MARK_RUN = 30


class BudgetSpent(Exception):
    """More characters would be normalised than the caller's `Budget` allows."""


class Budget:
    """Characters (decomposed) that `nfkc` may still normalise, shared by the calls of one review."""

    def __init__(self, chars: int) -> None:
        self.left = chars

    def spend(self, chars: int) -> None:
        if chars > self.left:
            self.left = 0
            raise BudgetSpent(f"{chars} characters past the budget")
        self.left -= chars


@functools.lru_cache(maxsize=4096)
def _profile(char: str) -> tuple[int, int, int]:
    """(leading non-starters, trailing non-starters, length) of the character's NFKD. All non-starters iff
    leading == length. Cached and bounded, so a scan stays linear."""
    marks = [unicodedata.combining(c) != 0 for c in unicodedata.normalize("NFKD", char)]
    lead = next((i for i, mark in enumerate(marks) if not mark), len(marks))
    trail = next((i for i, mark in enumerate(reversed(marks)) if not mark), len(marks))
    return lead, trail, len(marks)


def _step(run: int, char: str) -> tuple[int, int, bool]:
    """(run after `char`, decomposed length of `char`, whether `char` would make a run over MAX_MARK_RUN)."""
    if char < "\x80":
        return 0, 1, False
    lead, trail, size = _profile(char)
    if lead == size:
        return run + size, size, run + size > MAX_MARK_RUN
    return trail, size, run + lead > MAX_MARK_RUN


def has_long_mark_run(text: str) -> bool:
    """True if the NFKD of `text` holds more than MAX_MARK_RUN non-starters in a row (linear)."""
    run = 0
    for char in text:
        run, _, over = _step(run, char)
        if over:
            return True
    return False


def _stream_safe(text: str, limit: int) -> tuple[str, int]:
    """(text, its decomposed length): every character that would make a run over MAX_MARK_RUN dropped, and
    cut before the character that would take the decomposed length past `limit`."""
    if text.isascii():
        return text[:limit], min(len(text), limit)
    out, run, size = [], 0, 0
    for char in text:
        after, grows, over = _step(run, char)
        if over:
            continue
        if size + grows > limit:
            break
        out.append(char)
        run, size = after, size + grows
    return "".join(out), size


def nfkc(text: str, *, limit: int, budget: Budget | None = None) -> str:
    """NFKC of the first `limit` characters of `text`, in linear time; at most `limit` characters come out."""
    safe, size = _stream_safe(text[:limit], limit)
    if budget is not None:
        budget.spend(size)
    return unicodedata.normalize("NFKC", safe)


def _clean(text: str) -> str:
    out = []
    for char in text:
        category = unicodedata.category(char)
        if char in _KEEP:
            out.append(char)
        elif category in _LINE_BREAKS:
            out.append("\n")
        elif category not in _DROP:
            out.append(char)
    return "".join(out)


def neutralise(text: str, *, limit: int, budget: Budget | None = None) -> str:
    # Twice: removing a character can bring two others together, and the second pass normalises them.
    # Each pass is capped and stream-safe, so the second never sees more than `limit` characters.
    once = _clean(nfkc(text, limit=limit, budget=budget))
    return _clean(nfkc(once, limit=limit, budget=budget)).translate(_ANGLES)
