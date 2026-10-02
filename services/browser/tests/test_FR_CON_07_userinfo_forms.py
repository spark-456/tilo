"""FR-CON-07 userinfo in browser-equivalent URL forms (PR #140 security round 2; PRD 12.3, 16.1 rule 4).

Browsers pre-process a URL before parsing it (WHATWG URL standard): leading and trailing C0
controls and spaces are stripped and every tab, LF and CR is removed. `view-source:` and `blob:`
wrap a full URL. Each form below is therefore a real credentialed navigation to evil.net. The
gate must keep blocking it, and the password must never reach a Decision, `EgressPolicy.blocked`,
`redirect_from` or the `EgressBlocked` text (API.md: no userinfo in an error message or the log).

The password carries the RFC 3986 sub-delims "!$*" (legal unencoded in userinfo). It is assembled
at runtime; nothing here is a real secret.
"""

from __future__ import annotations

import pytest

SECRET = "Q7v" + "Rk2" + "mZ9"
PW = SECRET + "!$" + "x*"

FORMS = {
    "leading_space": " https://user:{pw}@evil.net/",
    "leading_tab": "\thttps://user:{pw}@evil.net/",
    "leading_nul": "\x00https://user:{pw}@evil.net/",
    "trailing_space_and_c0": "https://user:{pw}@evil.net/\x01 ",
    "lf_inside_scheme": "ht\ntps://user:{pw}@evil.net/",
    "lf_after_colon": "https:\n//user:{pw}@evil.net/",
    "cr_inside_userinfo": "https://user:{pw}\r@evil.net/",
    "tab_between_slashes": "https:/\t/user:{pw}@evil.net/",
    "view_source": "view-source:https://user:{pw}@evil.net/",
    "blob": "blob:https://user:{pw}@evil.net/0f1e2d3c",
    "nested_twice": "view-source:blob:https://user:{pw}@evil.net/",
    "view_source_with_lf": "view-source:\nhttps://user:{pw}@evil.net/",
}


def _url(form: str) -> str:
    return FORMS[form].format(pw=PW)


def _assert_clean(text: str) -> None:
    assert SECRET not in text, text
    assert PW not in text, text


def policy(allow=("example.com",)):
    from tilo_browser.egress import EgressPolicy

    return EgressPolicy(allow=list(allow))


@pytest.mark.parametrize("form", list(FORMS))
def test_FR_CON_07_userinfo_form_is_blocked_and_never_reaches_the_decision_or_blocked_log(form):
    p = policy()
    d = p.check(_url(form))
    assert d.allowed is False
    _assert_clean(d.url)
    _assert_clean(repr(d))
    _assert_clean(repr(p.decisions) + repr(p.blocked))
    assert "@" not in d.url


@pytest.mark.parametrize("form", list(FORMS))
def test_FR_CON_07_userinfo_form_never_reaches_redirect_from(form):
    p = policy()
    d = p.check("https://example.com/next", redirect_from=_url(form))
    _assert_clean(d.redirect_from or "")
    _assert_clean(repr(p.decisions))
    assert "@" not in (d.redirect_from or "")


@pytest.mark.parametrize("form", list(FORMS))
def test_FR_CON_07_userinfo_form_never_reaches_the_egress_blocked_text(make_rig, form):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate(_url(form))
    _assert_clean(str(ei.value))
    _assert_clean(repr(ei.value.decision))
    _assert_clean(repr(rig.policy.decisions) + repr(rig.policy.blocked))
    assert rig.web.requests == []


@pytest.mark.parametrize("form", ["leading_space", "lf_after_colon", "tab_between_slashes", "view_source"])
def test_FR_CON_07_userinfo_form_on_an_allowlisted_host_is_still_blocked_and_clean(form):
    p = policy()
    d = p.check(_url(form).replace("evil.net", "example.com"))
    assert d.allowed is False
    _assert_clean(repr(p.decisions))


@pytest.mark.parametrize(
    ("raw", "logged"),
    [
        (" https://evil.net/a", "https://evil.net/a"),
        ("ht\ntps://evil.net/a", "https://evil.net/a"),
        ("https:/\t/evil.net/a", "https://evil.net/a"),
        ("view-source:https://user:{pw}@evil.net/a", "view-source://evil.net/a"),
    ],
)
def test_FR_CON_07_the_log_names_the_host_a_browser_would_reach(raw, logged):
    d = policy().check(raw.format(pw=PW))
    assert d.allowed is False and d.url == logged


@pytest.mark.parametrize(
    "raw",
    ["https:user:{pw}@evil.net/", "https:/user:{pw}@evil.net/", "mailto:user:{pw}@evil.net", "user:{pw}@evil.net/"],
)
def test_FR_CON_07_a_url_without_scheme_and_authority_is_logged_as_scheme_only(raw):
    d = policy().check(raw.format(pw=PW))
    assert d.allowed is False and d.reason in ("invalid_url", "scheme_not_allowed")
    _assert_clean(d.url)
    assert "evil" not in d.url and "@" not in d.url and d.url.endswith(":")


@pytest.mark.parametrize("raw", ["https://user:pa/{pw}@evil.net/", "https://user:pa?{pw}@evil.net/"])
def test_FR_CON_07_a_password_cut_by_a_delimiter_does_not_leak_as_a_port(raw):
    d = policy().check(raw.format(pw=PW))
    assert d.allowed is False
    assert ":pa" not in d.url
    _assert_clean(d.url)


def test_FR_CON_07_a_url_over_8kb_is_invalid_and_logged_without_its_body():
    p = policy()
    d = p.check("https://example.com/" + "a" * 9000)
    assert (d.allowed, d.reason) == (False, "invalid_url")
    assert d.url == "https:"
