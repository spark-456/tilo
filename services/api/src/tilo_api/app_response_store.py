"""Memory and Firestore persistence for published apps and their responses."""

from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict
from typing import Any

from fastapi import HTTPException

from tilo_api import store_door

MAX_RESPONSES = 5000
RATE_PER_HOUR = 60
RATE_PER_APP_HOUR = 300


def _alternate(base: str, identity: str) -> str:
    return f"{base[:48]}-{hashlib.sha256(identity.encode()).hexdigest()[:12]}"


class InMemoryAppStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._apps: dict[str, dict[str, Any]] = {}
        self._rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._rates: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._app_rates: dict[str, list[float]] = defaultdict(list)

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            held = self._apps.get(record["artifact_id"])
            if held:
                record = {**record, "handle": held["handle"], "slug": held["slug"]}
            else:
                handle = record["handle"]
                if any(a["handle"] == handle and a["owner"] != record["owner"] for a in self._apps.values()):
                    handle = _alternate(handle, record["owner"])
                slug = record["slug"]
                if any(a["handle"] == handle and a["slug"] == slug for a in self._apps.values()):
                    slug = _alternate(slug, record["artifact_id"])
                record = {**record, "handle": handle, "slug": slug}
            self._apps[record["artifact_id"]] = dict(record)
            return dict(record)

    def unpublish(self, artifact_id: str) -> dict[str, Any] | None:
        with self._lock:
            held = self._apps.get(artifact_id)
            if held is None:
                return None
            held["published"] = False
            return dict(held)

    def public(self, handle: str, slug: str) -> dict[str, Any] | None:
        with self._lock:
            return next(
                (
                    dict(a)
                    for a in self._apps.values()
                    if a["handle"] == handle and a["slug"] == slug and a["published"]
                ),
                None,
            )

    def add(self, artifact_id: str, row: dict[str, Any], rate_key: str) -> int:
        with self._lock:
            if len(self._rows[artifact_id]) >= MAX_RESPONSES:
                raise HTTPException(409, "response_limit_reached")
            now = time.monotonic()
            recent = [stamp for stamp in self._rates[(artifact_id, rate_key)] if now - stamp < 3600]
            app_recent = [stamp for stamp in self._app_rates[artifact_id] if now - stamp < 3600]
            if len(recent) >= RATE_PER_HOUR or len(app_recent) >= RATE_PER_APP_HOUR:
                raise HTTPException(429, "rate_limited")
            self._rates[(artifact_id, rate_key)] = [*recent, now]
            self._app_rates[artifact_id] = [*app_recent, now]
            self._rows[artifact_id].append(dict(row))
            return len(self._rows[artifact_id])

    def responses(self, artifact_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(row) for row in self._rows[artifact_id]]

    def delete(self, artifact_id: str, response_id: str) -> bool:
        with self._lock:
            before = len(self._rows[artifact_id])
            self._rows[artifact_id] = [row for row in self._rows[artifact_id] if row["id"] != response_id]
            return len(self._rows[artifact_id]) != before

    def seed_count(self, artifact_id: str, count: int) -> None:
        self._rows[artifact_id] = [{"id": f"seed-{n}"} for n in range(count)]


class FirestoreAppStore:
    def __init__(self, client: Any) -> None:
        self._client = client

    def _app(self, artifact_id: str) -> Any:
        return self._client.document(f"app_publications/{artifact_id}")

    def _path(self, handle: str, slug: str) -> Any:
        return self._client.document(f"public_apps/{handle}--{slug}")

    def _handle(self, handle: str) -> Any:
        return self._client.document(f"public_app_handles/{handle}")

    def publish(self, record: dict[str, Any]) -> dict[str, Any]:
        from google.cloud import firestore

        app = self._app(record["artifact_id"])

        @firestore.transactional
        def work(tx: Any) -> dict[str, Any]:
            old = app.get(transaction=tx).to_dict() or {}
            handle, slug = old.get("handle", record["handle"]), old.get("slug", record["slug"])
            handle_ref = self._handle(handle)
            owner = handle_ref.get(transaction=tx).to_dict() or {}
            if owner and owner.get("owner") != record["owner"]:
                handle = _alternate(handle, record["owner"])
                handle_ref = self._handle(handle)
                owner = handle_ref.get(transaction=tx).to_dict() or {}
            if owner and owner.get("owner") != record["owner"]:
                raise HTTPException(409, "public_path_unavailable")
            path = self._path(handle, slug)
            taken = path.get(transaction=tx).to_dict() or {}
            if taken and taken.get("artifact_id") != record["artifact_id"]:
                slug = _alternate(slug, record["artifact_id"])
                path = self._path(handle, slug)
                taken = path.get(transaction=tx).to_dict() or {}
            if taken and taken.get("artifact_id") != record["artifact_id"]:
                raise HTTPException(409, "public_path_unavailable")
            saved = {
                **record,
                "handle": handle,
                "slug": slug,
                "response_count": old.get("response_count", 0),
                "rates": old.get("rates", {}),
                "app_rates": old.get("app_rates", []),
            }
            tx.set(handle_ref, {"owner": record["owner"]})
            tx.set(app, saved)
            tx.set(path, saved)
            return saved

        return dict(work(self._client.transaction()))

    def unpublish(self, artifact_id: str) -> dict[str, Any] | None:
        ref, snap = self._app(artifact_id), self._app(artifact_id).get()
        if not snap.exists:
            return None
        record = {**(snap.to_dict() or {}), "published": False}
        ref.set(record)
        self._path(record["handle"], record["slug"]).set(record)
        return record

    def public(self, handle: str, slug: str) -> dict[str, Any] | None:
        snap = self._path(handle, slug).get()
        record = dict(snap.to_dict()) if snap.exists else None
        return record if record and record.get("published") else None

    def add(self, artifact_id: str, row: dict[str, Any], rate_key: str) -> int:
        from google.cloud import firestore

        app, item = self._app(artifact_id), self._app(artifact_id).collection("responses").document(row["id"])

        @firestore.transactional
        def work(tx: Any) -> int:
            snap = app.get(transaction=tx)
            record = snap.to_dict() or {}
            count, rates = int(record.get("response_count", 0)), record.get("rates", {})
            hits = [stamp for stamp in rates.get(rate_key, []) if row["epoch"] - stamp < 3600]
            app_hits = [stamp for stamp in record.get("app_rates", []) if row["epoch"] - stamp < 3600]
            if count >= MAX_RESPONSES:
                raise HTTPException(409, "response_limit_reached")
            if len(hits) >= RATE_PER_HOUR or len(app_hits) >= RATE_PER_APP_HOUR:
                raise HTTPException(429, "rate_limited")
            tx.create(item, row)
            rates[rate_key] = [*hits, row["epoch"]]
            values = {"response_count": count + 1, "rates": rates, "app_rates": [*app_hits, row["epoch"]]}
            tx.update(app, values) if snap.exists else tx.set(
                app, {"artifact_id": artifact_id, "published": False, **values}
            )
            return count + 1

        return int(work(self._client.transaction()))

    def responses(self, artifact_id: str) -> list[dict[str, Any]]:
        rows = [dict(s.to_dict()) for s in self._app(artifact_id).collection("responses").stream()]
        return sorted(rows, key=lambda row: (row.get("epoch", 0), row.get("at", ""), row.get("id", "")))

    def delete(self, artifact_id: str, response_id: str) -> bool:
        from google.cloud import firestore

        app, item = self._app(artifact_id), self._app(artifact_id).collection("responses").document(response_id)

        @firestore.transactional
        def work(tx: Any) -> bool:
            if not item.get(transaction=tx).exists:
                return False
            held = app.get(transaction=tx).to_dict() or {}
            tx.delete(item)
            tx.update(app, {"response_count": max(0, int(held.get("response_count", 1)) - 1)})
            return True

        return bool(work(self._client.transaction()))


def get_app_store() -> FirestoreAppStore:
    try:
        return FirestoreAppStore(store_door.open_api_store().client)
    except store_door.ApiStoreNotConfigured:
        raise HTTPException(503, "not_configured") from None
