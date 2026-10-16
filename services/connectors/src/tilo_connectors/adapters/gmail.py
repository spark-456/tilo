"""GmailAdapter: reads at gmail.readonly; drafts and sends only as outbox side effects (FR-CON-04, FR-CHN-13,
OB-03, SEC-03). Mail content is untrusted data: returned verbatim with `untrusted: True`, never logged or
acted on. A side effect's audience is exactly the entry's recipients; no artifact or thread text adds a header."""

from __future__ import annotations

import base64
import email
import email.policy
import email.utils
import html
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC
from email.header import decode_header, make_header
from email.message import EmailMessage
from typing import Any

from .._time import format_ts
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
_KEPT_HEADERS = ("message-id", "in-reply-to", "references", "authentication-results")  # what channels reads
_CHARSET = re.compile(r"charset=\"?([\w.:-]+)", re.I)
BODY_CAP = 20_000  # characters of a message's text an agent reads (meeting_host_rpc read_email_result)
SUMMARY_FIELDS = "id,threadId,snippet,labelIds,payload/headers"
_GMAIL_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_HTML_SCAN = 400_000  # characters of an HTML part looked at
_HIDDEN_TAGS = frozenset({"script", "style", "head", "title"})
_BREAK_TAGS = frozenset({"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "blockquote"})
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

    def get_message(self, user_id: str, message_id: str, *, headers: Iterable[str] | None = None) -> dict[str, Any]:
        """The message; with `headers`, only those headers come back (format=metadata: no body leaves Google)."""
        params: dict[str, Any] = {"format": "full"}
        if headers is not None:
            params = {"format": "metadata", "metadataHeaders": [str(h) for h in headers]}
        return _message(self._get(user_id, self._scopes("read"), f"/messages/{checked_id(message_id)}", params))

    # ADR-0048 agent tools: reads at gmail.readonly, closed results (the contract's `search_email_result` and the like).
    def search_messages(self, user_id: str, query: str, *, max_results: int = 10) -> dict[str, Any]:
        """At most `max_results` summaries, newest first: the ids by Gmail's own search, then each message as metadata
        (From, Subject, Date and the snippet; no body leaves Google). A message that vanished meanwhile is skipped."""
        scopes = self._scopes("search")
        listed = self._get(user_id, scopes, "/messages", {"q": str(query), "maxResults": self._batch(max_results)})
        found: list[dict[str, Any]] = []
        for ref in (listed.get("messages") or [])[:max_results]:
            params = {"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"], "fields": SUMMARY_FIELDS}
            try:
                found.append(_summary(self._get(user_id, scopes, f"/messages/{checked_id(ref.get('id'))}", params)))
            except AdapterError as exc:
                if exc.status != 404:
                    raise
        return {"messages": found}

    def read_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        """One message: headers, its text (the text/plain part, else its HTML with the tags taken out), attachment
        names only. Attachment bytes are never requested."""
        resource = self._get(user_id, self._scopes("read"), f"/messages/{checked_id(message_id)}", {"format": "full"})
        try:
            return _readable(resource)
        except (ValueError, KeyError, TypeError):
            raise AdapterError("Google answered an unexpected message") from None

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
        return self._done(self._final_on_rejection(lambda: self._draft_or_send(entry)))

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
            self._reply_headers(user, scopes, thread_id, msg, item)
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

    def _reply_headers(
        self, user: str, scopes: list[str], thread_id: str, msg: EmailMessage, item: Mapping[str, Any]
    ) -> None:
        """Subject, In-Reply-To and References. An item that names the message it answers (`in_reply_to`, FR-CHN-13,
        BQ-185) gets exactly its own subject and headers, nothing read from the thread at send time; one that is not a
        single message id is refused. Otherwise they come from the thread's last message; its Reply-To is ignored."""
        if "in_reply_to" in item:
            target = item["in_reply_to"]
            if not isinstance(target, str) or _msg_ids(target) != [target]:
                raise SideEffectRefused("the message this reply answers is not named")
            msg["Subject"] = item["subject"]
            msg["In-Reply-To"] = target
            msg["References"] = " ".join(_msg_ids(str(item.get("references", "")))[-20:] or [target])  # bounded
            return
        thread = self._get(user, scopes, f"/threads/{thread_id}", {"format": "metadata"}, patient=False)
        messages = [m for m in thread.get("messages") or [] if "DRAFT" not in (m.get("labelIds") or [])]
        if not messages:
            raise SideEffectRefused("the thread has no message to reply to")
        headers = _headers(messages[-1].get("payload") or {})
        msg["Subject"] = "Re: " + _RE_PREFIX.sub("", _no_control(headers.get("subject", ""))).strip()
        if last_id := _MSG_ID.findall(headers.get("message-id", ""))[:1]:
            msg["In-Reply-To"] = last_id[0]
            msg["References"] = " ".join(_MSG_ID.findall(headers.get("references", ""))[-20:] + last_id)  # bounded


_TAG = re.compile(r"</?([A-Za-z][A-Za-z0-9]{0,15})")


def _text_of_html(markup: str) -> str:
    """HTML to text in one linear pass of `str.find` (not `HTMLParser`, whose tag and comment scanning backtracks on
    hostile input): comments, scripts, styles, head and title are dropped, block tags become line breaks, entities are
    decoded. Every step moves forward or stops, so the cost is linear in the (capped) input."""
    doc = markup[:_HTML_SCAN]
    low = doc.lower()
    out: list[str] = []
    i = 0
    while i < len(doc):
        j = doc.find("<", i)
        if j == -1:
            out.append(doc[i:])
            break
        out.append(doc[i:j])
        if doc.startswith("<!--", j):
            k = doc.find("-->", j + 4)
            if k == -1:
                break
            i = k + 3
            continue
        tag = _TAG.match(doc, j)
        if tag is None:
            if doc.startswith(("<!", "<?", "</"), j):  # a doctype, an instruction or a stray end tag
                k = doc.find(">", j)
                if k == -1:
                    break
                i = k + 1
            else:  # a lone "<" is doc
                out.append("<")
                i = j + 1
            continue
        k = doc.find(">", tag.end())
        if k == -1:
            break
        name, i = tag.group(1).lower(), k + 1
        if name in _BREAK_TAGS:
            out.append("\n")
        if name in _HIDDEN_TAGS and doc[j + 1] != "/":  # drop everything up to its end tag
            end = low.find("</" + name, i)
            close = doc.find(">", end) if end != -1 else -1
            if close == -1:
                break
            i = close + 1
    return re.sub(r"\n\s*\n+", "\n\n", html.unescape("".join(out))).strip()


def _line(value: str, cap: int) -> str:
    """A header value as one line of at most `cap` characters: RFC 2047 words decoded, controls folded to spaces."""
    try:
        value = str(make_header(decode_header(value)))
    except (UnicodeError, ValueError, LookupError):
        pass
    return " ".join(_no_control(value).split())[:cap]


def _clean_body(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) not in ("Cc", "Cs"))


def _shaped(value: Any) -> str:
    if not isinstance(value, str) or not _GMAIL_ID.fullmatch(value):
        raise AdapterError("Google answered an id that is not an id")
    return value


def _utc(value: str) -> str | None:
    try:
        moment = email.utils.parsedate_to_datetime(value)
        return format_ts(moment if moment.tzinfo else moment.replace(tzinfo=UTC))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _summary(resource: Mapping[str, Any]) -> dict[str, Any]:
    headers = _headers(resource.get("payload") or {})
    return {
        "id": _shaped(resource.get("id")),
        "thread_id": _shaped(resource.get("threadId")),
        "sender": _line(headers.get("from", ""), 320),
        "subject": _line(headers.get("subject", ""), 300),
        "date": _utc(headers.get("date", "")),
        "snippet": _line(html.unescape(str(resource.get("snippet", ""))), 300),
        "unread": "UNREAD" in (resource.get("labelIds") or []),
    }


def _readable(resource: Mapping[str, Any]) -> dict[str, Any]:
    message = _message(resource)
    kind, text = "none", ""
    if message["has_text_part"]:
        kind, text = "text", _clean_body(message["body_text"])
    else:
        pages = (p for p in _parts(resource.get("payload") or {}) if p.get("mimeType") == "text/html")
        page = next((p for p in pages if not p.get("filename") and "data" in (p.get("body") or {})), None)
        if page is not None:
            kind, text = "html_stripped", _clean_body(_text_of_html(_decoded(page)))
    cut = len(text) > BODY_CAP
    return {
        "id": _shaped(message["id"]),
        "thread_id": _shaped(message["thread_id"]),
        "sender": _line(message["from"], 320),
        "to": [a[:320] for a in message["to"][:50]],
        "cc": [a[:320] for a in message["cc"][:50]],
        "subject": _line(message["subject"], 300),
        "date": _utc(message["date"]),
        "body_text": text[:BODY_CAP],
        "body_kind": kind,
        "truncated": cut,
        "attachments": [
            {"filename": _line(a["filename"], 255), "mime_type": a["mime_type"][:255], "size": max(0, a["size"])}
            for a in message["attachments"][:20]
        ],
    }


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


def _msg_ids(text: str) -> list[str]:
    """The <id> tokens of a header value, printable ASCII only."""
    return [i for i in _MSG_ID.findall(text) if i.isascii() and i.isprintable()]


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
    if text is not None and ((text.get("body") or {}).get("attachmentId") or "data" not in (text.get("body") or {})):
        text = None  # its content is served separately (or absent): not text this message carries; it counts as "other"
    # What the body is made of, so a reader can tell "no text part" (HTML-only) from "empty text": a leaf part that is
    # neither the text part nor a named file (text/html, a second text/plain, an inline image) is "other".
    leaves = [p for p in parts if not (str(p.get("mimeType", "")).startswith("multipart/") or p.get("parts"))]
    other = [p for p in leaves if p is not text and not p.get("filename")]
    return {
        "id": str(resource.get("id", "")),
        "thread_id": str(resource.get("threadId", "")),
        "from": headers.get("from", ""),
        "date": headers.get("date", ""),
        "to": _addresses(headers.get("to", "")),
        "cc": _addresses(headers.get("cc", "")),
        "subject": headers.get("subject", ""),
        "message_id": headers.get("message-id", "").strip(),
        # lower-case names, only those four, the first of a repeated name (Gmail writes its own Authentication-Results
        # above any the sender wrote); the rest of the header block never leaves the adapter
        "headers": {name: headers[name] for name in _KEPT_HEADERS if name in headers},
        "label_ids": [str(x) for x in resource.get("labelIds") or []],
        "body_text": _decoded(text) if text is not None else "",
        "attachments": [_attachment(p) for p in parts if p.get("filename")],
        "has_text_part": text is not None,
        "has_other_parts": bool(other),
        "untrusted": True,
    }
