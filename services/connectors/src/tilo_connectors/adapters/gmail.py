"""GmailAdapter: reads at gmail.readonly; drafts and sends only as outbox side effects (FR-CON-04, FR-CHN-13,
OB-03, SEC-03). Mail content is untrusted data: returned verbatim with `untrusted: True`, never logged or
acted on. A side effect's audience is exactly the entry's recipients; no artifact or thread text adds a header."""

from __future__ import annotations

import base64
import email
import email.policy
import email.utils
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from email.message import EmailMessage
from typing import Any

from ..outbox import Grant
from ._google import RESOURCE_ID, GoogleAdapter, checked_id, side_effect_marker
from ._transport import AdapterError, SideEffectRefused

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # total attachment bytes per message (Gmail's limit)
BLOCKED_ATTACHMENT_EXTENSIONS: frozenset[str] = frozenset(  # Gmail's blocked file types
    ".ade .adp .apk .appx .appxbundle .bat .cab .chm .cmd .com .cpl .diagcab .diagcfg .diagpack .dll .dmg .ex .ex_"
    " .exe .hta .img .ins .iso .isp .jar .jnlp .js .jse .lib .lnk .mde .msc .msi .msix .msixbundle .msp .mst .nsh"
    " .pif .ps1 .scr .sct .shb .sys .vb .vbe .vbs .vhd .vxd .wsc .wsf .wsh .xll".split()
)
_CAPABILITY = {"create_draft": "write", "send_email": "send"}
_ADDRESS = re.compile(r"[^@\s,;:<>()\[\]\"\\]+@[^@\s,;:<>()\[\]\"\\]+")
_MSG_ID = re.compile(r"<[^<>\s]+>")
_MIME = re.compile(r"[A-Za-z0-9][\w.+-]*/[\w.+-]+")
_RE_PREFIX = re.compile(r"^(\s*re\s*:\s*)+", re.I)
_CHARSET = re.compile(r"charset=\"?([\w.:-]+)", re.I)
_TOPIC = re.compile(r"projects/[a-z][a-z0-9.:-]{4,62}/topics/[A-Za-z][\w.~+%-]{2,254}")  # Pub/Sub resource names


class GmailAdapter(GoogleAdapter):
    def __init__(self, *, max_attachment_bytes: int = MAX_ATTACHMENT_BYTES, **common: Any) -> None:
        super().__init__(**common)  # declaration, broker, transport, artifacts, owner_of, clock, emit, sleep, ...
        self._max_attachment_bytes = max_attachment_bytes

    def list_threads(  # reads need no grant: nothing leaves the mailbox
        self, user_id: str, *, label_ids: Iterable[str] = (), max_results: int = 20, page_token: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": self._batch(max_results), "pageToken": page_token}
        if labels := [str(label) for label in label_ids]:
            params["labelIds"] = labels
        return self._threads(user_id, "read", params)

    def search_threads(
        self, user_id: str, query: str, *, max_results: int = 20, page_token: str | None = None
    ) -> dict[str, Any]:
        params = {"q": str(query), "maxResults": self._batch(max_results), "pageToken": page_token}
        return self._threads(user_id, "search", params)

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        body = self._get(user_id, self._scopes("read"), f"/threads/{checked_id(thread_id)}", {"format": "full"})
        return {"id": str(body.get("id", thread_id)), "messages": [_message(m) for m in body.get("messages") or []]}

    def get_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        path = f"/messages/{checked_id(message_id)}"
        return _message(self._get(user_id, self._scopes("read"), path, {"format": "full"}))

    def list_labels(self, user_id: str) -> list[dict[str, Any]]:
        labels = self._get(user_id, self._scopes("read"), "/labels").get("labels") or []
        return [{k: str(x.get(k, "")) for k in ("id", "name", "type")} for x in labels]

    # FR-CHN-08 watch seam (tilo_channels.gmail_watch.Mailbox): reads of the user's own mailbox at the read
    # scope; nothing leaves it, so no outbox entry, no grant and no event. Ids only, never message content.
    def watch(self, user_id: str, *, topic_name: str, label_ids: Iterable[str]) -> dict[str, Any]:
        if not isinstance(topic_name, str) or not _TOPIC.fullmatch(topic_name):
            raise AdapterError("not a Pub/Sub topic name")
        body = {"topicName": topic_name, "labelIds": [str(x) for x in label_ids], "labelFilterBehavior": "include"}
        answer = self._json(user_id, self._scopes("read"), "POST", GMAIL_API + "/watch", json=body)
        try:
            return {"history_id": _history_id(answer.get("historyId")), "expiration": int(answer["expiration"]) / 1000}
        except (KeyError, TypeError, ValueError):
            raise AdapterError("Google answered an unexpected watch") from None

    def stop_watch(self, user_id: str) -> None:
        self._call(user_id, self._scopes("read"), "POST", GMAIL_API + "/stop")

    def list_history(self, user_id: str, start_history_id: str, *, page_token: str | None = None) -> dict[str, Any]:
        """INBOX messages added after `start_history_id`, oldest first. A 404 (the start id is older than
        the history Gmail keeps) raises AdapterError with `.status == 404`, once, with no retry."""
        params = {
            "startHistoryId": _history_id(start_history_id),
            "historyTypes": "messageAdded",
            "labelId": "INBOX",
            "pageToken": page_token,
        }
        body = self._get(user_id, self._scopes("read"), "/history", {k: v for k, v in params.items() if v is not None})
        added = [a.get("message") or {} for h in body.get("history") or [] for a in h.get("messagesAdded") or []]
        return {
            "history_id": _history_id(body.get("historyId")),
            "message_ids": [m["id"] for m in added if RESOURCE_ID.fullmatch(str(m.get("id", "")))],
            "next_page_token": body.get("nextPageToken") or None,
        }

    def recent_inbox(self, user_id: str, *, max_results: int) -> dict[str, Any]:
        """The current history id, read first, then the newest INBOX message ids (newest first)."""
        scopes = self._scopes("read")
        history_id = _history_id(self._get(user_id, scopes, "/profile").get("historyId"))
        params = {"labelIds": ["INBOX"], "maxResults": self._batch(max_results)}
        listed = self._get(user_id, scopes, "/messages", params).get("messages") or []
        ids = [str(m.get("id", "")) for m in listed]
        return {"history_id": history_id, "message_ids": [i for i in ids if RESOURCE_ID.fullmatch(i)]}

    def _threads(self, user_id: str, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v is not None}
        body = self._get(user_id, self._scopes(capability), "/threads", query)
        threads = [{k: str(t.get(k, "")) for k in ("id", "snippet")} for t in body.get("threads") or []]
        return {"threads": threads, "next_page_token": body.get("nextPageToken")}

    def _get(
        self, user_id: str, scopes: list[str], path: str, params: Any = None, patient: bool = True
    ) -> dict[str, Any]:
        return self._json(user_id, scopes, "GET", GMAIL_API + path, params=params, patient=patient)

    def execute_side_effect(self, entry: Mapping[str, Any], grant: Grant) -> dict[str, Any]:  # the only one (SEC-03)
        self._check_grant(entry, grant)
        return self._final_on_rejection(lambda: self._draft_or_send(entry))

    def _draft_or_send(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        capability = _CAPABILITY.get(str(entry.get("action_type")))
        if capability is None:
            raise SideEffectRefused("gmail has no side effect for this action")
        item = self._artifact(entry.get("item"), "email")
        subject, text = item.get("subject"), item.get("body_text")
        if not _sendable(subject) or not _sendable(text) or _has_control(str(subject)):
            raise SideEffectRefused("the email text cannot be sent as written")
        recipients = list(entry.get("recipients") or [])
        if not recipients or not all(isinstance(r, str) and _ADDRESS.fullmatch(r) for r in recipients):
            raise SideEffectRefused("the recipients cannot be used")
        if _to_round_trip(recipients) != recipients:  # nothing re-encoded or re-read: To is exactly these
            raise SideEffectRefused("the recipients cannot be used")
        files = [self._artifact(ref, "file") for ref in entry.get("attachments") or []]
        self._check_attachments(files)
        thread_id = entry.get("destination")
        if thread_id is not None and not (isinstance(thread_id, str) and RESOURCE_ID.fullmatch(thread_id)):
            raise SideEffectRefused("the destination is not a thread id")

        user = self._owner_of(str(entry["world_id"]))
        scopes = self._scopes(capability, "read")  # read: the thread headers and the earlier-attempt lookup
        message_id = f"<tilo.{side_effect_marker(entry)}@tilo.invalid>"
        if (earlier := self._earlier_attempt(user, scopes, capability, message_id)) is not None:
            return earlier  # OB-03: a lost response, a crash or another instance already did it
        msg = EmailMessage()
        msg["To"] = ", ".join(recipients)  # exactly the approved audience: no Cc, no Bcc, no Reply-To
        msg["Message-ID"] = message_id
        if thread_id is None:
            msg["Subject"] = subject
        else:
            self._reply_headers(user, scopes, thread_id, msg)
        try:  # final, not retried for ever: text the MIME writer cannot encode never becomes sendable
            msg.set_content(text)
            for f in files:
                mime = str(f.get("mime_type", ""))
                main, sub = (mime if _MIME.fullmatch(mime) else "application/octet-stream").split("/", 1)
                msg.add_attachment(bytes(f["content"]), maintype=main, subtype=sub, filename=_safe_name(f["name"]))
            raw = {"raw": base64.urlsafe_b64encode(msg.as_bytes(policy=email.policy.SMTP)).decode("ascii")}
        except (UnicodeError, ValueError, TypeError):
            raise SideEffectRefused("the email cannot be encoded as written") from None
        if thread_id is not None:
            raw["threadId"] = thread_id
        if capability == "write":
            draft = self._json(user, scopes, "POST", GMAIL_API + "/drafts", json={"message": raw}, patient=False)
            return _result(draft.get("id"), draft.get("message"))
        sent = self._json(user, scopes, "POST", GMAIL_API + "/messages/send", json=raw, patient=False)
        return _result(sent.get("id"), sent)

    def _check_attachments(self, files: list[Mapping[str, Any]]) -> None:
        total = 0
        for f in files:
            name, content = f.get("name"), f.get("content")
            if not isinstance(name, str) or not isinstance(content, bytes | bytearray) or not _sendable(name):
                raise SideEffectRefused("an attachment cannot be read")
            if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in name):  # NUL, ZWSP, RLO, ...
                raise SideEffectRefused("an attachment's name has hidden characters")
            # The name actually sent, cut at ':' (NTFS streams); "a.exe." and "a.exe " open as .exe on Windows.
            trimmed = _safe_name(name).split(":", 1)[0].rstrip().rstrip(". ").lower()
            if "." in trimmed and "." + trimmed.rsplit(".", 1)[1] in BLOCKED_ATTACHMENT_EXTENSIONS:
                raise SideEffectRefused("an attachment's file type is blocked")
            total += len(content)
        if total > self._max_attachment_bytes:
            raise SideEffectRefused("the attachments are over the size limit")

    def _earlier_attempt(self, user: str, scopes: list[str], capability: str, message_id: str) -> dict[str, Any] | None:
        """Only Tilo's own drafts or sent mail count: a received message with that Message-ID never does."""
        query = f"rfc822msgid:{message_id.strip('<>')}"
        if capability == "write":
            drafts = self._get(user, scopes, "/drafts", {"q": query}, patient=False).get("drafts") or []
            return _result(drafts[0].get("id"), drafts[0].get("message")) if drafts else None
        sent = self._get(user, scopes, "/messages", {"q": query + " in:sent"}, patient=False).get("messages") or []
        return _result(sent[0].get("id"), sent[0]) if sent else None

    def _reply_headers(self, user: str, scopes: list[str], thread_id: str, msg: EmailMessage) -> None:
        """Subject, In-Reply-To and References from the thread's last message; its Reply-To is ignored."""
        thread = self._get(user, scopes, f"/threads/{thread_id}", {"format": "metadata"}, patient=False)
        messages = [m for m in thread.get("messages") or [] if "DRAFT" not in (m.get("labelIds") or [])]
        if not messages:
            raise SideEffectRefused("the thread has no message to reply to")
        headers = _headers(messages[-1].get("payload") or {})
        msg["Subject"] = "Re: " + _RE_PREFIX.sub("", _no_control(headers.get("subject", ""))).strip()
        if last_id := _MSG_ID.findall(headers.get("message-id", ""))[:1]:
            msg["In-Reply-To"] = last_id[0]
            msg["References"] = " ".join(_MSG_ID.findall(headers.get("references", ""))[-20:] + last_id)  # bounded


def _history_id(value: Any) -> str:
    """A Gmail history id: ASCII decimal digits (an unsigned 64-bit number), as a string."""
    text = str(value) if isinstance(value, str | int) and not isinstance(value, bool) else ""
    if not (0 < len(text) <= 20 and text.isascii() and text.isdigit() and int(text) < 2**64):
        raise AdapterError("not a history id")
    return text


def _result(resource_id: Any, message: Any) -> dict[str, Any]:
    thread_id = message.get("threadId", "") if isinstance(message, dict) else ""
    return {"id": str(resource_id or ""), "thread_id": str(thread_id)}


def _sendable(text: Any) -> bool:
    """A str that UTF-8 can encode (no lone surrogate)."""
    try:
        return isinstance(text, str) and text.encode("utf-8") is not None
    except UnicodeEncodeError:
        return False


def _to_round_trip(recipients: list[str]) -> list[str]:
    """The addresses a mail reader parses back out of the To header as written. Printable ASCII only; an
    address the writer re-encodes (RFC 2047 inside the address) or splits never matches."""
    if not all(c.isascii() and c.isprintable() for r in recipients for c in r):
        return []
    probe = EmailMessage()
    probe["To"] = ", ".join(recipients)
    parsed = email.message_from_bytes(probe.as_bytes(policy=email.policy.SMTP), policy=email.policy.default)
    return [a.addr_spec for a in parsed["To"].addresses]


def _has_control(text: str) -> bool:
    return _no_control(text) != text


def _no_control(text: str) -> str:  # CR, LF and other controls and line breaks become spaces
    return "".join(" " if unicodedata.category(c) in ("Cc", "Zl", "Zp") else c for c in text)


def _safe_name(name: str) -> str:
    return _no_control(name).replace("/", "_").replace("\\", "_").strip() or "attachment"


def _headers(payload: Mapping[str, Any]) -> dict[str, str]:
    """Header name (lower-case) -> value; the first occurrence wins."""
    out: dict[str, str] = {}
    for h in payload.get("headers") or []:
        out.setdefault(str(h.get("name", "")).lower(), str(h.get("value", "")))
    return out


def _parts(part: Mapping[str, Any]) -> Iterator[Mapping[str, Any]]:
    yield part
    for child in part.get("parts") or []:
        yield from _parts(child)


def _addresses(value: str) -> list[str]:
    return [addr for _, addr in email.utils.getaddresses([value]) if addr] if value else []


def _decoded(part: Mapping[str, Any]) -> str:
    data = str((part.get("body") or {}).get("data", ""))
    raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    charset = _CHARSET.search(_headers(part).get("content-type", ""))
    try:
        return raw.decode(charset.group(1) if charset else "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _attachment(part: Mapping[str, Any]) -> dict[str, Any]:
    size = int((part.get("body") or {}).get("size", 0))
    return {"filename": str(part["filename"]), "mime_type": str(part.get("mimeType", "")), "size": size}


def _message(resource: Mapping[str, Any]) -> dict[str, Any]:
    payload = resource.get("payload") or {}
    headers = _headers(payload)
    parts = list(_parts(payload))
    text = next((p for p in parts if p.get("mimeType") == "text/plain" and not p.get("filename")), None)
    return {
        "id": str(resource.get("id", "")),
        "thread_id": str(resource.get("threadId", "")),
        "from": headers.get("from", ""),
        "date": headers.get("date", ""),
        "to": _addresses(headers.get("to", "")),
        "cc": _addresses(headers.get("cc", "")),
        "subject": headers.get("subject", ""),
        "message_id": headers.get("message-id", "").strip(),
        "label_ids": [str(x) for x in resource.get("labelIds") or []],
        "body_text": _decoded(text) if text is not None else "",
        "attachments": [_attachment(p) for p in parts if p.get("filename")],
        "untrusted": True,
    }
