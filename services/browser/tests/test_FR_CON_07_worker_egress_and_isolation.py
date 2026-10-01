"""FR-CON-07 through the worker (PRD 12.3, 16.1 rule 3, 16.2, SEC-09): a `BrowserWorker` is the
`HandsProvider` for one run. It opens ONE isolated browser context via `engine.new_context(gate)`,
installs the egress allowlist as that context's request gate (so navigation, every redirect hop,
subresources and click-triggered loads are all gated), blocks and logs what is not allowlisted,
and closes the context at the end of the run so no cookies or storage outlive it.

Defaults chosen (listed in the ticket report):
- a blocked top-level navigation (or a blocked redirect hop) raises `EgressBlocked` and the page
  is left as it was; a blocked subresource does not fail the page, it is just never sent;
- one worker = one run = one context; after `close()` every operation raises `WorkerClosed`.
"""

from __future__ import annotations

import pytest
from _browser_lib import EMAIL, FakeEngine, FakeWeb, button, doc, fake_secrets
from tilo_providers.interfaces import HandsProvider


def _blocked_hosts(policy) -> list[str | None]:
    return [d.host for d in policy.blocked]


def test_FR_CON_07_navigation_to_a_non_allowlisted_host_is_blocked_logged_and_never_sent(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate("https://evil.net/landing")
    assert ei.value.decision.allowed is False
    assert ei.value.decision.reason == "host_not_allowlisted"
    assert rig.driver.sent == []
    assert rig.web.requests == []
    assert _blocked_hosts(rig.policy) == ["evil.net"]


def test_FR_CON_07_navigation_to_an_allowlisted_host_loads_and_is_not_blocked(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/", title="Home", text="Hello")
    out = rig.worker.navigate("https://example.com/")
    assert out["url"].startswith("https://example.com/")
    assert rig.driver.sent == ["https://example.com/"]
    assert rig.policy.blocked == []


def test_FR_CON_07_a_redirect_to_a_non_allowlisted_host_is_blocked_logged_and_never_followed(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    rig.web.add("https://example.com/go", redirect_to="https://evil.net/steal")
    with pytest.raises(EgressBlocked):
        rig.worker.navigate("https://example.com/go")
    assert rig.driver.sent == ["https://example.com/go"], "the redirect target must never be requested"
    (blocked,) = rig.policy.blocked
    assert blocked.host == "evil.net"
    assert blocked.redirect_from is not None and blocked.redirect_from.startswith("https://example.com/go")


def test_FR_CON_07_a_multi_hop_redirect_chain_is_checked_hop_by_hop(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig(allow=["example.com", "*.cdn.example.org"])
    rig.web.add("https://example.com/a", redirect_to="https://img.cdn.example.org/b")
    rig.web.add("https://img.cdn.example.org/b", redirect_to="https://img.cdn.example.org.evil.net/c")
    with pytest.raises(EgressBlocked):
        rig.worker.navigate("https://example.com/a")
    assert rig.driver.sent == ["https://example.com/a", "https://img.cdn.example.org/b"]
    assert _blocked_hosts(rig.policy) == ["img.cdn.example.org.evil.net"]


def test_FR_CON_07_redirects_that_stay_on_the_allowlist_are_followed(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/old", redirect_to="https://example.com/new")
    rig.web.add("https://example.com/new", title="New")
    out = rig.worker.navigate("https://example.com/old")
    assert out["url"].startswith("https://example.com/new")
    assert rig.driver.sent == ["https://example.com/old", "https://example.com/new"]
    assert rig.policy.blocked == []


def test_FR_CON_07_an_https_to_http_redirect_downgrade_is_blocked(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    rig.web.add("https://example.com/", redirect_to="http://example.com/insecure")
    with pytest.raises(EgressBlocked) as ei:
        rig.worker.navigate("https://example.com/")
    assert ei.value.decision.reason == "scheme_not_allowed"
    assert rig.driver.sent == ["https://example.com/"]


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "https://user:pw@example.com/",
        "https://127.0.0.1/",
    ],
)
def test_FR_CON_07_the_worker_refuses_unsafe_urls_before_any_request_is_sent(make_rig, url):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    with pytest.raises(EgressBlocked):
        rig.worker.navigate(url)
    assert rig.web.requests == []
    assert len(rig.policy.blocked) == 1


def test_FR_CON_07_blocked_subresources_are_never_sent_but_the_page_still_loads(make_rig):
    rig = make_rig(allow=["example.com", "*.cdn.example.org"])
    rig.web.add(
        "https://example.com/shop",
        title="Shop",
        text="Winter boots",
        subrequests=(
            "https://static.cdn.example.org/app.js",
            f"https://tracker.evil.net/pixel.gif?d={EMAIL}",
            "https://example.com/style.css",
        ),
    )
    rig.worker.navigate("https://example.com/shop")
    assert rig.driver.sent == [
        "https://example.com/shop",
        "https://static.cdn.example.org/app.js",
        "https://example.com/style.css",
    ]
    assert _blocked_hosts(rig.policy) == ["tracker.evil.net"]
    assert EMAIL not in repr(rig.policy.decisions), "a blocked URL's query must not reach the log"
    assert "Winter boots" in rig.worker.capture().text


def test_FR_CON_07_a_click_that_navigates_off_the_allowlist_is_blocked_and_logged(make_rig):
    from tilo_browser.egress import EgressBlocked

    rig = make_rig()
    rig.web.add(
        "https://example.com/",
        tree=doc(button("go", "Visit partner"), title="Home"),
        links={"go": "https://partner.evil.net/offer"},
    )
    rig.worker.navigate("https://example.com/")
    ref = rig.worker.find_element("#go")["ref"]
    with pytest.raises(EgressBlocked):
        rig.worker.click(ref)
    assert rig.driver.sent == ["https://example.com/"]
    assert _blocked_hosts(rig.policy) == ["partner.evil.net"]


def test_FR_CON_07_the_blocked_log_holds_no_secrets_from_the_urls_that_were_blocked(make_rig):
    from tilo_browser.egress import EgressBlocked

    s = fake_secrets()
    rig = make_rig()
    with pytest.raises(EgressBlocked):
        rig.worker.navigate(f"https://user:{s['password']}@evil.net/x?token={s['kv_token']}")
    dump = repr(rig.policy.decisions)
    assert s["password"] not in dump and s["kv_token"] not in dump


# ---------------------------------------------------------------------------
# Isolation: no shared cookies or storage between runs (PRD 12.3, 16.1 rule 3).


def _cookie_site(web: FakeWeb) -> None:
    web.add(
        "https://example.com/",
        title="Home",
        cookies_set={"sid": "session-cookie-value"},
        local_storage_set={"seen": "1"},
    )


def test_FR_CON_07_a_second_run_starts_with_no_cookies_or_storage_from_the_first(make_rig):
    web = FakeWeb()
    _cookie_site(web)
    engine = FakeEngine(web)
    first = make_rig(web, engine=engine)
    first.worker.navigate("https://example.com/")
    assert engine.contexts[0].cookies == {"sid": "session-cookie-value"}
    first.worker.close()

    second = make_rig(web, engine=engine)
    second.worker.navigate("https://example.com/")
    assert web.requests[-1].context_index == 1
    assert web.requests[-1].cookies == {}, "run 2 must not send run 1's cookie"
    assert len(engine.contexts) == 2 and engine.contexts[0] is not engine.contexts[1]


def test_FR_CON_07_two_workers_alive_at_once_do_not_share_cookies(make_rig):
    web = FakeWeb()
    _cookie_site(web)
    engine = FakeEngine(web)
    a = make_rig(web, engine=engine)
    b = make_rig(web, engine=engine)
    a.worker.navigate("https://example.com/")
    b.worker.navigate("https://example.com/")
    by_ctx = {r.context_index: r.cookies for r in web.requests}
    assert by_ctx[1] == {}, "B's first request must carry none of A's cookies"
    assert engine.contexts[0].cookies is not engine.contexts[1].cookies


def test_FR_CON_07_close_ends_the_run_and_discards_the_context_storage(make_rig):
    rig = make_rig()
    _cookie_site(rig.web)
    rig.worker.navigate("https://example.com/")
    ctx = rig.driver
    assert ctx.cookies and ctx.local_storage
    rig.worker.close()
    assert ctx.closed is True and ctx.cookies == {} and ctx.local_storage == {}
    rig.worker.close()  # idempotent
    assert ctx.close_calls == 1


def test_FR_CON_07_a_closed_worker_refuses_further_operations(make_rig):
    from tilo_browser.worker import WorkerClosed

    rig = make_rig()
    rig.web.add("https://example.com/", tree=doc(button("go", "Go"), title="Home"))
    rig.worker.navigate("https://example.com/")
    rig.worker.close()
    for call in (
        lambda: rig.worker.navigate("https://example.com/"),
        lambda: rig.worker.find_element("#go"),
        lambda: rig.worker.click("go"),
        lambda: rig.worker.read_accessibility_tree(),
        lambda: rig.worker.screenshot(),
        lambda: rig.worker.capture(),
    ):
        with pytest.raises(WorkerClosed):
            call()


def test_FR_CON_07_the_worker_is_a_context_manager_that_closes_the_run(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/", title="Home")
    with rig.worker as w:
        w.navigate("https://example.com/")
    assert rig.driver.closed is True


def test_FR_CON_07_the_worker_opens_exactly_one_context_per_run(make_rig):
    rig = make_rig()
    rig.web.add("https://example.com/", title="Home")
    rig.worker.navigate("https://example.com/")
    rig.worker.navigate("https://example.com/")
    assert len(rig.engine.contexts) == 1


# ---------------------------------------------------------------------------
# FR-CON-13 (already specified for the interface in packages/providers) applied to this worker.


def _conformance_check(hands):
    """Same shape as packages/providers/tests/test_PRD_12_5_hands_provider_interface.py."""
    hands.navigate("https://example.com/")
    ref = hands.find_element("#go")["ref"]
    hands.click(ref)
    hands.type(ref, "hello")
    assert isinstance(hands.read_accessibility_tree(), dict)
    assert isinstance(hands.screenshot(), bytes | bytearray)
    hands.upload_file(ref, "file.txt")
    assert isinstance(hands.download_file(ref), bytes | bytearray)


def test_FR_CON_07_the_cloud_browser_worker_is_a_hands_provider_and_passes_the_conformance_check(make_rig):
    from tilo_browser.worker import BrowserWorker

    assert issubclass(BrowserWorker, HandsProvider)
    rig = make_rig()
    from _browser_lib import textbox

    rig.web.add("https://example.com/", tree=doc(textbox("go", "Search"), title="Home"))
    assert isinstance(rig.worker, HandsProvider)
    _conformance_check(rig.worker)
    assert rig.driver.typed == [("go", "hello")]
    assert rig.driver.uploaded == [("go", "file.txt")]
