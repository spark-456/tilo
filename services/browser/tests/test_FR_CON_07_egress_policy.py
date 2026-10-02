"""FR-CON-07 (PRD 12.3, 12.6, 16.2, SEC-09): "Egress only through an allowlist proxy" /
"Requests to non-allowlisted hosts are blocked and logged."

`tilo_browser.egress.EgressPolicy.check(url)` is the policy the allowlist proxy applies to every
request; it returns a `Decision` and appends it to `policy.decisions` (blocked ones also to
`policy.blocked`). Matching is exact host, or an explicit "*.parent" subdomain rule. Everything
else is blocked: suffix tricks, IP literals (v4, v6, odd encodings), userinfo, IDN look-alikes,
non-https schemes, malformed or ambiguous URLs.

Defaults chosen where the PRD is silent (listed in the ticket report):
- a bare allowlist entry "example.com" matches that host only, not "www.example.com";
- "*.example.com" matches any depth below example.com but NOT example.com itself;
- ports are not part of the allowlist (host-based, PRD 12.3 says "allowlist"); an out-of-range port is invalid;
- IP literals are never allowed, and an allowlist entry that is one is a configuration error;
- URLs carrying userinfo (user:pw@) are blocked even for an allowlisted host (SEC-01: no creds in URLs);
- hosts are compared in IDNA A-label form, so "bücher.de" and "xn--bcher-kva.de" are the same host;
- PRD 16.2 "no data in query strings" is read as: a query string that contains a secret or PII
  pattern (what `tilo_browser.masking.mask_text` would mask) is blocked, reason "sensitive_query".
"""

from __future__ import annotations

import pytest
from _browser_lib import EMAIL, fake_secrets

ALLOW = ["example.com", "*.cdn.example.org"]


def policy(**kw):
    from tilo_browser.egress import EgressPolicy

    kw.setdefault("allow", list(ALLOW))
    return EgressPolicy(**kw)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/",
        "https://example.com",
        "https://EXAMPLE.com/Path?page=2&sort=asc",
        "HTTPS://example.com/",
        "https://example.com:8443/x",
        "https://example.com/#frag",
        "https://assets.cdn.example.org/app.js",
        "https://a.b.cdn.example.org/x",
    ],
)
def test_FR_CON_07_allowlisted_hosts_pass(url):
    d = policy().check(url)
    assert d.allowed is True, d
    assert d.reason == "allowed"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.net/",
        "https://www.example.com/",  # subdomain of an exact entry is not allowed
        "https://evil-example.com/",  # suffix trick
        "https://notexample.com/",  # suffix trick
        "https://example.com.evil.net/",  # prefix trick
        "https://example.com.cdn.example.org.evil.net/",
        "https://example.org/",
        "https://cdn.example.org/",  # a wildcard rule never matches its own apex
        "https://xcdn.example.org/",
        "https://cdn.example.org.evil.net/",
    ],
)
def test_FR_CON_07_non_allowlisted_hosts_are_blocked_and_logged(url):
    p = policy()
    d = p.check(url)
    assert d.allowed is False
    assert d.reason == "host_not_allowlisted"
    assert p.blocked == [d]
    assert p.decisions == [d]


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/",
        "https://10.0.0.5:8080/",
        "https://169.254.169.254/latest/meta-data/",  # cloud metadata server
        "https://8.8.8.8/",
        "https://[::1]/",
        "https://[2001:db8::1]:8443/",
        "https://[::ffff:127.0.0.1]/",
        "https://[fe80::1%25eth0]/",
    ],
)
def test_FR_CON_07_ip_literals_are_blocked(url):
    p = policy()
    d = p.check(url)
    assert d.allowed is False
    assert d.reason in {"ip_literal", "invalid_url"}
    assert p.blocked == [d]


@pytest.mark.parametrize("url", ["https://2130706433/", "https://0x7f.0.0.1/", "https://0177.0.0.1/", "https://127.1/"])
def test_FR_CON_07_alternative_ip_encodings_are_blocked(url):
    assert policy().check(url).allowed is False


@pytest.mark.parametrize("entry", ["127.0.0.1", "[::1]", "10.0.0.0", "::1"])
def test_FR_CON_07_an_ip_literal_allowlist_entry_is_a_configuration_error(entry):
    from tilo_browser.egress import EgressPolicy

    with pytest.raises(ValueError):
        EgressPolicy(allow=[entry])


@pytest.mark.parametrize(
    "entry", ["*", "", " ", "https://example.com", "example.com/path", "ex*ample.com", "a.*.com", "*."]
)
def test_FR_CON_07_malformed_allowlist_entries_are_configuration_errors(entry):
    from tilo_browser.egress import EgressPolicy

    with pytest.raises(ValueError):
        EgressPolicy(allow=[entry])


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pw@example.com/",  # userinfo on an allowlisted host
        "https://user@example.com/",
        "https://example.com@evil.net/",  # looks allowlisted, host is evil.net
        "https://example.com:443@evil.net/",
        "https://example.com:pw@evil.net/",
    ],
)
def test_FR_CON_07_userinfo_in_urls_is_blocked(url):
    p = policy()
    d = p.check(url)
    assert d.allowed is False
    assert p.blocked == [d]


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.net\\@example.com/",  # urllib sees host example.com, browsers see evil.net
        "https://example.com\\@evil.net/",
        "https://evil.net#@example.com/",
        "https://evil.net?@example.com/",
        "https://example.com%40evil.net/",
        "https://example.com%2eevil.net/",
        "https://exa mple.com/",
        "https://example.com\n.evil.net/",
        "https://example.com\t/",
        "https://example.com\x00.evil.net/",
        "https://example.com:99999/",
        "https://example.com:abc/",
        "https://",
        "https:///example.com",
        "",
        "example.com",
        "/relative/path",
        "//example.com/x",  # protocol-relative
    ],
)
def test_FR_CON_07_ambiguous_or_malformed_urls_are_blocked(url):
    p = policy()
    d = p.check(url)
    assert d.allowed is False, f"{url!r} must not pass"
    assert p.blocked == [d]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "ftp://example.com/",
        "file:///etc/passwd",
        "data:text/html,hello",
        "javascript:alert(1)",
        "blob:https://example.com/0f8fad5b-d9cb-469f-a165-70867728950e",
        "wss://example.com/socket",
        "ws://example.com/socket",
        "about:blank",
        "chrome://settings",
    ],
)
def test_FR_CON_07_schemes_other_than_https_are_blocked_by_default(url):
    d = policy().check(url)
    assert d.allowed is False
    assert d.reason in {"scheme_not_allowed", "invalid_url"}


def test_FR_CON_07_an_explicitly_allowed_scheme_passes_and_others_still_do_not():
    p = policy(allow_schemes=("https", "http"))
    assert p.check("http://example.com/").allowed is True
    assert p.check("ftp://example.com/").allowed is False
    assert p.check("http://evil.net/").allowed is False


def test_FR_CON_07_the_default_scheme_set_is_https_only():
    assert policy().check("https://example.com/").allowed is True
    d = policy().check("http://example.com/")
    assert (d.allowed, d.reason) == (False, "scheme_not_allowed")


def test_FR_CON_07_idn_allowlist_matches_unicode_and_punycode_forms_of_the_same_host():
    p = policy(allow=["example.com", "bücher.example"])
    assert p.check("https://bücher.example/").allowed is True
    assert p.check("https://xn--bcher-kva.example/").allowed is True
    assert p.check("https://BÜCHER.example/").allowed is True


@pytest.mark.parametrize(
    "url",
    [
        "https://bucher.example/",  # the ASCII look-alike is a different host
        "https://exаmple.com/",  # Cyrillic a (U+0430)
        "https://xn--exmple-4nf.com/",  # the punycode of the Cyrillic look-alike
        "https://exampIe.com/",  # capital i for l
        "https://examp1e.com/",
        "https://xn--/",
        "https://xn--zzzzzzzzzzzz.com/",  # invalid punycode
    ],
)
def test_FR_CON_07_punycode_and_idn_lookalikes_are_blocked(url):
    p = policy(allow=["example.com", "bücher.example"])
    d = p.check(url)
    assert d.allowed is False, f"{url!r} must not pass"
    assert p.blocked == [d]


def test_FR_CON_07_redirect_hop_is_checked_like_any_request_and_remembers_where_it_came_from():
    p = policy()
    ok = p.check("https://example.com/start")
    hop = p.check("https://evil.net/landing", redirect_from="https://example.com/start")
    assert ok.allowed is True and hop.allowed is False
    assert hop.reason == "host_not_allowlisted"
    assert hop.redirect_from is not None and hop.redirect_from.startswith("https://example.com/start")
    assert p.blocked == [hop]
    assert p.decisions == [ok, hop]


def test_FR_CON_07_https_to_http_redirect_downgrade_is_blocked():
    p = policy()
    d = p.check("http://example.com/", redirect_from="https://example.com/")
    assert (d.allowed, d.reason) == (False, "scheme_not_allowed")


def test_FR_CON_07_every_check_is_logged_once_in_order():
    p = policy()
    urls = ["https://example.com/a", "https://evil.net/b", "https://example.com/c", "http://example.com/d"]
    for u in urls:
        p.check(u)
    assert [d.allowed for d in p.decisions] == [True, False, True, False]
    assert [d.allowed for d in p.decisions if not d.allowed] == [False, False]
    assert p.blocked == [d for d in p.decisions if not d.allowed]


def test_FR_CON_07_a_blocked_decision_names_the_host_scheme_and_reason():
    d = policy().check("https://tracker.evil.net/pixel.gif")
    assert d.allowed is False
    assert d.host == "tracker.evil.net"
    assert d.scheme == "https"
    assert d.reason == "host_not_allowlisted"
    assert d.url.startswith("https://tracker.evil.net/pixel.gif")


def test_FR_CON_07_the_log_never_holds_userinfo_query_or_fragment():
    secrets = fake_secrets()
    p = policy()
    p.check(f"https://user:{secrets['password']}@evil.net/path?token={secrets['kv_token']}#{secrets['bearer']}")
    p.check(f"https://example.com/ok?key={secrets['api_key']}#{secrets['jwt']}")
    p.check(f"https://example.com@evil.net/x?email={EMAIL}")
    dump = repr(p.decisions) + repr(p.blocked)
    for name in ("password", "kv_token", "bearer", "api_key", "jwt"):
        assert secrets[name] not in dump, name
    assert EMAIL not in dump
    for d in p.decisions:
        assert "@" not in d.url and "?" not in d.url and "#" not in d.url, d.url


@pytest.mark.parametrize(
    "query",
    [
        f"q={EMAIL}",
        "q=" + EMAIL.replace("@", "%40"),
        "token={kv_token}",
        "api_key={api_key}",
        "auth={jwt}",
        "password={password}",
    ],
)
def test_FR_CON_07_secrets_and_pii_in_a_query_string_are_blocked_even_on_an_allowed_host(query):
    secrets = fake_secrets()
    q = query.format(**secrets)
    p = policy()
    d = p.check(f"https://example.com/search?{q}")
    assert d.allowed is False
    assert d.reason == "sensitive_query"
    assert p.blocked == [d]
    assert q not in repr(p.decisions)


@pytest.mark.parametrize("query", ["page=2&sort=asc", "q=winter+boots", "utm_source=newsletter", "id=12345"])
def test_FR_CON_07_ordinary_query_strings_pass(query):
    assert policy().check(f"https://example.com/list?{query}").allowed is True


def test_FR_CON_07_an_empty_allowlist_blocks_everything():
    from tilo_browser.egress import EgressPolicy

    p = EgressPolicy(allow=[])
    assert p.check("https://example.com/").allowed is False
    assert p.check("https://evil.net/").allowed is False
