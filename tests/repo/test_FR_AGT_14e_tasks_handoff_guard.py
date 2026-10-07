"""FR-AGT-14e repo guards (Cloud Tasks hand-off of scheduled runs; design decisions 1, 5; PL-01; "no secrets in code"):

- the decision is written down: ONE BQ row, BQ-AGT14-5, is now the LAST table row of docs/open-questions.md,
  exactly once, and BQ-AGT14-4 is present once before it;
- NO Terraform change: the Tasks identity already holds `run.invoker` on harness only, api is public and checks its own
  token, and `tilo-api` already enqueues. So no `run.invoker` binding (or any Cloud Run IAM resource) is added, no entry
  of `extra_invokers` points at `api`, and the only IAM that names the Tasks identity is what was already there;
- the two env names (`TILO_RUNS_QUEUE`, `TILO_TASKS_CALLER`) are in the sources and documented in infra/ACCESS.md and
  infra/README.md, which also say the Scheduler never gets the Tasks mode and the reverse;
- no Cloud Tasks client library is added (the REST API is called through an injected transport), the api module names no
  service-account address and no queue path, and the new tests carry no model id and no secret.

Stdlib and pyyaml only except the model-id and secret scans, which import the repo's own scripts.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
import types

ROUTE_SRC = "services/api/src/tilo_api/schedules.py"
NEW_TESTS = (
    "services/api/tests/_fr_agt_14_lib.py",
    "services/api/tests/_fr_agt_14e_lib.py",
    "services/api/tests/test_FR_AGT_14e_fanout.py",
    "services/api/tests/test_FR_AGT_14e_no_new_route.py",
    "services/api/tests/test_FR_AGT_14e_run_wait.py",
    "services/api/tests/test_FR_AGT_14e_task_run.py",
    "tests/repo/test_FR_AGT_14e_tasks_handoff_guard.py",
)
IAM_TYPES = (
    "google_cloud_run_v2_service_iam_member",
    "google_cloud_run_v2_service_iam_binding",
    "google_cloud_run_v2_service_iam_policy",
    "google_cloud_run_service_iam_member",
    "google_cloud_run_service_iam_binding",
    "google_cloud_run_service_iam_policy",
    "google_cloud_tasks_queue_iam_member",
    "google_cloud_tasks_queue_iam_binding",
    "google_cloud_tasks_queue_iam_policy",
)


def _script(repo_root: pathlib.Path, name: str) -> types.ModuleType:
    path = repo_root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{name}_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _braced(text: str, head: re.Match[str]) -> str:
    depth, i = 1, head.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[head.end() : i - 1]


def _rows(repo_root: pathlib.Path) -> list[str]:
    text = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.startswith("|")]


def test_FR_AGT_14e_one_bq_row_logs_the_decisions_exactly_once(repo_root: pathlib.Path) -> None:
    """Where the row sits is not pinned (changed deliberately after #554: open-questions.md merges with
    `merge=union` and later tickets append their own rows, so a last-row pin made every PR conflict)."""
    rows = _rows(repo_root)
    fourth = [line for line in rows if line.startswith("| BQ-AGT14-4 |")]
    fifth = [line for line in rows if line.startswith("| BQ-AGT14-5 |")]
    assert len(fifth) == 1, "log the 14e decisions as ONE row, BQ-AGT14-5"
    assert len(fourth) == 1, "BQ-AGT14-4 (14d) stays ONE row"
    assert rows.index(fourth[0]) < rows.index(fifth[0])


def test_FR_AGT_14e_the_row_names_the_open_decisions(repo_root: pathlib.Path) -> None:
    (row,) = [line for line in _rows(repo_root) if line.startswith("| BQ-AGT14-5 |")]
    for name in ("TILO_RUNS_QUEUE", "TILO_TASKS_CALLER", "FR-AGT-14e"):
        assert name in row, name


def test_FR_AGT_14e_infra_adds_no_run_invoker_or_iam_resource_for_the_tasks_flow(repo_root: pathlib.Path) -> None:
    """The plan is no Terraform change. Cloud Run and Cloud Tasks IAM resources exist only in the service module (the
    `run.invoker` for_each and the per-service developer grants); no other file declares one, nothing grants the Tasks
    identity a role on api, and `extra_invokers` has no entry for api."""
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(repo_root).as_posix()
        for iam_type in IAM_TYPES:
            declared = re.findall(rf'^resource\s+"{iam_type}"\s+"([^"]+)"', text, re.M)
            if relative == "infra/modules/service/main.tf":
                assert set(declared) <= {"invoker", "developer"}, f"{relative}: a new {iam_type}: {declared}"
            else:
                assert not declared, f"{relative}: declares {iam_type} {declared}; the tasks flow needs no IAM change"
    main = (repo_root / "infra/envs/dev/main.tf").read_text(encoding="utf-8")
    block = re.search(r"extra_invokers\s*=\s*\{", main)
    assert block is not None
    entries = _braced(main, block)
    assert re.findall(r'^\s*"([^"]+)"\s*=\s*\{', entries, re.M) == [
        "channels::gmail-push",
        "harness::gmail-scheduler",
        "harness::cloud-tasks",
    ], "extra_invokers changed: the Tasks hand-off needs none (api is public and checks its own token)"
    assert not re.search(r'service\s*=\s*"api"', entries)


def test_FR_AGT_14e_the_tasks_identity_is_named_by_the_same_two_iam_things_as_before(repo_root: pathlib.Path) -> None:
    holders: list[str] = []
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for head in re.finditer(r'^resource\s+"(google_[a-z_]*iam[a-z_]*)"\s+"([^"]+)"\s*\{', text, re.M):
            if "tasks_invoker" in _braced(text, head) or "tilo-tasks-invoker" in _braced(text, head):
                holders.append(f"{path.relative_to(repo_root).as_posix()}::{head.group(2)}")
    assert holders == ["infra/envs/dev/main.tf::tasks_invoker_users"], holders  # enqueuers act as it: unchanged


def test_FR_AGT_14e_the_env_names_are_in_the_source_and_the_docs(repo_root: pathlib.Path) -> None:
    source = (repo_root / ROUTE_SRC).read_text(encoding="utf-8")
    for name in ("TILO_RUNS_QUEUE", "TILO_TASKS_CALLER", "TILO_SCHEDULE_TICK_AUDIENCE", "TILO_SCHEDULE_TICK_CALLER"):
        assert name in source, name
    for relative in ("infra/ACCESS.md", "infra/README.md"):
        text = (repo_root / relative).read_text(encoding="utf-8")
        assert "TILO_RUNS_QUEUE" in text and "TILO_TASKS_CALLER" in text, f"document the two env names in {relative}"
    access = (repo_root / "infra/ACCESS.md").read_text(encoding="utf-8")
    for needle in ("tilo-tasks-invoker", "tilo-schedule-scheduler", "/internal/schedules/tick"):
        assert needle in access, needle
    assert re.search(r"(?is)scheduler.{0,200}never.{0,200}tasks", access) or re.search(
        r"(?is)tasks.{0,200}never.{0,200}scheduler", access
    ), "ACCESS.md must say that neither caller ever gets the other's mode"
    claude = (repo_root / "services/api/CLAUDE.md").read_text(encoding="utf-8")
    assert "TILO_TASKS_CALLER" in claude and "TILO_RUNS_QUEUE" in claude, (
        "fold the 14e line into services/api/CLAUDE.md"
    )
    assert len(claude.splitlines()) <= 40, "services/api/CLAUDE.md stays at 40 lines or fewer"


def test_FR_AGT_14e_no_cloud_tasks_library_and_no_hard_coded_address_or_queue(repo_root: pathlib.Path) -> None:
    for pyproject in (repo_root / "services").glob("*/pyproject.toml"):
        assert "google-cloud-tasks" not in pyproject.read_text(encoding="utf-8"), pyproject.as_posix()
    assert "google-cloud-tasks" not in (repo_root / "pyproject.toml").read_text(encoding="utf-8")
    source = (repo_root / ROUTE_SRC).read_text(encoding="utf-8")
    assert not re.search(r"[\w.+-]+@[\w-]+\.iam\.gserviceaccount\.com", source)
    assert not re.search(r"projects/[a-z][a-z0-9-]+/locations/", source), "the queue path is TILO_RUNS_QUEUE's"
    assert "google.cloud.tasks" not in source and "google_cloud_tasks" not in source


def test_FR_AGT_14e_no_model_id_and_no_secret_in_the_new_tests(repo_root: pathlib.Path) -> None:
    lint, scan = _script(repo_root, "lint_model_ids"), _script(repo_root, "secret_scan")
    known = lint._configured_model_ids(repo_root)
    for relative in (ROUTE_SRC, *NEW_TESTS):
        path = repo_root / relative
        assert path.is_file(), relative
        text = path.read_text(encoding="utf-8")
        found = set(lint.FAMILY_PATTERN.findall(text)) | {m for m in known if m in text}
        assert not found, f"{relative}: a model id outside config/ and packages/providers/ (PL-01): {sorted(found)}"
        assert scan.scan_file(str(path)) == [], f"{relative}: looks like a secret"
