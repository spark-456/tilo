"""The mail reader the production service gives the Drafter, the Autopilot and the plate reply (FR-CHN-10, FR-PA-07).

Those consumers read the thread reader contract (`drafting.ThreadReader`): `thread_id`, and per message `message_id`
(the Gmail message id, which no sender writes), `thread_id`, `from`, `to`, `cc`, `subject`, `body`, `date` and a
`headers` map and the body shape (`has_text_part`, `has_other_parts`, `attachments`). The connectors' Gmail read speaks
its own names (`id`, `body_text`; `message_id` there is the Message-ID
header), so this maps one to the other. It is read only and pure: it wraps any object with the connectors' two read
methods (production: an RPC client to tilo-connectors, never `GmailAdapter` in-process, SEC-02), has no send path, and
holds, logs and copies no mail text. Everything it returns is untrusted data.
"""

from __future__ import annotations

from typing import Any, Protocol


class GmailRead(Protocol):  # the connectors' Gmail read (FR-CON-04)
    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any]: ...
    def get_message(self, user_id: str, message_id: str) -> dict[str, Any]: ...


def reader_message(raw: dict[str, Any]) -> dict[str, Any]:
    """One message in the reader contract's names. A field the connector did not return stays absent or empty, so a
    consumer fails closed on it."""
    return {
        "message_id": raw.get("id"),
        "thread_id": raw.get("thread_id"),
        "from": raw.get("from", ""),
        "to": raw.get("to", []),
        "cc": raw.get("cc", []),
        "subject": raw.get("subject", ""),
        "body": raw.get("body_text", ""),
        "date": raw.get("date", ""),
        "headers": raw.get("headers", {}),
        # What the body is made of (absent text is not empty text); a message that lacks these is never "clean"
        "has_text_part": raw.get("has_text_part"),
        "has_other_parts": raw.get("has_other_parts"),
        "attachments": raw.get("attachments"),
    }


class ConnectorMailReader:
    """`ThreadReader` and `MailReader` over the connectors' Gmail read."""

    def __init__(self, gmail: GmailRead) -> None:
        self._gmail = gmail

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        raw = self._gmail.get_thread(user_id, thread_id)
        messages = raw.get("messages")
        return {
            "thread_id": raw.get("id", thread_id),
            "messages": [reader_message(m) for m in messages if isinstance(m, dict)]
            if isinstance(messages, list)
            else [],
        }

    def get_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        return reader_message(self._gmail.get_message(user_id, message_id))
