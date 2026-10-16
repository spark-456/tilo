"""WEB-1 / AR-10 (contracts/artifact.rules.md) and WS-09: the store's put runs the static checker on every text/html
version, on the exact bytes it keeps, after the secret redactor, and refuses before hashing. HTML is text for AR-07.
An upload, a fetch or a render never stores HTML; a restore copies a stored website."""

from __future__ import annotations

import pytest
from _artifact_testlib import SECRET, Redactor, make_rig, scope_of, sha
from tilo_memory.artifacts import ArtifactRefused

GOOD = b"<!doctype html><html><body><h1>Clocks</h1><script>setInterval(function(){}, 1000)</script></body></html>"
BAD = b"<!doctype html><html><body><script>fetch('a')</script></body></html>"


@pytest.fixture(params=["memory", "local"])
def rig(request, tmp_path):
    return make_rig(request.param, tmp_path)


def test_WEB_1_AR_10_a_checked_page_is_stored_as_text_html_with_unit_origin(rig) -> None:
    stored = rig.put(GOOD, media_type="text/html")
    assert stored.record["media_type"] == "text/html" and stored.record["origin"]["kind"] == "unit"
    assert stored.record["content_sha256"] == sha(GOOD)
    assert rig.store.read(rig.scope, stored.ref) == GOOD


def test_WEB_1_AR_10_WS_09_a_failing_page_is_refused_before_hashing_and_nothing_is_stored(rig) -> None:
    with pytest.raises(ArtifactRefused) as caught:
        rig.put(BAD, media_type="text/html")
    assert "ws_script" in str(caught.value) and "fetch" not in str(caught.value)  # a code, never the file
    assert rig.hasher.calls == 0
    assert rig.blobs.inner.keys() == [] and rig.meta.inner.paths() == []


def test_WEB_1_AR_10_the_page_over_524288_bytes_is_refused_before_hashing(rig) -> None:
    head, tail = b"<!doctype html><p>", b"</p>"
    assert rig.put(head + b"a" * (524_288 - len(head) - len(tail)) + tail, media_type="text/html").version == 1
    calls = rig.hasher.calls
    with pytest.raises(ArtifactRefused):
        rig.put(head + b"a" * (524_288 - len(head) - len(tail) + 1) + tail, media_type="text/html", unit="U2")
    assert rig.hasher.calls == calls


def test_WEB_1_AR_10_the_checker_sees_the_bytes_after_the_redactor(tmp_path) -> None:
    redactor = Redactor()
    rig = make_rig("memory", tmp_path, redactor=redactor)
    page = b"<!doctype html><p>key " + SECRET.encode() + b"</p>"
    stored = rig.put(page, media_type="text/html")
    kept = rig.store.read(rig.scope, stored.ref)
    assert SECRET.encode() not in kept and stored.record["redacted"] is True
    assert redactor.calls and sha(kept) == stored.record["content_sha256"]

    class Injecting:  # a redactor whose output is what the checker must judge
        def __call__(self, text: str) -> str:
            return text.replace("PLACEHOLDER", "https://x.example")

    rig2 = make_rig("memory", tmp_path, redactor=Injecting())
    with pytest.raises(ArtifactRefused):
        rig2.put(b"<!doctype html><p>PLACEHOLDER</p>", media_type="text/html")
    assert rig2.blobs.inner.keys() == []


def test_WEB_1_AR_10_html_is_screened_like_text(rig) -> None:
    stored = rig.put(GOOD, media_type="text/html")
    assert stored.record["screening"] == "clean"
    assert rig.safety.calls and rig.safety.calls[-1]["text"] == GOOD.decode()


@pytest.mark.parametrize("kind", ["upload", "render", "fetch"])
def test_WEB_1_AR_10_only_a_unit_stores_html(rig, kind) -> None:
    with pytest.raises(ArtifactRefused):
        if kind == "upload":
            rig.upload(GOOD, "text/html")
        else:
            rig.put(GOOD, media_type="text/html", unit="U3", agent=None if kind == "render" else "A_s1", kind=kind)
    assert rig.hasher.calls == 0 and rig.blobs.inner.keys() == []


def test_WEB_1_AR_10_a_restore_copies_a_stored_website(rig) -> None:
    first = rig.put(GOOD, media_type="text/html")
    copy = rig.restore(first.ref)
    assert copy.record["media_type"] == "text/html" and copy.version == 2
    assert rig.store.read(rig.scope, copy.ref) == GOOD


def test_WEB_1_AR_10_markdown_still_may_not_carry_a_page_marker_and_text_types_are_unchanged(rig) -> None:
    assert rig.put(b"# <script>fetch(1)</script>\n", media_type="text/markdown").version == 1  # not HTML: not checked


def test_WEB_1_AR_10_an_imported_page_is_checked_again(tmp_path) -> None:
    source, dest = make_rig("memory", None), make_rig("memory", None)
    stored = source.put(GOOD, media_type="text/html")
    record = dict(stored.record)
    imported = dest.store.import_version(dest.scope, record, GOOD)
    assert imported.record["media_type"] == "text/html"
    other = make_rig("memory", None, scope=scope_of())
    forged = dict(record, content_sha256=sha(BAD), size_bytes=len(BAD))
    with pytest.raises(ArtifactRefused):
        other.store.import_version(other.scope, forged, BAD)
    assert other.blobs.inner.keys() == []
