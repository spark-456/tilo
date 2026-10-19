"""LW-08 security review round 1 fix pass (PR #698): deadline, event loop, HTML cap, transport errors, ports.

- One wall-clock deadline per `FetchService.fetch()` (DNS, robots.txt, every hop, headers, body).
- `POST /fetch` never blocks the event loop.
- HTML is capped at `MAX_HTML_BYTES` before decoding or parsing (and is not read in full from the wire).
- Every transport failure is a logged `upstream_error` (502); a body shorter than its Content-Length is refused.
- Only port 443 (plus the configured sandbox port for sandbox hosts) is fetched.
"""

from __future__ import annotations

import asyncio
import http.client
import io
import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

SANDBOX_HOST = "sandbox.tilo.test"
PUBLIC_HOST = "docs.allowed.example"
PUBLIC_IP = "93.184.216.34"
SERVICE_CALLER = "tilo-harness@tilo-dev.iam.gserviceaccount.com"
AUDIENCE = "https://tilo-browser.run.app"
VALID_TOKEN = "valid-" + "harness-oidc-token"
FIXED_NOW = datetime(2026, 10, 8, 9, 30, 0, tzinfo=UTC)
PDF = b"%PDF-1.4\n" + b"x" * 100 + b"\n%%EOF\n"
ROBOTS_ALLOW = b"User-agent: *\nAllow: /\n"


def _resolve(host: str, port: int) -> list[str]:
    return [PUBLIC_IP]


class ScriptTransport:
    """Programmable `FetchTransport`: robots.txt is 404 (allow), everything else goes to `handler`."""

    def __init__(self, handler: Callable[[str], Any]) -> None:
        self.handler = handler
        self.calls: list[tuple[str, str, int, str]] = []
        self.budgets: list[float | None] = []

    def send_get(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        pinned_ip: str,
        path_and_query: str,
        headers: dict[str, str],
        connect_timeout: float,
        read_timeout: float,
        max_bytes: int,
        time_budget: float | None = None,
    ):
        from tilo_browser.fetch import UpstreamResponse

        self.calls.append((scheme, host, port, path_and_query))
        self.budgets.append(time_budget)
        if path_and_query == "/robots.txt":
            return UpstreamResponse(404, {}, b"")
        return self.handler(path_and_query)


def make_service(tmp_path: Path, transport: Any, **kwargs: Any):
    from tilo_browser.fetch import FetchService, RawArchiveStore

    options: dict[str, Any] = {
        "base_allow": (),
        "sandbox_hosts": (SANDBOX_HOST,),
        "dns_resolver": _resolve,
        "transport": transport,
        "archive_store": RawArchiveStore(tmp_path / "archive"),
        "clock": lambda: FIXED_NOW,
    }
    options.update(kwargs)
    return FetchService(**options)


def make_client(service: Any) -> TestClient:
    return TestClient(make_app(service))


def make_app(service: Any):
    from tilo_browser.app import create_app

    def verify(token: str, audience: str) -> dict[str, Any]:
        if token != VALID_TOKEN:
            raise ValueError("invalid token")
        return {"iss": "https://accounts.google.com", "aud": audience, "email": SERVICE_CALLER, "email_verified": True}

    return create_app(fetch_service=service, oidc_verifier=verify, audience=AUDIENCE, allowed_callers=(SERVICE_CALLER,))


AUTH = {"Authorization": f"Bearer {VALID_TOKEN}"}


def pdf_ok(_path: str):
    from tilo_browser.fetch import UpstreamResponse

    return UpstreamResponse(200, {"content-type": "application/pdf"}, PDF)


# ---------------------------------------------------------------------------------------------------------------
# 1. One wall-clock deadline per fetch
# ---------------------------------------------------------------------------------------------------------------


class DripServer:
    """Local TCP server: robots.txt answers at once; any other path drips (body) or stalls inside the headers."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.stop = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.stop.set()
        self.listener.close()

    def _accept_loop(self) -> None:
        while not self.stop.is_set():
            try:
                conn, _addr = self.listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn: socket.socket) -> None:
        try:
            request = b""
            while b"\r\n\r\n" not in request:
                piece = conn.recv(4096)
                if not piece:
                    return
                request += piece
            path = request.split(b" ", 2)[1]
            if path == b"/robots.txt":
                head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(ROBOTS_ALLOW)}\r\nConnection: close\r\n\r\n"
                conn.sendall(head.encode("ascii") + ROBOTS_ALLOW)
                return
            if self.mode == "body":
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 10000000\r\nConnection: close\r\n\r\n%PDF-1.4\n")
                chunk = b"A"
            elif self.mode == "nolen":
                conn.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n%PDF-1.4\n")
                chunk = b"A"
            elif self.mode == "chunked":
                conn.sendall(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
                conn.sendall(b"9\r\n%PDF-1.4\n\r\n")
                chunk = b"1\r\nA\r\n"
            else:
                conn.sendall(b"HTTP/1.1 200 OK\r\nX-Pad: ")
                chunk = b"p"
            give_up = time.monotonic() + 20
            while not self.stop.is_set() and time.monotonic() < give_up:
                conn.sendall(chunk)
                time.sleep(0.2)
        except OSError:
            return
        finally:
            conn.close()


@pytest.fixture()
def drip(monkeypatch: pytest.MonkeyPatch):
    servers: list[DripServer] = []
    real_create = socket.create_connection

    def start(mode: str) -> DripServer:
        server = DripServer(mode)
        servers.append(server)

        def to_local(address: tuple[str, int], timeout: float | None = None, *_a: Any, **_kw: Any):
            return real_create(("127.0.0.1", server.port), timeout)

        monkeypatch.setattr(socket, "create_connection", to_local)
        return server

    yield start
    for server in servers:
        server.close()


@pytest.mark.parametrize("mode", ["body", "headers"])
def test_LW_08_slow_drip_upstream_hits_the_wall_clock_deadline_and_is_logged_as_timeout(
    tmp_path: Path, drip: Callable[[str], DripServer], mode: str
) -> None:
    from tilo_browser.fetch import FetchBlocked, PinnedHttpTransport

    drip(mode)
    deadline = 1.0
    # read_timeout (15 s) is far longer than the byte interval (0.2 s): only a wall-clock deadline can stop this.
    service = make_service(tmp_path, PinnedHttpTransport(), total_timeout=deadline, read_timeout=15.0)
    started = time.monotonic()
    with pytest.raises(FetchBlocked) as err:
        service.fetch(f"http://{SANDBOX_HOST}/papers/slow.pdf", allow_hosts=[SANDBOX_HOST])
    elapsed = time.monotonic() - started
    assert err.value.block.reason == "timeout"
    assert service.blocked[-1].reason == "timeout"
    assert elapsed < deadline + 1.0


def test_LW_08_deadline_is_shared_across_robots_and_every_redirect_hop_with_a_fake_clock(tmp_path: Path) -> None:
    from tilo_browser.fetch import FetchBlocked, UpstreamResponse

    now = [1000.0]

    def monotonic() -> float:
        return now[0]

    def redirecting(_path: str):
        return UpstreamResponse(302, {"location": "/papers/next"}, b"")

    transport = ScriptTransport(redirecting)
    inner = transport.send_get

    def slow_send(**kwargs: Any):
        now[0] += 25.0  # every upstream call "takes" 25 s of wall clock
        return inner(**kwargs)

    transport.send_get = slow_send  # type: ignore[method-assign]
    service = make_service(tmp_path, transport, total_timeout=60.0, monotonic=monotonic)
    with pytest.raises(FetchBlocked) as err:
        service.fetch(f"http://{SANDBOX_HOST}/papers/start", allow_hosts=[SANDBOX_HOST])
    assert err.value.block.reason == "timeout"
    assert service.blocked[-1].reason == "timeout"
    # robots (25 s) + hop 0 (50 s) + hop 1 would start with 10 s left; the third send is cut off by the deadline.
    assert len(transport.calls) <= 4
    budgets = [b for b in transport.budgets if b is not None]
    assert budgets and budgets == sorted(budgets, reverse=True)
    assert budgets[0] == pytest.approx(60.0)


def test_LW_08_default_total_timeout_is_60_seconds_and_must_be_positive(tmp_path: Path) -> None:
    from tilo_browser.fetch import DEFAULT_TOTAL_TIMEOUT

    assert DEFAULT_TOTAL_TIMEOUT == 60.0
    for bad in (0, -1, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            make_service(tmp_path, ScriptTransport(pdf_ok), total_timeout=bad)


def test_LW_08_slow_dns_counts_against_the_deadline(tmp_path: Path) -> None:
    from tilo_browser.fetch import FetchBlocked

    release = threading.Event()

    def hanging_resolver(host: str, port: int) -> list[str]:
        release.wait(10)
        return [PUBLIC_IP]

    service = make_service(tmp_path, ScriptTransport(pdf_ok), dns_resolver=hanging_resolver, total_timeout=0.5)
    started = time.monotonic()
    try:
        with pytest.raises(FetchBlocked) as err:
            service.fetch(f"http://{SANDBOX_HOST}/papers/paper-1.pdf", allow_hosts=[SANDBOX_HOST])
    finally:
        release.set()
    assert err.value.block.reason == "timeout"
    assert time.monotonic() - started < 1.5


# ---------------------------------------------------------------------------------------------------------------
# 2. The event loop stays free while a fetch is in flight
# ---------------------------------------------------------------------------------------------------------------


def test_LW_08_slow_fetch_does_not_block_health_on_the_event_loop(tmp_path: Path) -> None:
    def slow(_path: str):
        time.sleep(2.0)
        return pdf_ok(_path)

    app = make_app(make_service(tmp_path, ScriptTransport(slow)))

    async def scenario() -> tuple[float, httpx.Response]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:

            async def health_after_delay() -> float:
                await asyncio.sleep(0.3)
                began = time.perf_counter()
                reply = await client.get("/health")
                assert reply.status_code == 200
                return time.perf_counter() - began

            fetch_call = client.post(
                "/fetch",
                json={"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf", "allow_hosts": [SANDBOX_HOST]},
                headers=AUTH,
            )
            health_seconds, fetched = await asyncio.gather(health_after_delay(), fetch_call)
            return health_seconds, fetched

    health_seconds, fetched = asyncio.run(scenario())
    assert fetched.status_code == 200, fetched.text
    assert health_seconds < 0.2


# ---------------------------------------------------------------------------------------------------------------
# 3. HTML is capped before parsing
# ---------------------------------------------------------------------------------------------------------------


def test_LW_08_huge_html_with_parser_bomb_is_refused_html_too_large_in_under_a_second(tmp_path: Path) -> None:
    from tilo_browser.fetch import MAX_HTML_BYTES, UpstreamResponse

    assert MAX_HTML_BYTES == 512 * 1024
    bomb = b"<html>" + b"</" * ((25 * 1024 * 1024 - 6) // 2)
    transport = ScriptTransport(lambda _p: UpstreamResponse(200, {"content-type": "text/html"}, bomb))
    service = make_service(tmp_path, transport)
    client = make_client(service)
    started = time.monotonic()
    resp = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/bomb.html", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert time.monotonic() - started < 1.0
    assert resp.status_code == 413
    assert resp.json()["reason"] == "html_too_large"
    assert service.blocked[-1].reason == "html_too_large"


def test_LW_08_html_under_the_cap_is_still_converted_to_text(tmp_path: Path) -> None:
    from tilo_browser.fetch import UpstreamResponse

    page = b"<html><body><p>" + b"word " * 100_000 + b"</p><script>evil()</script></body></html>"
    assert len(page) < 512 * 1024
    service = make_service(tmp_path, ScriptTransport(lambda _p: UpstreamResponse(200, {}, page)))
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/long.html", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["media_type"] == "text/plain"


class FakeSocket:
    """Socket double for `PinnedHttpTransport`: the raw response depends on the requested path."""

    def __init__(self, routes: dict[str, bytes]) -> None:
        self.routes = routes
        self.sent = bytearray()
        self.streams: list[io.BytesIO] = []
        self.timeouts: list[float | None] = []

    def settimeout(self, value: float | None) -> None:
        self.timeouts.append(value)

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        path = bytes(self.sent).split(b" ", 2)[1].decode("ascii")
        stream = io.BytesIO(self.routes[path])
        self.streams.append(stream)
        return stream

    def close(self) -> None:
        pass


def patch_sockets(monkeypatch: pytest.MonkeyPatch, routes: dict[str, bytes]) -> list[FakeSocket]:
    made: list[FakeSocket] = []

    def fake_create_connection(address: tuple[str, int], timeout: float | None = None, *_a: Any, **_kw: Any):
        sock = FakeSocket(routes)
        made.append(sock)
        return sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    return made


ROBOTS_404 = b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"


def test_LW_08_pinned_transport_stops_reading_an_html_body_at_the_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from tilo_browser.fetch import MAX_HTML_BYTES, FetchBlocked, PinnedHttpTransport

    body = b"<html>" + b"</" * ((25 * 1024 * 1024 - 6) // 2)
    head = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
    sockets = patch_sockets(monkeypatch, {"/big.html": head + body})
    with pytest.raises(FetchBlocked) as err:
        PinnedHttpTransport().send_get(
            scheme="http",
            host=SANDBOX_HOST,
            port=80,
            pinned_ip=PUBLIC_IP,
            path_and_query="/big.html",
            headers={},
            connect_timeout=1.0,
            read_timeout=1.0,
            max_bytes=25 * 1024 * 1024,
        )
    assert err.value.block.reason == "html_too_large"
    assert sockets[0].streams[0].tell() < MAX_HTML_BYTES + 1024 * 1024


# ---------------------------------------------------------------------------------------------------------------
# 4. Transport failures are logged upstream_error (502), never 500 or 422
# ---------------------------------------------------------------------------------------------------------------


def _response(headers: str, body: bytes = b"") -> bytes:
    return b"HTTP/1.1 200 OK\r\n" + headers.encode("latin-1") + b"\r\n" + body


MALFORMED_RESPONSES: dict[str, bytes] = {
    "bad_status_line": b"garbage line\r\n\r\n",
    "too_many_headers": _response("X-A: y\r\n" * 101),
    "line_too_long": b"HTTP/1.1 200 OK\r\nX-A: " + b"a" * 70_000 + b"\r\n\r\n",
    "unicode_digit_content_length": _response("Content-Length: \xb2\r\n", b"%PDF-1.4\n"),
    "body_shorter_than_content_length": _response("Content-Length: 100\r\n", b"%PDF-1.4"),
}


@pytest.mark.parametrize("label", sorted(MALFORMED_RESPONSES))
def test_LW_08_malformed_upstream_responses_are_logged_upstream_error_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    from tilo_browser.fetch import PinnedHttpTransport

    raw = MALFORMED_RESPONSES[label]
    patch_sockets(monkeypatch, {"/robots.txt": ROBOTS_404, "/papers/bad.pdf": raw})
    service = make_service(tmp_path, PinnedHttpTransport())
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/bad.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 502, (label, resp.text)
    assert resp.json()["reason"] == "upstream_error"
    assert service.blocked[-1].reason == "upstream_error"
    assert not list((tmp_path / "archive").glob("**/*.blobs/*"))  # nothing archived or hashed


@pytest.mark.parametrize(
    "exc",
    [http.client.BadStatusLine("x"), http.client.LineTooLong("header line"), ValueError("bad"), ConnectionResetError()],
)
def test_LW_08_any_transport_exception_maps_to_logged_upstream_error(tmp_path: Path, exc: Exception) -> None:
    def boom(_path: str):
        raise exc

    service = make_service(tmp_path, ScriptTransport(boom))
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 502
    assert resp.json()["reason"] == "upstream_error"
    assert service.blocked[-1].reason == "upstream_error"


def test_LW_08_transport_exception_on_robots_txt_is_also_logged_upstream_error(tmp_path: Path) -> None:
    class BrokenRobots:
        def send_get(self, **_kw: Any):
            raise http.client.BadStatusLine("x")

    service = make_service(tmp_path, BrokenRobots())
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 502
    assert service.blocked[-1].reason == "upstream_error"


# ---------------------------------------------------------------------------------------------------------------
# 5. Ports
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("port", [22, 6379, 8443, 80])
def test_LW_08_only_port_443_is_fetched_for_public_hosts(tmp_path: Path, port: int) -> None:
    transport = ScriptTransport(pdf_ok)
    service = make_service(tmp_path, transport)
    resp = make_client(service).post(
        "/fetch", json={"url": f"https://{PUBLIC_HOST}:{port}/a.pdf", "allow_hosts": [PUBLIC_HOST]}, headers=AUTH
    )
    assert resp.status_code == 403
    assert resp.json()["reason"] == "port_not_allowed"
    assert transport.calls == []
    assert service.blocked[-1].reason == "port_not_allowed"


def test_LW_08_explicit_443_is_allowed_and_sandbox_hosts_may_use_the_configured_port(tmp_path: Path) -> None:
    transport = ScriptTransport(pdf_ok)
    service = make_service(tmp_path, transport, sandbox_port=8080)
    client = make_client(service)
    ok_public = client.post(
        "/fetch", json={"url": f"https://{PUBLIC_HOST}:443/a.pdf", "allow_hosts": [PUBLIC_HOST]}, headers=AUTH
    )
    assert ok_public.status_code == 200, ok_public.text
    ok_sandbox = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}:8080/a.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert ok_sandbox.status_code == 200, ok_sandbox.text
    other = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}:9999/a.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert other.status_code == 403
    assert other.json()["reason"] == "port_not_allowed"
    default_port = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/a.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert default_port.status_code == 403  # port 80 is not the configured sandbox port here


# ---------------------------------------------------------------------------------------------------------------
# Round 2: no deadlock at the unit cap, no truncated 200 at the deadline, /health independent of the fetch pool
# ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["body", "nolen", "chunked"])
def test_LW_08_deadline_never_returns_a_truncated_200_and_always_logs_timeout(
    tmp_path: Path, drip: Callable[[str], DripServer], mode: str
) -> None:
    from tilo_browser.fetch import FetchBlocked, PinnedHttpTransport

    drip(mode)
    for attempt in range(15):
        service = make_service(tmp_path, PinnedHttpTransport(), total_timeout=0.35, read_timeout=15.0)
        with pytest.raises(FetchBlocked) as err:
            service.fetch(f"http://{SANDBOX_HOST}/papers/slow{attempt}.pdf", allow_hosts=[SANDBOX_HOST])
        assert err.value.block.reason == "timeout", (mode, attempt, err.value.block.reason)
    assert not list((tmp_path / "archive").glob("**/*.blobs/*"))  # nothing truncated was archived or hashed


class _EofOnShutdownSocket:
    """Socket double whose blocked read returns a clean EOF once `shutdown` is called (as Linux does)."""

    def __init__(self, head: bytes) -> None:
        self.head = head
        self.shut = threading.Event()

    def settimeout(self, value: float | None) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        pass

    def shutdown(self, how: int) -> None:
        self.shut.set()

    def close(self) -> None:
        pass

    def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
        shut = self.shut

        class Stream(io.BytesIO):
            def read1(self, size: int = -1) -> bytes:
                data = super().read1(size)
                if data:
                    return data
                shut.wait(5)
                return b""

        return Stream(self.head)


@pytest.mark.parametrize("length_header", ["", "Content-Length: 100\r\n"])
def test_LW_08_eof_caused_by_the_watchdog_shutdown_is_a_timeout_not_a_truncated_body(
    monkeypatch: pytest.MonkeyPatch, length_header: str
) -> None:
    from tilo_browser.fetch import FetchBlocked, PinnedHttpTransport

    head = f"HTTP/1.1 200 OK\r\n{length_header}Connection: close\r\n\r\n%PDF-1.4\n".encode("ascii")
    sock = _EofOnShutdownSocket(head)
    monkeypatch.setattr(socket, "create_connection", lambda *_a, **_kw: sock)
    started = time.monotonic()
    with pytest.raises(FetchBlocked) as err:
        PinnedHttpTransport().send_get(
            scheme="http",
            host=SANDBOX_HOST,
            port=80,
            pinned_ip=PUBLIC_IP,
            path_and_query="/slow.pdf",
            headers={},
            connect_timeout=1.0,
            read_timeout=15.0,
            max_bytes=1024 * 1024,
            time_budget=0.3,
        )
    assert err.value.block.reason == "timeout"
    assert time.monotonic() - started < 2.0


def test_LW_08_unit_file_cap_under_concurrent_fetches_does_not_deadlock_the_service_lock(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    from tilo_browser.fetch import FetchBlocked

    callers = 12
    gate = threading.Barrier(callers, timeout=10)

    def after_everyone_downloaded(path: str):
        gate.wait()  # all callers pass the early cap check before any reaches the post-download one
        return pdf_ok(path)

    service = make_service(tmp_path, ScriptTransport(after_everyone_downloaded))

    def one(i: int) -> str:
        try:
            service.fetch(
                f"http://{SANDBOX_HOST}/papers/p{i}.pdf", allow_hosts=[SANDBOX_HOST], run_id="r_cap", unit_id="U1"
            )
            return "ok"
        except FetchBlocked as exc:
            return exc.block.reason

    pool = ThreadPoolExecutor(max_workers=callers)
    futures = [pool.submit(one, i) for i in range(callers)]
    results = sorted(f.result(timeout=15) for f in futures)
    pool.shutdown(wait=True)
    assert results == ["ok"] * 10 + ["unit_file_limit"] * 2
    assert service._lock.acquire(timeout=1), "service lock was left held"
    service._lock.release()


def test_LW_08_unit_file_cap_through_the_app_leaves_later_fetches_working(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    callers = 12
    gate = threading.Barrier(callers, timeout=10)

    def after_everyone_downloaded(path: str):
        try:
            gate.wait()
        except threading.BrokenBarrierError:
            pass  # aborted below so the later fetch does not wait for a crowd
        return pdf_ok(path)

    service = make_service(tmp_path, ScriptTransport(after_everyone_downloaded))
    client = make_client(service)

    def one(i: int) -> tuple[int, str | None]:
        resp = client.post(
            "/fetch",
            json={
                "url": f"http://{SANDBOX_HOST}/papers/p{i}.pdf",
                "allow_hosts": [SANDBOX_HOST],
                "run_id": "r_cap",
                "unit_id": "U1",
            },
            headers=AUTH,
        )
        return resp.status_code, resp.json().get("reason")

    pool = ThreadPoolExecutor(max_workers=callers)
    try:
        results = sorted(f.result(timeout=20) for f in [pool.submit(one, i) for i in range(callers)])
    finally:
        pool.shutdown(wait=False)  # a deadlocked worker must fail the test, not hang it
    assert [r for r in results if r[0] == 200] == [(200, None)] * 10
    assert [r for r in results if r[0] != 200] == [(413, "unit_file_limit")] * 2

    gate.abort()  # later fetches must not wait for a crowd
    later = client.post(
        "/fetch",
        json={"url": f"http://{SANDBOX_HOST}/papers/later.pdf", "allow_hosts": [SANDBOX_HOST], "run_id": "r_other"},
        headers=AUTH,
    )
    assert later.status_code == 200, later.text
    assert service._lock.acquire(timeout=1)
    service._lock.release()


def test_LW_08_health_stays_fast_with_more_slow_fetches_than_pool_threads(tmp_path: Path) -> None:
    def slow(path: str):
        time.sleep(1.0)
        return pdf_ok(path)

    app = make_app(make_service(tmp_path, ScriptTransport(slow)))

    async def scenario() -> tuple[float, list[int]]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:

            async def health_after_delay() -> float:
                await asyncio.sleep(0.4)
                began = time.perf_counter()
                assert (await client.get("/health")).status_code == 200
                return time.perf_counter() - began

            fetches = [
                client.post(
                    "/fetch",
                    json={
                        "url": f"http://{SANDBOX_HOST}/papers/p.pdf",
                        "allow_hosts": [SANDBOX_HOST],
                        "run_id": f"r_load{i}",
                    },
                    headers=AUTH,
                )
                for i in range(50)
            ]
            health_seconds, *replies = await asyncio.gather(health_after_delay(), *fetches)
            return health_seconds, [r.status_code for r in replies]

    health_seconds, statuses = asyncio.run(scenario())
    assert statuses == [200] * 50
    assert health_seconds < 0.2


def test_LW_08_broken_endtag_html_under_cap_parses_quickly_and_honors_deadline(tmp_path: Path) -> None:
    from tilo_browser.fetch import MAX_HTML_BYTES, FetchBlocked, UpstreamResponse, detect_media_type

    bomb_under_cap = b"<html><body>ok " + b"</" * ((MAX_HTML_BYTES - 64) // 2) + b"</body></html>"
    assert len(bomb_under_cap) <= MAX_HTML_BYTES
    started = time.monotonic()
    media_type, plain = detect_media_type(bomb_under_cap, url="https://a.test/x", host="a.test")
    assert time.monotonic() - started < 0.5
    assert media_type == "text/plain" and b"ok" in plain

    with pytest.raises(FetchBlocked) as err:
        detect_media_type(
            b"<html><body><p>a</p></body></html>",
            url="https://a.test/x",
            host="a.test",
            deadline=0.0,
            monotonic=lambda: 1.0,
        )
    assert err.value.block.reason == "timeout"
    _ = UpstreamResponse


@pytest.mark.parametrize("exc", [UnicodeError("idna"), ValueError("bad"), RuntimeError("resolver boom")])
def test_LW_08_non_oserror_resolver_exceptions_map_to_logged_502_upstream_error(tmp_path: Path, exc: Exception) -> None:
    def broken_resolver(_host: str, _port: int) -> list[str]:
        raise exc

    service = make_service(tmp_path, ScriptTransport(pdf_ok), dns_resolver=broken_resolver)
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 502
    assert resp.json()["reason"] == "upstream_error"
    assert service.blocked[-1].reason == "upstream_error"


def test_LW_08_multi_ip_fallback_tries_next_validated_ip_while_blocking_any_private_ip(tmp_path: Path) -> None:
    from tilo_browser.fetch import UpstreamResponse

    seen_ips: list[str] = []

    class FallbackTransport:
        def send_get(self, *, pinned_ip: str, path_and_query: str, **_kw: Any) -> UpstreamResponse:
            seen_ips.append(pinned_ip)
            if pinned_ip == "2606:4700:4700::1111":
                raise OSError("IPv6 unreachable")
            return pdf_ok(path_and_query)

    service = make_service(
        tmp_path, FallbackTransport(), dns_resolver=lambda _h, _p: ["2606:4700:4700::1111", PUBLIC_IP]
    )
    resp = make_client(service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert resp.status_code == 200, resp.text
    assert seen_ips[:2] == ["2606:4700:4700::1111", PUBLIC_IP]
    assert service.blocked == []

    mixed_service = make_service(tmp_path, FallbackTransport(), dns_resolver=lambda _h, _p: [PUBLIC_IP, "10.0.0.1"])
    mixed_resp = make_client(mixed_service).post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert mixed_resp.status_code == 403
    assert mixed_resp.json()["reason"] == "ssrf_blocked"


def test_LW_08_robots_error_cache_expires_and_blocked_history_is_bounded(tmp_path: Path) -> None:
    from tilo_browser.fetch import MAX_BLOCKED_HISTORY, UpstreamResponse

    now = [100.0]
    robots_status = [503]

    class RobotsTransport:
        def send_get(self, *, path_and_query: str, **_kw: Any) -> UpstreamResponse:
            if path_and_query == "/robots.txt":
                return UpstreamResponse(robots_status[0], {}, b"User-agent: *\nAllow: /\n")
            return pdf_ok(path_and_query)

    service = make_service(
        tmp_path, RobotsTransport(), monotonic=lambda: now[0], robots_error_ttl=10.0, robots_ttl=60.0
    )
    client = make_client(service)
    r1 = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert r1.status_code == 403 and r1.json()["reason"] == "robots_disallowed"

    robots_status[0] = 200
    now[0] += 11.0  # past robots_error_ttl
    r2 = client.post(
        "/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]}, headers=AUTH
    )
    assert r2.status_code == 200

    for i in range(MAX_BLOCKED_HISTORY + 25):
        service._record_block(
            "host_not_allowed", f"https://untrusted.example/{i}", host="untrusted.example", allowlist=()
        )
    assert len(service.blocked) == MAX_BLOCKED_HISTORY


def test_LW_08_ooxml_with_vba_or_ole_is_refused_and_html_strips_void_embed_and_hidden(tmp_path: Path) -> None:
    import zipfile

    from tilo_browser.fetch import FetchBlocked, detect_media_type

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
        zf.writestr("word/vbaProject.bin", b"macro")
    with pytest.raises(FetchBlocked) as err:
        detect_media_type(buf.getvalue(), url="https://a.test/doc.docx", host="a.test")
    assert err.value.block.reason == "archive_refused"

    html = (
        b"<!doctype html><html><body>"
        b"<embed src='x.swf'>Visible text"
        b"<div hidden>secret1</div>"
        b"<span aria-hidden='true'>secret2</span>"
        b"<p style='display: none'>secret3</p>"
        b"&lt;script&gt;evil()&lt;/script&gt;"
        b"</body></html>"
    )
    media_type, plain = detect_media_type(html, url="https://a.test/page.html", host="a.test")
    text = plain.decode("utf-8")
    assert media_type == "text/plain"
    assert "Visible text" in text
    assert "secret1" not in text and "secret2" not in text and "secret3" not in text
    assert "<script>" not in text


def test_LW_08_slow_oidc_verifier_runs_in_threadpool_without_blocking_health(tmp_path: Path) -> None:
    from tilo_browser.app import create_app

    def slow_verifier(_token: str, audience: str) -> dict[str, Any]:
        time.sleep(0.3)
        return {"email": SERVICE_CALLER, "email_verified": True, "aud": audience, "iss": "https://accounts.google.com"}

    app = create_app(
        fetch_service=make_service(tmp_path, ScriptTransport(pdf_ok)),
        oidc_verifier=slow_verifier,
        audience=AUDIENCE,
        allowed_callers=[SERVICE_CALLER],
    )

    async def scenario() -> tuple[float, int]:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://browser.test") as client:
            fetch_task = asyncio.create_task(
                client.post(
                    "/fetch",
                    json={"url": f"http://{SANDBOX_HOST}/papers/p.pdf", "allow_hosts": [SANDBOX_HOST]},
                    headers=AUTH,
                )
            )
            await asyncio.sleep(0.05)
            t0 = time.perf_counter()
            assert (await client.get("/health")).status_code == 200
            elapsed = time.perf_counter() - t0
            resp = await fetch_task
            return elapsed, resp.status_code

    elapsed, status = asyncio.run(scenario())
    assert status == 200
    assert elapsed < 0.15
