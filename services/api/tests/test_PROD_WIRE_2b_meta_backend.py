"""PROD-WIRE 2b (issue #522): `FirestoreMetaBackend(client, *, collection_root)` is a `MetaBackend` (ADR-0018 T8,
`tilo_memory.artifacts`) with the behaviour of `MemoryMetaBackend`. Contract tests run over both; the Firestore rows run
on the emulator (`tilo_harness.emulator.running_emulator()`, a `demo-` project, no credentials) under `-m emulator`.

Pinned mapping: the store's path string IS the document path, `orgs/{org}/worlds/{world}/artifacts/{art}/versions/
{n:06d}` and `.../versions/{n:06d}/manifests/{n:04d}` (ADR-0018 section 2; the ticket text says `orgs/{org}/artifacts`,
the ADR and the store's `_record_path` have the world segment, so the ADR wins). `collection_root` is the first
segment ("orgs"): a path outside it, with `..`, `.`, an empty or a non-`[0-9A-Za-z_]` segment, or with an odd number of
segments (not a document) is a `ValueError` raised before the client is touched. The stored representation is not
pinned (Firestore refuses arrays of arrays, so `DOC` holds one: the backend must cope).
`tilo_api.run_stores` does not exist yet: every test here fails at collection with `ModuleNotFoundError`.
"""

from __future__ import annotations

import re
import secrets
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from _prod_wire_2b_lib import race
from google.api_core import exceptions as gexc
from google.cloud import firestore
from tilo_api.run_stores import FirestoreMetaBackend
from tilo_harness.emulator import running_emulator
from tilo_memory.artifacts import MemoryMetaBackend

DOC = {"owner": "u_a", "sources": [{"id": "S1", "archive_ref": "r_1/3"}], "rows": [[1, 2.5], [None, True]],
       "empty": [], "deep": {"a": {"b": ["é", "日本"]}}, "note": None, "n": 2**40}  # fmt: skip


def where() -> tuple[str, str]:
    org = "org_" + secrets.token_hex(4)  # unique per test: the emulator is shared, never cleared
    return org, f"orgs/{org}/worlds/w_1/artifacts/art_1/versions/000001"


@pytest.fixture(scope="session")
def emulator_client():
    with running_emulator():
        yield firestore.Client(project="demo-tilo")


@pytest.fixture(params=["memory", pytest.param("firestore", marks=pytest.mark.emulator)])
def meta(request):
    if request.param == "memory":
        return MemoryMetaBackend()
    return FirestoreMetaBackend(request.getfixturevalue("emulator_client"), collection_root="orgs")


def test_PROD_WIRE_2b_meta_get_returns_what_create_stored_as_an_independent_copy(meta):
    _, path = where()
    assert meta.get(path) is None
    meta.create(path, DOC)
    got = meta.get(path)
    assert got == DOC
    got["owner"] = "u_other"
    got["rows"].append("x")
    assert meta.get(path) == DOC


def test_PROD_WIRE_2b_meta_create_never_overwrites(meta):
    _, path = where()
    meta.create(path, DOC)
    with pytest.raises(FileExistsError):
        meta.create(path, {**DOC, "owner": "u_thief"})
    assert meta.get(path) == DOC
    outcomes = race(lambda i: meta.create(path + "/manifests/0001", {"i": i}))
    assert sorted(outcomes) == ["exists"] * 7 + ["ok"], outcomes


def test_PROD_WIRE_2b_meta_delete_is_idempotent_and_frees_the_path(meta):
    _, path = where()
    meta.delete(path)
    meta.create(path, DOC)
    meta.delete(path)
    meta.delete(path)
    assert meta.get(path) is None
    meta.create(path, {"again": 1})
    assert meta.get(path) == {"again": 1}


def test_PROD_WIRE_2b_meta_paths_lists_documents_under_a_prefix_sorted(meta):
    org, path = where()
    base = path.rsplit("/", 2)[0]
    mine = [f"{base}/versions/000001", f"{base}/versions/000002", f"{base}/versions/000002/manifests/0001"]
    mine += [f"{base}/versions/000002/manifests/0002", f"orgs/{org}/worlds/w_2/artifacts/art_9/versions/000001"]
    for p in reversed(mine):
        meta.create(p, {"p": p})
    assert meta.paths(f"orgs/{org}/") == sorted(mine)  # no entry for the parents that are not documents
    assert meta.paths(f"{base}/versions/") == sorted(mine[:4])  # manifests are under versions, as in memory
    assert meta.paths(f"{base}/versions/000002/manifests/") == mine[2:4]
    assert meta.paths(f"orgs/{org}/worlds/w_3/") == []
    assert set(mine) <= set(meta.paths("orgs/")) and set(mine) <= set(meta.paths())


@pytest.mark.emulator
def test_PROD_WIRE_2b_meta_the_document_lives_at_the_store_path_and_outlives_the_backend(emulator_client):
    _, path = where()
    FirestoreMetaBackend(emulator_client, collection_root="orgs").create(path, DOC)
    manifest = path + "/manifests/0001"
    reopened = FirestoreMetaBackend(emulator_client, collection_root="orgs")
    reopened.create(manifest, {"n": 1})
    assert emulator_client.document(path).get().exists and emulator_client.document(manifest).get().exists
    assert reopened.get(path) == DOC
    reopened.delete(manifest)
    assert not emulator_client.document(manifest).get().exists and emulator_client.document(path).get().exists


BAD_PATHS = ["", "orgs", "orgs/org_a/worlds", "/orgs/org_a/x", "orgs//org_a/x", "orgs/org_a/x/", "orgs/../org_a/x"]
BAD_PATHS += ["orgs/org_a/../org_b/x", "orgs/org_a/./x", "other/org_a/x", "orgs/org_a/w b/x", "orgs/org_a/x\n"]
BAD_PATHS += ["orgs/org_a/a\\b/x"]
BAD_PREFIXES = ["orgs//", "orgs/../", "orgs/org_a/../", "/orgs/", "other/", "orgs/org a/"]


def test_PROD_WIRE_2b_meta_a_path_that_escapes_the_root_is_refused_before_the_client_is_touched():
    client = MagicMock(name="client")
    backend = FirestoreMetaBackend(client, collection_root="orgs")
    other_root = FirestoreMetaBackend(client, collection_root="elsewhere")
    built = [str(c[0]) for c in client.mock_calls]  # building may name a collection or document, never read or write
    assert all(re.fullmatch(r"(collection|document)(\(\)\.(collection|document))*", name) for name in built), built
    before = list(client.mock_calls)
    for path in BAD_PATHS:
        for call in (lambda: backend.create(path, DOC), lambda: backend.get(path), lambda: backend.delete(path)):
            with pytest.raises(ValueError):
                call()
    for prefix in BAD_PREFIXES:
        with pytest.raises(ValueError):
            backend.paths(prefix)
    with pytest.raises(ValueError):
        other_root.create(where()[1], DOC)  # "orgs/..." is outside the root "elsewhere"
    for bad_root in ("", "a/b", "..", "orgs/", "or gs"):
        with pytest.raises(ValueError):
            FirestoreMetaBackend(client, collection_root=bad_root)
    assert client.mock_calls == before


class _LostReplyRef:
    """A document whose `create` stores the body, then answers AlreadyExists: the Firestore client's own retry met
    the document its first attempt wrote (the answer was lost), on attempt 0 of the backend's own loop."""

    def __init__(self, stored: Any = None) -> None:
        self.stored, self.creates = stored, 0

    def create(self, body: Any) -> None:
        self.creates += 1
        if self.stored is None:
            self.stored = body
        raise gexc.AlreadyExists("409 the document already exists")

    def get(self) -> Any:
        stored = self.stored
        return types.SimpleNamespace(exists=stored is not None, to_dict=lambda: dict(stored))


def test_PROD_WIRE_2b_meta_a_lost_reply_on_the_first_attempt_is_success_only_over_the_same_body():
    _, path = where()
    ours, client = _LostReplyRef(), MagicMock(name="client")
    client.document.return_value = ours
    FirestoreMetaBackend(client, collection_root="orgs").create(path, DOC)  # our own body is there: success
    assert ours.creates == 1
    client.document.return_value = _LostReplyRef(stored={"v": 1, "doc": "{}"})
    with pytest.raises(FileExistsError):
        FirestoreMetaBackend(client, collection_root="orgs").create(path, DOC)
