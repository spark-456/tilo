"""FR-CHN-11 (BQ-278 n; BQ-274 e, f): the DMARC verdict is believed only from the configured server, and header
names are matched without regard to case.

A sender can write any header, so an Authentication-Results value is trusted only when its authserv-id (the text before
the first ";") is the one in `config/mail_trust.yaml` (Gmail's own, "mx.google.com"). "attacker.example; dmarc=pass"
is not trusted. A missing, different or unreadable id, and a config that is missing or unusable, fail closed: the card
stays L1 (no undo window, nothing queued). Header names come lower-cased from the Gmail adapter, so they are matched
case-insensitively; two keys that differ only by case are ambiguous and fail closed.

This module runs against the REAL config file (the other FR-CHN-11 modules pin their own fixture id through conftest).
Fake clock, fake outbox, no network, no paid call.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable

import pytest
from _chn11_inbound_lib import (
    KINDS,
    SCHEDULING_INBOUND,
    assert_rides_l2,
    assert_waits_for_a_person,
    make_l2,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
REAL_CONFIG = REPO_ROOT / "config" / "mail_trust.yaml"
AUTH = "Authentication-Results"
TRUSTED = "mx.google.com"
YES = "Yes, confirmed."
PASS = "dmarc=pass header.from=harriercharters.example"


@pytest.fixture(autouse=True)
def _trusted_authserv(monkeypatch: pytest.MonkeyPatch) -> None:  # replaces conftest's fixture of the same name
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", REAL_CONFIG)


def _card(kind: str, edit: Callable[[dict], None] | None = None, *, headers: dict[str, str] | None = None):
    """The replied-to message carries a pass from the trusted server unless `headers` says otherwise."""
    h = make_l2(kind)
    thread = h.thread(SCHEDULING_INBOUND, headers=headers or {AUTH: f"{TRUSTED}; {PASS}"})
    if edit is not None:
        h.tamper(edit)
    p, ctx, _ = h.preview(thread, YES)
    return h, p, ctx


def _rename(old: str, new: str) -> Callable[[dict], None]:
    def edit(message: dict) -> None:
        message["headers"][new] = message["headers"].pop(old)

    return edit


def _add(name: str, value: str) -> Callable[[dict], None]:
    def edit(message: dict) -> None:
        message["headers"][name] = value

    return edit


# ---------------------------------------------------------------------------
# The configured value


def test_FR_CHN_11_the_trusted_authserv_id_is_configured_not_hard_coded() -> None:
    from tilo_channels.autopilot_inbound import trusted_authserv_id

    assert REAL_CONFIG.is_file()
    assert trusted_authserv_id() == TRUSTED


@pytest.mark.parametrize(
    "text",
    [
        "",
        "gmail_authserv_id: ''\n",
        "gmail_authserv_id: '   '\n",
        "gmail_authserv_id: null\n",
        "gmail_authserv_id: 5\n",
        "gmail_authserv_id: [mx.google.com]\n",
        "gmail_authserv_id: {a: b}\n",
        "other: mx.google.com\n",
        "- mx.google.com\n",
        "gmail_authserv_id: [unclosed\n",
        "gmail_authserv_id: mx.google.com; dmarc=pass\n",
        "gmail_authserv_id: mx google com\n",
    ],
)
def test_FR_CHN_11_an_unusable_config_means_no_trusted_id(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    from tilo_channels.autopilot_inbound import trusted_authserv_id

    path = tmp_path / "mail_trust.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)

    assert trusted_authserv_id() is None


def test_FR_CHN_11_a_missing_config_file_means_no_trusted_id(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_channels.autopilot_inbound import trusted_authserv_id

    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", tmp_path / "missing.yaml")

    assert trusted_authserv_id() is None


def test_FR_CHN_11_the_configured_id_is_read_trimmed_and_lower_cased(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_channels.autopilot_inbound import trusted_authserv_id

    path = tmp_path / "mail_trust.yaml"
    path.write_text("gmail_authserv_id: '  MX.Corp.Example '\n", encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)

    assert trusted_authserv_id() == "mx.corp.example"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("text", ["", "gmail_authserv_id: ''\n", "gmail_authserv_id: [unclosed\n", None])
def test_FR_CHN_11_an_unusable_config_keeps_a_perfect_reply_off_l2(
    kind: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, text: str | None
) -> None:
    path = tmp_path / "mail_trust.yaml"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)

    h, p, ctx = _card(kind, headers={AUTH: f"{TRUSTED}; {PASS}"})

    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_the_pin_follows_the_config_not_a_constant(
    kind: str, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "mail_trust.yaml"
    path.write_text("gmail_authserv_id: mx.corp.example\n", encoding="utf-8")
    monkeypatch.setattr("tilo_channels.autopilot_inbound.CONFIG_PATH", path)

    h, p, ctx = _card(kind, headers={AUTH: f"{TRUSTED}; {PASS}"})
    assert_waits_for_a_person(h, p, ctx)

    h, p, _ = _card(kind, headers={AUTH: f"mx.corp.example; {PASS}"})
    assert_rides_l2(h, p)


# ---------------------------------------------------------------------------
# The authserv-id of the header


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "value",
    [
        f"{TRUSTED}; {PASS}",
        f"{TRUSTED.upper()}; {PASS.upper()}",
        f"  {TRUSTED} ; {PASS}",
        f"{TRUSTED}\t;{PASS}",
        f"{TRUSTED}; spf=pass smtp.mailfrom=x.example; dkim=pass; dmarc=pass (p=NONE dis=NONE) header.from=x.example",
    ],
    ids=["plain", "upper_case", "spaces_before_semicolon", "tab", "gmail_shape"],
)
def test_FR_CHN_11_a_dmarc_pass_from_the_configured_server_still_rides_l2(kind: str, value: str) -> None:
    h, p, _ = _card(kind, headers={AUTH: value})

    assert_rides_l2(h, p)


FORGED = {
    "attacker_id": f"attacker.example; {PASS}",
    "attacker_id_upper": f"ATTACKER.EXAMPLE; {PASS.upper()}",
    "trusted_id_as_suffix": f"{TRUSTED}.attacker.example; {PASS}",
    "trusted_id_as_prefix": f"attacker.{TRUSTED}; {PASS}",
    "trusted_id_second": f"attacker.example {TRUSTED}; {PASS}",
    "trusted_id_in_a_comment": f"attacker.example (via {TRUSTED}); {PASS}",
    "trusted_id_after_a_semicolon": f"attacker.example; {TRUSTED}; {PASS}",
    "trusted_id_in_the_verdict_text": f"attacker.example; {PASS} reason={TRUSTED}",
    "with_a_version": f"{TRUSTED} 1; {PASS}",
    "id_missing": f"; {PASS}",
    "id_blank": f"   ; {PASS}",
    "no_id_no_semicolon": PASS,
    "id_and_verdict_without_semicolon": f"{TRUSTED} {PASS}",
    "look_alike_dot": f"mx{chr(0x2024)}google.com; {PASS}",
    "look_alike_letter": f"mx.g{chr(0x043E)}ogle.com; {PASS}",
    "full_width": f"{chr(0xFF4D)}{chr(0xFF58)}.google.com; {PASS}",
    "zero_width": f"mx.google{chr(0x200B)}.com; {PASS}",
    "trailing_dot": f"{TRUSTED}.; {PASS}",
    "newline_before": f"attacker.example\n{TRUSTED}; {PASS}",
}


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("value", list(FORGED.values()), ids=list(FORGED))
def test_FR_CHN_11_a_dmarc_pass_from_any_other_authserv_id_keeps_the_reply_off_l2(kind: str, value: str) -> None:
    h, p, ctx = _card(kind, headers={AUTH: value})

    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_a_trusted_id_does_not_rescue_a_failing_verdict(kind: str) -> None:
    h, p, ctx = _card(kind, headers={AUTH: f"{TRUSTED}; dmarc=fail header.from=harriercharters.example"})

    assert_waits_for_a_person(h, p, ctx)


# ---------------------------------------------------------------------------
# Header names are matched without regard to case


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", ["authentication-results", "AUTHENTICATION-RESULTS", "Authentication-results"])
def test_FR_CHN_11_the_authentication_results_name_is_matched_case_insensitively(kind: str, name: str) -> None:
    h, p, _ = _card(kind, edit=_rename(AUTH, name))

    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("name", ["message-id", "MESSAGE-ID", "Message-Id"])
def test_FR_CHN_11_the_message_id_name_is_matched_case_insensitively(kind: str, name: str) -> None:
    h, p, _ = _card(kind, edit=_rename("Message-ID", name))

    assert_rides_l2(h, p)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    ("first", "second"),
    [
        (f"{TRUSTED}; dmarc=fail header.from=a.example", f"{TRUSTED}; {PASS}"),
        (f"{TRUSTED}; {PASS}", f"{TRUSTED}; dmarc=fail header.from=a.example"),
        (f"attacker.example; {PASS}", f"{TRUSTED}; {PASS}"),
        (f"{TRUSTED}; {PASS}", f"attacker.example; {PASS}"),
        (f"{TRUSTED}; {PASS}", f"{TRUSTED}; {PASS}"),
    ],
    ids=["fail_then_pass", "pass_then_fail", "forged_then_real", "real_then_forged", "two_passes"],
)
def test_FR_CHN_11_two_authentication_results_keys_that_differ_only_by_case_fail_closed(
    kind: str, first: str, second: str
) -> None:
    def edit(message: dict) -> None:
        message["headers"][AUTH] = first
        message["headers"]["authentication-results"] = second

    h, p, ctx = _card(kind, edit=edit)

    assert_waits_for_a_person(h, p, ctx)


@pytest.mark.parametrize("kind", KINDS)
def test_FR_CHN_11_a_spoofed_second_message_id_key_in_another_case_fails_closed(kind: str) -> None:
    """Two Message-ID keys differing only by case: the id names no one message, so the reply cannot ride L2."""
    h, p, ctx = _card(kind, edit=_add("message-id", "<other@mail.example>"))

    assert_waits_for_a_person(h, p, ctx)
