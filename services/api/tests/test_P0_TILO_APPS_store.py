import pytest
from fastapi import HTTPException
from tilo_api import app_response_store
from tilo_api.app_response_store import InMemoryAppStore


def test_P0_TILO_APPS_memory_paths_are_stable_collision_safe_and_rate_limited():
    apps = InMemoryAppStore()
    base = {"handle": "jo-smith", "slug": "survey", "published": True}
    first = apps.publish(base | {"artifact_id": "art_one", "owner": "u_one"})
    other = apps.publish(base | {"artifact_id": "art_two", "owner": "u_two"})
    sibling = apps.publish(base | {"artifact_id": "art_three", "owner": "u_one"})
    assert first == apps.publish(base | {"artifact_id": "art_one", "owner": "u_one"})
    assert len({(app["handle"], app["slug"]) for app in (first, other, sibling)}) == 3
    for index in range(60):
        apps.add("art_rate", {"id": str(index)}, "same-ip")
    with pytest.raises(HTTPException) as limited:
        apps.add("art_rate", {"id": "blocked"}, "same-ip")
    assert limited.value.status_code == 429


def test_P0_TILO_APPS_live_store_uses_firestore_door(monkeypatch):
    from types import SimpleNamespace

    client = object()
    monkeypatch.setattr(app_response_store.store_door, "open_api_store", lambda: SimpleNamespace(client=client))
    assert app_response_store.get_app_store()._client is client


def test_P0_REGRESSION_SMOKE_public_app_limit_survives_ip_rotation():
    apps = InMemoryAppStore()
    for index in range(300):
        apps.add("art_public", {"id": str(index)}, f"ip-{index}")
    with pytest.raises(HTTPException) as limited:
        apps.add("art_public", {"id": "blocked"}, "fresh-ip")
    assert limited.value.status_code == 429
