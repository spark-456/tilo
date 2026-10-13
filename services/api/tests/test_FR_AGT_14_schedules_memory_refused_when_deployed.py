"""FR-AGT-14 (#648 follow-up): a deployed service never opens the in-memory schedule store, even when named."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize("marker", ["K_SERVICE", "CLOUD_RUN_JOB"])
def test_FR_AGT_14_memory_schedule_store_is_refused_when_deployed(monkeypatch: pytest.MonkeyPatch, marker: str) -> None:
    from fastapi import HTTPException
    from tilo_api import schedules

    for name in ("TILO_API_DEV", "K_SERVICE", "CLOUD_RUN_JOB", "TILO_FIRESTORE_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TILO_SCHEDULES_STORE", "memory")
    monkeypatch.setenv(marker, "")  # presence, not truthiness
    schedules.get_schedule_store.cache_clear()  # type: ignore[attr-defined]
    with pytest.raises(HTTPException) as refused:
        schedules.get_schedule_store()
    assert refused.value.status_code == 503 and refused.value.detail == "not_configured"
    schedules.get_schedule_store.cache_clear()  # type: ignore[attr-defined]
