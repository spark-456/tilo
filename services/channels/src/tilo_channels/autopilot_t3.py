"""tilo_channels.autopilot_t3: the deterministic money / legal / commitment signal that keeps a draft off the L2 undo
window (FR-CHN-11; PRD 10.4 T3 "money, contract or legal terms"; issue #243; BQ-153).

It never depends on the drafting checker's `ready`. The text is cleaned (line breaks as "\\n", other format and
control characters removed), NFKC-normalised and lower-cased, then matched against fixed word families. It fails
closed with "obfuscated": on a format, control (newline, tab and CR aside) or line-separator character in the raw text,
on any non-ASCII character after NFKC that is not punctuation, a space or a currency sign (a look-alike letter, a
combining mark, a foreign digit, an emoji), and on text over SIGNAL_CAP. An accented name therefore also makes a
draft T3: a safe false positive. Callers pass the raw body, so a hidden character the preview drops is itself T3.

BQ-224 (issue #256): the families also run on a squeezed copy (separators `- . _ *` and line breaks between letters or
digits dropped, 0 o, 1 i, 3 e, 4 a, 5 s, 7 t, @ a), and L2 is an allowlist: a body over SHORT_BODY_MAX, a link, a digit
that is not a time of day, or a word off the scheduling list gives "unlisted". Every step is linear, no model.

CHN-GATE-E (FR-CHN-11, ADR-0025): a name is a word in `names`, the names of the draft's own To and Cc and of the mailbox
that `participants.read_participants` vouches for from the thread (no names, the default, fails closed). It may stand
anywhere; a row of name words is at most two long and every join of the row runs through the families. The position
rules of PR #525 (greeting and signature runs, clause openers, Title case) and the number-word checks on the body are
retired: an amount or number word is never in `names` (the name filter keeps them out) so it stays "unlisted".

BQ-274 (issue #298): `inbound_signal` is the same check for the message a draft answers, minus the allowlist, plus
what an inbound message may hide: an amount, a magnitude suffix ("5m", "50 K") or a number word is "money" with no
money word around it, and punctuation inside a word (any run of non-letter, non-digit characters, a tab or line break
included, between two letters or digits) is dropped and single letters spread apart are joined, in both orders, before
the families run. A risky inbound message ("please confirm the transfer of $5,000") keeps even a clean draft ("Yes,
confirmed.") off L2. A draft's own `t3_content_signal` does not get these two: the allowlist already holds it.

BQ-274 redesign (security round 3): a denylist cannot list every obfuscation, so `inbound_plain` adds an allowlist for
the replied-to body and Subject: only ASCII letters, spaces, newlines, stop marks before a space, contractions and times
of day are plain. Punctuation, underscore, glue and digit-suffix classes are closed by construction. L2 needs both
`not inbound_signal` and `inbound_plain`; real mail with a link, a quoted line, a hyphen, a digit or a non-ASCII
character waits for a person.

BQ-274 round 4: `inbound_plain` reads the raw text (no NFKC), `inbound_signal` also checks every join of pieces cut by
line breaks or marks as a whole word, and a time of day between single letters keeps their run going.

BQ-278 (i)-(m): the piece-join check is `_join_hits`. A space next to a line break and a time of day are piece cuts
too ("the \\ntrans \\nfer", "trans 5pm fer"); a phrase family cut inside a word ("account\\nnum\\nber") is matched
piece by piece (`_PHRASES`); the joined length is capped at 2,000 characters (over it fails closed as "obfuscated")
and the scan stops at the first hit. Plain-ASCII text skips the per-character Unicode checks.
"""

from __future__ import annotations

import itertools
import re
import unicodedata
from collections.abc import Iterable

SIGNAL_CAP = 20_000  # the drafting checker's CHECK_CAP: a longer body is not read, it is T3

_MONEY = re.compile(
    r"\b(?:refund\w*|invoic\w*|pay|pays|paid|payment\w*|payable|wire[sd]?|wiring|bank\w*|iban|swift|deposit\w*"
    r"|pric\w*|cost\w*|fees?|charg\w*|discount\w*|quot(?:e|es|ed|ation)|estimat\w*|rates?|money|cash|billing"
    r"|budget\w*|dollars?|euros?|pounds?|rupees?|usd|eur|gbp|inr|sgd|aud|cad|jpy|chf"
    r"|transfer\w*|account\s+numbers?|sort\s+codes?|paypal|venmo|zelle|btc|bitcoin|owe[sd]?|owing|loans?|penalt\w*"
    r"|bucks?|grand|quid|rs|rm|\d+k)\b"  # BQ-224 (b)
)
_LEGAL = re.compile(
    r"\b(?:contract\w*|liab\w*|lawsuits?|sue[sd]?|suing|legal\w*|lawyers?|attorneys?|courts?|nda|non-disclosure"
    r"|terms|waiver\w*|waive[sd]?|indemn\w*|agreement\w*|clauses?|settlement\w*|breach\w*|warrant\w*"
    r"|agree\w*|accept\w*|authori[sz]\w*|sign|signs|signed|signing|signature\w*|solicitors?|gdpr)\b"
)
_COMMITMENT = re.compile(
    r"\b(?:we|i)\s+(?:will|shall)\b|\b(?:we|i)['\u2019]ll\b"
    r"|\b(?:guarant\w*|promis\w*|commit\w*|deadlines?|assur\w*|pledg\w*|hereby|deals?)\b"
    r"|\b(?:yours|will\s+do|for\s+free|on\s+(?:us|me|it))\b"
    r"|\b(?:consider\s+it\s+(?:done|settled|sorted)|my\s+word|count\s+on\s+(?:me|us)|rest\s+assured"
    r"|leave\s+it\s+(?:with|to)\s+(?:me|us)|you\s+can\s+rely|(?:we|i)\s+(?:am|are|['\u2019]m|['\u2019]re)\s+going\s+to)\b"
)
_FAMILIES = (("money", _MONEY), ("legal", _LEGAL), ("commitment", _COMMITMENT))
# Inbound only: a joined spread run ("a w i r e" gives "awire") is searched without word edges, so a stray single
# letter before or after the word ("a", "I") cannot glue it to its neighbour. Money and legal only (commitment needs
# a space inside its phrases).
_INSIDE = tuple((n, re.compile(p.pattern.replace(r"\b", "").replace(r"\d+k", r"\dk"))) for n, p in _FAMILIES[:2])
# BQ-224 (c): a separator or line break between two letters or digits is dropped, then digit look-alikes mapped back.
_SPLIT = re.compile(r"(?<=[a-z0-9])[-._*\n]+(?=[a-z0-9])")
_LEET = str.maketrans("013457@", "oieasta")
# BQ-274 (inbound only): punctuation is a class, not a list. Any run of characters that are neither letters, digits nor
# a plain space (a tab and a line break count) between two letters or digits is dropped ("trans,fer"), and single
# letters or digits spread apart by spaces and/or any such run are joined ("w i r-e"). Each class is disjoint from the
# letters and digits it sits between, so both patterns are linear.
_DROP = re.compile(r"(?<=[a-z0-9])[^a-z0-9 ]+(?=[a-z0-9])")
_SPREAD = re.compile(r"(?<![a-z0-9])[a-z0-9](?:[^a-z0-9]+[a-z0-9](?![a-z0-9]))+(?![a-z0-9])")
# Round 4: pieces are cut by non-space runs (a line break, stop marks); each join of pieces is a word. BQ-278: a space
# next to a line break and a time of day are cuts too (`_prepare_cuts`).
_ANY_CUT = re.compile(r"[a-z0-9][^a-z0-9 ]+(?=[a-z0-9])")
_PIECE_GAP = re.compile(r"([a-z0-9]+)([^a-z0-9]*)")
_SPACE_AT_BREAK = re.compile(r"(?<! ) +(?=\n)|(?<=\n) +")  # linear: a match starts only at the start of a space run
_DIGIT_OR_PERCENT = re.compile(r"[\d%]")
_STEM_MAX = 10  # as long as the longest family stem ("settlement", "solicitors"): a join past it needs no more pieces
JOIN_CAP = 2_000  # BQ-278 (l): joined characters read; over it the text is not read in full and fails closed
_CHECK_EVERY = 256  # joined characters between two family checks (stop at the first hit)
# BQ-278 (k): the phrase families (those with `\s+` inside) as words, each word a set of spellings. A word may be cut
# into pieces by line breaks or marks; a word break is any whitespace-only gap or cut.
_Phrase = tuple[tuple[str, ...], ...]
_PHRASES: tuple[tuple[str, _Phrase], ...] = (
    ("money", (("account",), ("number", "numbers"))),
    ("money", (("sort",), ("code", "codes"))),
    ("commitment", (("we", "i"), ("will", "shall"))),
    ("commitment", (("we", "i"), ("ll",))),
    ("commitment", (("will",), ("do",))),
    ("commitment", (("for",), ("free",))),
    ("commitment", (("on",), ("us", "me", "it"))),
    ("commitment", (("consider",), ("it",), ("done", "settled", "sorted"))),
    ("commitment", (("my",), ("word",))),
    ("commitment", (("count",), ("on",), ("me", "us"))),
    ("commitment", (("rest",), ("assured",))),
    ("commitment", (("leave",), ("it",), ("with", "to"), ("me", "us"))),
    ("commitment", (("you",), ("can",), ("rely",))),
    ("commitment", (("we", "i"), ("am", "are", "m", "re"), ("going",), ("to",))),
)


def _phrase_index() -> tuple[dict[str, list[tuple[str, _Phrase]]], re.Pattern[str]]:
    """The phrases by every prefix of their first word's spellings (a start piece must be one), and one pattern for
    every spelling of every phrase with no gaps ("accountnumber"): no match in the pieces joined as one string, no
    phrase."""
    starts: dict[str, list[tuple[str, _Phrase]]] = {}
    for family, words in _PHRASES:
        for spelling in words[0]:
            for n in range(1, len(spelling) + 1):
                starts.setdefault(spelling[:n], []).append((family, words))
    flat = {"".join(spellings) for _, words in _PHRASES for spellings in itertools.product(*words)}
    return starts, re.compile("|".join(sorted(flat)))


_PHRASE_STARTS, _PHRASE_FLAT = _phrase_index()
# BQ-274: an amount with no money word. A decimal part or a thousands separator, a run of 3+ digits that is not a
# 2020-2039 year, a percent sign, a number word, or a number with a magnitude suffix ("5m", "50 K", "10L"). Times of
# day and small counts ("2 tarps", "dock 14", "2 kayaks") stay clean.
_NUMBER_WORD = re.compile(r"\b(?:hundred|thousand|million|billion|lakh|crore|lacs?|mil|mn|bn|cr)s?\b")
_AMOUNT = re.compile(r"\d[.,]\d|%|(?<!\d)\d+\s?(?:k|m|mn|b|bn|cr|l|lacs?)\b")
_DIGITS = re.compile(r"\d{3,}")
_YEAR = re.compile(r"\b20[23]\d\b")
# BQ-224 (a): L2 auto-send is an allowlist. A time of day is the only digit shape that passes; a link, any other digit
# or any word off the list is the signal "unlisted".
SHORT_BODY_MAX = 2_000
_TIME = re.compile(r"\b(?:(?:1[0-2]|0?[1-9])(?::[0-5][0-9])?\s?(?:am|pm)|(?:[01]?[0-9]|2[0-3]):[0-5][0-9])\b", re.I)
_LINK = re.compile(r"://|[/@\\]|[a-z0-9][.\u3002\uff61][a-z]")
_ITEM = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?|[^\sA-Za-z]")
_STOP = "\0"  # stands in for a time of day: not a letter or a digit, so it ends a name run
# BQ-274 `inbound_plain`: a time of day with a plain space only; a character off the list; a stop mark glued to what
# follows; an apostrophe inside a contraction; a word, or a time of day, as one token.
_PLAIN_TIME = re.compile(_TIME.pattern.replace(r"\s?", " ?"), re.I | re.A)
_OFF_LIST = re.compile(r"[^A-Za-z \n.,?!:'\0]")
_STOP_GLUED = re.compile(r"[.,?!:](?![ \n]|\Z)")
_CONTRACTION = re.compile(r"(?<=[A-Za-z])'(?:re|ve|ll|[stdm])(?![A-Za-z])")
_TOKEN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*|\0")
# Words that may come before the greeting's name run ("Hi", "Good morning", "Thank you"), and the only words a
# sign-off line ("Best,", "Kind regards,", "Many thanks!") may hold.
_GREETING = frozenset("hi hello hey dear good morning afternoon evening thanks thank you".split())
_SIGN_OFF = frozenset("best regards kind warm wishes cheers thanks thank you many sincerely all the".split())
# CHN-GATE-D: number words, used by `_numberish` (the participants' name filter, ADR-0025).
_NUMBER_WORDS = frozenset(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety dozen hundred hundreds thousand thousands "
    "million millions billion billions trillion lakh lakhs lac lacs crore crores mil mn bn cr".split()
)


def _alternation(words: Iterable[str]) -> str:
    return "(?:" + "|".join(sorted(words, key=len, reverse=True)) + ")"


# With apostrophes dropped a name word is never a name when (a) it is number words followed by at most one unit
# (k, m, b, l, s, ks, grand(s) or any word `_MONEY` matches, taken from `_MONEY` itself: "Fifty'Thousand", "Tenk",
# "Tenrm", "Tenfee"); (b) it starts with a number word of four or more letters ("Fiftyfoo"); or (c) it holds hundred,
# thousand, million, billion, trillion, lakh or crore anywhere. Three-letter number words (one, two, six, ten) and the
# abbreviations (mil, lac, cr) are caught only by (a), so Craig, Milan, Miles, Tenzin and Sixtine stay names. Accepted
# false positives: Fournier, Lakhani, Ninette, Sevenoaks, Crowe, Milbank and any long name over `_NAME_WORD_MAX`.
# Bounded scans, no model.
_NUMBER_ONLY = re.compile(
    _alternation(_NUMBER_WORDS)
    + "+(?:"
    + _alternation("k m b l s ks grand grands".split())
    + "|"
    + _MONEY.pattern.replace(r"\b", "")
    + ")?"
)
_NUMBER_START = re.compile(_alternation(w for w in _NUMBER_WORDS if len(w) >= 4))
_MAGNITUDE_INSIDE = re.compile(_alternation("hundred thousand million billion trillion lakh crore".split()))
# CHN-GATE-F (BQ-274, inbound only): the same word edges for a number word glued to a unit in free text ("Tenrm",
# "Fiftydollars", "Onemil", "Tenkk"). Base: the counting words that `_NUMBER_WORD` does not match whole (so "Milan",
# "Craig", "Miles", "milk" stay words); tail: a magnitude suffix (k, m, b, l, repeated, or ks), an abbreviation or
# magnitude `_NUMBER_WORD` knows, or any word `_MONEY` matches, both taken from those patterns. Between the counting
# words and the unit come zero or more of those abbreviations ("Fivelacrupees", "Tenmildollars"). The middle group is
# disjoint from the counting group (a group of all `_NUMBER_WORDS` is quadratic). A bare number word ("Fifty-fifty",
# "ones", "Tenant") is no amount. A magnitude inside any word counts ("Halfmillion"). Linear: one `\b` start per word,
# and a backtrack step costs a constant.
_ABBREVIATIONS = [w for w in _NUMBER_WORDS if _NUMBER_WORD.fullmatch(w)]
_GLUED = re.compile(
    r"\b"
    + _alternation(w for w in _NUMBER_WORDS if w not in _ABBREVIATIONS)
    + "+"
    + _alternation(_ABBREVIATIONS)
    + "*(?:ks|[kmbl]+|"
    + _NUMBER_WORD.pattern.replace(r"\b", "")
    + "|"
    + _MONEY.pattern.replace(r"\b", "")
    + r")\b"
)
_NAME_WORD_MAX = 24  # a longer word is no name: the check stays bounded (a 20k-character word is read no further)
_WORDS = frozenset(
    (
        "hi hello hey dear good morning afternoon evening night thanks thank you your very much so again for "
        "the a an and it its is that this we us our i me my to be at on in by with from of or but then there here see "
        "talk "
        "soon next last week weekend month year tomorrow today tonight monday tuesday wednesday thursday friday "
        "saturday sunday jan feb mar apr may jun jul aug sep oct nov dec january february march april june july "
        "august september october november december works work fine great sounds sound happy glad meet meeting call "
        "chat catch up time day date confirmed confirm let know looks look forward best regards cheers kind sincerely "
        "warm wishes ok okay yes sure please can could would not no all also too just well "
        "out are was were am what when where who how if any some more both available around about "
        "after before late early noon lunch coffee hope perfect lovely nice enjoy safe travels office room slot "
        "same sorry i'm it's that's don't doesn't can't let's you're we're we've i've you've isn't"
    ).split()
)
_WORDS |= _GREETING | _SIGN_OFF  # ADR-0025: the greeting and sign-off words are listed words
_BREAKS = re.compile("\r\n|[\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def clean_text(text: str) -> str:
    """`text` with every line break (CRLF, a lone CR as the MIME text encoder sends it, and the others
    `str.splitlines` breaks on) as "\\n", then without Unicode format (Cf) characters and control (Cc) characters other
    than newline and tab. A break between two words never joins them."""
    text = _BREAKS.sub("\n", text)
    if text.isascii():  # BQ-278: ASCII has no Cf; its Cc other than newline and tab are these
        return _ASCII_CONTROL.sub("", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cf"))


_ASCII_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ASCII_HIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")  # `_hidden` for ASCII: Cc but not newline, tab, CR


def _hidden(c: str) -> bool:
    kind = unicodedata.category(c)
    return kind in ("Cf", "Zl", "Zp") or (kind == "Cc" and c not in "\n\t\r")


def _suspicious(c: str) -> bool:
    kind = unicodedata.category(c)
    return not c.isascii() and kind[0] not in "PZ" and kind != "Sc"


def _numberish(word: str) -> bool:
    """CHN-GATE-D: `word` (lower case) is no name: too long, or a number by the rules above."""
    word = word.replace("'", "")
    return len(word) > _NAME_WORD_MAX or bool(
        _NUMBER_ONLY.fullmatch(word) or _NUMBER_START.match(word) or _MAGNITUDE_INSIDE.search(word)
    )


def _unlisted(cleaned: str, names: frozenset[str]) -> bool:
    """True when the body is not plain scheduling talk: too long, a link, a digit that is not a time of day, or a word
    that is neither listed nor in `names` (ADR-0025: the vouched names of the draft's recipients and the mailbox, in any
    position). A row of name words is at most two long, and every join of it ("Re Fund") is checked against the
    families. Linear, no backtracking."""
    if len(cleaned) > SHORT_BODY_MAX:
        return True
    if _LINK.search(cleaned.lower()):  # before times are removed: "5pm.me" is a link
        return True
    cleaned = _TIME.sub(f" {_STOP} ", cleaned).replace("\u2019", "'")
    if any(c.isdigit() for c in cleaned):
        return True
    for line in cleaned.split("\n"):
        run: list[str] = []
        for item in _ITEM.findall(line):
            word = item.lower()
            if word in names:
                run = [*run, word]
                joins = ("".join(run[-n:]) for n in range(2, len(run) + 1))
                if len(run) > 2 or any(p.search(j) for j in joins for _, p in _FAMILIES):
                    return True
            else:
                if item[0].isalpha() and word not in _WORDS:
                    return True
                run = []
    return False


def t3_content_signal(text: str, names: frozenset[str] = frozenset()) -> frozenset[str]:
    """Subset of {"money", "legal", "commitment", "obfuscated", "unlisted"}; empty means no signal. `names`: lower-case
    name words the thread vouches for (ADR-0025); with none, a name in the text is "unlisted" (fail closed)."""
    return _signal(text, inbound=False, names=names)


def _join(match: re.Match[str]) -> str:
    return "".join(c for c in match.group() if c.isalnum())


def _prepare_cuts(folded: str) -> str:
    """BQ-278 (i), (j): a time of day becomes a line break (a cut between two pieces), and a space next to a line break
    is dropped ("the \\ntrans \\nfer" gives "the\\ntrans\\nfer")."""
    text = _TIME.sub("\n", folded) if _DIGIT_OR_PERCENT.search(folded) else folded
    return _SPACE_AT_BREAK.sub("", text) if "\n" in text else text


def _match_phrase(
    pieces: list[str], joinable: list[bool], breakable: list[bool], start: int, words: _Phrase, k: int = 0
) -> bool:
    """The phrase `words` from piece `start`: each word is one piece or several pieces joined across cuts, and the next
    word starts after any whitespace-only gap or cut. A spelling that is a prefix of another ("number", "numbers")
    branches; a word grows only while it is a prefix of a spelling, so the work per start is bounded by the phrase."""
    word = ""
    for j in range(start, len(pieces)):
        if j > start and not joinable[j - 1]:
            break
        word += pieces[j]
        if word in words[k] and (
            k + 1 == len(words)
            or (
                j + 1 < len(pieces) and breakable[j] and _match_phrase(pieces, joinable, breakable, j + 1, words, k + 1)
            )
        ):
            return True
        if not any(w.startswith(word) for w in words[k]):
            break
    return False


def _number_word(folded: str) -> bool:
    """BQ-274, CHN-GATE-F: a number word as a whole word, glued to a unit (`_GLUED`), or a magnitude inside any word."""
    return bool(_NUMBER_WORD.search(folded) or _GLUED.search(folded) or _MAGNITUDE_INSIDE.search(folded))


def _word_hits(words: list[str]) -> frozenset[str]:
    text = "\x01".join(words)  # not whitespace: a family phrase ("we will") cannot match across two joins
    hits = {name for name, pattern in _FAMILIES if pattern.search(text)}
    return frozenset(hits | {"money"} if _number_word(text) else hits)


def _join_hits(prepared: str) -> frozenset[str]:
    """Round 4, inbound only (BQ-278 (i)-(m)): pieces of a word cut by marks or line breaks ("the\\ntrans\\nfer") with a
    neighbour glued the same way lose their word edges once the cuts are dropped ("thetransfer"). So every join of 2 or
    more consecutive pieces cut that way is a word of its own, and the families see it with edges; a join stops growing
    at a stem's worth of characters (_STEM_MAX). A phrase family cut inside a word is matched piece by piece
    (`_PHRASES`). The scan stops at the first hit; over JOIN_CAP joined characters the rest is not read, so the text is
    "obfuscated" (fail closed). Linear."""
    if not _ANY_CUT.search(prepared):
        return frozenset()
    pairs = _PIECE_GAP.findall(prepared)
    pieces = [piece for piece, _ in pairs]
    joinable = [" " not in gap for _, gap in pairs]  # the gap after the piece holds no space: a cut
    breakable = [cut or gap.isspace() for cut, (_, gap) in zip(joinable, pairs, strict=True)]
    reach, next_long = [0] * len(pieces), len(pieces)  # the next piece of 2 or more characters, from each piece on
    for i in range(len(pieces) - 1, -1, -1):
        next_long = i if len(pieces[i]) > 1 else next_long
        reach[i] = next_long
    words: list[str] = []
    size = checked = 0
    for i in range(len(pieces) - 1):
        if reach[i] - i >= _STEM_MAX:  # a run of single letters: no join from here is a word of its own
            continue
        word = pieces[i]
        j = i
        while joinable[j] and j + 1 < len(pieces) and len(word) < _STEM_MAX:
            j += 1
            word += pieces[j]
            if len(word) > j - i + 1:  # single letters only: `_SPREAD` already joins and searches them
                words.append(word)
                size += len(word)
        if size - checked >= _CHECK_EVERY or size > JOIN_CAP:
            if hits := _word_hits(words):
                return hits | {"obfuscated"} if size > JOIN_CAP else hits
            if size > JOIN_CAP:
                return frozenset({"obfuscated"})
            words, checked = [], size
    if hits := _word_hits(words):
        return hits
    if _PHRASE_FLAT.search("".join(pieces)):
        for i, piece in enumerate(pieces):
            for family, phrase in _PHRASE_STARTS.get(piece, ()):
                if _match_phrase(pieces, joinable, breakable, i, phrase):
                    return frozenset({family})
    return frozenset()


def _forms(folded: str) -> list[str]:
    """`folded`, then punctuation dropped and spread letters joined, then the same two steps the other way round."""
    return [folded, _SPREAD.sub(_join, _DROP.sub("", folded)), _DROP.sub("", _SPREAD.sub(_join, folded))]


def _amount(folded: str) -> bool:
    """BQ-274: a decimal part or thousands separator, 3+ digits in a row (a recent 4-digit year aside), "%" or a number
    word."""
    if not _DIGIT_OR_PERCENT.search(folded):  # every other shape needs a digit or "%"
        return _number_word(folded)
    return bool(_AMOUNT.search(folded) or _number_word(folded) or _DIGITS.search(_YEAR.sub(" ", folded)))


def _signal(text: str, *, inbound: bool, names: frozenset[str] = frozenset()) -> frozenset[str]:
    if len(text) > SIGNAL_CAP:
        return frozenset({"obfuscated"})
    ascii_only = text.isascii()  # BQ-278: no per-character Unicode checks on plain ASCII
    hidden = _ASCII_HIDDEN.search(text) if ascii_only else any(_hidden(c) for c in text)
    signal = {"obfuscated"} if hidden else set()
    raw = clean_text(text)
    if raw.isascii():  # NFKC leaves ASCII as it is
        cleaned = raw
    else:
        parts, size = [], 0
        for i in range(0, len(raw), 512):  # NFKC can expand a character 18-fold: stop when the output is too big
            parts.append(unicodedata.normalize("NFKC", raw[i : i + 512]))
            size += len(parts[-1])
            if size > SIGNAL_CAP:
                return frozenset(signal | {"obfuscated"})
        cleaned = "".join(parts)
    folded = cleaned.lower()
    if cleaned.isascii():
        if "$" in folded:  # the only ASCII currency sign
            signal.add("money")
    else:
        if any(_suspicious(c) for c in folded):
            signal.add("obfuscated")
        if any(unicodedata.category(c) == "Sc" for c in folded):
            signal.add("money")
    if inbound:  # BQ-274: punctuation as a class, both split orders, spread-out letters, amounts with no money word
        prepared = _prepare_cuts(folded)
        prepared_leet = _prepare_cuts(folded.translate(_LEET))  # look-alikes first: "3:35" is letters, not a time
        joined = _join_hits(prepared) or (_join_hits(prepared_leet) if prepared_leet != prepared else frozenset())
        if joined:  # the first hit stops the scan (or more joined text than JOIN_CAP: not read in full, fail closed)
            return frozenset(signal | joined)
        spread = _SPREAD.sub(_join, folded)
        leet = folded.translate(_LEET)  # translated: "@" is an "a" before it can be dropped
        forms = _forms(folded) + (_forms(leet) if leet != folded else [])
        if _amount(folded) or (spread != folded and _amount(spread)) or any(_number_word(f) for f in {*forms[1:3]}):
            signal.add("money")
        runs = " ".join(_join(m) for t in forms[::3] for m in _SPREAD.finditer(t))
        texts = list(dict.fromkeys([*forms, *(f.translate(_LEET) for f in forms[:3])]))
        signal |= {n for n, p in _INSIDE if p.search(runs)}
    else:
        texts = [folded, _SPLIT.sub("", folded).translate(_LEET)]
    signal |= {name for name, pattern in _FAMILIES if any(pattern.search(t) for t in texts)}
    if not inbound and _unlisted(cleaned, names):
        signal.add("unlisted")
    return frozenset(signal)


def inbound_plain(text: str) -> bool:
    """BQ-274 allowlist for the message a draft answers: True only when `text` is structurally plain talk. After
    `clean_text` (no NFKC: a raw non-ASCII character is never plain), every character is an ASCII letter, a space, a
    newline, one of `. , ? ! :` or `'`, or a digit that is part of a time of day (`_TIME`). A stop mark is followed
    only by a space, a newline or the end; `'` stands only inside a contraction (suffix s, t, re, ve, ll, d, m); two or
    more single-letter tokens in a row ("w i r e", a time of day between them included) are not plain, a lone "a" or
    "I" is. Over SIGNAL_CAP is not plain; empty text is. Linear, no model. Words split by plain spaces into longer
    chunks ("trans fer") are an accepted gap; `inbound_signal` is the other half."""
    if len(text) > SIGNAL_CAP:
        return False
    plain = _PLAIN_TIME.sub(_STOP, clean_text(text))  # no NFKC: a raw non-ASCII character is off the list
    if _OFF_LIST.search(plain) or _STOP_GLUED.search(plain) or "'" in _CONTRACTION.sub("", plain):
        return False
    single = False
    for token in _TOKEN.findall(plain):
        if token == _STOP:  # a time of day between single letters does not end their run ("w 5pm i 5pm r 5pm e")
            continue
        short = len(token) == 1
        if short and single:
            return False
        single = short
    return True


def inbound_signal(text: str) -> frozenset[str]:
    """The same signal for the message a draft answers (FR-CHN-11, ADR-0013, BQ-274): `t3_content_signal` without
    "unlisted", because an inbound message is free text, not a draft held to the L2 allowlist, and with the two
    additions documented above (an amount or number word is "money"; wider separators are dropped). A subset of
    {"money", "legal", "commitment", "obfuscated"}; empty means clean. A hidden character or a body over SIGNAL_CAP is
    "obfuscated" (fail closed)."""
    return _signal(text, inbound=True)
