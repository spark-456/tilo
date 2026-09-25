"""PRD 15.3 / ADR-0003 (local-first): "no cloud credentials, never a real project" --
`FirestoreStore` "refuses to start unless FIRESTORE_EMULATOR_HOST is set and the project id
starts with demo- (default demo-tilo)". These are pure config guards (no emulator, no network),
so they run in the default suite; the emulator-backed positive path (constructing and actually
reading/writing through a live emulator) is in test_PRD_15_3_emulator_skeleton_run.py.

The ticket brief names no exception class for this guard (unlike EventRejected/WriterBusy,
which are in the public API), so these assert only `pytest.raises(Exception)` -- refusing to
start, whatever the exact type -- to avoid pinning an unspecified detail.
"""

from __future__ import annotations

import pytest


def test_PRD_15_3_firestore_store_refuses_without_FIRESTORE_EMULATOR_HOST(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017 -- type intentionally unspecified, see module docstring
        FirestoreStore(project_id="demo-tilo")


@pytest.mark.parametrize("bad_project_id", ["tilo-prod", "prod-demo-tilo", "Demo-tilo", "tilo"])
def test_PRD_15_3_firestore_store_refuses_a_non_demo_project_id(
    monkeypatch: pytest.MonkeyPatch, bad_project_id: str
) -> None:
    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8199")
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017
        FirestoreStore(project_id=bad_project_id)


def test_PRD_15_3_firestore_store_refuses_without_host_even_with_a_demo_project_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both guards are required, not either/or: a demo- project id alone must not be enough."""
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017
        FirestoreStore(project_id="demo-tilo")
