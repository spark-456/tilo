"""tilo_channels.autopilot_t3: the deterministic money / legal / commitment signal that keeps a draft off the L2 undo
window (FR-CHN-11; PRD 10.4 T3 "money, contract or legal terms"; issue #243; BQ-153).

It never depends on the drafting checker's `ready`. The text is cleaned (format and control characters removed),
NFKC-normalised and lower-cased, then matched against fixed word families. It fails closed with "obfuscated": on a
format or control character in the raw text (newline, tab and carriage return aside), on any non-ASCII character
after NFKC that is not punctuation, a space or a currency sign (a look-alike letter, a combining mark, a foreign
digit, an emoji), and on text over SIGNAL_CAP. An accented name therefore also makes a draft T3: a safe false
positive. Callers pass the raw body, so a hidden character the cleaned preview would not show is itself T3.
"""

from __future__ import annotations

import re
import unicodedata

SIGNAL_CAP = 20_000  # the drafting checker's CHECK_CAP: a longer body is not read, it is T3

_MONEY = re.compile(
    r"\b(?:refund\w*|invoic\w*|pay|pays|paid|payment\w*|payable|wire[sd]?|wiring|bank\w*|iban|swift|deposit\w*"
    r"|pric\w*|cost\w*|fees?|charg\w*|discount\w*|quot(?:e|es|ed|ation)|estimat\w*|rates?|money|cash|billing"
    r"|budget\w*|dollars?|euros?|pounds?|rupees?|usd|eur|gbp|inr|sgd|aud|cad|jpy|chf)\b"
)
_LEGAL = re.compile(
    r"\b(?:contract\w*|liab\w*|lawsuits?|sue[sd]?|suing|legal\w*|lawyers?|attorneys?|courts?|nda|non-disclosure"
    r"|terms|waiver\w*|waive[sd]?|indemn\w*|agreement\w*|clauses?|settlement\w*|breach\w*|warrant\w*)\b"
)
_COMMITMENT = re.compile(
    r"\b(?:we|i)\s+(?:will|shall)\b|\b(?:we|i)['’]ll\b"
    r"|\b(?:guarant\w*|promis\w*|commit\w*|deadlines?|assur\w*|pledg\w*)\b"
)
_FAMILIES = (("money", _MONEY), ("legal", _LEGAL), ("commitment", _COMMITMENT))


def clean_text(text: str) -> str:
    """`text` without Unicode format (Cf) characters and without control (Cc) characters other than newline and tab."""
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def _hidden(c: str) -> bool:
    kind = unicodedata.category(c)
    return kind == "Cf" or (kind == "Cc" and c not in "\n\t\r")


def _suspicious(c: str) -> bool:
    kind = unicodedata.category(c)
    return not c.isascii() and kind[0] not in "PZ" and kind != "Sc"


def t3_content_signal(text: str) -> frozenset[str]:
    """Subset of {"money", "legal", "commitment", "obfuscated"}; empty means no signal."""
    if len(text) > SIGNAL_CAP:
        return frozenset({"obfuscated"})
    signal = {"obfuscated"} if any(_hidden(c) for c in text) else set()
    folded = unicodedata.normalize("NFKC", clean_text(text)).lower()
    if any(_suspicious(c) for c in folded):
        signal.add("obfuscated")
    if any(unicodedata.category(c) == "Sc" for c in folded):
        signal.add("money")
    signal.update(name for name, pattern in _FAMILIES if pattern.search(folded))
    return frozenset(signal)
