"""tilo_channels.drafting_check: the deterministic content checker of Email Autopilot drafts (FR-CHN-10; PRD 11.4
Content; BQ-140).

The draft and every source are cleaned the same way before any regex: NFKC, default-ignorable characters and
combining marks dropped, Cyrillic and Greek look-alikes mapped to Latin, lower case. Hyphen-split words are read both
as written and joined. A commitment word is allowed only by an instruction mention that is not negated; a draft
mention that is negated ("no refund", "cannot offer a refund", or the instruction's own words) is allowed when the
instruction mentions the word at all.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

CHECK_CAP, SOURCES_CAP = 20_000, 100_000  # per text, and across all sources (a cut fact is reported, never assumed)

_DROP = ("Cc", "Cf", "Mn", "Me")  # controls, format characters (zero-width, soft hyphen, tags), joiners, marks
_CONTROLS = dict.fromkeys(c for c in [*range(32), 127] if chr(c) not in "\n\r\t")
_FILLERS = "\u115f\u1160\u3164\uffa0"  # Hangul fillers: default-ignorable letters
_LOOKALIKES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУҮԚԜӀЗасеһнвіјкмоѕртхуүԁԛԝӏпгьзΑΒΕΖΗΙΚΜΝΟΡΤΥΧϹαβγεικνορτυχωημϲϳςıɑɡ",
    "ABCEHIJKMOPSTXYYQWI3acehhbijkmosptxyydqwlnrb3ABEZHIKMNOPTYXCabyeikvoptuxwnucjciag",
)
_JOIN = re.compile(r"(?<=[^\W\d_])[-\u2010-\u2015\u2212\u2043][ \t]{0,3}(?:\r?\n)?[ \t]{0,3}(?=[^\W\d_])")

# Every quantifier that can fail after a long scan is bounded, and an address or bare domain starts only at a token
# start (an address whose local part is too long still counts, as "@domain").
_CONTACT = re.compile(
    r"(?:https?://|www\.)[^\s‹›<>\"']+|(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}"
    r"|@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}"
    r"|(?<![\w.@/-])[a-z0-9][a-z0-9-]{0,62}(?:\.[a-z0-9-]{1,63}){0,8}\.[a-z]{2,24}\b(?:/[^\s‹›<>\"']*)?"
)
_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:[.:]\d+)*")
_TENS = "twenty thirty forty fifty sixty seventy eighty ninety".split()
_UNITS = "two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen"
_NUMBER_WORDS = {w: str(n) for n, w in enumerate(f"{_UNITS} eighteen nineteen".split(), 2)}
_NUMBER_WORDS |= {w: str(n) for n, w in zip(range(20, 100, 10), _TENS, strict=True)}
_NUMBER_WORDS |= {"hundred": "100", "thousand": "1000", "million": "1000000", "billion": "1000000000"}
# Spelled ordinals; "first" and "second" (like "one") are too common to count, and "a second" is a time unit.
_IRREGULAR = {"two": "", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}
_NUMBER_WORDS |= {
    _IRREGULAR.get(w, w[:-1] + "ieth" if w in _TENS else w + "th"): v for w, v in _NUMBER_WORDS.items()
} | {"dozen": "12", "half": "0.5"}
_NUMBER_WORDS.pop("", None)
_NUMBER_WORD = re.compile(r"\b(?:" + "|".join(_NUMBER_WORDS) + r")\b")
_DATE = re.compile(
    r"\b(?:(mon|tues|wednes|thurs|fri|satur|sun)days?|(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)|today|tonight|tomorrow|weekends?"
    r"|this week|next week|next month|end of (?:the )?day|eod|same[- ]?day|overnight|asap)\b"
)
_COMMITMENTS = [  # one family per pattern; a family in the draft must also be in the instruction
    re.compile(p)
    for p in r"\bfree\b;\bdiscount\w*;\bwaive\w*;\bwaiving\b;\brefund\w*;\breimburs\w*;\bcompensat\w*;\bguarantee\w*;"
    r"\bpromise\w*;\bpromising\b;\bcomplimentary\b;\bwarrant(?:y|ies)\b;\bno[- ]?(?:extra[- ]|additional[- ])?"
    r"(?:charge|cost)s?\b;\bprepa(?:y\w*|id)\b;\bpay\w*;\bpaid\b".split(";")
]
_NEGATIONS = frozenset("no not never cannot unable without decline declined declining neither nor".split())
_FILLER = frozenset("a an the any offer offering give giving provide providing issue full partial cash".split())


@dataclass(frozen=True)
class Finding:
    kind: str  # "number" | "date" | "contact" | "commitment"
    text: str  # the draft span no source supports; shown to the user, never logged or emitted


def clean(text: str) -> str:
    """`text` as every check reads it (see the module docstring)."""
    if text.isascii():
        return text.translate(_CONTROLS).lower()
    text = unicodedata.normalize("NFKC", text).translate(_LOOKALIKES).lower().translate(_LOOKALIKES)
    return "".join(c for c in text if c in "\n\r\t" or (c not in _FILLERS and unicodedata.category(c) not in _DROP))


def _number(text: str) -> str:
    text = text.replace(",", "")
    return re.sub(r"^0+(?=\d)", "", text[:-3] if text.endswith((".00", ":00")) else text)


def _date(match: re.Match[str]) -> str:
    if match.group(1) or match.group(2):
        return match.group(1) + "day" if match.group(1) else match.group(2)[:3]
    word = re.sub(r"[- ]", "", match.group(0)).removesuffix("s")
    return "eod" if word.startswith("endof") else word


def _cue(word: str) -> bool:
    return word in _NEGATIONS or word.endswith(("n't", "n’t"))


def _negation(text: str, start: int) -> str | None:
    """The words from the last negation cue (at most four words back, same clause) up to `start`; None when there
    is none or the cue is itself negated ("not without")."""
    words = re.findall(r"[\w'’]+", re.split(r"[.,;:!?\n]", text[max(0, start - 100) : start])[-1])
    cues = [i for i in range(max(0, len(words) - 4), len(words)) if _cue(words[i])]
    if not cues or (cues[-1] > 0 and _cue(words[cues[-1] - 1])):
        return None
    return " ".join(words[cues[-1] :])


def _read(text: str, commitments: bool = True) -> tuple[list[tuple[str, str, str]], list[tuple[int, str, str | None]]]:
    """(kind, normalised value, span) for every contact, number and date in cleaned `text`, and (family, span,
    negation) for every commitment word."""
    facts = [("contact", c, c) for m in _CONTACT.finditer(text) if (c := m.group(0).rstrip(".,;:!?)"))]
    words: list[tuple[int, str, str | None]] = []
    rest = _CONTACT.sub(" ", text)
    for variant in dict.fromkeys((rest, _JOIN.sub("", rest))):
        facts += [("number", _number(m.group(0)), m.group(0)) for m in _NUMBER.finditer(variant)]
        facts += [("number", _NUMBER_WORDS[m.group(0)], m.group(0)) for m in _NUMBER_WORD.finditer(variant)]
        facts += [("date", _date(m), m.group(0)) for m in _DATE.finditer(variant)]
        variant = re.sub(r"\bfeel free\b", "feel", variant)
        for n, family in enumerate(_COMMITMENTS if commitments else ()):
            words += [(n, m.group(0), _negation(variant, m.start())) for m in family.finditer(variant)]
    return facts, words


def find_invented(body: str, *, instruction: str, thread: Sequence[str], trusted: Sequence[str] = ()) -> list[Finding]:
    """Every number, date, address or link in `body` that no source holds, and every commitment word the
    instruction does not allow (the thread and `trusted` never authorise a commitment). Deterministic. A body over
    CHECK_CAP raises ValueError; sources are read up to CHECK_CAP each and SOURCES_CAP in all, instruction first."""
    if len(body) > CHECK_CAP:
        raise ValueError("draft too long to check")
    pieces, budget = [], SOURCES_CAP
    for text in (instruction, *trusted, *thread):
        pieces.append(text[: max(0, min(CHECK_CAP, budget))])
        budget -= len(pieces[-1])
    known = {(kind, value) for kind, value, _ in _read(clean("\n".join(pieces)), commitments=False)[0]}
    granted, mentioned, denied = set(), set(), set()
    for family, _, negation in _read(clean(instruction[:CHECK_CAP]))[1]:
        mentioned.add(family)
        if negation is None:
            granted.add(family)
        else:
            denied.add((family, negation))
    facts, words = _read(clean(body))
    found: dict[tuple[str, str], Finding] = {}
    for kind, value, span in facts:
        if (kind, value) not in known:
            found.setdefault((kind, value), Finding(kind, span))
    for family, span, negation in words:
        negated = negation is not None and ((family, negation) in denied or set(negation.split()[1:]) <= _FILLER)
        if family not in granted and not (negated and family in mentioned):
            found.setdefault(("commitment", span), Finding("commitment", span))
    return list(found.values())
