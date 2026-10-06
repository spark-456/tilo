"""FR-AGT-14 (PRD 6.3 Cloud Scheduler, 8.6): the Terraform half of scheduled runs. A PR only: the user applies it.

Design (docs/open-questions.md will carry the BQ): ONE Cloud Scheduler job, not one per user schedule.
`tilo-schedule-tick`
runs every minute (the Scheduler floor) and POSTs `/internal/schedules/tick` on tilo-harness with an OIDC token for a
new
service account `tilo-schedule-scheduler`, which holds `run.invoker` on harness only and no other IAM. The tick reads
due
schedules from the store.

Static checks (no terraform binary, no network, no credentials, nothing is planned or applied), in the style of
test_NFR_27_cost_alert_terraform.py. The planned IAM is pinned by `infra/envs/dev/tests/schedule_tick.tftest.hcl` and by
the deliberate change to the harness invoker list in `cloud_run.tftest.hcl`.

  * exactly one `google_service_account` with account_id `tilo-schedule-scheduler`;
  * exactly one `google_cloud_scheduler_job` named `tilo-schedule-tick`: no for_each or count (one job, not one per
    user),
    `* * * * *`, POST, OIDC (not OAuth), path `/internal/schedules/tick` with no query and no body, `retry_count = 1`;
  * that service account appears in no project-level IAM resource, and in the Cloud Run `extra_invokers` map exactly
    once,
    for the harness service;
  * infra/ACCESS.md names the account, the job and the route.

Ambiguity resolved (the brief fixes `UTC`; the gmail jobs write `Etc/UTC`): either spelling of UTC is accepted.
"""

from __future__ import annotations

import pathlib
import re

SA_ACCOUNT_ID = "tilo-schedule-scheduler"
JOB_NAME = "tilo-schedule-tick"
ROUTE = "/internal/schedules/tick"
# How the SA may be referred to in Terraform: a literal, or any resource/module reference named after the schedule SA.
SA_REF = re.compile(
    r"tilo-schedule-scheduler|google_service_account\.schedule_(?:scheduler|tick)\w*|module\.schedule_tick\b"
)


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _braced(text: str, head: re.Match[str]) -> str:
    depth, i = 1, head.end()
    while depth and i < len(text):
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        i += 1
    return text[head.end() : i - 1]


def _resources(repo_root: pathlib.Path, resource_type: str) -> list[tuple[pathlib.Path, str, str]]:
    found = []
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for head in re.finditer(rf'^resource\s+"{re.escape(resource_type)}"\s+"([^"]+)"\s*\{{', text, re.M):
            found.append((path, head.group(1), _braced(text, head)))
    return found


def _sibling_text(path: pathlib.Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(path.parent.glob("*.tf")))


def _the_job(repo_root: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    jobs = [j for j in _resources(repo_root, "google_cloud_scheduler_job") if re.search(rf'"{JOB_NAME}"', j[2])]
    assert len(jobs) == 1, (
        f"FR-AGT-14: expected exactly one google_cloud_scheduler_job named {JOB_NAME}, found {len(jobs)}"
    )
    return jobs[0]


def test_FR_AGT_14_the_schedule_scheduler_service_account_exists_once(repo_root):
    accounts = [
        a
        for a in _resources(repo_root, "google_service_account")
        if re.search(rf'account_id\s*=\s*"{SA_ACCOUNT_ID}"', a[2])
    ]
    assert len(accounts) == 1, f"FR-AGT-14: expected one service account {SA_ACCOUNT_ID}, found {len(accounts)}"


def test_FR_AGT_14_one_scheduler_job_ticks_every_minute_and_is_not_one_job_per_user(repo_root):
    path, _name, body = _the_job(repo_root)
    assert not re.search(r"^\s*(for_each|count)\s*=", body, re.M), (
        "FR-AGT-14: one job for all schedules, never one per user"
    )
    assert re.search(rf'name\s*=\s*"{JOB_NAME}"', body)
    module_text = _sibling_text(path)
    assert re.search(r'schedule\s*=\s*"\* \* \* \* \*"', body) or re.search(
        r'variable\s+"\w*schedule\w*"\s*\{[^}]*default\s*=\s*"\* \* \* \* \*"', module_text, re.S
    ), "FR-AGT-14: the tick runs every minute (`* * * * *`)"
    assert re.search(r'time_zone\s*=\s*"(Etc/)?UTC"', body)


def test_FR_AGT_14_the_job_posts_the_tick_path_with_oidc_retry_one_and_no_body_or_query(repo_root):
    path, _name, body = _the_job(repo_root)
    assert re.search(r'http_method\s*=\s*"POST"', body)
    assert re.search(r"oidc_token\s*\{", body) and not re.search(r"oauth_token\s*\{", body), (
        "OIDC, never an OAuth token"
    )
    assert re.search(r"retry_count\s*=\s*1\b", body), "FR-AGT-14: retry_count 1 (the next minute is the real retry)"
    assert not re.search(r"^\s*body\s*=", body, re.M), "the tick takes no body"
    assert not re.search(r"^\s*headers\s*=", body, re.M)
    assert ROUTE in body or ROUTE in _sibling_text(path), f"FR-AGT-14: the job targets {ROUTE}"
    uri = re.search(r"\buri\s*=\s*(.+)", body)
    assert uri and "?" not in uri.group(1), "FR-AGT-14: no query string on the tick URI"


def test_FR_AGT_14_the_job_authenticates_as_the_schedule_scheduler_and_for_the_harness_audience(repo_root):
    path, _name, body = _the_job(repo_root)
    oidc = re.search(r"oidc_token\s*\{(.*?)\}", body, re.S)
    assert oidc, "FR-AGT-14: the job needs an oidc_token block"
    sa = re.search(r"service_account_email\s*=\s*(.+)", oidc.group(1))
    assert sa and not re.search(r"gmail|tasks_invoker|tasks-invoker", sa.group(1)), (
        "FR-AGT-14: the job must not borrow the Gmail scheduler or the Cloud Tasks identity"
    )
    assert re.search(r"audience\s*=", oidc.group(1)), "FR-AGT-14: set the OIDC audience to the harness URL"
    audience = re.search(r"audience\s*=\s*(\S+)", oidc.group(1)).group(1)
    uri = re.search(r"\buri\s*=\s*\"(.+)\"", body)
    assert uri and uri.group(1).startswith(f"${{{audience}}}"), (
        "FR-AGT-14: the OIDC audience is the base URL the job calls (the uri is that plus the tick path)"
    )


def test_FR_AGT_14_the_schedule_scheduler_holds_no_project_level_role(repo_root):
    for kind in ("google_project_iam_member", "google_project_iam_binding", "google_project_iam_custom_role"):
        for path, name, body in _resources(repo_root, kind):
            assert not SA_REF.search(body), (
                f"FR-AGT-14: {path.name}:{kind}.{name} grants something to the schedule scheduler"
            )
    for kind in ("google_service_account_iam_member", "google_service_account_iam_binding"):
        for path, name, body in _resources(repo_root, kind):
            assert not (SA_REF.search(body) and "serviceAccountUser" in body), (
                f"FR-AGT-14: {path.name}:{name} lets something act as the schedule scheduler or vice versa"
            )


def test_FR_AGT_14_the_only_invoker_binding_for_the_schedule_scheduler_is_harness(repo_root):
    entries: list[tuple[str, str, pathlib.Path]] = []
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'\{\s*service\s*=\s*"([\w-]+)"\s*member\s*=\s*"([^"]*)"\s*\}', text):
            if SA_REF.search(m.group(2)):
                entries.append((m.group(1), m.group(2), path))
    assert len(entries) == 1, (
        f"FR-AGT-14: expected one run.invoker entry for the schedule scheduler, found {len(entries)}"
    )
    assert entries[0][0] == "harness", "FR-AGT-14: run.invoker on harness only (never api, channels, connectors, ...)"


def test_FR_AGT_14_access_doc_names_the_account_the_job_and_the_route(repo_root):
    access = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    for needle in (SA_ACCOUNT_ID, JOB_NAME, ROUTE):
        assert needle in access, f"FR-AGT-14: infra/ACCESS.md must mention {needle}"
    rows = [line for line in access.splitlines() if SA_ACCOUNT_ID in line and line.lstrip().startswith("|")]
    assert any("run.invoker" in r and "harness" in r for r in rows), (
        "FR-AGT-14: an ACCESS.md row says tilo-schedule-scheduler holds run.invoker on harness"
    )


def test_FR_AGT_14_nothing_applies_itself(repo_root):
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        if JOB_NAME in text or SA_ACCOUNT_ID in text:
            assert "local-exec" not in text and "provisioner" not in text, f"{path.name}: nothing may apply itself"
