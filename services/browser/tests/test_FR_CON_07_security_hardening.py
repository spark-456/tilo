"""FR-CON-07 security hardening (PR #140 security round 1; PRD 12.3, 16.1 rule 4, 16.2, SEC-09).

Page content and URLs are untrusted. These tests pin: the masker and the egress gate stay
linear on hostile input; userinfo never reaches a log in ANY URL form; a secret in a path or a
host label never reaches a Decision, an error or a returned URL; hosts are compared the way
browsers compare them (UTS 46 non-transitional), so look-alikes do not pass as allowlisted.

Fake secrets are assembled at runtime (`_browser_lib.fake_secrets`); nothing here is real.
"""

from __future__ import annotations

import time
from urllib.parse import quote

import pytest
from _browser_lib import FakeDriver, FakeEngine, FakeWeb, fake_secrets

S = fake_secrets()
LIMIT_S = 1.0


def policy(allow=("example.com",), **kw):
    from tilo_browser.egress import EgressPolicy

    return EgressPolicy(allow=list(allow), **kw)


def _timed(fn, arg) -> float:
    start = time.perf_counter()
    fn(arg)
    return time.perf_counter() - start


# -- 1. no super-linear work on hostile input ------------------------------------------------------

HOSTILE = {
    "single_digit_groups": "1 " * 50000,
    "two_digit_groups": "11 " * 50000,
    "dash_words": "a-" * 50000,
    "one_long_word": "a" * 200000,
    "long_digit_run": "1" * 200000,
    "jwt_prefixes": "eyJ" * 60000,
    "key_prefixes": "sk-" * 60000,
    "keywords": "token " * 40000,
    "keyword_equals": "password=" * 30000,
    "at_signs": "a@" * 100000,
    "at_after_word": "a" * 100000 + "@" + "b" * 100000,
    "plus_numbers": "+1 " * 60000,
    "bearer": "Bearer " * 30000,
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_FR_CON_07_mask_text_is_linear_on_hostile_page_content(name):
    from tilo_browser.masking import mask_text

    assert _timed(mask_text, HOSTILE[name]) < LIMIT_S, name


@pytest.mark.parametrize("name", ["single_digit_groups", "dash_words", "one_long_word", "two_digit_groups"])
def test_FR_CON_07_a_card_in_a_hostile_run_of_digits_is_still_masked(name):
    from _browser_lib import fake_card_numbers
    from tilo_browser.masking import mask_text

    card = fake_card_numbers()["spaced"]
    out = mask_text(HOSTILE[name] + " " + card)
    assert card not in out and out.endswith("[masked:card]")


@pytest.mark.parametrize("query", ["1+" * 4000, "a-" * 4000, "q=" + "a" * 8000, "x=" + "11+" * 2700])
def test_FR_CON_07_the_egress_gate_checks_an_8kb_query_in_under_a_second(query):
    p = policy()
    assert _timed(p.check, f"https://example.com/search?{query}") < LIMIT_S


def test_FR_CON_07_the_egress_gate_is_linear_on_a_huge_path_and_host():
    p = policy()
    assert _timed(p.check, "https://example.com/" + "a-" * 50000) < LIMIT_S
    assert _timed(p.check, "https://" + "a" * 200000 + ".net/") < LIMIT_S
    assert _timed(p.check, "https://user:" + "a-" * 50000 + "@evil.net/") < LIMIT_S


# -- 2. userinfo is removed in every form, before any truncation ------------------------------------

USERINFO_FORMS = {
    "scheme_no_slashes": "https:user:{pw}@evil.net/path",
    "scheme_one_slash": "https:/user:{pw}@evil.net/path",
    "protocol_relative": "//user:{pw}@evil.net/path",
    "normal": "https://user:{pw}@evil.net/path",
    "long_userinfo": "https://admin:{pad}{pw}@evil.net/path",
    "two_ats": "https://a@user:{pw}@evil.net/path",
}


@pytest.mark.parametrize("form", list(USERINFO_FORMS))
def test_FR_CON_07_userinfo_never_reaches_the_decision_log_in_any_url_form(form):
    pw = S["password"]
    p = policy()
    d = p.check(USERINFO_FORMS[form].format(pw=pw, pad="x" * 300))
    assert d.allowed is False
    dump = repr(p.decisions) + repr(p.blocked) + repr(d)
    assert pw not in dump and "@" not in d.url
    assert len(d.url) <= 200


@pytest.mark.parametrize("form", ["scheme_no_slashes", "scheme_one_slash", "protocol_relative", "long_userinfo"])
def test_FR_CON_07_userinfo_never_reaches_the_blocked_error_text(make_rig, form):
    from tilo_browser.egress import EgressBlocked

    pw = S["password"]
    rig = make_rig()
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate(USERINFO_FORMS[form].format(pw=pw, pad="x" * 300))
    assert pw not in str(ei.value) and pw not in repr(rig.policy.decisions)


def test_FR_CON_07_the_redirect_from_log_also_drops_userinfo():
    pw = S["password"]
    p = policy()
    d = p.check("https://evil.net/x", redirect_from=f"https:user:{pw}@example.com/start")
    assert pw not in repr(d)


# -- 3. secrets in a path or a host label never leave the worker -------------------------------------


def test_FR_CON_07_a_secret_in_the_path_is_masked_in_every_decision_and_error(make_rig):
    from tilo_browser.egress import EgressBlocked

    key = S["api_key"]
    p = policy()
    ok = p.check(f"https://example.com/k/{key}")
    bad = p.check(f"https://evil.net/collect/{key}")
    assert ok.allowed is True and bad.allowed is False
    assert key not in repr(p.decisions) and key not in repr(p.blocked)
    assert "[masked:secret]" in ok.url and bad.url.startswith("https://evil.net/collect/")
    rig = make_rig()
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate(f"https://evil.net/collect/{key}")
    assert key not in str(ei.value) and key not in repr(rig.policy.decisions)


def test_FR_CON_07_a_percent_encoded_secret_in_the_path_is_masked_too():
    key = S["api_key"]
    p = policy()
    d = p.check("https://evil.net/collect/" + quote(key, safe="") + "/x")
    assert key not in repr(d) and quote(key, safe="") not in repr(d)
    d2 = p.check("https://evil.net/c/" + "".join(f"%{ord(c):02X}" for c in key))
    assert key not in repr(d2) and "%73%6B" not in repr(d2)


def test_FR_CON_07_a_secret_in_a_host_label_is_masked_in_the_decision_host_url_and_error(make_rig):
    from tilo_browser.egress import EgressBlocked

    key = S["api_key"]
    p = policy()
    d = p.check(f"https://{key}.evil.net/")
    assert d.allowed is False
    assert key not in repr(p.decisions) and key not in (d.host or "") and key not in d.url
    rig = make_rig()
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate(f"https://{key}.evil.net/")
    assert key not in str(ei.value) and key not in repr(rig.policy.decisions)


def test_FR_CON_07_navigate_and_capture_return_urls_with_the_path_secret_masked(make_rig):
    key = S["api_key"]
    rig = make_rig()
    rig.web.add(f"https://example.com/k/{key}", title="Page", text="Hello")
    out = rig.worker.navigate(f"https://example.com/k/{key}")
    assert key not in repr(out)
    cap = rig.worker.capture()
    assert key not in repr(cap) and key not in cap.url


def test_FR_CON_07_the_login_card_names_no_secret_even_if_the_host_label_looks_like_one(make_rig):
    from _browser_lib import button, login_page, password_box

    key = S["api_key"]
    rig = make_rig(allow=["*.example.com"])
    url = f"https://{key}.example.com/login"
    login_page(rig.web, url, password_box("pw"), button("go", "Sign in"))
    rig.worker.navigate(url)
    assert len(rig.cards) == 1 and key not in repr(rig.cards)


# -- 4. hosts compare the way browsers compare them (UTS 46 non-transitional) -------------------------


def test_FR_CON_07_a_sharp_s_host_is_not_the_double_s_host():
    p = policy(allow=["glasses.com"])
    assert p.check("https://glasses.com/").allowed is True
    d = p.check("https://glaßes.com/")
    assert d.allowed is False and d.reason == "host_not_allowlisted"
    assert d.host == "xn--glaes-nqa.com"


def test_FR_CON_07_the_sharp_s_look_alike_is_blocked_through_the_worker_and_never_sent(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig(allow=["glasses.com"])
    with pytest.raises(EgressBlocked):
        rig.worker.navigate("https://glaßes.com/")
    assert rig.web.requests == []


def test_FR_CON_07_a_final_sigma_is_not_a_sigma():
    p = policy(allow=["σσ.com"])
    assert p.check("https://σσ.com/").allowed is True
    assert p.check("https://σς.com/").allowed is False


@pytest.mark.parametrize("joiner", ["‌", "‍"])
def test_FR_CON_07_zero_width_joiners_do_not_vanish_into_an_allowlisted_host(joiner):
    d = policy(allow=["ab.com"]).check(f"https://a{joiner}b.com/")
    assert d.allowed is False


@pytest.mark.parametrize("host", ["EXAMPLE.com", "Example.COM", "example.com"])
def test_FR_CON_07_case_still_folds(host):
    assert policy().check(f"https://{host}/").allowed is True


# -- cheap follow-ups -------------------------------------------------------------------------------


class _AbortWithoutGate(FakeDriver):
    """A driver that reports an aborted request without ever asking the gate."""

    def goto(self, url):
        return {"chain": [url], "aborted": url, "final_url": None}


class _AbortEngine(FakeEngine):
    def new_context(self, gate):
        driver = _AbortWithoutGate(self.web, gate, len(self.contexts))
        self.contexts.append(driver)
        return driver


def test_FR_CON_07_an_aborted_request_with_no_logged_decision_still_raises_egress_blocked(make_rig):
    from tilo_browser.egress import EgressBlocked

    web = FakeWeb()
    rig = make_rig(web, engine=_AbortEngine(web))
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate("https://example.com/?token=" + S["kv_token"])
    assert ei.value.decision.allowed is False
    assert S["kv_token"] not in str(ei.value)


def test_FR_CON_07_the_login_card_options_are_built_from_the_pinned_option_ids():
    from tilo_browser import login

    ctx = login.CardContext("w_01", "r_01", {"building": "B2", "agent": "A_s1"}, lambda: "X", lambda: "T", 60)
    card = login.build_login_card(login.LoginSignal("password_field", ()), url="https://example.com/", ctx=ctx)
    assert tuple(o["id"] for o in card["options"]) == login.LOGIN_CARD_OPTION_IDS
