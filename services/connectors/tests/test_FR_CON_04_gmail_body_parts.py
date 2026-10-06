"""FR-CON-04 / FR-CHN-11 (BQ-278 n fix pass): the Gmail message says what its body is made of.

`body_text` is "" both for a message with no text/plain part (HTML-only) and for an empty one, so the channels gate
cannot tell them apart from it. The message therefore also carries `has_text_part` (a text/plain part with no filename
exists) and `has_other_parts` (a leaf part that is neither that text part nor an attachment: text/html, a second
text/plain, an inline image). `attachments` already lists the files.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from tilo_connectors.adapters.gmail import _message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _plain(text: str = "Hello") -> dict[str, Any]:
    return {"mimeType": "text/plain", "headers": [], "body": {"data": _b64(text)}}


def _html(text: str = "<p>Hello</p>") -> dict[str, Any]:
    return {"mimeType": "text/html", "headers": [], "body": {"data": _b64(text)}}


def _pdf() -> dict[str, Any]:
    return {
        "mimeType": "application/pdf",
        "filename": "a.pdf",
        "headers": [],
        "body": {"attachmentId": "a1", "size": 9},
    }


def _msg(payload: dict[str, Any]) -> dict[str, Any]:
    return _message({"id": "g1", "threadId": "t1", "labelIds": ["INBOX"], "payload": payload})


def _multi(kind: str, *parts: dict[str, Any]) -> dict[str, Any]:
    return {"mimeType": kind, "headers": [], "parts": list(parts)}


@pytest.mark.parametrize(
    ("payload", "text", "other", "files"),
    [
        (_plain(), True, False, 0),
        (_multi("multipart/mixed", _plain(), _pdf()), True, False, 1),
        (_html(), False, True, 0),
        (_multi("multipart/alternative", _plain(), _html()), True, True, 0),
        (_multi("multipart/alternative", _html(), _plain()), True, True, 0),
        (_multi("multipart/alternative", _plain("a"), _plain("b")), True, True, 0),
        (_multi("multipart/mixed", _html(), _pdf()), False, True, 1),
        (_multi("multipart/related", _multi("multipart/alternative", _plain(), _html())), True, True, 0),
        (_multi("multipart/mixed"), False, False, 0),
        ({"mimeType": "application/pdf", "headers": [], "body": {"size": 3}}, False, True, 0),
    ],
    ids=[
        "plain",
        "plain_and_pdf",
        "html_only",
        "alternative",
        "alternative_html_first",
        "two_plain_parts",
        "html_and_pdf",
        "nested_alternative",
        "no_leaf",
        "unnamed_binary",
    ],
)
def test_FR_CON_04_message_says_what_its_body_is_made_of(payload: dict, text: bool, other: bool, files: int) -> None:
    msg = _msg(payload)

    assert msg["has_text_part"] is text
    assert msg["has_other_parts"] is other
    assert len(msg["attachments"]) == files


def test_FR_CON_04_an_html_only_message_has_an_empty_body_text_and_no_text_part() -> None:
    msg = _msg(_html("<p>Please confirm the transfer of $5,000.</p>"))

    assert msg["body_text"] == "" and msg["has_text_part"] is False
