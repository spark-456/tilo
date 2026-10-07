"""tilo_channels.autopilot_inbound: may a draft ride L2 given the message it answers? (FR-CHN-11, ADR-0013, BQ-274).

The replied-to message is the thread message whose Message-ID header equals the draft's `in_reply_to`, compared the
way the Drafter wrote it (`message_id_of`). Only that message counts, not earlier or quoted ones (a quote inside its
body does). It is read through the Autopilot's own thread reader: no model, no network of its own. L2 needs all of:
exactly one message with that Message-ID (a shared id names no one message), a body and a Subject that are text, are
`inbound_plain` (structurally plain: ASCII letters, stop marks, contractions and times of day only) and have no
`inbound_signal` (money, legal, commitment, amounts, obfuscation), and an Authentication-Results header written by the
configured server (`config/mail_trust.yaml`; its authserv-id, the text before the first ";") with a DMARC pass (a
spoofed sender is not the person the reply goes to; a header the sender wrote is not believed). Header names are matched
without regard to case; two keys differing only by case fail closed. Every doubt fails closed and means "ask a
person": an empty `in_reply_to`, an unreadable or empty thread, a Message-ID that names no message or more than
one, a message older than the MAX_MESSAGES window, a field that is not text, not plain, a signal, or no clear DMARC
pass. Real mail with a link, a quoted line, a hyphen, a digit or a non-ASCII character therefore waits at L1.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from tilo_channels.autopilot_t3 import inbound_plain, inbound_signal
from tilo_channels.drafting import MAX_MESSAGES, ThreadReader, headers_of, message_id_of

AUTH_HEADER = "authentication-results"  # lower-cased: names are matched without regard to case (`headers_of`)
CONFIG_PATH = Path(__file__).resolve().parents[4] / "config" / "mail_trust.yaml"
_AUTHSERV = re.compile(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?")
AUTH_CAP = 8_000  # characters; a longer header is not read
_METHOD = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]*")  # the method of a resinfo clause (RFC 8601)
_RESULT = re.compile(r"\s*(?:/\s*[0-9]+\s*)?=\s*([A-Za-z]+)(?=\s|$)")  # "=pass", after the method


def trusted_authserv_id() -> str | None:
    """The authserv-id whose Authentication-Results header is believed (`config/mail_trust.yaml`, trimmed and lower-
    cased), or None when the file is missing, unreadable or does not hold one name: then nothing is trusted."""
    return _configured_id(CONFIG_PATH)


@lru_cache(maxsize=8)
def _configured_id(path: Path) -> str | None:
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    value = doc.get("gmail_authserv_id") if isinstance(doc, dict) else None
    value = value.strip() if isinstance(value, str) else ""
    value = value.lower() if value.isascii() else ""  # ASCII only: Unicode lower-casing folds U+212A to "k"
    return value if _AUTHSERV.fullmatch(value) else None


def inbound_is_clean(reader: ThreadReader, user_id: str, thread_id: str | None, in_reply_to: str) -> bool:
    """True only when the thread was read, exactly one message carries the draft's `in_reply_to` as its Message-ID,
    and that message has a body and a Subject that are plain with no inbound signal, and a DMARC pass. Never raises."""
    if not in_reply_to or not isinstance(thread_id, str) or not thread_id:  # no thread: nothing to be clean
        return False
    try:
        listed = reader.get_thread(user_id, thread_id).get("messages")
        window = (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:]
        found = [m for m in window if message_id_of(m) == in_reply_to]
        if len(found) != 1:  # none, or an id that does not name one message: nothing can be called clean
            return False
        message = found[0]
        text = (message["body"], message["subject"])
        return (
            _text_only(message)
            and all(isinstance(t, str) and inbound_plain(t) and not inbound_signal(t) for t in text)
            and _dmarc_pass(message, trusted_authserv_id())
        )
    except Exception:  # an unreadable thread or a malformed message: no undo window
        return False


def _text_only(message: dict[str, Any]) -> bool:
    """True only for a message that is one plain-text body: a text/plain part exists (absent text is not empty
    text), no other body part (HTML, a second text part, an inline image) and no attachment. The reader carries these
    as `has_text_part`, `has_other_parts` and `attachments`; a message that lacks them is not text-only."""
    return (
        message.get("has_text_part") is True
        and message.get("has_other_parts") is False
        and message.get("attachments") == []
    )


def _clauses(value: str) -> list[str] | None:
    """The header split as RFC 8601 does, for a value with no quote or backslash (`_dmarc_pass` refuses those):
    nested comments are dropped and ";" splits only outside them. None when a comment is unbalanced."""
    clauses: list[str] = []
    current: list[str] = []
    depth = 0
    for c in value:
        if depth:
            depth += (c == "(") - (c == ")")
        elif c == "(":
            depth = 1
            current.append(" ")
        elif c == ")":
            return None
        elif c == ";":
            clauses.append("".join(current))
            current = []
        else:
            current.append(c)
    return None if depth else [*clauses, "".join(current)]


def _dmarc_pass(message: dict[str, Any], trusted: str | None) -> bool:
    """True when the Authentication-Results header is text written by the trusted server (its authserv-id, the text
    before the first top-level ";", is `trusted`, compared as ASCII) and holds at least one top-level `dmarc` clause
    (a clause whose method is exactly `dmarc`) and every such clause is "pass". Text inside a comment or another
    method's clause (Gmail copies the envelope sender's local part into its spf clause, and an arc comment) is never
    a verdict. No trusted id, another or no id, a value with a quote or a backslash, an unbalanced comment, a `dmarc`
    clause with no result, any other result, a pass beside a failure, no dmarc clause, a missing or non-text header
    (or two keys that differ only by case): False."""
    value = headers_of(message).get(AUTH_HEADER)
    if not trusted or not isinstance(value, str) or len(value) > AUTH_CAP:
        return False
    # A quote opens a string at top level but is plain text inside a comment, and the sender's text is copied into both
    # (the spf comment and smtp.mailfrom), so a parser can be desynchronised. Gmail's own syntax needs neither a quote
    # nor a backslash: a value that holds one is not read.
    if '"' in value or "\\" in value:
        return False
    clauses = _clauses(value)
    if clauses is None or len(clauses) < 2:
        return False
    server = clauses[0].strip()
    if not server.isascii() or server.lower() != trusted:
        return False
    verdicts: list[str] = []
    for clause in clauses[1:]:
        clause = clause.strip()
        method = _METHOD.match(clause)
        if method and method.group(0).lower() == "dmarc":
            result = _RESULT.match(clause[method.end() :])
            verdicts.append(result.group(1).lower() if result else "")
    return bool(verdicts) and set(verdicts) == {"pass"}
