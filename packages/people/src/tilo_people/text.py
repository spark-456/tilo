"""Text hygiene for people records (PE-24)."""

from __future__ import annotations

import unicodedata

_STRIPPED = frozenset({"Cc", "Cf", "Zl", "Zp"})


def clean_line(text: str) -> str:
    """Removes every character whose `unicodedata.category` is Cc, Cf, Zl or Zp: controls, format
    characters (bidi overrides, zero-width characters, astral tag characters U+E0000..U+E007F), line and
    paragraph separators. Nothing else changes."""
    return "".join(c for c in text if unicodedata.category(c) not in _STRIPPED)
