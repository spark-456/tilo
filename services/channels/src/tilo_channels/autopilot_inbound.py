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
_DMARC = re.compile(r"\bdmarc\b")
_VERDICT = re.compile(r"\bdmarc\s*=\s*([a-z]*)")


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
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if _AUTHSERV.fullmatch(value) else None


def inbound_is_clean(reader: ThreadReader, user_id: str, thread_id: str, in_reply_to: str) -> bool:
    """True only when the thread was read, exactly one message carries the draft's `in_reply_to` as its Message-ID,
    and that message has a body and a Subject that are plain with no inbound signal, and a DMARC pass. Never raises."""
    if not in_reply_to:
        return False
    try:
        listed = reader.get_thread(user_id, thread_id).get("messages")
        window = (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:]
        found = [m for m in window if message_id_of(m) == in_reply_to]
        if len(found) != 1:  # none, or an id that does not name one message: nothing can be called clean
            return False
        message = found[0]
        text = (message["body"], message["subject"])
        return all(isinstance(t, str) and inbound_plain(t) and not inbound_signal(t) for t in text) and _dmarc_pass(
            message, trusted_authserv_id()
        )
    except Exception:  # an unreadable thread or a malformed message: no undo window
        return False


def _dmarc_pass(message: dict[str, Any], trusted: str | None) -> bool:
    """True when the Authentication-Results header is text written by the trusted server (its authserv-id, the text
    before the first ";", is `trusted`), with at least one DMARC verdict and every one "pass". No trusted id, another
    or no id, a `dmarc` token with no verdict, any other verdict, a pass beside a failure, a missing or non-text header
    (or two keys that differ only by case): False."""
    value = headers_of(message).get(AUTH_HEADER)
    if not trusted or not isinstance(value, str):
        return False
    server, separator, results = value.partition(";")
    if not separator or server.strip().lower() != trusted:
        return False
    lowered = results.lower()
    verdicts = _VERDICT.findall(lowered)
    return bool(verdicts) and set(verdicts) == {"pass"} and len(verdicts) == len(_DMARC.findall(lowered))
