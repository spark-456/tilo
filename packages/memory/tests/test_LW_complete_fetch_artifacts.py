"""AR-09 fetched artifacts use code-sniffed kinds, f-keys and their own archived bytes."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from tilo_browser.fetch import detect_media_type
from tilo_memory.artifacts import (
    ArtifactError,
    ArtifactStore,
    MemoryBlobBackend,
    MemoryMetaBackend,
    NewVersion,
    Origin,
    Scope,
)
from tilo_providers.safety import FakeSafetyProvider
from tilo_sandbox_web.fetch_fixtures import PAPERS, WRONG_MAGIC_PNG

SCOPE = Scope("org_liveweb", "w_liveweb", "u_owner")
RUN = "r_liveweb"


@pytest.mark.parametrize(
    "flaw",
    [
        "none",
        "magic",
        "key",
        "missing_sniffer",
        "zero_sources",
        "two_sources",
        "other_run",
        "archive_missing",
        "not_fetch",
        "different_bytes",
        "credential_url",
    ],
)
def test_fetched_file_has_matching_kind_key_scope_and_archive(flaw):
    raw = PAPERS["paper-1.pdf"]
    payload = {
        "tool": "fetch_url",
        "source": {"kind": "web", "ref": "https://source.example/paper.pdf"},
        "media_type": "application/pdf",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size": len(raw),
    }
    if flaw == "not_fetch":
        payload["tool"] = "web_search"
    elif flaw == "different_bytes":
        payload["sha256"] = "0" * 64
    elif flaw == "credential_url":
        payload["source"]["ref"] = "https://user:password@source.example/paper.pdf"
    store = ArtifactStore(
        MemoryMetaBackend(),
        MemoryBlobBackend(),
        clock=lambda: datetime(2026, 10, 11, tzinfo=UTC),
        redactor=lambda text: text,
        alert_sink=lambda _a: None,
        screener=FakeSafetyProvider(),
        archive_lookup=lambda scope, ref: None if flaw == "archive_missing" else json.dumps(payload),
        file_sniffer=None
        if flaw == "missing_sniffer"
        else lambda data: detect_media_type(data, url="https://source.example/file", host="source.example")[0],
    )
    source = {"id": "source", "archive_ref": f"{RUN}/1"}
    new = NewVersion(
        "application/pdf", raw, RUN, Origin("fetch", "U1", "A_s1"), sources=(source,), idempotency_key=f"{RUN}:U1:0:f0"
    )
    if flaw == "magic":
        new = replace(new, content=WRONG_MAGIC_PNG)
    elif flaw == "key":
        new = replace(new, idempotency_key=f"{RUN}:U1:0:0")
    elif flaw == "zero_sources":
        new = replace(new, sources=())
    elif flaw == "two_sources":
        new = replace(new, sources=(source, {"id": "second", "archive_ref": f"{RUN}/2"}))
    elif flaw == "other_run":
        new = replace(new, sources=({"id": "source", "archive_ref": "r_other/1"},))
    if flaw != "none":
        with pytest.raises(ArtifactError):
            store.put(SCOPE, new)
    else:
        first = store.put(SCOPE, new)
        assert first.record["origin"] == {"kind": "fetch", "unit": "U1", "agent": "A_s1"}
        assert first.record["screening"] == "clean"
        assert store.read(SCOPE, first.ref) == raw
        assert store.put(SCOPE, new).ref == first.ref
        assert store.head(Scope(SCOPE.org_id, SCOPE.world_id, "u_other"), first.ref) is None
