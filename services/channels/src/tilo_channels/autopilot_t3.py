"""tilo_channels.autopilot_t3: the deterministic money / legal / commitment signal that keeps a draft off the L2 undo
window (FR-CHN-11; PRD 10.4 T3 "money, contract or legal terms"; issue #243; BQ-153).

It never depends on the drafting checker's `ready`. The text is cleaned (line breaks as "\\n", other format and
control characters removed), NFKC-normalised and lower-cased, then matched against fixed word families. It fails
closed with "obfuscated": on a format, control (newline, tab and CR aside) or line-separator character in the raw text,
on any non-ASCII character after NFKC that is not punctuation, a space or a currency sign (a look-alike letter, a
combining mark, a foreign digit, an emoji), and on text over SIGNAL_CAP. An accented name therefore also makes a
draft T3: a safe false positive. Callers pass the raw body, so a hidden character the preview drops is itself T3.

BQ-186 (issue #256): the families also run on a squeezed copy (separators `- . _ *` and line breaks between letters or
digits dropped, 0 o, 1 i, 3 e, 4 a, 5 s, 7 t, @ a), and L2 is an allowlist: a body over SHORT_BODY_MAX, a link, a digit
that is not a time of day, or a word off the scheduling list gives "unlisted". Every step is linear, no model.
"""

from __future__ import annotations

import re
import unicodedata

SIGNAL_CAP = 20_000  # the drafting checker's CHECK_CAP: a longer body is not read, it is T3

_MONEY = re.compile(
    r"\b(?:refund\w*|invoic\w*|pay|pays|paid|payment\w*|payable|wire[sd]?|wiring|bank\w*|iban|swift|deposit\w*"
    r"|pric\w*|cost\w*|fees?|charg\w*|discount\w*|quot(?:e|es|ed|ation)|estimat\w*|rates?|money|cash|billing"
    r"|budget\w*|dollars?|euros?|pounds?|rupees?|usd|eur|gbp|inr|sgd|aud|cad|jpy|chf"
    r"|transfer\w*|account\s+numbers?|sort\s+codes?|paypal|venmo|zelle|btc|bitcoin|owe[sd]?|owing|loans?|penalt\w*"
    r"|bucks?|grand|quid|rs|rm|\d+k)\b"  # BQ-186 (b)
)
_LEGAL = re.compile(
    r"\b(?:contract\w*|liab\w*|lawsuits?|sue[sd]?|suing|legal\w*|lawyers?|attorneys?|courts?|nda|non-disclosure"
    r"|terms|waiver\w*|waive[sd]?|indemn\w*|agreement\w*|clauses?|settlement\w*|breach\w*|warrant\w*"
    r"|agree\w*|accept\w*|authori[sz]\w*|sign|signs|signed|signing|signature\w*|solicitors?|gdpr)\b"
)
_COMMITMENT = re.compile(
    r"\b(?:we|i)\s+(?:will|shall)\b|\b(?:we|i)['’]ll\b"
    r"|\b(?:guarant\w*|promis\w*|commit\w*|deadlines?|assur\w*|pledg\w*|hereby|deals?)\b"
    r"|\b(?:consider\s+it\s+(?:done|settled|sorted)|my\s+word|count\s+on\s+(?:me|us)|rest\s+assured"
    r"|leave\s+it\s+(?:with|to)\s+(?:me|us)|you\s+can\s+rely|(?:we|i)\s+(?:am|are|['’]m|['’]re)\s+going\s+to)\b"
)
_FAMILIES = (("money", _MONEY), ("legal", _LEGAL), ("commitment", _COMMITMENT))
# BQ-186 (c): a separator or line break between two letters or digits is dropped, then digit look-alikes mapped back.
_SPLIT = re.compile(r"(?<=[a-z0-9])[-._*\n]+(?=[a-z0-9])")
_LEET = str.maketrans("013457@", "oieasta")
# BQ-186 (a): L2 auto-send is an allowlist. A time of day is the only digit shape that passes; a link, any other digit
# or any word off the list is the signal "unlisted".
SHORT_BODY_MAX = 2_000
_TIME = re.compile(r"\b(?:(?:1[0-2]|0?[1-9])(?::[0-5][0-9])?\s?(?:am|pm)|(?:[01]?[0-9]|2[0-3]):[0-5][0-9])\b", re.I)
_LINK = re.compile(r"://|[/@\\]|[a-z]\.[a-z]")
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
_NAME_LEADS = frozenset("hi hello hey dear thanks thank best regards cheers sincerely".split())
_WORDS = frozenset(
    (
        "hi hello hey dear good morning afternoon evening night thanks thank you your yours very much so again for "
        "the a an and it its is that this we us our i me my to be at on in by with from of or but then there here see "
        "talk "
        "soon next last week weekend month year tomorrow today tonight monday tuesday wednesday thursday friday "
        "saturday sunday jan feb mar apr may jun jul aug sep oct nov dec january february march april june july "
        "august september october november december works work fine great sounds sound happy glad meet meeting call "
        "chat catch up time day date confirmed confirm let know looks look forward best regards cheers kind sincerely "
        "warm wishes ok okay yes sure please can could would should will does do not no all also too just well back "
        "out have has had are was were am what when where who how if any some more both free available around about "
        "after before late early noon lunch coffee hope perfect lovely nice enjoy safe travels office room slot "
        "same sorry i'm it's that's don't doesn't can't let's you're we're we've i've you've isn't won't"
    ).split()
)
_BREAKS = re.compile("\r\n|[\r\x0b\x0c\x1c\x1d\x1e\x85  ]")


def clean_text(text: str) -> str:
    """`text` with every line break (CRLF, a lone CR as the MIME text encoder sends it, and the others
    `str.splitlines` breaks on) as "\\n", then without Unicode format (Cf) characters and control (Cc) characters other
    than newline and tab. A break between two words never joins them."""
    text = _BREAKS.sub("\n", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


def _hidden(c: str) -> bool:
    kind = unicodedata.category(c)
    return kind in ("Cf", "Zl", "Zp") or (kind == "Cc" and c not in "\n\t\r")


def _suspicious(c: str) -> bool:
    kind = unicodedata.category(c)
    return not c.isascii() and kind[0] not in "PZ" and kind != "Sc"


def _unlisted(cleaned: str) -> bool:
    """True when the body is not plain scheduling talk: too long, a link, a digit that is not a time of day, or a word
    that is neither on the list nor a name straight after a greeting or sign-off. One pass, no backtracking."""
    if len(cleaned) > SHORT_BODY_MAX:
        return True
    cleaned = _TIME.sub(" ", cleaned)
    if _LINK.search(cleaned.lower()) or any(c.isdigit() for c in cleaned):
        return True
    names_ok = False  # the last word was a greeting, a sign-off or a name ("and" keeps it)
    for token in _TOKEN.findall(cleaned.replace("’", "'")):
        word = token.lower()
        name = names_ok and word not in _WORDS and token.istitle()
        if word not in _WORDS and not name:
            return True
        names_ok = word in _NAME_LEADS or name or (names_ok and word == "and")
    return False


def t3_content_signal(text: str) -> frozenset[str]:
    """Subset of {"money", "legal", "commitment", "obfuscated", "unlisted"}; empty means no signal."""
    if len(text) > SIGNAL_CAP:
        return frozenset({"obfuscated"})
    signal = {"obfuscated"} if any(_hidden(c) for c in text) else set()
    cleaned = unicodedata.normalize("NFKC", clean_text(text))
    folded = cleaned.lower()
    if any(_suspicious(c) for c in folded):
        signal.add("obfuscated")
    if any(unicodedata.category(c) == "Sc" for c in folded):
        signal.add("money")
    squeezed = _SPLIT.sub("", folded).translate(_LEET)
    for name, pattern in _FAMILIES:
        if pattern.search(folded) or pattern.search(squeezed):
            signal.add(name)
    if _unlisted(cleaned):
        signal.add("unlisted")
    return frozenset(signal)
