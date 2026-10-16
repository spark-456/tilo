"""RT-10, RT-03: the Firestore backend asks for vector search with org, scope and profile filters INSIDE the query
(never after ranking), never hands back the embedding, and writes the vector as a Firestore Vector. No network."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from google.cloud.firestore_v1.base_vector_query import DistanceMeasure
from google.cloud.firestore_v1.vector import Vector
from tilo_memory.chunks_backends import FirestoreChunkBackend

ORG = "org_tilo"


class _Snap:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def to_dict(self) -> dict[str, Any]:
        return dict(self._data)


class _Query:
    def __init__(self, log: dict[str, Any], rows: list[dict[str, Any]]) -> None:
        self.log, self.rows = log, rows

    def where(self, *, filter: Any) -> _Query:  # noqa: A002 - the SDK's keyword
        self.log.setdefault("filters", []).append((filter.field_path, filter.op_string, filter.value))
        return self

    def find_nearest(self, **kwargs: Any) -> _Query:
        self.log["nearest"] = kwargs
        self.log["filters_before_nearest"] = list(self.log["filters"])
        return self

    def stream(self) -> list[_Snap]:
        return [_Snap(r) for r in self.rows]

    def count(self) -> Any:
        return SimpleNamespace(get=lambda: [[SimpleNamespace(value=len(self.rows))]])


class _Doc:
    def __init__(self, log: dict[str, Any]) -> None:
        self.log = log

    def set(self, data: dict[str, Any]) -> None:
        self.log["set"] = data

    def delete(self) -> None:
        self.log["deleted"] = True


class _Col(_Query):
    def document(self, key: str) -> _Doc:
        self.log["doc"] = key
        return _Doc(self.log)


class _Client:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.log: dict[str, Any] = {}
        self.rows = rows

    def collection(self, name: str) -> Any:
        self.log["path"] = [name]
        outer = self

        class _Org:
            def document(self, org: str) -> Any:
                outer.log["path"].append(org)
                return SimpleNamespace(
                    collection=lambda c: (outer.log["path"].append(c), _Col(outer.log, outer.rows))[1]
                )

        return _Org()


def _doc(chunk_id: str = "ch_" + "a" * 32) -> dict[str, Any]:
    return {"id": chunk_id, "owner": "u_alice", "text": "hello", "embedding": Vector([1.0, 0.0])}


def test_RT_10_nearest_filters_org_scope_and_profile_inside_the_vector_query_and_drops_the_embedding():
    client = _Client([{**_doc(), "_score": 0.75}])
    hits = FirestoreChunkBackend(client).nearest(ORG, "team_id", "tm_design", "embed-google", [1.0, 0.0], 6)
    assert client.log["path"] == ["orgs", ORG, "chunks"]
    assert client.log["filters_before_nearest"] == [
        ("org_id", "==", ORG), ("team_id", "==", "tm_design"), ("embed_profile", "==", "embed-google"),
    ]  # fmt: skip
    nearest = client.log["nearest"]
    assert nearest["vector_field"] == "embedding" and nearest["limit"] == 6
    assert nearest["distance_measure"] == DistanceMeasure.DOT_PRODUCT
    assert nearest["query_vector"] == Vector([1.0, 0.0])
    assert hits == [(0.75, {"id": "ch_" + "a" * 32, "owner": "u_alice", "text": "hello"})]


def test_RT_10_put_writes_a_firestore_vector_and_scan_never_returns_it():
    client = _Client([_doc()])
    backend = FirestoreChunkBackend(client)
    backend.put(ORG, {"id": "ch_" + "b" * 32, "embedding": [0.5, 0.5]})
    assert client.log["set"]["embedding"] == Vector([0.5, 0.5])
    assert all("embedding" not in d for d in backend.scan(ORG))
    assert backend.count(ORG, "owner", "u_alice") == 1
    assert backend.for_source(ORG, "pin", "pb_one")[0]["embedding"] == [1.0, 0.0]  # the indexer reuses stored vectors
