"""FR-MEM-05 / SEC-14, security review fixes (BQ-FRMEM05-1): linear time on hostile input, one key rule for trees and
text, header lines, escaped JSON, URL userinfo, an unterminated key block that stops where its body stops, a log
filter that is safe for a formatter calling `formatException(record.exc_info)`, and `redact_value`'s edge cases.
Every fake secret is assembled at runtime (CLAUDE.md); the shapes themselves are KINDS in `_redact_samples_lib.py`.
"""

from __future__ import annotations

import io
import json
import logging
import time

import pytest
from _redact_samples_lib import FIXED_TAIL, build, leaks
from tilo_redact import MAX_DEPTH, REDACTED, RedactingFilter, redact, redact_value

BEGIN = "-----BEGIN " + "PRIV" + "ATE KEY-----"  # assembled: the repo secret scan reads this file too
END = "-----END " + "PRIV" + "ATE KEY-----"
MB = 1_000_000


def _rep(unit: str, size: int = MB) -> str:
    return unit * (size // len(unit))


HOSTILE = {  # one 1 MB input per pattern, built to make a backtracking or restarting regex quadratic
    "jwt_dashes": _rep("eyJ-"),
    "jwt_dots": _rep("eyJa."),
    "jwt_one_dot": _rep("eyJa.b "),
    "pem_headers": _rep(BEGIN),
    "pem_words": _rep("-----BEGIN " + "A" * 20 + " "),
    "pem_lines": _rep(BEGIN + "\n" + "A" * 64 + "\n"),
    "pem_newlines": BEGIN + "\n" * MB,
    "pem_escaped": _rep(BEGIN + "\\n" + "A" * 20 + "\\n"),
    "userinfo_scheme": _rep("a://"),
    "userinfo_long": _rep("x://" + "a" * 1000),
    "userinfo_at": "http://" + _rep("a@"),
    "header_spaces": "Authorization:" + " " * MB,
    "header_repeat": _rep("Authorization: "),
    "cookie_repeat": _rep("cookie:"),
    "bearer_repeat": _rep("bearer "),
    "bearer_spaces": "bearer" + " " * MB + "x",
    "bearer_short": _rep("bearer " + "a" * 19 + " "),
    "google_key": _rep("AIza"),
    "google_key_short": _rep("AIza" + "a" * 34 + " "),
    "ya29": _rep("ya29."),
    "ya29_dots": "ya29." + "a." * (MB // 2),
    "sk_glued": _rep("_sk-"),
    "github": _rep("ghp_"),
    "github_pat": _rep("github_pat_"),
    "slack": _rep("xoxb-"),
    "slack_hook": _rep("hooks.slack.com/services/"),
    "aws": _rep("AKIA"),
    "auth_code": _rep("4/0A"),
    "firebase": _rep("AMf-vB"),
    "refresh": _rep("1//0"),
    "meta": _rep("EAA"),
    "aq": _rep("AQ."),
    "nvidia": _rep("nvapi-"),
    "service_account": '"type"' + " " * MB,
    "card_digits": "1" * MB,
    "card_groups": _rep("1234 "),
    "card_dash_groups": _rep("1234-"),
    "card_dots": _rep("1."),
    "label_spaces": "password" + " " * MB,
    "label_repeat": _rep("password="),
    "label_open_quote": 'password="' + "a" * MB,
    "label_escaped_quotes": _rep('password=\\"'),
    "label_backslashes": 'password="' + "\\" * MB,
    "label_token_repeat": _rep("token:"),
    "label_query": _rep("?code="),
    "label_entity": _rep("password=&quot;"),
    "mixed": _rep("eyJ-password='Authorization: bearer 4111 "),
    # second security review: escaped values, JSON, prose labels, headers, OAuth URLs and JSON-number cards
    "entity_value_backslashes": "password=&quot;" + "\\" * MB,
    "escaped_value_backslashes": 'password=\\"' + "\\" * MB,
    "entity_value_zeros": "password=&quot;&#" + "0" * MB,
    "entity_value_hashes": "password=&quot;" + _rep("&#0"),
    "key_backslashes": _rep("password" + "\\" * 50 + " "),
    "value_quote_spaces": 'password="' + " " * MB,
    "value_single_quotes": "password='" + _rep('"x'),
    "value_escaped_quotes": 'password="' + _rep('\\"x'),
    "value_quote_runs": 'password="' + _rep('\\\\\\"'),
    "json_keys": _rep('"token":'),
    "json_numbers": _rep('"token": 5, '),
    "json_in_json": _rep('{\\"password\\": \\"x\\", '),
    "prose_labels": _rep("token: ab "),
    "exact_labels": _rep("pass: ab "),
    "cursor_labels": _rep("next_page_token: x "),
    "auth_prose": _rep("authorization: a "),
    "auth_key_scan": "a-" * (MB // 2) + "authorization: Zq1234567890abcd",
    "auth_mid_quotes": "x Authorization: Bearer " + _rep('" '),
    "auth_mid_escaped": "x Authorization: Bearer " + _rep('\\" '),
    "cookie_long_name": _rep("cookie: " + "a" * 300 + " "),
    "code_one_url": "https://x.example/p?" + _rep("&code=a"),
    "code_many_urls": _rep("https://x.example/p?code=a "),
    "code_scheme_runs": _rep("a://") + "?code=a",
    "code_letter_run": "x" * MB + "://p?code=a",
    "code_after_markers": _rep("[REDACTED]&code=a"),
    "card_json_numbers": "[" + _rep("4111111111111111, "),
    "card_in_strings": _rep('"4111111111111111", '),
    "card_after_quotes": _rep('\\"') + "4111111111111111",
    "pem_quotes": BEGIN + "\n" + _rep('A"\n'),
    "pem_closing_quotes": BEGIN + _rep('" '),
    "userinfo_quotes": "a://" + _rep('"@'),
    "bearer_letters": _rep("Bearer abcdefghijk "),
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_FR_MEM_05_hostile_input_of_one_megabyte_is_redacted_in_linear_time(name):
    started = time.perf_counter()
    redact(HOSTILE[name])
    assert time.perf_counter() - started < 3.0, name  # under 1 s measured; a quadratic pattern takes minutes


def test_FR_MEM_05_a_service_account_access_token_with_dots_does_not_survive():
    body = (FIXED_TAIL * 3)[:200]
    token = "ya" + "29.c.c0ASRK0Ga" + body
    for text in (token, f"token refresh failed: {token}", f"Bearer {token}", json.dumps({"note": token})):
        assert body[:60] not in redact(text), text


@pytest.mark.parametrize(
    "key",
    [
        "password",
        "passwd",
        "pwd",
        "pass",
        "passphrase",
        "secret",
        "client_secret",
        "clientSecret",
        "token",
        "access_token",
        "accessToken",
        "refresh_token",
        "id_token",
        "api_key",
        "apiKey",
        "apikey",
        "x-api-key",
        "X-Goog-Api-Key",
        "x-auth-token",
        "authorization",
        "Proxy-Authorization",
        "cookie",
        "Set-Cookie",
        "db_password",
        "aws_secret_access_key",
    ],
)
def test_SEC_14_one_key_rule_for_trees_whatever_the_case_dashes_or_camel_case(key):
    assert redact_value({key: "plain words"}) == {key: REDACTED}
    assert redact_value({key.upper(): {"a": [1, 2]}}) == {key.upper(): REDACTED}


@pytest.mark.parametrize(
    "template",
    [
        "{k}=Zq1234567890abcd",
        "{k}: Zq1234567890abcd",
        '{{"{k}": "Zq1234567890abcd"}}',
        "?a=1&{k}=Zq1234567890abcd",
        "{k} = Zq1234567890abcd",
    ],
)
@pytest.mark.parametrize(
    "key",
    ["password", "passwd", "passphrase", "secret", "client_secret", "client-secret", "clientSecret", "token"]
    + ["access_token", "accessToken", "refresh_token", "id_token", "api_key", "api-key", "apikey", "apiKey"]
    + ["x-api-key", "x-goog-api-key", "x-auth-token", "private_key", "aws_secret_access_key"],
)
def test_SEC_14_the_same_keys_are_secrets_in_text(key, template):
    assert "Zq1234567890abcd" not in redact(template.format(k=key))


@pytest.mark.parametrize("key", ["code", "key", "signature", "X-Goog-Signature", "X-Amz-Signature", "pass", "pwd"])
def test_SEC_14_query_parameters_are_secrets_but_the_same_words_in_prose_are_kept(key):
    assert "Zq1234567890abcd" not in redact(f"https://example.com/cb?x=1&{key}=Zq1234567890abcd")
    assert "Zq1234567890abcd" not in redact(f"https://example.com/cb?{key}=Zq1234567890abcd&x=1")
    plain = f"the {key}=200 flag and {key}: 404 in this line stay"
    assert redact(plain) == plain


def test_SEC_14_keys_that_only_look_like_secrets_are_kept():
    tree = {"max_output_tokens": 50, "input_tokens": 12, "cached_tokens": 1, "authz": {"tier": "T3"}, "usage": {"a": 1}}
    tree |= {"key": "k1", "code": 200, "signature": "none", "tokens": 3, "bypass": True, "keyboard": "x"}
    assert redact_value(tree) == tree
    text = "max_output_tokens: 1024, input_tokens=12, keyboard=us, status code=200, tokens: 5"
    assert redact(text) == text


@pytest.mark.parametrize(
    "header", ["Authorization", "authorization", "AUTHORIZATION", "Proxy-Authorization", "Cookie", "Set-Cookie"]
)
@pytest.mark.parametrize("value", ["Basic dXNlcjpwYXNz", "Digest user=a, realm=b", "Zq1234567890abcd", "Bearer x y z"])
def test_FR_MEM_05_a_header_value_goes_to_the_end_of_the_line_whatever_its_scheme(header, value):
    out = redact(f"GET /x HTTP/1.1\n{header}: {value}\nAccept: application/json\n")
    assert out == f"GET /x HTTP/1.1\n{header}: {REDACTED}\nAccept: application/json\n"


def test_FR_MEM_05_a_json_value_with_an_escaped_quote_or_an_escaped_json_layer_loses_all_of_it():
    inner = 'Hun\\"ter2 Secret!x'
    assert redact('{"password": "' + inner + '", "user": "ann"}') == '{"password": "[REDACTED]", "user": "ann"}'
    escaped = json.dumps({"body": json.dumps({"password": "Zq1234 5678abcd", "user": "ann"})})
    out = redact(escaped)
    assert "Zq1234" not in out and "5678abcd" not in out and "ann" in out
    assert redact("{&quot;password&quot;: &quot;Zq1 2&quot;, &quot;n&quot;: 1}") == (
        "{&quot;password&quot;: &quot;[REDACTED]&quot;, &quot;n&quot;: 1}"
    )


def test_FR_MEM_05_url_userinfo_goes_and_the_rest_of_the_url_stays():
    for scheme in ("https", "http", "postgres", "redis", "ftp", "amqps"):
        out = redact(f"see {scheme}://ann:Zq1234@host.example:5432/db?x=1#top now")
        assert out == f"see {scheme}://{REDACTED}@host.example:5432/db?x=1#top now"
    assert redact("https://Zq1234token@host.example/p") == f"https://{REDACTED}@host.example/p"


def test_FR_MEM_05_plain_emails_and_urls_without_userinfo_are_unchanged():
    text = "write to ops@harrier-logistics.example or ann+tag@example.co.uk; see https://example.com/a@b?c=d@e"
    assert redact(text) == text
    assert redact("mailto:ann@example.com and https://example.com/u/@ann") == (
        "mailto:ann@example.com and https://example.com/u/@ann"
    )


def test_FR_MEM_05_an_unterminated_key_block_ends_where_its_body_ends():
    body = ["A" * 64, "B" * 64, "C" * 20]
    text = f"Hi team.\n{BEGIN}\n" + "\n".join(body) + "\nMARKER>>>\nAfter the mail: never reply without approval.\n"
    out = redact(text)
    assert out == "Hi team.\n" + REDACTED + "\nMARKER>>>\nAfter the mail: never reply without approval.\n"
    assert (
        redact(f"{BEGIN}\r\n{body[0]}\r\n\r\nDone.") == f"{REDACTED}\r\nDone."
    )  # CRLF; a blank line is part of the block
    assert redact(f"{BEGIN}\\n{body[0]}\\n{body[1]}\\nnext.") == f"{REDACTED}\\nnext."  # a JSON-escaped one-liner
    legacy = f"{BEGIN}\nProc-Type: 4,ENCRYPTED\nDEK-Info: AES-128-CBC,AB12\n\n{body[0]}\nThanks."
    assert redact(legacy) == f"{REDACTED}\nThanks."


def test_FR_MEM_05_a_terminated_key_block_is_removed_whole_even_with_odd_lines():
    text = f"before\n{BEGIN}\n> quoted body\n  indented body\n{END}\nafter"
    assert redact(text) == f"before\n{REDACTED}\nafter"


class _Nfr26Formatter(logging.Formatter):
    """The NFR-26 `_JsonFormatter` pattern: reads `record.exc_info` itself instead of `record.exc_text`."""

    def format(self, record: logging.LogRecord) -> str:
        line = {"severity": record.levelname, "message": record.getMessage()}
        if record.exc_info:
            line["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            line["stack"] = self.formatStack(record.stack_info)
        return json.dumps(line)


def test_FR_MEM_05_a_formatter_that_formats_exc_info_itself_emits_no_secret():
    secret = build("google_oauth_access", FIXED_TAIL).text
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(_Nfr26Formatter())
    handler.addFilter(RedactingFilter())
    logger = logging.Logger("fr_mem_05_nfr26", logging.DEBUG)
    logger.addHandler(handler)
    try:
        raise RuntimeError("refresh refused for " + secret)
    except RuntimeError:
        logger.exception("token refresh failed", stack_info=True, extra={"detail": {"auth": secret}, "obj": object()})
    line = json.loads(stream.getvalue())
    assert secret not in stream.getvalue() and FIXED_TAIL[:30] not in stream.getvalue()
    assert "RuntimeError" in line["exception"] and "token refresh failed" in line["message"]


def test_FR_MEM_05_extra_fields_of_any_type_are_redacted_or_replaced_by_their_redacted_text():
    secret = build("google_oauth_access", FIXED_TAIL).text

    class Request:
        def __repr__(self) -> str:
            return f"Request(prompt={secret!r})"

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(message)s %(req)s %(raw)s %(bag)s"))
    handler.addFilter(RedactingFilter())
    logger = logging.Logger("fr_mem_05_extra", logging.DEBUG)
    logger.addHandler(handler)
    logger.info("x", extra={"req": Request(), "raw": secret.encode(), "bag": {secret}})
    assert FIXED_TAIL[:30] not in stream.getvalue()


def test_FR_MEM_05_two_keys_that_redact_to_one_string_both_stay():
    first, second = build("google_oauth_access", FIXED_TAIL).text, build("google_oauth_access", FIXED_TAIL[::-1]).text
    out = redact_value({first: "one", second: "two", "plain": 3})
    assert sorted(out.values(), key=str) == [3, "one", "two"] and len(out) == 3
    assert redact_value(out) == out  # idempotent: the suffixed key is already clean
    assert redact_value({first: "one", second: "two"}) == redact_value({first: "one", second: "two"})


def test_FR_MEM_05_tuple_keys_bytes_and_sets_are_redacted_inside():
    secret = build("google_oauth_access", FIXED_TAIL).text
    out = redact_value({(secret, 1): [secret.encode(), {secret}, frozenset({secret}), bytearray(secret.encode())]})
    assert FIXED_TAIL[:30] not in repr(out)
    assert list(out)[0] == (REDACTED, 1)
    assert redact_value(b"\xff\xfe plain \x00") == b"\xff\xfe plain \x00"  # bytes that are not text survive intact


def test_FR_MEM_05_a_value_of_an_unknown_type_is_refused_not_passed_through():
    with pytest.raises(TypeError):
        redact_value({"a": object()})


def test_FR_MEM_05_a_tree_deeper_than_the_cap_or_holding_itself_raises_a_clear_error():
    deep: dict = {}
    node = deep
    for _ in range(MAX_DEPTH + 5):
        node["n"] = {}
        node = node["n"]
    with pytest.raises(ValueError, match="deeper"):
        redact_value(deep)
    cycle: list = []
    cycle.append(cycle)
    with pytest.raises(ValueError, match="deeper"):
        redact_value(cycle)
    ok: dict = {}
    node = ok
    for _ in range(MAX_DEPTH - 2):
        node["n"] = {}
        node = node["n"]
    assert redact_value(ok) == ok


def test_FR_MEM_05_a_prose_password_with_a_label_is_redacted_on_purpose_and_without_a_label_is_kept():
    assert redact("password: none") == f"password: {REDACTED}"  # fails closed: BQ-FRMEM05-1
    assert redact("my password is Hunter2") == "my password is Hunter2"  # no label: not a secret shape


def test_FR_MEM_05_the_new_shapes_leave_nothing_behind():
    for kind in ("github_fine_grained", "slack_bot_token", "slack_webhook", "aws_session_key", "firebase_refresh"):
        sample = build(kind, FIXED_TAIL)
        assert leaks(redact(sample.text), sample) == [], kind
    assert leaks(redact(build("sk_after_underscore", FIXED_TAIL).text), build("sk_after_underscore", FIXED_TAIL)) == []
