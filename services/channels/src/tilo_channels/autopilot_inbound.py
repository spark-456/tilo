"""tilo_channels.autopilot_inbound: may a draft ride L2 given the message it answers? (FR-CHN-11, ADR-0013, BQ-223).

The replied-to message is the thread message whose Message-ID header equals the draft's `in_reply_to`, compared the
way the Drafter wrote it (`_reply_header`). Only that message counts, not earlier or quoted ones (a quote inside its
body does). It is read through the Autopilot's own thread reader and checked with `inbound_signal`: no model, no
network of its own. Every doubt fails closed: an empty `in_reply_to`, an unreadable or empty thread, a Message-ID that
names no message, a body that is not text, or a signal in the body all mean "ask a person".
"""

from __future__ import annotations

from typing import Any

from tilo_channels.autopilot_t3 import inbound_signal
from tilo_channels.drafting import MAX_MESSAGES, ThreadReader, _reply_header


def inbound_is_clean(reader: ThreadReader, user_id: str, thread_id: str, in_reply_to: str) -> bool:
    """True only when the thread was read, a message carries the draft's `in_reply_to` as its Message-ID, and every
    message that does (a duplicate id is not trusted) has a body with no money, legal, commitment or obfuscation
    signal. Never raises."""
    if not in_reply_to:
        return False
    try:
        listed = reader.get_thread(user_id, thread_id).get("messages")
        found = [
            m for m in (listed if isinstance(listed, list) else [])[-MAX_MESSAGES:] if _message_id(m) == in_reply_to
        ]
        return bool(found) and all(isinstance(m["body"], str) and not inbound_signal(m["body"]) for m in found)
    except Exception:  # an unreadable thread or a malformed message: no undo window
        return False


def _message_id(message: Any) -> str:
    headers = message.get("headers") if isinstance(message, dict) else None
    lowered = {str(k).lower(): v for k, v in headers.items()} if isinstance(headers, dict) else {}
    return _reply_header(lowered.get("message-id"))
