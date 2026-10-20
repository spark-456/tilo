"""Run-scoped public reads; replay never constructs a network transport."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from tilo_browser.egress import EgressPolicy
from tilo_browser.fetch import FetchBlocked, FetchService, RawArchiveStore, UpstreamResponse, is_forbidden_hostname
from tilo_harness.tools import FakeFetchUrl, FakeWebSearch, ToolResult, archive_id
from tilo_memory.artifacts import NewVersion, Origin
from tilo_providers.diagnostics import log_caught
from tilo_providers.media import MediaPart

_URL = re.compile(r"https://[^\s<>\"'`\)\]}]+", re.IGNORECASE)
# DEMO-BROWSER: a site named without a scheme ("open wikipedia.org"): dot-separated labels ending in letters, not part
# of an address, a path or a longer name. A last label that is a common file ending is a file name, not a site.
_BARE_HOST = re.compile(
    r"(?<![\w@./:%-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,24})"
    r"(?![\w-]|\.[a-z0-9])",
    re.IGNORECASE,
)
_FILE_ENDINGS = frozenset(
    (
        "pdf doc docx xls xlsx xlsm ppt pptx csv tsv txt md rtf odt ods json xml yaml yml html htm "
        "png jpg jpeg gif svg webp heic mp3 mp4 m4a wav mov webm mkv avi zip gz tar rar "
        "py js ts tsx jsx css sh bat ps exe dll log ini cfg"
    ).split()
)
MAX_TYPED_HOSTS = 20
# P0-RUNS-FIX: a search engine's page is never read; web research goes through the search provider (web_search).
_SEARCH_ENGINES = frozenset({"google", "bing", "duckduckgo", "yahoo", "baidu", "yandex", "ecosia", "startpage", "ask"})
_QUERY_KEYS = ("q", "query", "p", "text", "wd")
SEARCH_ENGINE_NOTE = (
    "(not opened: {host} is a search engine. Tilo searches with web_search: call web_search with the words to find, "
    "then fetch_url one of its result links.)"
)
BLOCKED_NOTE = (
    "(not read: {host} is not among this task's search results or the sites the person named ({reason}). "
    "Skip this source; use web_search and read one of its result links.)"
)
BROWSER_FALLBACK_NOTE = "(The visible browser could not open this page, so Tilo read it directly.)\n"


def search_engine_host(host: str) -> bool:
    """google.com, www.google.co.in, bing.com, search.yahoo.com and the like: a search page, not a source."""
    labels = host.lower().rstrip(".").split(".")
    while labels and labels[0] in ("www", "m", "search"):
        labels = labels[1:]
    return len(labels) >= 2 and labels[0] in _SEARCH_ENGINES


def typed_hosts(texts: Iterable[Any]) -> set[str]:
    """FR-CON-07: the hosts of the https URLs a person typed or attached, and of the sites they named without a scheme
    ("open wikipedia.org"), found by code in the brief's text. A host the fetch policy would refuse anyway (an IP,
    localhost, an internal or bare name), an email address, a file name, userinfo, another port and any other scheme
    add nothing; the fetch itself still runs every egress, DNS and robots check."""
    found: set[str] = set()
    for text in texts:
        if not isinstance(text, str):
            continue
        hosts: list[str | None] = []
        for match in _URL.finditer(text):
            try:
                parts = urlsplit(match.group().rstrip(".,;:!?"))
                if not parts.username and not parts.password and parts.port in (None, 443):
                    hosts.append(parts.hostname)
            except ValueError:
                continue
        hosts += [m.group(1).lower() for m in _BARE_HOST.finditer(text) if m.group(1).rsplit(".", 1)[-1].lower()
                  not in _FILE_ENDINGS]  # fmt: skip
        for host in hosts:
            try:
                if not host or is_forbidden_hostname(host):
                    continue
                EgressPolicy([host])  # ValueError for an IP literal or anything but a plain DNS name
            except ValueError:
                continue
            found.add(host)
            if len(found) >= MAX_TYPED_HOSTS:
                return found
    return found


def allow_entries(hosts: Iterable[str], typed: Iterable[str]) -> list[str]:
    """BR-02: a run's allowlist. Each host the person typed (or a used taught skill names) also counts as *.<host>, so
    any page of a site they named opens (wikipedia.org covers en.wikipedia.org); the other known hosts (search results)
    stay exact. The patterns come first, so a capped list keeps the person's own sites."""
    named = sorted(set(typed))
    return list(dict.fromkeys([*(f"*.{host}" for host in named), *named, *sorted(hosts)]))


class RunArchiveBridge(RawArchiveStore):
    """Fetched bytes live only until persisted; metadata uses the run's shared archive."""

    def __init__(self, run: Any, archive: Any):
        self.run, self.archive = run, archive
        self._lock = threading.RLock()
        self._bytes: dict[str, bytes] = {}
        self.refs: dict[
            str, str
        ] = {}  # a tool call's id -> its record in the run's archive (event `trace.archive_ref`)

    def record(self, payload):
        with self._lock:
            ident = archive_id({"run_id": self.run.run_id, **payload})
            self.refs[ident] = self.archive.append("tool_call", {"id": ident, **payload})
            return ident

    def archive_fetch(self, *, org_id, run_id, source_url, publisher_host, media_type, sha256_hex, raw_bytes, clock):
        if (org_id, run_id) != (self.run.org_id, self.run.run_id):
            raise ValueError("wrong run")
        with self._lock:
            ref = self.archive.append(
                "tool_call",
                {
                    "tool": "fetch_url",
                    "source": {"kind": "web", "ref": source_url},
                    "content": raw_bytes.decode() if media_type == "text/plain" else f"sha256:{sha256_hex}",
                    "sha256": sha256_hex,
                    "media_type": media_type,
                    "size": len(raw_bytes),
                    "publisher_host": publisher_host,
                },
            )
            self._bytes[sha256_hex] = raw_bytes
            return ref

    def get_bytes(self, org_id, run_id, sha256_hex):
        if (org_id, run_id) != (self.run.org_id, self.run.run_id):
            raise ValueError("wrong run")
        return self._bytes.pop(sha256_hex)


class ReplayTransport:
    """Exact recorded HTTP responses and DNS answers, still checked by FetchService."""

    def __init__(self, root: Path):
        self.root = root

    def resolve(self, host, port):
        record = json.loads(
            (self.root / "dns" / f"{hashlib.sha256(f'{host}:{port}'.encode()).hexdigest()}.json").read_text()
        )
        if record["host"] != host or record["port"] != port:
            raise ValueError("replay DNS mismatch")
        return record["addresses"]

    def send_get(self, *, scheme, host, port, pinned_ip, path_and_query, max_bytes, **kwargs):
        url = f"{scheme}://{host}:{port}{path_and_query}"
        record = json.loads((self.root / "http" / f"{hashlib.sha256(url.encode()).hexdigest()}.json").read_text())
        if record["url"] != url or record["pinned_ip"] != pinned_ip:
            raise ValueError("replay HTTP mismatch")
        body = base64.b64decode(record["body"], validate=True)
        if len(body) > max_bytes or hashlib.sha256(body).hexdigest() != record["sha256"]:
            raise ValueError("replay body mismatch")
        return UpstreamResponse(record["status"], record["headers"], body)


def fetch_service(mode, archive, fixtures):
    if mode == "live":
        return FetchService(archive_store=archive)
    replay = ReplayTransport(fixtures / "fetch-recordings")
    return FetchService(archive_store=archive, transport=replay, dns_resolver=replay.resolve)


class SearchTool:
    name, description = FakeWebSearch.name, FakeWebSearch.description
    input_schema = FakeWebSearch.input_schema
    tier, external_content, side_effect = "T1", True, False

    def __init__(self, search, hosts):
        self.search, self.hosts = search, hosts

    def run(self, args):
        result, credits = self.search(args["query"])
        for source in result.sources:
            urls = [source.redirect_url, source.resolved_url]
            if source.domain:
                urls.append(f"https://{source.domain}/")
            for url in urls:
                if not url:
                    continue
                parsed = urlsplit(url)
                if parsed.scheme == "https" and parsed.hostname and not parsed.username:
                    self.hosts.add(parsed.hostname)
        return ToolResult(result.model_dump_json(), credits)


class FetchTool:
    name, description = FakeFetchUrl.name, FakeFetchUrl.description
    input_schema = FakeFetchUrl.input_schema
    tier, external_content, side_effect = "T1", True, False
    web_egress = True  # WT-04: a unit that read the person's private data loses it

    def __init__(self, run, service, hosts, unit, context, sources, *, search=None, browser=None, typed=frozenset()):
        self.owner, self.service, self.hosts = run, service, hosts
        self.typed = typed  # BR-02: the sites the person named, each also as *.<host>
        self.unit, self.context, self.sources = unit, context, sources
        self.search = search  # P0-RUNS-FIX: a search-engine URL becomes a web_search of its query
        self.browser = browser  # P0-RUNS-FIX: (url, host) -> text read in the visible browser, or None for no browser
        self.count = 0

    def run(self, args):
        run = self.owner
        url = args["url"]
        host = (urlsplit(url).hostname or "").lower() if isinstance(url, str) else ""
        if search_engine_host(host):
            query = next((v[0] for k in _QUERY_KEYS if (v := parse_qs(urlsplit(url).query).get(k)) and v[0]), "")
            if query.strip() and self.search is not None:
                return self.search.run({"query": query.strip()[:400]})
            return ToolResult(SEARCH_ENGINE_NOTE.format(host=host))
        note = ""
        allow = allow_entries(self.hosts, self.typed)
        if self.browser is not None and allow and EgressPolicy(allow).check(url).allowed:
            try:
                text = self.browser(url, host)
            except Exception as caught_error:  # unavailable, refused or a login wall: read it directly instead
                log_caught(caught_error, __name__, locals())
                text = ""
            if text.strip():
                return ToolResult(text)
            note = BROWSER_FALLBACK_NOTE
        try:
            got = self.service.fetch(
                url, allow_hosts=tuple(allow), org_id=run.org_id, run_id=run.run_id, unit_id=self.unit["id"]
            )
        except FetchBlocked as blocked:  # one source is skipped; the unit goes on with the others
            log_caught(blocked, __name__, locals())
            return ToolResult(BLOCKED_NOTE.format(host=blocked.block.host or "that site", reason=blocked.block.reason))
        raw = self.service.archive_store.get_bytes(run.org_id, run.run_id, got.sha256)
        if got.media_type == "text/plain":
            return ToolResult(note + raw.decode())
        if self.count >= 10:
            raise ValueError("source limit")
        made = run.seams.artifacts.put(
            run.scope,
            NewVersion(
                got.media_type,
                raw,
                run.run_id,
                Origin("fetch", self.unit["id"], self.context.agent_id),
                sources=({"id": "source", "archive_ref": got.archive_ref},),
                idempotency_key=f"{run.run_id}:{self.unit['id']}:0:f{self.count}",
            ),
        )
        self.count += 1
        run.put(
            "artifact.created",
            self.context.agent_id,
            made.artifact_id,
            "A source was fetched.",
            {
                "artifact": made.ref,
                **{k: made.record[k] for k in ("content_sha256", "media_type", "size_bytes")},
            },
            district=self.unit["district"],
        )
        if made.record["screening"] != "clean":
            raise ValueError("source not clean")
        part = MediaPart(mime_type=got.media_type, data=raw)
        self.sources.setdefault(self.unit["id"], []).append((made.ref, part))
        return ToolResult(json.dumps({"artifact": made.ref, "archive_ref": got.archive_ref}), parts=(part,))
