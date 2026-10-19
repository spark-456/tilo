"""Chunk backends (RT-03, RT-10): an exact-KNN in-memory one for dev, demo and tests, and Firestore vector search.

Both rank by dot product (the embeddings are unit vectors, so higher is closer) and apply the scope filter inside the
query. Neither returns the `embedding` field from `nearest` or `scan`.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

COLLECTION = "chunks"


def _bare(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in doc.items() if k != "embedding"}


class MemoryChunkBackend:
    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def put(self, org_id: str, doc: Mapping[str, Any]) -> None:
        with self._lock:
            self._docs[(org_id, doc["id"])] = {**doc, "embedding": list(doc["embedding"])}

    def delete(self, org_id: str, chunk_id: str) -> None:
        with self._lock:
            self._docs.pop((org_id, chunk_id), None)

    def _all(self, org_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [d for (org, _), d in self._docs.items() if org == org_id]

    def for_source(self, org_id: str, kind: str, source_id: str) -> list[dict[str, Any]]:
        return [d for d in self._all(org_id) if d["source"]["kind"] == kind and d["source"]["id"] == source_id]

    def count(self, org_id: str, field: str, value: str) -> int:
        return sum(1 for d in self._all(org_id) if d.get(field) == value)

    def nearest(
        self, org_id: str, field: str, value: str, profile: str, vector: Sequence[float], limit: int
    ) -> list[tuple[float, dict[str, Any]]]:
        scored = [
            (sum(a * b for a, b in zip(d["embedding"], vector, strict=True)), _bare(d))
            for d in self._all(org_id)
            if d.get(field) == value and d["embed_profile"] == profile and len(d["embedding"]) == len(vector)
        ]
        return sorted(scored, key=lambda pair: -pair[0])[:limit]

    def scan(self, org_id: str) -> Iterator[dict[str, Any]]:
        return iter([_bare(d) for d in self._all(org_id)])


class FirestoreChunkBackend:
    """`orgs/{org}/chunks/{id}` with a Firestore vector field. Needs the two composite vector indexes of
    infra/envs/dev/chunk_vector_indexes.tf (RT-10); until they exist `nearest` raises and the ask goes on ungrounded."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def _col(self, org_id: str) -> Any:
        return self._client.collection("orgs").document(org_id).collection(COLLECTION)

    def put(self, org_id: str, doc: Mapping[str, Any]) -> None:
        from google.cloud.firestore_v1.vector import Vector  # noqa: PLC0415

        self._col(org_id).document(doc["id"]).set({**doc, "embedding": Vector(list(doc["embedding"]))})

    def delete(self, org_id: str, chunk_id: str) -> None:
        self._col(org_id).document(chunk_id).delete()

    def for_source(self, org_id: str, kind: str, source_id: str) -> list[dict[str, Any]]:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415

        query = self._col(org_id).where(filter=FieldFilter("source.kind", "==", kind))
        query = query.where(filter=FieldFilter("source.id", "==", source_id))
        return [_with_vector(s.to_dict()) for s in query.stream()]  # the indexer reuses stored vectors

    def count(self, org_id: str, field: str, value: str) -> int:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415

        result = self._col(org_id).where(filter=FieldFilter(field, "==", value)).count().get()
        return int(result[0][0].value)

    def nearest(
        self, org_id: str, field: str, value: str, profile: str, vector: Sequence[float], limit: int
    ) -> list[tuple[float, dict[str, Any]]]:
        from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: PLC0415
        from google.cloud.firestore_v1.base_vector_query import DistanceMeasure  # noqa: PLC0415
        from google.cloud.firestore_v1.vector import Vector  # noqa: PLC0415

        query = self._col(org_id).where(filter=FieldFilter("org_id", "==", org_id))  # the filters ride inside the query
        query = query.where(filter=FieldFilter(field, "==", value)).where(
            filter=FieldFilter("embed_profile", "==", profile)
        )
        found = query.find_nearest(
            vector_field="embedding", query_vector=Vector(list(vector)), distance_measure=DistanceMeasure.DOT_PRODUCT,
            limit=limit, distance_result_field="_score",
        )  # fmt: skip
        rows = [s.to_dict() for s in found.stream()]
        return [(float(r.pop("_score")), _plain(r)) for r in rows]

    def scan(self, org_id: str) -> Iterator[dict[str, Any]]:
        return (_plain(s.to_dict()) for s in self._col(org_id).stream())


def _plain(doc: Mapping[str, Any]) -> dict[str, Any]:
    return _bare(doc)


def _with_vector(doc: Mapping[str, Any]) -> dict[str, Any]:
    return {**doc, "embedding": list(doc["embedding"])}
