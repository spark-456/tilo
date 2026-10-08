"""Service-to-service live web fetch for tilo-browser (LW-08, PRD 12.3, 16.2, SEC-09, FR-INT-01, ADR-0029).

Security invariants enforced on every call:
- HTTPS GET only (`http` permitted solely for explicitly configured `sandbox_hosts`).
- No cookies stored or sent; no `Authorization` or credential headers forwarded upstream.
- Host must pass `EgressPolicy` (base allowlist + per-task `allow_hosts` from the request).
- Custom DNS resolution before connecting; every resolved IP must be global unicast (refuses loopback,
  RFC1918 private, CGNAT 100.64.0.0/10, link-local 169.254.0.0/16 and fe80::/10, cloud metadata
  169.254.169.254 and metadata.google.internal, IPv6 ULA fc00::/7, IPv6-mapped IPv4, NAT64, 6to4, Teredo).
- Resolved IP is pinned for the TCP connection while keeping the original host for `Host` and TLS SNI.
- Every redirect hop (at most 5) re-runs egress policy, DNS resolution, IP pinning, and `robots.txt`.
- `robots.txt` is honoured and cached per `(scheme, host, port)`.
- One wall-clock deadline per `FetchService.fetch()` (default 60 s) covers DNS, `robots.txt`, every redirect hop,
  the header read and the body; the remaining time is passed to the transport, which checks it inside its read
  loop and aborts a stalled socket. Expiry is refused and logged as `timeout` (HTTP 504).
- Only port 443 is fetched (plus the configured sandbox port for sandbox hosts).
- Streaming enforces 25 MiB per file and 10 files / 50 MB per unit (FR-INT-01). HTML is capped at
  `MAX_HTML_BYTES` (2 MiB) before it is decoded or parsed; larger pages are refused as `html_too_large` (HTTP 413),
  and the transport stops reading an HTML body at the cap. A body shorter than its `Content-Length`, a malformed
  header or any other transport error is refused as `upstream_error` (HTTP 502).
- Media type is determined strictly from magic bytes (`tilo_planning.extraction.FILE_TYPES`), never from
  URL extension or `Content-Type`; bare archives and executables are refused; HTML is converted to plain
  text with `<script>`/`<style>` removed.
- Every blocked request is logged with its reason and sanitised URL (no query string, no userinfo, no body).
"""

from __future__ import annotations

import hashlib
import http.client
import io
import ipaddress
import logging
import math
import re
import socket
import ssl
import threading
import time
import urllib.robotparser
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit

from tilo_archive.archive import ORG_ID_RE, RUN_ID_RE, LocalDirStore, RunArchive, Store
from tilo_archive.record import format_ts
from tilo_planning.extraction import FILE_TYPES, ExtractionError, _check_directory

from tilo_browser.egress import EgressPolicy, _normalise_host, sanitise_url
from tilo_browser.masking import mask_data, mask_text

log = logging.getLogger("tilo_browser.fetch")

MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MiB per file
MAX_ROBOTS_BYTES = 512 * 1024
MAX_HTML_BYTES = 2 * 1024 * 1024  # HTML is parsed in memory: refuse larger pages before decoding
MAX_UNIT_FILES = 10  # FR-INT-01: max 10 files per unit
MAX_UNIT_BYTES = 50_000_000  # FR-INT-01 / BQ-98: 50 MB per unit
MAX_REDIRECTS = 5
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 15.0
DEFAULT_TOTAL_TIMEOUT = 60.0  # wall clock for one fetch(): DNS, robots, every hop, headers and body
DEFAULT_SANDBOX_PORT = 80
USER_AGENT = "TiloBot/1.0"
UNIT_ID_RE = re.compile(r"^U[0-9]{1,4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTENT_LENGTH_RE = re.compile(r"[0-9]{1,18}")

_CGNAT_NET = ipaddress.IPv4Network("100.64.0.0/10")
_BENCHMARK_NET = ipaddress.IPv4Network("198.18.0.0/15")
_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.IPv6Network("64:ff9b:1::/48")
_SITE_LOCAL_V6 = ipaddress.IPv6Network("fec0::/10")

_FORBIDDEN_HOSTS = frozenset({"metadata.google.internal", "metadata", "localhost"})
_FORBIDDEN_SUFFIXES = (".google.internal", ".internal", ".localhost")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})

_EXECUTABLE_PREFIXES = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"#!",
    b"\x00asm",
)
_ARCHIVE_PREFIXES = (
    b"\x1f\x8b",
    b"BZh",
    b"\xfd7zXZ\x00",
    b"7z\xbc\xaf\x27\x1c",
    b"Rar!\x1a\x07",
    b"PK\x05\x06",
    b"PK\x07\x08",
)
_OOXML_MAIN_PARTS: tuple[tuple[str, str], ...] = (
    ("word/document.xml", FILE_TYPES[".docx"][1]),
    ("ppt/presentation.xml", FILE_TYPES[".pptx"][1]),
    ("xl/workbook.xml", FILE_TYPES[".xlsx"][1]),
)
_STRIP_HTML_TAGS = frozenset({"script", "style", "noscript", "template", "iframe", "object", "embed", "svg"})
_BLOCK_HTML_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "header",
        "footer",
        "main",
        "aside",
        "li",
        "tr",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "title",
    }
)


@dataclass(frozen=True)
class FetchBlock:
    reason: str
    url: str
    host: str | None
    allowlist: tuple[str, ...]
    redirect_from: str | None = None


class _DnsDeadline(Exception):
    """The resolver was still running when the fetch deadline expired."""


class FetchBlocked(Exception):
    def __init__(
        self,
        reason: str,
        url: str,
        *,
        host: str | None = None,
        allowlist: Sequence[str] = (),
        redirect_from: str | None = None,
    ) -> None:
        clean = sanitise_url(url)
        masked_host = mask_text(host) if host else None
        self.block = FetchBlock(
            reason=reason,
            url=clean,
            host=masked_host,
            allowlist=tuple(allowlist),
            redirect_from=sanitise_url(redirect_from) if redirect_from else None,
        )
        super().__init__(f"fetch blocked ({reason}): {clean}")


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True)
class FetchResult:
    sha256: str
    media_type: str
    size: int
    source_url: str
    publisher_host: str
    fetched_at: str
    archive_ref: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sha256": self.sha256,
            "media_type": self.media_type,
            "size": self.size,
            "source_url": self.source_url,
            "publisher_host": self.publisher_host,
            "fetched_at": self.fetched_at,
            "archive_ref": self.archive_ref,
        }


class FetchTransport(Protocol):
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
    ) -> UpstreamResponse: ...


def _is_safe_ipv4(addr: ipaddress.IPv4Address) -> bool:
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
        or addr in _CGNAT_NET
        or addr in _BENCHMARK_NET
    )


def is_public_ip(raw_ip: str) -> bool:
    """True iff `raw_ip` is a global unicast address with no private/loopback/metadata/CGNAT/ULA mapping."""
    if not raw_ip or "%" in raw_ip:
        return False
    try:
        addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv4Address):
        return _is_safe_ipv4(addr)
    if addr.ipv4_mapped is not None:
        return _is_safe_ipv4(addr.ipv4_mapped)
    if addr.sixtofour is not None:
        return _is_safe_ipv4(addr.sixtofour)
    if addr.teredo is not None:
        server_ip, client_ip = addr.teredo
        return _is_safe_ipv4(server_ip) and _is_safe_ipv4(client_ip)
    if addr in _NAT64_WELL_KNOWN or addr in _NAT64_LOCAL:
        embedded = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        return _is_safe_ipv4(embedded)
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_site_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
        or addr in _SITE_LOCAL_V6
    )


def is_forbidden_hostname(host: str) -> bool:
    low = host.lower().rstrip(".")
    return low in _FORBIDDEN_HOSTS or low.endswith(_FORBIDDEN_SUFFIXES) or "." not in low


def default_dns_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for _family, _type, _proto, _canon, sockaddr in infos:
        ip_str = str(sockaddr[0])
        if ip_str not in ips:
            ips.append(ip_str)
    return ips


def clean_source_url(scheme: str, ascii_host: str, port: int | None, raw_path: str) -> str:
    """BQ-104 cleaned source URL: lower-case scheme/host, drop userinfo/query/fragment and `;` params."""
    norm_path = raw_path if raw_path.startswith("/") else "/" + raw_path
    cleaned_segments = [seg.split(";", 1)[0] for seg in norm_path.split("/")]
    cleaned_path = "/".join(cleaned_segments) or "/"
    default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
    authority = ascii_host if (port is None or default_port) else f"{ascii_host}:{port}"
    return f"{scheme}://{authority}{cleaned_path}"


class _HtmlPlainExtractor(HTMLParser):
    """Extracts visible plain text from HTML while dropping `<script>`, `<style>`, and executable tags."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._pieces: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low = tag.lower()
        if low in _STRIP_HTML_TAGS:
            self._skip_depth += 1
        elif self._skip_depth == 0 and low in _BLOCK_HTML_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        low = tag.lower()
        if low in _STRIP_HTML_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif self._skip_depth == 0 and low in _BLOCK_HTML_TAGS:
            self._pieces.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data:
            self._pieces.append(data)

    def plain_output(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self._pieces).splitlines()]
        return "\n".join(line for line in lines if line)


def _looks_like_html(raw_bytes: bytes) -> bool:
    if b"\x00" in raw_bytes[:4096]:
        return False
    head = raw_bytes[:1024].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith((b"<!doctype svg", b"<svg", b"<?xml")):
        return False
    return head.startswith((b"<!doctype html", b"<html"))


def _detect_ooxml(raw_bytes: bytes, url: str, host: str) -> str:
    try:
        _check_directory(raw_bytes)
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
            names = {info.filename for info in zf.infolist()}
    except (ExtractionError, zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError) as exc:
        raise FetchBlocked("archive_refused", url, host=host) from exc
    if "[Content_Types].xml" not in names:
        raise FetchBlocked("archive_refused", url, host=host)
    for main_part, mime_type in _OOXML_MAIN_PARTS:
        if main_part in names:
            return mime_type
    raise FetchBlocked("archive_refused", url, host=host)


def detect_media_type(raw_bytes: bytes, *, url: str, host: str) -> tuple[str, bytes]:
    """Determine media type strictly from magic bytes (`extraction.FILE_TYPES`); convert HTML to script-free text."""
    if not raw_bytes:
        raise FetchBlocked("unsupported_media_type", url, host=host)
    if raw_bytes.startswith(_EXECUTABLE_PREFIXES):
        raise FetchBlocked("executable_refused", url, host=host)
    if raw_bytes.startswith(_ARCHIVE_PREFIXES) or (len(raw_bytes) > 262 and raw_bytes[257:262] == b"ustar"):
        raise FetchBlocked("archive_refused", url, host=host)

    for ext in (".pdf", ".png", ".jpg"):
        _kind, mime_type, magic = FILE_TYPES[ext]
        if magic and raw_bytes.startswith(magic):
            return mime_type, raw_bytes

    if raw_bytes.startswith(FILE_TYPES[".docx"][2]):  # PK\x03\x04
        return _detect_ooxml(raw_bytes, url, host), raw_bytes

    if _looks_like_html(raw_bytes):
        if len(raw_bytes) > MAX_HTML_BYTES:
            raise FetchBlocked("html_too_large", url, host=host)
        try:
            decoded_html = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FetchBlocked("unsupported_media_type", url, host=host) from exc
        parser = _HtmlPlainExtractor()
        parser.feed(decoded_html)
        parser.close()
        cleaned_plain = mask_text(parser.plain_output())
        plain_bytes = cleaned_plain.encode("utf-8")
        if not plain_bytes:
            raise FetchBlocked("unsupported_media_type", url, host=host)
        return "text/plain", plain_bytes

    raise FetchBlocked("unsupported_media_type", url, host=host)


class PinnedHttpTransport:
    """Stdlib HTTP/HTTPS GET transport that connects directly to `pinned_ip` and verifies TLS against `host`.

    `time_budget` is the wall-clock time left for the whole call (connect, TLS, headers, body). It is checked
    before every read and enforced on a stalled socket by a watchdog that shuts the socket down at expiry.
    """

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
    ) -> UpstreamResponse:
        url_for_err = f"{scheme}://{host}:{port}{path_and_query}"
        started = time.monotonic()
        timed_out = threading.Event()
        sock: Any = None
        watchdog: threading.Timer | None = None

        def time_left() -> float:
            return math.inf if time_budget is None else time_budget - (time.monotonic() - started)

        def io_timeout() -> float:
            return max(min(read_timeout, time_left()), 0.001)

        def abort() -> None:
            timed_out.set()
            target = sock
            if target is None:
                return
            try:
                if isinstance(target, socket.socket):
                    socket.socket.shutdown(target, socket.SHUT_RDWR)  # skips SSLSocket's override
                else:
                    target.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass

        try:
            if time_left() <= 0:
                raise FetchBlocked("timeout", url_for_err, host=host)
            sock = socket.create_connection((pinned_ip, port), timeout=max(min(connect_timeout, time_left()), 0.001))
            if time_budget is not None:
                watchdog = threading.Timer(max(time_left(), 0.001), abort)
                watchdog.daemon = True
                watchdog.start()
            sock.settimeout(io_timeout())
            if scheme == "https":
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=host)
                sock.settimeout(io_timeout())

            default_port = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            host_header = host if default_port else f"{host}:{port}"
            req_lines = [
                f"GET {path_and_query or '/'} HTTP/1.1",
                f"Host: {host_header}",
                f"User-Agent: {USER_AGENT}",
                "Accept: */*",
                "Accept-Encoding: identity",
                "Connection: close",
                "",
                "",
            ]
            sock.sendall("\r\n".join(req_lines).encode("ascii"))
            http_resp = http.client.HTTPResponse(sock)
            http_resp.begin()
            resp_headers = {k.lower(): v for k, v in http_resp.getheaders()}
            expected: int | None = None
            cl = resp_headers.get("content-length")
            if cl is not None:
                if not _CONTENT_LENGTH_RE.fullmatch(cl.strip()):
                    raise FetchBlocked("upstream_error", url_for_err, host=host)
                expected = int(cl)
                if expected > max_bytes:
                    raise FetchBlocked("file_too_large", url_for_err, host=host)

            buf = bytearray()
            html_checked = False
            is_html = False
            while True:
                if time_left() <= 0:
                    raise FetchBlocked("timeout", url_for_err, host=host)
                sock.settimeout(io_timeout())
                chunk = http_resp.read1(65536)  # one underlying read at a time, so the deadline is re-checked
                if not chunk:
                    break
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    raise FetchBlocked("file_too_large", url_for_err, host=host)
                if not html_checked and len(buf) >= 1024:
                    html_checked = True
                    is_html = _looks_like_html(bytes(buf[:1024]))
                if is_html and len(buf) > MAX_HTML_BYTES:
                    raise FetchBlocked("html_too_large", url_for_err, host=host)
            if timed_out.is_set() or time_left() <= 0:
                # The watchdog's shutdown (or a stalled upstream) can look like a clean EOF: never accept that body.
                raise FetchBlocked("timeout", url_for_err, host=host)
            body_expected = http_resp.status >= 200 and http_resp.status not in (204, 304) and not http_resp.chunked
            if expected is not None and body_expected and len(buf) < expected:
                raise FetchBlocked("upstream_error", url_for_err, host=host)
            return UpstreamResponse(status_code=http_resp.status, headers=resp_headers, body=bytes(buf))
        except FetchBlocked:
            raise
        except (OSError, http.client.HTTPException, ValueError) as exc:
            if timed_out.is_set() or isinstance(exc, TimeoutError):
                raise FetchBlocked("timeout", url_for_err, host=host) from exc
            raise FetchBlocked("upstream_error", url_for_err, host=host) from exc
        finally:
            if watchdog is not None:
                watchdog.cancel()
                watchdog.join()  # an abort in progress finishes before the socket is closed
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass


class RawArchiveStore:
    """Stores raw fetched bytes by SHA-256 alongside `RunArchive` hash-chained `tool_call` records."""

    def __init__(self, root: Path, *, store: Store | None = None) -> None:
        self._root = Path(root)
        self._store: Store = store if store is not None else LocalDirStore(self._root)
        self._lock = threading.Lock()

    def _blob_path(self, org_id: str, run_id: str, sha256_hex: str) -> Path:
        if not ORG_ID_RE.fullmatch(org_id):
            raise ValueError(f"invalid org_id: {org_id!r}")
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError(f"invalid run_id: {run_id!r}")
        if not SHA256_RE.fullmatch(sha256_hex):
            raise ValueError("invalid sha256 digest")
        return self._root / org_id / f"{run_id}.blobs" / sha256_hex

    def archive_fetch(
        self,
        *,
        org_id: str,
        run_id: str,
        source_url: str,
        publisher_host: str,
        media_type: str,
        sha256_hex: str,
        raw_bytes: bytes,
        clock: Callable[[], datetime],
    ) -> str:
        blob_path = self._blob_path(org_id, run_id, sha256_hex)
        content_str = raw_bytes.decode("utf-8") if media_type == "text/plain" else f"sha256:{sha256_hex}"
        payload = {
            "tool": "fetch_url",
            "source": {"kind": "web", "ref": source_url},
            "content": content_str,
            "sha256": sha256_hex,
            "media_type": media_type,
            "size": len(raw_bytes),
            "publisher_host": publisher_host,
        }
        with self._lock:
            blob_path.parent.mkdir(parents=True, exist_ok=True)
            if not blob_path.exists():
                blob_path.write_bytes(raw_bytes)
            run_archive = RunArchive(
                self._store,
                org_id=org_id,
                run_id=run_id,
                redactor=mask_data,
                clock=clock,
            )
            return run_archive.append("tool_call", payload)

    def get_bytes(self, org_id: str, run_id: str, sha256_hex: str) -> bytes:
        blob_path = self._blob_path(org_id, run_id, sha256_hex)
        if not blob_path.exists():
            raise FileNotFoundError(sha256_hex)
        return blob_path.read_bytes()


class FetchService:
    """Executes SSRF-guarded, allowlisted, size-capped `GET` fetches and records every block (SEC-09)."""

    def __init__(
        self,
        *,
        base_allow: Sequence[str] = (),
        sandbox_hosts: Sequence[str] = (),
        dns_resolver: Callable[[str, int], Sequence[str]] = default_dns_resolver,
        transport: FetchTransport | None = None,
        archive_store: RawArchiveStore | None = None,
        clock: Callable[[], datetime] | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        total_timeout: float = DEFAULT_TOTAL_TIMEOUT,
        sandbox_port: int = DEFAULT_SANDBOX_PORT,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not (math.isfinite(connect_timeout) and connect_timeout > 0):
            raise ValueError("connect_timeout must be a positive finite number")
        if not (math.isfinite(read_timeout) and read_timeout > 0):
            raise ValueError("read_timeout must be a positive finite number")
        if not (math.isfinite(total_timeout) and total_timeout > 0):
            raise ValueError("total_timeout must be a positive finite number")
        if not 0 < sandbox_port < 65536:
            raise ValueError("sandbox_port must be a valid TCP port")
        self._total_timeout = total_timeout
        self._sandbox_port = sandbox_port
        self._monotonic = monotonic
        self._base_allow = tuple(base_allow)
        self._sandbox_hosts = frozenset(norm for h in sandbox_hosts if (norm := _normalise_host(h)) is not None)
        self._dns_resolver = dns_resolver
        self._transport: FetchTransport = transport if transport is not None else PinnedHttpTransport()
        self.archive_store = archive_store if archive_store is not None else RawArchiveStore(Path(".tilo-archive"))
        self._clock = clock or (lambda: datetime.now(UTC))
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self.blocked: list[FetchBlock] = []
        self._robots_cache: dict[tuple[str, str, int], urllib.robotparser.RobotFileParser] = {}
        self._unit_usage: dict[tuple[str, str, str], tuple[int, int]] = {}
        self._lock = threading.Lock()

    def _record_block(
        self,
        reason: str,
        url: str,
        *,
        host: str | None,
        allowlist: Sequence[str],
        redirect_from: str | None = None,
    ) -> FetchBlocked:
        exc = FetchBlocked(reason, url, host=host, allowlist=allowlist, redirect_from=redirect_from)
        with self._lock:
            self.blocked.append(exc.block)
        log.warning(
            "fetch blocked: reason=%s url=%s host=%s allowlist=%s",
            exc.block.reason,
            exc.block.url,
            exc.block.host or "-",
            list(exc.block.allowlist),
        )
        return exc

    def _build_policy(self, task_allowlist: Sequence[str]) -> tuple[EgressPolicy, tuple[str, ...]]:
        combined: list[str] = list(self._base_allow)
        for entry in task_allowlist:
            if not isinstance(entry, str):
                raise ValueError("allowlist entry must be a string")
            norm = _normalise_host(entry[2:] if entry.startswith("*.") else entry)
            if norm is None or is_forbidden_hostname(norm):
                raise ValueError(f"forbidden or invalid allowlist entry: {entry!r}")
            if entry not in combined:
                combined.append(entry)
        return EgressPolicy(allow=combined, allow_schemes=("https", "http")), tuple(combined)

    def _time_left(
        self,
        deadline: float,
        *,
        url: str,
        host: str | None,
        allowlist: Sequence[str],
        redirect_from: str | None = None,
    ) -> float:
        """Seconds left on this fetch's wall-clock deadline; expiry is a logged `timeout` refusal."""
        left = deadline - self._monotonic()
        if left <= 0:
            raise self._record_block("timeout", url, host=host, allowlist=allowlist, redirect_from=redirect_from)
        return left

    def _resolve_within(self, host: str, port: int, seconds: float) -> list[str]:
        """Run the (blocking) resolver on a helper thread so a stalled lookup cannot outlive the deadline."""
        outcome: list[tuple[list[str] | None, BaseException | None]] = []

        def run() -> None:
            try:
                outcome.append((list(self._dns_resolver(host, port)), None))
            except BaseException as exc:
                outcome.append((None, exc))

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(seconds)
        if not outcome:
            raise _DnsDeadline
        addresses, error = outcome[0]
        if error is not None:
            raise error
        return addresses or []

    def _resolve_and_pin(
        self, host: str, port: int, *, url: str, allowlist: Sequence[str], deadline: float, redirect_from: str | None
    ) -> str:
        if is_forbidden_hostname(host):
            raise self._record_block("ssrf_blocked", url, host=host, allowlist=allowlist)
        left = self._time_left(deadline, url=url, host=host, allowlist=allowlist, redirect_from=redirect_from)
        try:
            resolved = self._resolve_within(host, port, left)
        except _DnsDeadline:
            raise self._record_block(
                "timeout", url, host=host, allowlist=allowlist, redirect_from=redirect_from
            ) from None
        except OSError:
            raise self._record_block("dns_failed", url, host=host, allowlist=allowlist) from None
        if not resolved or not all(is_public_ip(ip) for ip in resolved):
            raise self._record_block("ssrf_blocked", url, host=host, allowlist=allowlist)
        return resolved[0]

    def _check_hop(
        self,
        url: str,
        *,
        policy: EgressPolicy,
        allowlist: tuple[str, ...],
        deadline: float,
        redirect_from: str | None = None,
    ) -> tuple[str, str, int, str, str, str]:
        decision = policy.check(url, redirect_from=redirect_from)
        if not decision.allowed:
            raise self._record_block(
                decision.reason,
                url,
                host=decision.host,
                allowlist=allowlist,
                redirect_from=redirect_from,
            )
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        ascii_host = _normalise_host(parts.hostname or "")
        if ascii_host is None:
            raise self._record_block("invalid_url", url, host=parts.hostname, allowlist=allowlist)
        if scheme == "http" and ascii_host not in self._sandbox_hosts:
            raise self._record_block(
                "scheme_not_allowed",
                url,
                host=ascii_host,
                allowlist=allowlist,
                redirect_from=redirect_from,
            )
        port = parts.port if parts.port is not None else (443 if scheme == "https" else 80)
        allowed_ports = {443, self._sandbox_port} if ascii_host in self._sandbox_hosts else {443}
        if port not in allowed_ports:
            raise self._record_block(
                "port_not_allowed", url, host=ascii_host, allowlist=allowlist, redirect_from=redirect_from
            )
        pinned_ip = self._resolve_and_pin(
            ascii_host, port, url=url, allowlist=allowlist, deadline=deadline, redirect_from=redirect_from
        )
        raw_path = parts.path or "/"
        clean_path = "/".join(seg.split(";", 1)[0] for seg in raw_path.split("/")) or "/"
        path_and_query = f"{clean_path}?{parts.query}" if parts.query else clean_path
        cleaned = clean_source_url(scheme, ascii_host, parts.port, clean_path)
        return scheme, ascii_host, port, pinned_ip, path_and_query, cleaned

    def _upstream_get(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        pinned_ip: str,
        path_and_query: str,
        max_bytes: int,
        url: str,
        allowlist: tuple[str, ...],
        deadline: float,
        redirect_from: str | None = None,
        unit_capped: bool = False,
    ) -> UpstreamResponse:
        """One upstream GET inside the fetch deadline; every failure becomes a logged refusal, never a 500."""
        left = self._time_left(deadline, url=url, host=host, allowlist=allowlist, redirect_from=redirect_from)
        try:
            return self._transport.send_get(
                scheme=scheme,
                host=host,
                port=port,
                pinned_ip=pinned_ip,
                path_and_query=path_and_query,
                headers={},
                connect_timeout=self._connect_timeout,
                read_timeout=self._read_timeout,
                max_bytes=max_bytes,
                time_budget=left,
            )
        except FetchBlocked as exc:
            reason = exc.block.reason
            if reason == "file_too_large" and unit_capped:
                reason = "unit_byte_limit"
            raise self._record_block(reason, url, host=host, allowlist=allowlist, redirect_from=redirect_from) from None
        except TimeoutError:
            reason = "timeout"
        except (OSError, http.client.HTTPException, ValueError):
            reason = "upstream_error"
        raise self._record_block(reason, url, host=host, allowlist=allowlist, redirect_from=redirect_from)

    def _check_robots(
        self,
        *,
        scheme: str,
        host: str,
        port: int,
        pinned_ip: str,
        path_and_query: str,
        url: str,
        allowlist: tuple[str, ...],
        deadline: float,
    ) -> None:
        cache_key = (scheme, host, port)
        with self._lock:
            cached = self._robots_cache.get(cache_key)
        if cached is None:
            resp = self._upstream_get(
                scheme=scheme,
                host=host,
                port=port,
                pinned_ip=pinned_ip,
                path_and_query="/robots.txt",
                max_bytes=MAX_ROBOTS_BYTES,
                url=url,
                allowlist=allowlist,
                deadline=deadline,
            )
            rp = urllib.robotparser.RobotFileParser()
            if resp.status_code == 200:
                robots_lines = resp.body.decode("utf-8", errors="replace").splitlines()
                rp.parse(robots_lines)
            elif resp.status_code == 404:
                rp.parse(["User-agent: *", "Allow: /"])
            else:
                rp.parse(["User-agent: *", "Disallow: /"])
            with self._lock:
                self._robots_cache[cache_key] = rp
            cached = rp
        path_only = path_and_query.split("?", 1)[0] or "/"
        if not cached.can_fetch(USER_AGENT, path_only):
            raise self._record_block("robots_disallowed", url, host=host, allowlist=allowlist)

    def fetch(
        self,
        url: str,
        *,
        allow_hosts: Sequence[str] = (),
        org_id: str = "org_local",
        run_id: str = "r_local",
        unit_id: str = "U1",
    ) -> FetchResult:
        if not ORG_ID_RE.fullmatch(org_id):
            raise ValueError("invalid org_id")
        if not RUN_ID_RE.fullmatch(run_id):
            raise ValueError("invalid run_id")
        if not UNIT_ID_RE.fullmatch(unit_id):
            raise ValueError("invalid unit_id")

        policy, allowlist = self._build_policy(allow_hosts)
        unit_key = (org_id, run_id, unit_id)
        with self._lock:
            files_used, bytes_used = self._unit_usage.get(unit_key, (0, 0))
        if files_used >= MAX_UNIT_FILES:
            raise self._record_block("unit_file_limit", url, host=None, allowlist=allowlist)
        remaining_unit_bytes = MAX_UNIT_BYTES - bytes_used
        if remaining_unit_bytes <= 0:
            raise self._record_block("unit_byte_limit", url, host=None, allowlist=allowlist)

        deadline = self._monotonic() + self._total_timeout
        current_url = url
        previous_url: str | None = None
        for hop in range(MAX_REDIRECTS + 1):
            scheme, host, port, pinned_ip, path_and_query, cleaned_url = self._check_hop(
                current_url,
                policy=policy,
                allowlist=allowlist,
                deadline=deadline,
                redirect_from=previous_url,
            )
            self._check_robots(
                scheme=scheme,
                host=host,
                port=port,
                pinned_ip=pinned_ip,
                path_and_query=path_and_query,
                url=current_url,
                allowlist=allowlist,
                deadline=deadline,
            )
            resp = self._upstream_get(
                scheme=scheme,
                host=host,
                port=port,
                pinned_ip=pinned_ip,
                path_and_query=path_and_query,
                max_bytes=min(MAX_FILE_BYTES, remaining_unit_bytes),
                url=current_url,
                allowlist=allowlist,
                deadline=deadline,
                redirect_from=previous_url,
                unit_capped=remaining_unit_bytes < MAX_FILE_BYTES,
            )

            if resp.status_code in _REDIRECT_STATUSES:
                if hop >= MAX_REDIRECTS:
                    raise self._record_block(
                        "too_many_redirects",
                        current_url,
                        host=host,
                        allowlist=allowlist,
                        redirect_from=previous_url,
                    )
                location = resp.headers.get("location", "").strip()
                if not location:
                    raise self._record_block("upstream_error", current_url, host=host, allowlist=allowlist)
                previous_url = current_url
                current_url = urljoin(f"{scheme}://{host}:{port}{path_and_query}", location)
                continue

            if resp.status_code != 200:
                raise self._record_block("upstream_error", current_url, host=host, allowlist=allowlist)

            try:
                media_type, stored_bytes = detect_media_type(resp.body, url=current_url, host=host)
            except FetchBlocked as exc:
                raise self._record_block(exc.block.reason, current_url, host=host, allowlist=allowlist) from None

            # Decide under the lock, record the refusal after releasing it (`_record_block` takes the same lock).
            refusal: str | None = None
            with self._lock:
                cur_files, cur_bytes = self._unit_usage.get(unit_key, (0, 0))
                if cur_files >= MAX_UNIT_FILES:
                    refusal = "unit_file_limit"
                elif cur_bytes + len(stored_bytes) > MAX_UNIT_BYTES:
                    refusal = "unit_byte_limit"
                else:
                    self._unit_usage[unit_key] = (cur_files + 1, cur_bytes + len(stored_bytes))
            if refusal is not None:
                raise self._record_block(refusal, current_url, host=host, allowlist=allowlist)

            sha256_hex = hashlib.sha256(stored_bytes).hexdigest()
            fetched_at = format_ts(self._clock())
            archive_ref = self.archive_store.archive_fetch(
                org_id=org_id,
                run_id=run_id,
                source_url=cleaned_url,
                publisher_host=host,
                media_type=media_type,
                sha256_hex=sha256_hex,
                raw_bytes=stored_bytes,
                clock=self._clock,
            )
            return FetchResult(
                sha256=sha256_hex,
                media_type=media_type,
                size=len(stored_bytes),
                source_url=cleaned_url,
                publisher_host=host,
                fetched_at=fetched_at,
                archive_ref=archive_ref,
            )

        raise self._record_block("too_many_redirects", current_url, host=None, allowlist=allowlist)


def service_caller_ok(claims: Mapping[str, Any], *, audience: str, allowed_callers: Sequence[str]) -> bool:
    """Verify Google OIDC claims for a service-to-service caller (e.g. tilo-harness)."""
    return (
        isinstance(claims.get("iss"), str)
        and claims["iss"] in {"https://accounts.google.com", "accounts.google.com"}
        and claims.get("aud") == audience
        and claims.get("email_verified") is True
        and isinstance(claims.get("email"), str)
        and claims["email"] in set(allowed_callers)
    )
