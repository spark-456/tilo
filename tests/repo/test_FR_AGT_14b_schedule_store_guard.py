"""FR-AGT-14b repo guards (design decision 5; ADR-0003 local-first; PL-01; "no secrets in code"):

- by default the schedule store refuses to open a live Firestore client: nothing happens at import, and
  `open_schedule_store` with no explicit config raises before any client is built. The emulator/demo- guard of
  `tilo_harness.store.FirestoreStore` is still there, untouched;
- the new sources carry no model id, no secret and no hard-coded service-account address;
- the decision is written down: an ADR-0003 addendum (or a new ADR) names the switch, and ONE BQ row per
  ticket (BQ-AGT14-3, -4, -5) ends docs/open-questions.md, the newest last.

Needs the uv workspace (it imports tilo_harness); run with `uv run pytest tests/repo`.
"""

from __future__ import annotations

import importlib
import importlib.util
import pathlib
import re
import types
from typing import Any

import pytest

STORE_SRC = "services/harness/src/tilo_harness/schedule_store.py"
API_SRC = "services/api/src/tilo_api/schedules.py"
NEW_TESTS = (
    "services/api/tests/test_FR_AGT_14_schedule_routes.py",
    "services/api/tests/test_FR_AGT_14_scheduled_start.py",
    "services/api/tests/test_FR_AGT_14_tick_route.py",
    "services/api/tests/_fr_agt_14_lib.py",
    "services/harness/tests/test_FR_AGT_14_schedule_store.py",
    "services/harness/tests/test_FR_AGT_14_ticker_hardening.py",
    "services/harness/tests/fr_agt_14_store_support.py",
    "tests/repo/test_FR_AGT_14b_schedule_store_guard.py",
)


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    path = repo_root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Bomb:
    def __init__(self) -> None:
        self.built: list[Any] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.built.append((args, kwargs))
        raise AssertionError("a live Firestore client was opened")


@pytest.fixture
def bomb(monkeypatch: pytest.MonkeyPatch) -> _Bomb:
    from google.cloud import firestore

    bomb = _Bomb()
    monkeypatch.setattr(firestore, "Client", bomb)
    for name in ("FIRESTORE_EMULATOR_HOST", "TILO_SCHEDULES_STORE", "TILO_FIRESTORE_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        monkeypatch.delenv(name, raising=False)
    return bomb


def test_FR_AGT_14_importing_the_schedule_store_opens_no_client(bomb: _Bomb) -> None:
    module = importlib.import_module("tilo_harness.schedule_store")
    importlib.reload(module)
    assert bomb.built == []


def test_FR_AGT_14_the_default_store_config_refuses_a_live_firestore_client(bomb: _Bomb) -> None:
    from tilo_harness.schedule_store import ScheduleStoreNotConfigured, open_schedule_store

    with pytest.raises(ScheduleStoreNotConfigured):
        open_schedule_store({})
    with pytest.raises(ScheduleStoreNotConfigured):
        open_schedule_store()  # the real process environment, cleared by the fixture
    assert bomb.built == []


def test_FR_AGT_14_the_existing_firestore_store_guard_still_requires_the_emulator_and_a_demo_project(
    repo_root: pathlib.Path, bomb: _Bomb
) -> None:
    from tilo_harness.store import FirestoreStore

    with pytest.raises(Exception):  # noqa: B017 - the type is unspecified by the PRD 15.3 tests
        FirestoreStore(project_id="demo-tilo")
    source = (repo_root / "services/harness/src/tilo_harness/store.py").read_text(encoding="utf-8")
    assert "FIRESTORE_EMULATOR_HOST" in source and "demo" in source  # the guard text is still in place
    assert bomb.built == []


def test_FR_AGT_14_the_new_sources_exist(repo_root: pathlib.Path) -> None:
    for relative in (STORE_SRC, API_SRC):
        assert (repo_root / relative).is_file(), f"{relative} is the module API_FR_AGT_14b.md pins"


def test_FR_AGT_14_no_model_id_and_no_secret_in_the_new_sources_or_tests(repo_root: pathlib.Path) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (STORE_SRC, API_SRC, *NEW_TESTS):
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"


def test_FR_AGT_14_the_api_module_hard_codes_no_service_account_address(repo_root: pathlib.Path) -> None:
    """The caller is `TILO_SCHEDULE_TICK_CALLER` (config); the code names no address of its own."""
    source = (repo_root / API_SRC).read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.iam\.gserviceaccount\.com", source)
    assert "TILO_SCHEDULE_TICK_CALLER" in source and "TILO_SCHEDULE_TICK_AUDIENCE" in source


def test_FR_AGT_14_an_adr_names_the_explicit_switch_that_opens_the_live_store(repo_root: pathlib.Path) -> None:
    adrs = sorted((repo_root / "docs" / "adr").glob("*.md"))
    holders = [p.name for p in adrs if "TILO_SCHEDULES_STORE" in p.read_text(encoding="utf-8")]
    assert holders, "write the ADR-0003 addendum (or a new ADR) before a live Firestore path exists"
    text = "\n".join((repo_root / "docs" / "adr" / name).read_text(encoding="utf-8") for name in holders)
    assert "TILO_FIRESTORE_PROJECT" in text and "emulator" in text.lower() and "demo-" in text


def test_FR_AGT_14_one_bq_row_logs_the_decisions_and_it_is_the_last_row(repo_root: pathlib.Path) -> None:
    """14b logged ONE row, BQ-AGT14-3; 14d appended ONE more, BQ-AGT14-4; 14e appends ONE more, BQ-AGT14-5, which is now
    the last row (deliberately changed from "BQ-AGT14-4 is last"): each is present exactly once, in this order, and the
    newest ends the file."""
    rows = [
        line
        for line in (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8").splitlines()
        if line.startswith("|")
    ]
    third = [line for line in rows if line.startswith("| BQ-AGT14-3 |")]
    assert len(third) == 1, "the 14b decisions stay ONE row, BQ-AGT14-3"
    fourth = [line for line in rows if line.startswith("| BQ-AGT14-4 |")]
    assert len(fourth) == 1, "the 14d decisions stay ONE row, BQ-AGT14-4"
    fifth = [line for line in rows if line.startswith("| BQ-AGT14-5 |")]
    assert len(fifth) == 1, "log the 14e decisions as ONE row, BQ-AGT14-5"
    assert rows[-1] == fifth[0], "append it at the end of docs/open-questions.md"
    assert rows.index(third[0]) < rows.index(fourth[0]) < rows.index(fifth[0])
