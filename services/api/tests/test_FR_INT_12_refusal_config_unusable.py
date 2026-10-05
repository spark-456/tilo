"""FR-INT-12 fail closed through `POST /intake`: a refusal config that cannot be loaded is 503, nothing is stored and
the task text is not echoed (no refusal list means no brief, never an unscreened pass)."""

from __future__ import annotations

import pathlib

import pytest
import tilo_planning.refusal as refusal
from tilo_api import intake as intake_module
from tilo_planning.artifacts import InMemoryArtifactStore


@pytest.mark.parametrize(
    "content",
    [None, "", "categories: []\n", "categories: [unclosed"],
    ids=["missing", "empty", "no categories", "bad yaml"],
)
def test_FR_INT_12_an_unusable_refusal_config_is_503_and_stores_nothing(clear_flow, monkeypatch, tmp_path, content):
    path = pathlib.Path(tmp_path) / "out_of_policy.yaml"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(refusal, "DEFAULT_REFUSAL_CONFIG", path)
    artifacts = InMemoryArtifactStore()
    clear_flow.app.dependency_overrides[intake_module.get_store] = lambda: artifacts

    response = clear_flow.intake(text="Summarise the weekly supplier prices ECHOME-zq7")

    assert response.status_code == 503 and "ECHOME-zq7" not in response.text
    assert artifacts.list_ids() == [] and not clear_flow.store.tasks and not clear_flow.store.events
