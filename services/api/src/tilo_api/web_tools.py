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
from urllib.parse import urlsplit

from tilo_browser.egress import EgressPolicy
from tilo_browser.fetch import FetchService, RawArchiveStore, UpstreamResponse, is_forbidden_hostname
from tilo_harness.tools import FakeFetchUrl, FakeWebSearch, ToolResult, archive_id
from tilo_memory.artifacts import NewVersion, Origin
from tilo_providers.media import MediaPart

_URL = re.compile(r"https://[^\s<>\"'`\)\]}]+", re.IGNORECASE)
MAX_TYPED_HOSTS = 20


def typed_hosts(texts: Iterable[Any]) -> set[str]:
    """FR-CON-07: the hosts of the https URLs a person typed or attached, found by code in the brief's text. A host the
    fetch policy would refuse anyway (an IP, localhost, an internal or bare name), userinfo, another port and any
    other scheme add nothing; the fetch itself still runs every egress, DNS and robots check."""
    found: set[str] = set()
    for text in texts:
        for match in _URL.finditer(text) if isinstance(text, str) else ():
            try:
                parts = urlsplit(match.group().rstrip(".,;:!?"))
                host, port = parts.hostname, parts.port
                if not host or parts.username or parts.password or port not in (None, 443):
                    continue
                if is_forbidden_hostname(host):
                    continue
                EgressPolicy([host])  # ValueError for an IP literal or anything but a plain DNS name
            except ValueError:
                continue
            found.add(host)
            if len(found) >= MAX_TYPED_HOSTS:
                return found
    return found


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

    def __init__(self, run, service, hosts, unit, context, sources):
        self.owner, self.service, self.hosts = run, service, hosts
        self.unit, self.context, self.sources = unit, context, sources
        self.count = 0

    def run(self, args):
        run = self.owner
        got = self.service.fetch(
            args["url"], allow_hosts=tuple(self.hosts), org_id=run.org_id, run_id=run.run_id, unit_id=self.unit["id"]
        )
        raw = self.service.archive_store.get_bytes(run.org_id, run.run_id, got.sha256)
        if got.media_type == "text/plain":
            return ToolResult(raw.decode())
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
