"""tilo_redact: the one shared secret redactor (FR-MEM-05, SEC-14; PRD 13.2, 16.1 rule 4, 16.2). Standard library only,
so providers, archive, memory, api, connectors, harness, evals and logging can all use it without a cycle.

    redact(text)          text with every secret replaced by REDACTED; unchanged when it holds none
    redact_value(obj)     the same over a JSON tree (a new tree): every string and key, and a secure field whole
    RedactingFilter       a `logging.Filter` that redacts a record's message, traceback and extra fields

What goes (each rule is deterministic, and the result is idempotent: `redact(redact(t)) == redact(t)`):
  - a private key block (PEM, PGP, any `... PRIVATE KEY` label): to its END line; with none, only its header and the
    base64 lines after it, so the text that follows an untrusted header survives;
  - the token shapes of `scripts/secret_scan.py` plus Google access, refresh and auth-code tokens (`ya29.c.`, `4/0A`),
    Firebase refresh tokens, GitHub (incl. fine-grained), Slack and AWS keys, JWTs and a `Bearer` token (20 characters,
    or 8 with a digit or symbol, so "Bearer securities" stays);
  - the userinfo of any `scheme://user:pass@host`;
  - the value of a labelled secret. One key rule (`_secure`) serves trees and text: a key is split into words at any
    non-alphanumeric and at camelCase, and it is secure when its last words spell a `_STRONG` key (`api_key`,
    `X-Api-Key`, `apikey`, `accessToken`, `payment_authorization`), when its last word ends in password, passwd, pwd,
    secret or token (`PGPASSWORD`, `MYSQL_PWD`, `csrftoken`), or when it is exactly `pass`; paging cursors
    (`page_token`, `nextSyncToken`, `continuation_token`, ...) are not. In text, a quoted value (JSON, JSON-in-JSON
    `\\"`, `&quot;`, a repr) ends only at a quote of its own JSON-in-JSON level, so a secure field holding JSON loses
    all of it. The value after a quoted key or after `=` always goes; after an unquoted `key:` it goes when it is
    quoted, credential-shaped (16 characters, or 8 with a digit or symbol) or a lone word, and a word followed by more
    prose stays ("The secret: ship small"), except after password, passwd or passphrase, which fail closed (a
    passphrase to the line end or punctuation). `pass`/`pwd` need a credential shape or quotes. An `Authorization` or
    `Cookie` value goes to the end of its line (in a JSON string, to its closing quote) only when it starts with an
    auth scheme, `name=value` or a credential shape. `code`, `key`, `signature` are only secrets as `?x=` or `&x=`
    parameters, and `code` only in an OAuth URL (one with `state=`, `scope=`, `redirect_uri=`, `grant_type=`,
    `client_id=`, or an auth, callback or login path);
  - a card number: 13 to 19 digits (plain, or in groups under a space or dash), Luhn-valid, not touching a letter,
    digit, `_`, `.` or `-` (so digests, ULIDs, ids and decimals are safe). It leaves REDACTED and its last four digits.
  - in a tree, the whole value of a secure key unless it is a bool or None, which cannot hold a secret.

JSON stays JSON: no value crosses a closing quote or splits an escape, `{` and `[` values are left to the inner rules,
a JSON number after a secure key becomes the string "[REDACTED]" (as in a tree), true, false and null stay, and a card
in a JSON number's place becomes a string too.

What stays: emails and phone numbers (PRD 16.1 rule 4 is about secrets; recipients are the data the archive holds),
other JSON numbers that are not cards, and any Luhn-failing digit run. The artifact store, connectors and run bundle
REFUSE content this would change (MF-06, AR-07), so a false positive breaks real work. A number that cannot be a card is
therefore not one: it never starts with 0 (no card IIN does), and a plain 13-digit run from 1500000000000 to
1999999999999 is an epoch-millisecond timestamp (2017 to 2033), about one in ten of which passes Luhn, so it is kept.

Out of scope, and so a miss: a secret wrapped in base64, URL-encoding or any other encoding, and Unicode look-alikes.
The raw archive is append-only, so a secret this misses is stored for good: add the shape here, with a keeps test,
before the archive sees it (BQ-FRMEM05-1). Every pattern is linear: a prefix is anchored where the body could restart
inside itself, quantifiers are possessive, and each lookahead is bounded or scans a run only once.
"""

from __future__ import annotations

import logging
import re
import string
from typing import Any

REDACTED = "[REDACTED]"
MAX_DEPTH = 200  # redact_value refuses a deeper tree (or a cycle) with a ValueError, never a RecursionError

_STRONG = (  # keys whose value is a secret wherever they appear, as words
    "password passwd passphrase secret secret_key client_secret token access_token refresh_token id_token auth_token "
    "api_key private_key authorization cookie aws_secret_access_key aws_session_token"
).split()
_EXACT = ("pass", "pwd")  # common words: in text only as a whole key with a credential-shaped or quoted value
_QUERY = (*_EXACT, "code", "key", "signature", "x_goog_signature", "x_amz_signature", "x_amz_security_token")
SECURE_KEYS = frozenset((*_STRONG, *_EXACT))  # normalised: lower case, `_` between words
_FLAT = frozenset(key.replace("_", "") for key in _STRONG)  # `apikey`, `accesstoken`: one word spells the key too
_GLUED = ("password", "passwd", "pwd", "secret", "token")  # a one-word key may end in one: `PGPASSWORD`, `csrftoken`
_CURSORS = ("pagetoken", "synctoken", "continuationtoken")  # paging cursors (`next_page_token`), not credentials
_PASSWORDS = ("password", "passwd", "passphrase")  # labels that fail closed even before prose
_KEYCHARS = string.ascii_letters + string.digits + "_.%-"


def _words(key: str) -> list[str]:
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", re.sub(r"%[0-9A-Fa-f]{2}", " ", key))
    return [word for word in re.split(r"[^a-z0-9]+", key.lower()) if word]


def _cursor(words: list[str]) -> bool:
    return "".join(words[-2:]).endswith(_CURSORS)


def _secure(key: str) -> bool:
    """The one key rule (see the module docstring); text labels follow it too."""
    words = _words(key)
    if not words or _cursor(words):
        return False
    if words[-1].endswith(_GLUED) or any("".join(words[i:]) in _FLAT for i in range(len(words))):
        return True
    chunks = key.split()
    return bool(chunks) and re.fullmatch(r"[^A-Za-z0-9_.%\\\[-]*(?:pass|pwd)[ _.-]*", chunks[-1], re.I) is not None


def _cred(word: str) -> bool:
    """Credential-shaped: 16 characters, or 8 with a digit or symbol."""
    return len(word) >= 16 or (len(word) >= 8 and not word.isalpha())


def _label(keys: tuple[str, ...] | list[str]) -> str:
    return "|".join(r"(?:[ _.-]|%[0-9A-Fa-f]{2})?".join(k.split("_")) for k in sorted(keys, key=len, reverse=True))


_NAME = r"(?:(?!PRIVATE KEY)[A-Z0-9]++ )*+PRIVATE KEY(?: BLOCK)?"
_NL = r"(?:\r?\n|\\n)"
_HEADERS = "Proc-Type|DEK-Info|Version|Comment|Charset|Hash"
# what follows a closing quote in JSON, including the quote that closes an outer string (JSON-in-JSON)
_CL = r"""(?:\s|\\[nrt])*+(?:[,:}\]]|\Z|\\*+["'])"""
_LINE = rf"""(?:[^\r\n\\"]|"(?!{_CL}))*+"""  # the rest of a key line: never past the quote that closes a JSON string
_PEM = re.compile(
    rf"-----BEGIN {_NAME}-----"
    rf"""(?:(?:(?!-----BEGIN |-----END {_NAME}-----)(?:[^"]|"(?!{_CL})))*+-----END {_NAME}-----"""
    rf"|(?:{_NL}[ \t]*+(?:[A-Za-z0-9+/=]{{16,}}+{_LINE}"  # a key line, and anything else on it
    rf"|(?:[A-Za-z0-9+/=]++|(?:{_HEADERS}): {_LINE})?[ \t]*+(?={_NL}|\Z)))*+)"
)
_USERINFO = re.compile(r"""(?<![A-Za-z0-9+.-])([A-Za-z][A-Za-z0-9+.-]{0,31}://)[^\s/?#"\\]{1,1024}@""")
_B = r"[A-Za-z0-9._~+/=-]"  # a bearer token: 20 of these, or 8 with a digit or symbol (not `-`, nor a final `.`)
_TOKENS = re.compile(
    "|".join(
        [
            rf"\b(?i:bearer)\s{{1,8}}+(?:{_B}{{20,}}+|(?=[A-Za-z-]*+(?:\d|[_~+/=]|\.(?={_B}))){_B}{{8,}}+)",
            r"AIza[0-9A-Za-z_-]{35,}+",
            r"(?<![A-Za-z0-9])AQ\.[0-9A-Za-z_-]{40,}+",
            r"ya29\.[0-9A-Za-z_.-]{20,}+",
            r"1//0[0-9A-Za-z_-]{30,}+",
            r"(?<![A-Za-z0-9/_-])4/0A[0-9A-Za-z_-]{30,}+",
            r"AMf-vB[0-9A-Za-z_-]{50,}+",
            r"(?<![A-Za-z0-9-])sk-[A-Za-z0-9_-]{20,}+",
            r"(?<![A-Za-z0-9])gh[pousr]_[A-Za-z0-9]{36,}+",
            r"github_pat_[A-Za-z0-9_]{22,}+",
            r"xox[abeprs]-[A-Za-z0-9-]{10,}+",
            r"hooks\.slack\.com/services/[A-Za-z0-9/]{20,}+",
            r"(?<![A-Za-z0-9])EAA[A-Za-z0-9]{60,}+",
            r"(?<![A-Za-z0-9])nvapi-[A-Za-z0-9_-]{20,}+",
            r"(?<![A-Za-z0-9])A[KS]IA[0-9A-Z]{16}(?![A-Za-z0-9])",
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]++\.[A-Za-z0-9_-]++\.[A-Za-z0-9_-]*+",
        ]
    )
)
_SERVICE_ACCOUNT = re.compile(r'("type"\s*+:\s*+")service_account(")')  # the value goes, so the JSON stays JSON
_SEP = "[ \u00a0\u2009\u202f-]"  # a space, no-break space, thin space, narrow no-break space or dash
_CARD = re.compile(rf"(?<![\w.-])(?:\d{{13,19}}|\d{{4,6}}{_SEP}\d{{4,6}}(?:{_SEP}\d{{1,6}}){{1,3}})(?![\w-])(?!\.\d)")
_EPOCH_MS = re.compile(r"1[5-9]\d{11}")

_EQ = r"""(?:\\\\)*+\\["']|&(?i:quot|apos);|&#0*+3[49];"""  # a quote as JSON-in-JSON (odd backslashes) or HTML has it
_START = r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2})|(?<=\\[nrt])|(?-i:(?<=[a-z0-9])(?=[A-Z])))"  # a word starts here
_WORD_START = r"(?:(?<![A-Za-z0-9])|(?<=%[0-9A-Fa-f]{2})|(?<=\\[nrt]))"  # the same, without camelCase: a whole word
_LABELLED = re.compile(
    rf"(?<=[?&#;])(?P<query>{_label(_QUERY)})="
    rf"|(?:{_START}(?P<strong>{_label(_STRONG)})|(?<![A-Za-z0-9_.%\\\[-])(?P<exact>pass|pwd)"
    rf"|{_WORD_START}(?P<glued>[A-Za-z0-9]{{0,60}}?(?:{'|'.join(_GLUED)}))(?![A-Za-z0-9]))"
    rf"""[ \t_.-]{{0,8}}+(?:(?P<kq>{_EQ}|["'])|\]|%5[Dd])?[ \t]{{0,8}}+(?P<sep>[:=])[ \t]{{0,8}}+""",
    re.I,
)
_OPENER = re.compile(rf"""(?P<eq>{_EQ})|["']""")
_CLOSER = re.compile(_CL)
_JSON_SCAN = re.compile(r'(?<!\\)\\*+"|[\[\]{}]')  # a quote (after its backslashes) or a bracket
_AFTER_NUMBER = re.compile(r"(?:\s|\\[nrt])*+(?:[,}\]]|\Z)")
_ENTITY_BODY = re.compile(r"""(?:[^"\\&\n]|\\++(?![\\"'])|(?:\\\\)++(?=["'])|&(?!(?i:quot|apos);|#0*+3[49];))++""")
_QUOTE_RUN = re.compile(r"""(?<!\\)\\*+["']|\n""")  # a quote after its whole backslash run, or a line end
_PLAIN = re.compile(  # an unquoted value: stops at JSON punctuation, a quote, an escaped quote or line end, `&`, space
    r"""(?:[^\s\\&"'<>,}\]]|[,}\]](?![\s,}\]"'\\]|\Z)|\\++(?![\\"'nrt]))++"""
)
_HEADER_LINE = {  # a header inside a line: to its end, an escaped line end, or the quote that closes its string
    True: re.compile(
        rf"""(?:[^\r\n\\"']|\\++(?![\\"'nrt])|(?:\\\\)*+\\["'](?!{_CL})|(?:\\\\)++(?=["'])|["'](?!{_CL}))*+"""
    ),
    False: re.compile(rf"""(?:[^\r\n\\']|\\++(?![\\'nrt])|(?:\\\\)*+\\'(?!{_CL})|(?:\\\\)++(?=')|'(?!{_CL}))*+"""),
}  # outside a JSON string (False) a `"` is the header's own (`Digest realm="r"`), and only a `'` can close a string
# an Authorization or Cookie value that is a credential: an auth scheme, `name=value` or a credential shape
_SCHEME = re.compile(r"(?i:basic|bearer|digest|token|negotiate|ntlm|aws4-hmac-sha256|bot|apikey)[ \t]++[^\s,;]")
_COOKIE = re.compile(r"""[^\s=;,"'<>\\:]{1,256}+=""")
_PHRASE = re.compile(r"""[^\r\n.,;!?"'<>&\\{}\[\]]*+""")  # a passphrase: to the line end or punctuation
_WORD = re.compile(r"""[^\s,;"'<>\\]{1,16}""")
_PROSE = re.compile(r"""[ \t]++[^\s,;"'}\]\\&<>]""")  # the value is followed by more words on its line
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|Infinity)|NaN")
_LITERALS = frozenset({"true", "false", "null", "True", "False", "None"})
_OAUTH_PARAM = re.compile(r"(?:^|[?&#;])(?:state|scope|redirect_uri|grant_type|client_id|code_verifier)=", re.I)
_OAUTH_PATH = re.compile(  # the host and path of a URL in the run
    r"(?<![A-Za-z0-9+.-])[A-Za-z][A-Za-z0-9+.-]*+://(?:(?!://)[^?#])*?"
    r"(?:oauth|callback|auth|login|signin|sso|/cb(?![A-Za-z0-9]))",
    re.I,
)
_RUN_END = re.compile(r"""[\s"'<>]|\[REDACTED\]""")
_EOL = re.compile(r"[\r\n]")


class _Url:
    """Whether the URL around a position is an OAuth one; each run is read once. A run stops at whitespace, a quote
    and REDACTED, so a second pass, whose values are REDACTED, only ever sees part of a run the first pass saw."""

    def __init__(self, text: str) -> None:
        self.text, self.end, self.oauth = text, -1, False

    def at(self, pos: int) -> bool:
        if pos >= self.end:
            text = self.text
            lo = max(self.end, 0)
            start = max(text.rfind(c, lo, pos) + 1 for c in " \t\r\n\"'<>")
            if (marker := text.rfind(REDACTED, lo, pos)) >= 0:
                start = max(start, marker + len(REDACTED))
            stop = _RUN_END.search(text, pos)
            self.end = stop.start() if stop else len(text)
            run = text[start : self.end]
            self.oauth = bool(_OAUTH_PARAM.search(run) or _OAUTH_PATH.search(run))
        return self.oauth


def _quote(token: str) -> str:
    """The quote `token` (a backslash run and a quote, or an entity) is, without the escaped backslashes before it: at
    JSON-in-JSON level L a quote is 2**L - 1 backslashes and the quote, and a backslash in its text is 2**L of them."""
    if token.startswith("&"):
        return token
    run, level = len(token) - 1, 0
    while run % 2 ** (level + 1) == 2 ** (level + 1) - 1:
        level += 1
    return "\\" * (2**level - 1) + token[-1]


def _ones(run: int) -> int:
    """The JSON-in-JSON level of a quote after `run` backslashes: the count of its trailing one bits."""
    return (run ^ (run + 1)).bit_length() - 1


def _quoted_end(text: str, start: int, opener: str, strings: int) -> int:
    """Where a value opened by `opener` (a quote after its backslashes) ends: at a quote of its own JSON-in-JSON level
    or a shallower one, or a line end. A deeper (escaped) quote is text, so a secure field holding JSON loses all of
    it. A `"` ends a `'`-quoted value only as the end of a JSON string around it (`strings` deep), so a `"` in a
    repr's `'`-quoted value is text. Backslash runs are never split."""
    char, level = opener[-1], _ones(len(opener) - 1)
    for mark in _QUOTE_RUN.finditer(text, start):
        found = mark.group()
        if found == "\n":
            return mark.start()
        depth = _ones(len(found) - 1)
        if found[-1] == char and depth <= level:
            return mark.start()
        if found[-1] == '"' and depth < (max(level, strings) if char == "'" else level):
            return mark.start()
    return len(text)


def _key_start(text: str, pos: int) -> int:
    before = text[max(0, pos - 256) : pos]
    return pos - (len(before) - len(before.rstrip(_KEYCHARS)))


def _header_end(text: str, key_start: int, pos: int, in_string: bool) -> int:
    """A header at the start of a line runs to the line's end; one inside a line stops at a closing quote too."""
    before = text[max(0, key_start - 64) : key_start]
    head = before.rstrip(" \t")
    if head.endswith(("\n", "\r")) or (not head and key_start <= 64):
        stop = _EOL.search(text, pos)
        return stop.start() if stop else len(text)
    return _HEADER_LINE[in_string].match(text, pos).end()  # type: ignore[union-attr]  # `*+` always matches


def _value(text: str, m: re.Match[str], url: _Url, strings: _Strings) -> tuple[int, int, str] | None:
    """Where the value after label `m` starts and ends, and what replaces it; None when it stays."""
    pos = m.end()
    if text.startswith(("[", "{"), pos):  # a nested object or array, or a value already redacted
        return None
    if m["query"]:
        if m["query"].lower() == "code" and not url.at(m.start()):
            return None
        value = _PLAIN.match(text, pos)
        return (pos, value.end(), REDACTED) if value else None
    strong = m["strong"] or m["glued"]
    label, keyq = strong or m["exact"], m["kq"] and _quote(m["kq"])
    if strong and label.lower().endswith("token"):
        if _cursor(_words(text[_key_start(text, m.start()) : m.start()] + label)):
            return None
    opener = _OPENER.match(text, pos)
    if opener:
        quote, depth = _quote(opener.group()), strings.at(m.start())
        # A quote unlike its key's may close a string, and then there is no value here; but outside a JSON string a
        # repr mixes quote styles (`{'k': "it's"}`), so a quote of the key's own level opens the value.
        mixed = keyq and len(keyq) == len(quote) and depth <= _ones(len(quote) - 1)
        if keyq != quote and not mixed and _CLOSER.match(text, opener.end()):
            return None
        if opener.group().startswith("&"):
            body = _ENTITY_BODY.match(text, opener.end())
            end = body.end() if body else opener.end()
        else:
            end = _quoted_end(text, opener.end(), opener.group(), depth)
        return (opener.end(), end, REDACTED) if end > opener.end() else None
    flat = re.sub(r"[^a-z]", "", label.lower())
    if strong and not keyq and flat.endswith(("authorization", "cookie")):
        first = _WORD.match(text, pos)
        credential = _SCHEME.match(text, pos) or _COOKIE.match(text, pos) or _cred(first[0] if first else "")
        if m["sep"] == ":" and not credential:
            return None  # "Payment Authorization: approved by finance", "Cookie: oatmeal raisin"
        if m["sep"] == ":" or _SCHEME.match(text, pos):
            end = _header_end(text, _key_start(text, m.start()), pos, strings.at(m.start()) > 0)
            return pos, end, REDACTED
    value = _PLAIN.match(text, pos)
    if value is None:
        return None
    word = value.group()
    if keyq:
        if word in _LITERALS:
            return None
        if _NUMBER.fullmatch(word):  # a JSON number becomes a JSON string, as a tree's value does
            return pos, value.end(), f"{keyq}{REDACTED}{keyq}"
    elif strong and flat.endswith(_PASSWORDS):  # "Password: changeme (temporary)": fails closed, even before prose
        if flat.endswith("passphrase") and m["sep"] == ":":  # a passphrase runs to the line end or punctuation
            phrase = _PHRASE.match(text, pos).group().rstrip()  # type: ignore[union-attr]  # `*+` always matches
            return pos, max(value.end(), pos + len(phrase)), REDACTED
    elif not _cred(word) and (m["exact"] or (m["sep"] == ":" and _PROSE.match(text, value.end()))):
        return None
    return pos, value.end(), REDACTED


def _labelled(text: str) -> str:
    out, last, url, strings = [], 0, _Url(text), _Strings(text)
    for m in _LABELLED.finditer(text):  # the value is matched where the label ends, so each part is read once
        if m.start() < last:  # inside a value already removed
            continue
        found = _value(text, m, url, strings)
        if found is None:
            continue
        start, end, new = found
        out += [text[last:start], new]
        last = end
    out.append(text[last:])
    return "".join(out)


def _luhn(digits: str) -> bool:
    total = sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d for i, d in enumerate(map(int, digits[::-1])))
    return total % 10 == 0


class _Strings:
    """How deep a position is in JSON strings: 0 outside, 1 inside a string, 2 inside a JSON-in-JSON string within it
    (its quotes are `\\"` after escaped backslashes in fours); and, outside strings, whether the innermost open bracket
    is an array's. The text is scanned forward once."""

    def __init__(self, text: str) -> None:
        self.text, self.pos, self.depth, self.brackets = text, 0, 0, [""]

    def at(self, pos: int) -> int:
        for token in _JSON_SCAN.finditer(self.text, self.pos, pos):
            mark = token.group()
            if mark in "[{]}":
                if self.depth:  # a bracket inside a string is text
                    continue
                if mark in "[{":
                    self.brackets.append(mark)
                elif len(self.brackets) > 1:
                    self.brackets.pop()
            elif (len(mark) - 1) % 2 == 0:
                self.depth = 0 if self.depth else 1
            elif (len(mark) - 1) % 4 == 1 and self.depth:
                self.depth = 3 - self.depth
        self.pos = max(self.pos, pos)
        return self.depth


def _number_quote(text: str, start: int, end: int, depth: int, array: bool) -> str | None:
    """The quote that keeps JSON valid around a card standing where a JSON number does: `"` outside a string (after a
    quoted key's colon, `[`, or `,` inside an array), and inside one (JSON-in-JSON) `\\"` or `&quot;` like its key."""
    if not _AFTER_NUMBER.match(text, end):
        return None
    before = text[max(0, start - 64) : start].rstrip()
    key = before[:-1].rstrip() if before.endswith(":") else ""
    if depth == 0:  # a comma in prose ("cards 1, 4111..., 2") is not one in an array
        return '"' if (before.endswith(("[", ",")) and array) or key.endswith('"') else None
    if depth > 1:
        return None
    if before.endswith(("[", ",")):
        return '\\"'
    if key.endswith("&quot;"):
        return "&quot;"
    run = len(key) - 1 - len(key[:-1].rstrip("\\"))
    return '\\"' if key.endswith('"') and run % 2 else None


def _card(match: re.Match[str], strings: _Strings) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if not 13 <= len(digits) <= 19 or digits[0] == "0" or _EPOCH_MS.fullmatch(raw) or not _luhn(digits):
        return raw
    new = f"{REDACTED} (ends {digits[-4:]})"
    if raw.isascii() and raw.isdigit():  # a JSON number: a string in its place keeps the JSON valid
        depth = strings.at(match.start())
        quote = _number_quote(match.string, match.start(), match.end(), depth, strings.brackets[-1] == "[")
        return f"{quote}{new}{quote}" if quote else new
    return new


def redact(text: str) -> str:
    """`text` with every secret replaced by REDACTED (see the module docstring); `text` itself when it holds none."""
    if "-----begin" in text.lower():
        text = _PEM.sub(REDACTED, text)
    text = _SERVICE_ACCOUNT.sub(rf"\1{REDACTED}\2", _TOKENS.sub(REDACTED, text))
    if "://" in text:  # after the tokens, whose removal can join a userinfo across a space
        text = _USERINFO.sub(rf"\1{REDACTED}@", text)
    strings = _Strings(text)
    return _labelled(_CARD.sub(lambda match: _card(match, strings), text))


def _field(key: Any, value: Any, depth: int) -> Any:
    if isinstance(key, str) and _secure(key) and not (value is None or isinstance(value, bool)):
        return REDACTED
    return redact_value(value, depth)


def redact_value(obj: Any, _depth: int = 0) -> Any:
    """A new tree like `obj` with every string (and key) redacted and every secure field's value replaced whole (a
    bool or None stays). Dicts, lists, tuples, sets, bytes and scalars are walked; any other type, and a tree deeper
    than MAX_DEPTH (or one that holds itself), is refused with a TypeError or ValueError, never passed through
    unredacted. Two keys that redact to one string both stay (the second gets a `#2` suffix)."""
    if _depth > MAX_DEPTH:
        raise ValueError(f"redact_value: tree is deeper than {MAX_DEPTH} levels")
    if isinstance(obj, str):
        return redact(obj)
    if obj is None or isinstance(obj, bool | int | float):
        return obj
    deeper = _depth + 1
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            new = base = redact_value(key, deeper)
            for n in range(2, len(out) + 3):
                if new not in out:
                    break
                new = f"{redact(str(base))}#{n}"
            out[new] = _field(key, value, deeper)
        return out
    if isinstance(obj, list | tuple):
        items = [redact_value(item, deeper) for item in obj]
        return items if isinstance(obj, list) else tuple(items)
    if isinstance(obj, set | frozenset):
        return type(obj)(redact_value(item, deeper) for item in obj)
    if isinstance(obj, bytes | bytearray):  # lossless: bytes that are not text survive as they are
        return type(obj)(redact(bytes(obj).decode("utf-8", "surrogateescape")).encode("utf-8", "surrogateescape"))
    raise TypeError(f"redact_value: cannot redact a {type(obj).__name__}")


_STANDARD = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime", "taskName"}


class RedactedError(Exception):
    """Stands in for a logged exception whose traceback text has been redacted (`str()` is that text)."""


def _log_safe(name: str, value: Any) -> Any:
    try:
        return _field(name, value, 0)
    except (TypeError, ValueError):
        return redact(repr(value))  # an object, or a tree too deep: its text, redacted


class RedactingFilter(logging.Filter):
    """Attach to a handler (PRD 16.1 rule 4: secrets never enter logs). Rewrites the record's message (after the
    %-arguments are applied; a non-string message too), its traceback and stack text, and any extra field (a secure
    field NAME, such as `extra={"password": ...}`, loses its value as a tree key does), so a formatter built on
    `logging.Formatter.format` emits no secret. `record.exc_info` is replaced by a redacted stand-in, so a formatter
    that calls `formatException(record.exc_info)` itself is safe too. Never drops a record and never raises: if
    redaction itself fails, the message is replaced whole."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg, record.args = redact(record.getMessage()), None
            if record.exc_info and not record.exc_text:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            if record.exc_text:
                record.exc_text = redact(record.exc_text)
                record.exc_info = (RedactedError, RedactedError(record.exc_text), None)
            record.stack_info = redact(record.stack_info) if record.stack_info else record.stack_info
            for name in set(vars(record)) - _STANDARD:
                setattr(record, name, _log_safe(name, getattr(record, name)))
        except Exception:  # noqa: BLE001 (a logger must not fail the caller; fail closed instead)
            record.msg, record.args, record.exc_info, record.exc_text, record.stack_info = (
                REDACTED,
                None,
                None,
                None,
                None,
            )
        return True
