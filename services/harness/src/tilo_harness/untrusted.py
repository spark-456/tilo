"""Untrusted text on its way into a prompt template (PRD 16.3 item 1).

Templates fence untrusted data in `<<<NAME ... NAME>>>` blocks. `neutralise` makes sure no text can open,
close or forge a block, whatever the block's name:

- only the first `limit` characters are kept (NFKC is quadratic on characters that expand, such as U+FDFA),
  and the result is capped to `limit` again after normalising;
- the text is NFKC-normalised, so no full-width or small-form look-alike of `<` or `>` survives;
- format characters (soft hyphen, zero-width, bidi and tag characters), control characters except newline
  and tab, surrogates and private-use characters are removed;
- `<` and `>` become single angle quotes, so no template marker can be spelled in the result;
- NFKC is quadratic on a long run of combining marks (U+0F73 and the like, UAX #15 stream-safe
  limit 30), so `has_long_mark_run` lets a caller refuse such text before it normalises anything,
  and `neutralise` cuts every run to `MAX_MARK_RUN` characters before each NFKC pass.
"""

from __future__ import annotations

import unicodedata

_ANGLES = str.maketrans({"<": "‹", ">": "›"})
_DROP = {"Cf", "Cc", "Cs", "Co", "Cn"}
_KEEP = {"\n", "\t"}
_LINE_BREAKS = {"Zl", "Zp"}
MAX_MARK_RUN = 30


def _is_mark(char: str) -> bool:
    return unicodedata.category(char) in ("Mn", "Mc", "Me") or unicodedata.combining(char) != 0


def has_long_mark_run(text: str) -> bool:
    """True if `text` holds more than MAX_MARK_RUN combining characters in a row (linear)."""
    run = 0
    for char in text:
        run = run + 1 if _is_mark(char) else 0
        if run > MAX_MARK_RUN:
            return True
    return False


def _limit_runs(text: str) -> str:
    out, run = [], 0
    for char in text:
        run = run + 1 if _is_mark(char) else 0
        if run <= MAX_MARK_RUN:
            out.append(char)
    return "".join(out)


def _clean(text: str) -> str:
    out = []
    for char in unicodedata.normalize("NFKC", text):
        category = unicodedata.category(char)
        if char in _KEEP:
            out.append(char)
        elif category in _LINE_BREAKS:
            out.append("\n")
        elif category not in _DROP:
            out.append(char)
    return "".join(out)


def neutralise(text: str, *, limit: int) -> str:
    # Twice: removing a character can bring two others together, and the second pass normalises them.
    # Runs are cut before each pass, so each NFKC sees only short runs and the cost stays linear.
    once = _clean(_limit_runs(text[:limit]))
    return _clean(_limit_runs(once)).translate(_ANGLES)[:limit]
