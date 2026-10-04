"""tilo_channels.drafting_check: the deterministic content checker of Email Autopilot drafts (FR-CHN-10; PRD 11.4
Content; BQ-140). A heuristic gate: every rule fails toward a finding (needs_you), never toward a ready draft.

The draft and every source are read the same way: NFKD (compatibility and canonical decomposition), then controls,
format characters, combining marks and fillers dropped (so "refụnd" reads "refund"), single-script Cyrillic and
Greek look-alikes mapped to Latin, lower case; hyphen-split words are also read joined. In the draft (and a model
question) a text-direction control, or a word that mixes Latin with another script or holds a Latin small capital or
IPA letter, is an "obfuscation" finding. A commitment word is allowed only when an instruction sentence holding it
has no negator at all; a draft sentence with exactly one negator just before the word ("no refund", "cannot offer a
refund", or the instruction's own words) is allowed when the instruction mentions the word.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

CHECK_CAP, SOURCES_CAP = 20_000, 100_000  # per text, and across all sources (a cut fact is reported, never assumed)

_DROP = ("Cc", "Cf", "Mn", "Me")  # controls, format characters (zero-width, soft hyphen, tags), joiners, marks
_CONTROLS = dict.fromkeys(c for c in [*range(32), 127] if chr(c) not in "\n\r\t")
_FILLERS = "".join(map(chr, (0x115F, 0x1160, 0x3164, 0xFFA0)))  # Hangul fillers: default-ignorable letters
_BIDI = "".join(map(chr, (*range(0x202A, 0x202F), *range(0x2066, 0x206A), 0x200E, 0x200F, 0x061C)))
_BIDI_GAP = dict.fromkeys(map(ord, _BIDI), " ")
_BIDI_SPAN = re.compile(f"\\S{{0,40}}[{_BIDI}]\\S{{0,40}}")
_LATIN_OK = frozenset("ßøæœđłþðħı")  # Latin letters with no ASCII decomposition that are ordinary spelling
_LOOKALIKES = str.maketrans(
    "АВСЕНІЈКМОРЅТХУҮԚԜӀЗасеһнвіјкмоѕртхуүԁԛԝӏпгьзΑΒΕΖΗΙΚΜΝΟΡΤΥΧϹαβγεικνορτυχωημϲϳςı",
    "ABCEHIJKMOPSTXYYQWI3acehhbijkmosptxyydqwlnrb3ABEZHIKMNOPTYXCabyeikvoptuxwnucjci",
)
_DASHES = "".join(map(chr, (*range(0x2010, 0x2016), 0x2212, 0x2043)))
_JOIN = re.compile(f"(?<=[^\\W\\d_])[-{_DASHES}][ \\t]{{0,3}}(?:\\r?\\n)?[ \\t]{{0,3}}(?=[^\\W\\d_])")
_SENTENCE = re.compile(r"[;!?\n]|\.(?!\d)")

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
# Spelled ordinals; "one", "first" and "second" are too common to count ("a second" is also a time unit): BQ-140.
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
_NO_CHARGE = r"\bno[- ]?(?:extra[- ]|additional[- ])?(?:charge|cost)s?\b"  # a commitment, not a negator
_COMMITMENTS = [  # one family per pattern; a family in the draft must also be in the instruction
    re.compile(p)
    for p in r"\bfree\b;\bdiscount\w*;\bwaive\w*;\bwaiving\b;\brefund\w*;\breimburs\w*;\bcompensat\w*;\bguarantee\w*;"
    r"\bpromise\w*;\bpromising\b;\bcomplimentary\b;\bwarrant(?:y|ies)\b;\bprepa(?:y\w*|id)\b;\bpay\w*;\bpaid\b".split(
        ";"
    )
] + [re.compile(_NO_CHARGE)]
_NEGATORS = frozenset(
    "no not never none nothing nobody neither nor without cannot unable impossible unavailable decline declines "
    "declined declining refuse refuses refused refusing deny denies denied denying avoid avoids avoided avoiding "
    "withhold withholds withheld".split()
)
_FILLER = frozenset("a an the any offer offering give giving provide providing issue full partial cash".split())


@dataclass(frozen=True)
class Finding:
    kind: str  # "number" | "date" | "contact" | "commitment" | "obfuscation"
    text: str  # the draft span no source supports; shown to the user, never logged or emitted


def _strip(text: str) -> str:
    """NFKD, with controls, format characters, marks and fillers dropped; a direction control becomes a space."""
    if text.isascii():
        return text.translate(_CONTROLS)
    text = unicodedata.normalize("NFKD", text.translate(_BIDI_GAP))
    return "".join(c for c in text if c in "\n\r\t" or (c not in _FILLERS and unicodedata.category(c) not in _DROP))


def clean(text: str) -> str:
    """`text` as every check reads it (see the module docstring)."""
    text = _strip(text)
    return text.lower() if text.isascii() else text.translate(_LOOKALIKES).lower().translate(_LOOKALIKES)


def _suspect(word: str) -> bool:
    """True for a word mixing Latin with another script, or holding a Latin letter that is a look-alike trick."""
    scripts = set()
    for c in word:
        script = "LATIN" if c.isascii() else unicodedata.name(c, "?").split(" ", 1)[0]
        if script == "LATIN" and not c.isascii() and c.lower() not in _LATIN_OK:
            return True
        scripts.add(script)
    return "LATIN" in scripts and len(scripts) > 1


def _obfuscations(text: str) -> list[Finding]:
    """Direction controls and mixed-script words in model text: what a person sees is not what is checked."""
    found = [Finding("obfuscation", m.group(0).translate(_BIDI_GAP).strip() or "?") for m in _BIDI_SPAN.finditer(text)]
    words = re.finditer(r"[^\W\d_]+", _strip(text)) if not text.isascii() else ()
    return found + [
        Finding("obfuscation", m.group(0)) for m in words if not m.group(0).isascii() and _suspect(m.group(0))
    ]


def _number(text: str) -> str:
    text = text.replace(",", "")
    return re.sub(r"^0+(?=\d)", "", text[:-3] if text.endswith((".00", ":00")) else text)


def _date(match: re.Match[str]) -> str:
    if match.group(1) or match.group(2):
        return match.group(1) + "day" if match.group(1) else match.group(2)[:3]
    word = re.sub(r"[- ]", "", match.group(0)).removesuffix("s")
    return "eod" if word.startswith("endof") else word


def _cue(word: str) -> bool:
    return word in _NEGATORS or word.endswith(("n't", "n’t"))


def _negators(sentence: str) -> int:
    sentence = re.sub(_NO_CHARGE, " ", sentence)
    return sum(map(_cue, re.findall(r"[\w'’]+", sentence))) + sentence.count("out of the question")


def _negation(text: str, start: int) -> str | None:
    """The words from a negation cue at most four words back in the same clause up to `start`, or None."""
    words = re.findall(r"[\w'’]+", re.split(r"[.,;:!?\n]", text[max(0, start - 100) : start])[-1])
    cues = [i for i in range(max(0, len(words) - 4), len(words)) if _cue(words[i])]
    return " ".join(words[cues[-1] :]) if cues else None


def _plain(phrase: str) -> bool:  # "no", "cannot offer a": only filler words between the negator and the word
    return set(phrase.split()[1:]) <= _FILLER


Words = list[tuple[int, str, str | None, int]]  # (family, span, negation phrase, negators in its sentence)


def _read(text: str, commitments: bool = True) -> tuple[list[tuple[str, str, str]], Words]:
    """(kind, normalised value, span) for every contact, number and date in cleaned `text`, and every commitment
    word with its negation."""
    facts = [("contact", c, c) for m in _CONTACT.finditer(text) if (c := m.group(0).rstrip(".,;:!?)"))]
    words: Words = []
    rest = _CONTACT.sub(" ", text)
    for variant in dict.fromkeys((rest, _JOIN.sub("", rest))):
        facts += [("number", _number(m.group(0)), m.group(0)) for m in _NUMBER.finditer(variant)]
        facts += [("number", _NUMBER_WORDS[m.group(0)], m.group(0)) for m in _NUMBER_WORD.finditer(variant)]
        facts += [("date", _date(m), m.group(0)) for m in _DATE.finditer(variant)]
        for sentence in _SENTENCE.split(re.sub(r"\bfeel free\b", "feel", variant)) if commitments else ():
            hits = [(n, m) for n, family in enumerate(_COMMITMENTS) for m in family.finditer(sentence)]
            count = _negators(sentence) if hits else 0
            words += [(n, m.group(0), _negation(sentence, m.start()), count) for n, m in hits]
    return facts, words


class Checker:
    """`find_invented` with its sources read once, for every body and question of one draft."""

    def __init__(self, *, instruction: str, thread: Sequence[str], trusted: Sequence[str] = ()) -> None:
        pieces, budget = [], SOURCES_CAP
        for text in (instruction, *trusted, *thread):
            pieces.append(text[: max(0, min(CHECK_CAP, budget))])
            budget -= len(pieces[-1])
        self._known = {(kind, value) for kind, value, _ in _read(clean("\n".join(pieces)), commitments=False)[0]}
        self._granted, self._mentioned, self._denied = set[int](), set[int](), set[tuple[int, str]]()
        for family, _, phrase, count in _read(clean(instruction[:CHECK_CAP]))[1]:
            self._mentioned.add(family)
            if count == 0:  # any negator anywhere in the instruction sentence: not granted
                self._granted.add(family)
            elif phrase is not None:
                self._denied.add((family, phrase))

    def find(self, body: str) -> list[Finding]:
        """Every unsupported fact, unallowed commitment and obfuscation in `body`. Over CHECK_CAP: ValueError."""
        if len(body) > CHECK_CAP:
            raise ValueError("draft too long to check")
        found = {(f.kind, f.text): f for f in _obfuscations(body)}
        facts, words = _read(clean(body))
        for kind, value, span in facts:
            if (kind, value) not in self._known:
                found.setdefault((kind, value), Finding(kind, span))
        for family, span, phrase, count in words:
            negated = count == 1 and phrase is not None and ((family, phrase) in self._denied or _plain(phrase))
            if family not in self._granted and not (negated and family in self._mentioned):
                found.setdefault(("commitment", span), Finding("commitment", span))
        return list(found.values())


def find_invented(body: str, *, instruction: str, thread: Sequence[str], trusted: Sequence[str] = ()) -> list[Finding]:
    """Every number, date, address or link in `body` that no source holds, every commitment word the instruction does
    not allow (the thread and `trusted` never authorise one) and every obfuscation. Deterministic. Sources are read
    up to CHECK_CAP each and SOURCES_CAP in all, instruction first."""
    return Checker(instruction=instruction, thread=thread, trusted=trusted).find(body)
