"""FR-CHN-11 (BQ-278 n fix pass after security review): what Gmail's header says, and what the message is made of.

1. The authserv-id pin proves Gmail wrote the header, not that the text inside is Gmail's own: Gmail copies sender-
   chosen
   text (the envelope sender's local part in `smtp.mailfrom=` and in the spf comment, an arc comment) into it. Only a
   top-level resinfo clause whose method is exactly `dmarc` counts (RFC 8601: comments stripped, quoted strings kept
   whole, clauses split on ";" outside both). A "dmarc=pass" inside another clause, a comment or a quoted string is
   not a verdict. No dmarc clause: no pass. An unbalanced comment or quote fails closed. The authserv-id is compared
   as ASCII (U+212A folds to "k" under Unicode lower-casing).
2. A reply rides L2 only when the replied-to message is a plain-text body with no attachment and no other body part
   (HTML-only, a multipart/alternative decoy, "see attached" plus a PDF all wait for a person). The reader carries
   `has_text_part`, `has_other_parts` and `attachments`; a message that lacks them fails closed.

Real `config/mail_trust.yaml`, real `GmailAdapter._message` and `ConnectorMailReader`. Fake clock, no network.
"""

from __future__ import annotations

import base64
import pathlib
from collections.abc import Callable
from typing import Any

import pytest
from _chn11_inbound_lib import KINDS, SCHEDULING_INBOUND, assert_rides_l2, assert_waits_for_a_person, make_l2
from tilo_connectors.adapters.gmail import _message

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REAL_CONFIG = REPO_ROOT / "config" / "mail_trust.yaml"
AUTH = "Authentication-Results"
YES = "Yes, confirmed."
GMAIL_SPF = "spf=pass (google.com: domain of bounce@attacker.example designates 192.0.2.1 as permitted sender)"


@pytest.fixture(autouse=True)
def _trusted_authserv(monkeypatch: pytest.MonkeyPatch) -> None:  # replaces conftest's fixture of the same name
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", REAL_CONFIG)


def _card(kind: str, value: str, edit: Callable[[dict], None] | None = None):
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, headers={AUTH: value})
    if edit is not None:
        h.tamper(edit)
    p, ctx, _ = h.preview(thread, YES)
    return h, p, ctx


# ---------------------------------------------------------------------------
# 1. Only a top-level dmarc clause is a verdict

NO_REAL_VERDICT = {
    "mailfrom_local_part": (
        "mx.google.com; spf=pass (google.com: domain of dmarc=pass@attacker.example designates 192.0.2.1 as "
        "permitted sender) smtp.mailfrom=dmarc=pass@attacker.example"
    ),
    "mailfrom_local_part_softfail": (
        "mx.google.com; spf=softfail (google.com: domain of transitioning dmarc=pass@attacker.example does not "
        "designate 192.0.2.1 as permitted sender) smtp.mailfrom=dmarc=pass@attacker.example"
    ),
    "verp_plus": (
        "mx.google.com; spf=pass (google.com: domain of b+dmarc=pass@attacker.example designates 192.0.2.1 as "
        "permitted sender) smtp.mailfrom=b+dmarc=pass@attacker.example"
    ),
    "spf_comment_only": f"mx.google.com; {GMAIL_SPF} (note dmarc=pass) smtp.mailfrom=bounce@attacker.example",
    "quoted_local_part_with_semicolon": (
        'mx.google.com; spf=pass (google.com: domain of "x;dmarc=pass"@attacker.example designates 192.0.2.1 as '
        'permitted sender) smtp.mailfrom="x;dmarc=pass"@attacker.example'
    ),
    "quoted_outside_a_comment": 'mx.google.com; spf=pass smtp.mailfrom="x;dmarc=pass"@attacker.example',
    "quoted_with_parentheses": 'mx.google.com; spf=pass smtp.mailfrom="a)(;dmarc=pass"@attacker.example',
    "arc_comment": (
        "mx.google.com; arc=pass (i=1 spf=pass spfdomain=relay.attacker.example dkim=pass "
        "dkdomain=relay.attacker.example "
        "dmarc=pass fromdomain=harriercharters.example); spf=pass smtp.mailfrom=bounce@relay.attacker.example"
    ),
    "nested_comments": "mx.google.com; spf=pass (a (b (c dmarc=pass) d) e) smtp.mailfrom=x@attacker.example",
    "escaped_parenthesis_in_comment": "mx.google.com; spf=pass (a \\) dmarc=pass) smtp.mailfrom=x@attacker.example",
    "dmarc_in_a_reason": 'mx.google.com; dkim=fail reason="dmarc=pass" header.d=attacker.example',
    "method_with_a_dmarc_suffix": "mx.google.com; x-dmarc=pass header.from=attacker.example",
    "method_with_a_dmarc_prefix": "mx.google.com; dmarc2=pass header.from=attacker.example",
    "dmarc_after_other_words": "mx.google.com; spf=pass foo dmarc=pass",
    "only_a_none_clause": "mx.google.com; none",
    "real_fail_plus_comment_pass": (
        "mx.google.com; spf=pass (google.com: domain of dmarc=pass@attacker.example designates 192.0.2.1 as permitted "
        "sender) smtp.mailfrom=dmarc=pass@attacker.example; dmarc=fail (p=NONE sp=NONE dis=NONE) "
        "header.from=harriercharters.example"
    ),
    "real_fail_plus_arc_comment_pass": "mx.google.com; arc=pass (dmarc=pass); dmarc=fail header.from=a.example",
    "unterminated_comment": "mx.google.com; dmarc=pass (p=none header.from=a.example",
    "unterminated_quote": 'mx.google.com; dmarc=pass header.from="a.example',
    "stray_close_parenthesis": "mx.google.com; dmarc=pass) header.from=a.example",
    "comment_hides_the_authserv_id_semicolon": "attacker.example (x; mx.google.com); dmarc=pass header.from=a.example",
}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("value", list(NO_REAL_VERDICT.values()), ids=list(NO_REAL_VERDICT))
def test_FR_CHN_11_a_dmarc_pass_that_is_not_a_top_level_clause_keeps_the_reply_off_l2(kind: str, value: str) -> None:
    h, p, ctx = _card(kind, value)

    assert_waits_for_a_person(h, p, ctx)


GENUINE = {
    "plain": "mx.google.com; dmarc=pass header.from=harriercharters.example",
    "gmail_shape": (
        "mx.google.com;\r\n       dkim=pass header.i=@harriercharters.example header.s=s1 header.b=AbCdEf12;\r\n"
        "       spf=pass (google.com: domain of david@harriercharters.example designates 192.0.2.1 as permitted "
        "sender) smtp.mailfrom=david@harriercharters.example;\r\n       dmarc=pass (p=NONE sp=NONE dis=NONE) "
        "header.from=harriercharters.example"
    ),
    "with_a_hostile_spf_clause_before": (
        "mx.google.com; spf=pass (google.com: domain of dmarc=pass@attacker.example designates 192.0.2.1 as permitted "
        "sender) smtp.mailfrom=dmarc=pass@attacker.example; dmarc=pass (p=NONE) header.from=harriercharters.example"
    ),
    "comment_before_the_method": "mx.google.com; (checked) dmarc=pass header.from=harriercharters.example",
    "nested_comment_after_pass": "mx.google.com; dmarc=pass (p=NONE (policy) sp=NONE) header.from=a.example",
    "upper_case": "MX.GOOGLE.COM; DMARC=PASS HEADER.FROM=HARRIERCHARTERS.EXAMPLE",
    "two_passes": "mx.google.com; dmarc=pass header.from=a.example; dmarc=pass header.from=b.example",
    "quoted_property": 'mx.google.com; dmarc=pass header.from="harriercharters.example"',
}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("value", list(GENUINE.values()), ids=list(GENUINE))
def test_FR_CHN_11_a_genuine_top_level_dmarc_pass_still_rides_l2(kind: str, value: str) -> None:
    h, p, _ = _card(kind, value)

    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "value",
    [
        "mx.google.com; dmarc=fail header.from=a.example",
        "mx.google.com; dmarc=pass header.from=a.example; dmarc=fail header.from=b.example",
        "mx.google.com; dmarc=pass header.from=a.example; dmarc",
        "mx.google.com; dmarc=",
        "mx.google.com; dmarc",
        "mx.google.com; dmarc=pass; (dmarc=fail) dmarc=none",
    ],
    ids=["fail", "pass_then_fail", "pass_then_bare", "empty_verdict", "bare", "pass_then_none"],
)
def test_FR_CHN_11_any_top_level_dmarc_clause_that_is_not_a_pass_keeps_the_reply_off_l2(kind: str, value: str) -> None:
    h, p, ctx = _card(kind, value)

    assert_waits_for_a_person(h, p, ctx)


def test_FR_CHN_11_the_authserv_id_is_compared_as_ascii(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_channels.autopilot_inbound import _dmarc_pass, trusted_authserv_id

    path = tmp_path / "mail_trust.yaml"
    path.write_text("gmail_authserv_id: mx.kcorp.example\n", encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)
    trusted = trusted_authserv_id()
    assert trusted == "mx.kcorp.example"

    ok = {"headers": {AUTH: "mx.kcorp.example; dmarc=pass header.from=a.example"}}
    kelvin = {"headers": {AUTH: f"mx.{chr(0x212A)}corp.example; dmarc=pass header.from=a.example"}}
    assert _dmarc_pass(ok, trusted) is True
    assert _dmarc_pass(kelvin, trusted) is False


def test_FR_CHN_11_a_configured_id_with_a_non_ascii_letter_is_not_a_trusted_id(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_channels.autopilot_inbound import trusted_authserv_id

    path = tmp_path / "mail_trust.yaml"
    path.write_text(f"gmail_authserv_id: mx.{chr(0x212A)}corp.example\n", encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)

    assert trusted_authserv_id() is None


@pytest.mark.parametrize("size", [50_000])
def test_FR_CHN_11_a_huge_header_is_refused_quickly(size: int) -> None:
    from tilo_channels.autopilot_inbound import _dmarc_pass

    value = "mx.google.com; spf=pass (" + "(" * size + ") dmarc=pass header.from=a.example"

    assert _dmarc_pass({"headers": {AUTH: value}}, "mx.google.com") is False


# ---------------------------------------------------------------------------
# 2. What the replied-to message is made of (real _message and ConnectorMailReader)

GMAIL_AR = GENUINE["gmail_shape"]
MSGID = "<m1@harriercharters.example>"
RISKY = "<p>Please confirm the transfer of $5,000 to the new account today.</p>"
CLEAN = "Hi Sarah, can Marcus come by on Friday afternoon?"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _headers(auth: str = GMAIL_AR) -> list[dict[str, str]]:
    return [
        {"name": "Authentication-Results", "value": auth},
        {"name": "From", "value": "David Miller <david@harriercharters.example>"},
        {"name": "To", "value": "sarah@tilo.example"},
        {"name": "Subject", "value": "Quick question"},
        {"name": "Message-ID", "value": MSGID},
    ]


def _leaf(kind: str, text: str) -> dict[str, Any]:
    return {"mimeType": kind, "headers": [], "body": {"data": _b64(text)}}


def _pdf() -> dict[str, Any]:
    return {
        "mimeType": "application/pdf",
        "filename": "invoice.pdf",
        "headers": [],
        "body": {"attachmentId": "a1", "size": 9},
    }


def _top(mime: str, parts: list[dict] | None = None, text: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"mimeType": mime, "headers": _headers()}
    if parts is not None:
        payload["parts"] = parts
    if text is not None:
        payload["body"] = {"data": _b64(text)}
    return payload


class FakeConnector:
    """The connectors' Gmail read over one raw Gmail message, mapped by the real `_message`."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.raw = {"id": "g1", "threadId": "t1", "labelIds": ["INBOX"], "payload": payload}

    def get_thread(self, user_id: str, thread_id: str) -> dict[str, Any]:
        return {"id": thread_id, "messages": [_message(self.raw)]}

    def get_message(self, user_id: str, message_id: str) -> dict[str, Any]:
        return _message(self.raw)


def _clean(payload: dict[str, Any]) -> bool:
    from tilo_channels.autopilot_inbound import inbound_is_clean
    from tilo_channels.mail_reader import ConnectorMailReader

    return inbound_is_clean(ConnectorMailReader(FakeConnector(payload)), "u", "t1", MSGID)


def test_FR_CHN_11_a_plain_text_only_message_with_a_genuine_dmarc_pass_is_clean_over_the_real_reader() -> None:
    assert _clean(_top("text/plain", text=CLEAN)) is True


def test_FR_CHN_11_a_plain_text_part_inside_multipart_mixed_without_files_is_clean() -> None:
    assert _clean(_top("multipart/mixed", [_leaf("text/plain", CLEAN)])) is True


@pytest.mark.parametrize(
    "payload",
    [
        _top("text/html", text=RISKY),
        _top("multipart/alternative", [_leaf("text/plain", CLEAN), _leaf("text/html", RISKY)]),
        _top("multipart/alternative", [_leaf("text/html", RISKY), _leaf("text/plain", CLEAN)]),
        _top("multipart/mixed", [_leaf("text/plain", "Hi Sarah, see attached. Thanks, David"), _pdf()]),
        _top("multipart/mixed", [_leaf("text/html", RISKY), _pdf()]),
        _top("multipart/alternative", [_leaf("text/plain", CLEAN), _leaf("text/plain", "Please wire the money")]),
        _top("multipart/mixed", []),
        _top("application/pdf", text="x"),
        _top("text/plain", text="Please confirm the transfer of $5,000 to the new account today."),
    ],
    ids=[
        "html_only",
        "decoy_alternative",
        "decoy_alternative_html_first",
        "plain_and_pdf",
        "html_and_pdf",
        "two_plain_parts",
        "no_parts",
        "binary_only",
        "plain_risky_control",
    ],
)
def test_FR_CHN_11_a_message_that_is_not_a_lone_plain_text_body_is_never_clean(payload: dict[str, Any]) -> None:
    assert _clean(payload) is False


def test_FR_CHN_11_an_arc_comment_dmarc_pass_is_not_clean_over_the_real_reader() -> None:
    auth = (
        "mx.google.com; arc=pass (i=1 spf=pass dkim=pass dmarc=pass fromdomain=harriercharters.example); "
        "spf=pass (google.com: domain of bounce@relay.attacker.example designates 192.0.2.9 as permitted sender) "
        "smtp.mailfrom=bounce@relay.attacker.example"
    )
    payload = _top("text/plain", text=CLEAN)
    payload["headers"] = _headers(auth)

    assert _clean(payload) is False


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("field", ["has_text_part", "has_other_parts", "attachments"])
@pytest.mark.parametrize("how", ["missing", "wrong_type"])
def test_FR_CHN_11_a_reader_message_without_the_body_shape_fields_fails_closed(kind: str, field: str, how: str) -> None:
    def edit(message: dict) -> None:
        if how == "missing":
            message.pop(field, None)
        else:
            message[field] = "yes"

    h, p, ctx = _card(kind, GENUINE["plain"], edit)

    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("has_text_part", False),
        ("has_other_parts", True),
        ("attachments", [{"filename": "a.pdf", "mime_type": "application/pdf", "size": 9}]),
    ],
    ids=["no_text_part", "other_parts", "attachment"],
)
def test_FR_CHN_11_the_card_waits_for_a_person_when_the_body_shape_says_so(kind: str, field: str, value: Any) -> None:
    h, p, ctx = _card(kind, GENUINE["plain"], lambda message: message.__setitem__(field, value))

    assert_waits_for_a_person(h, p, ctx)
