"""Untrusted text on its way into a prompt template (PRD 16.3 item 1).

Templates fence untrusted data in `<<<NAME ... NAME>>>` blocks. `neutralise` makes sure no text can open,
close or forge a block, whatever the block's name:

- only the first `limit` characters are kept (NFKC is quadratic on characters that expand, such as U+FDFA),
  and the result is capped to `limit` again after normalising;
- the text is NFKC-normalised, so no full-width or small-form look-alike of `<` or `>` survives;
- format characters (soft hyphen, zero-width, bidi and tag characters), control characters except newline
  and tab, surrogates and private-use characters are removed;
- `<` and `>` become single angle quotes, so no template marker can be spelled in the result.
"""

from __future__ import annotations

import unicodedata

_ANGLES = str.maketrans({"<": "‹", ">": "›"})
_DROP = {"Cf", "Cc", "Cs", "Co", "Cn"}
_KEEP = {"\n", "\t"}
_LINE_BREAKS = {"Zl", "Zp"}


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
    return _clean(_clean(text[:limit])).translate(_ANGLES)[:limit]
