"""EFF-05c-lite: hardening of the nightly eval job (PR #465 review follow-ups). Static checks; no terraform binary.

* (1) a failure alert for the nightly Cloud Run job in the monitoring module, on its email channel;
* (2) an exhaustive Terraform check of every IAM grant that names an eval account (`tilo-eval-scheduler`,
  `tilo-eval-runner`), by resource reference, member literal or `local.*` alias: the scheduler holds only
  `roles/run.invoker` on the one job, the runner nothing; no public member on the job; no secret volume or env; cpu at
  most 1, memory at most 1Gi; the image comes from the project's own Artifact Registry repository. The checker is run on
  the real tree (clean) and on injected mutants (each must be reported);
* (3) credential-file filters in both Docker ignore files; (4) a keep-last-N cleanup policy scoped to the evals
  package; (5) a `just tf-validate` recipe, named in docs/deploy-dev.md before the apply.
"""

from __future__ import annotations

import pathlib
import re
import shutil

import pytest
import test_EFF_05_nightly_scheduler_terraform as pinned

INFRA_DEV = "infra/envs/dev"
IMAGE = re.compile(
    r"^(?:\$\{var\.region\}|asia-southeast1)-docker\.pkg\.dev/\$\{var\.project_id\}/tilo/evals(?::[\w.-]+|@sha256:[0-9a-f]{64})?$"
)
PUBLIC = re.compile(r"allUsers|allAuthenticatedUsers")
SECRETISH = re.compile(r"\b(?:volumes|volume_mounts|secret|secret_key_ref|value_source)\b\s*[={]")


def _code(body: str) -> str:
    return re.sub(r"(?m)^[ \t]*(?:#|//).*$", "", body)


def _local_values(blocks: list[pinned.Block]) -> dict[str, str]:
    values: dict[str, str] = {}
    for b in (x for x in blocks if x.kind == "locals"):
        for m in re.finditer(r"^[ \t]*(\w+)[ \t]*=", b.body, re.M):
            if pinned._depth_at(b.body, m.start()) == 0:
                values[m.group(1)] = _code(b.attr(m.group(1)) or "")
    return values


def _expand(text: str, values: dict[str, str]) -> str:
    for _ in range(4):
        text = re.sub(r"\blocal\.(\w+)", lambda m: values.get(m.group(1), m.group(0)), text)
    return text


def _identities(blocks: list[pinned.Block], values: dict[str, str]) -> dict[str, re.Pattern[str]]:
    """Per eval service account: its resource reference, its account id, or a local that holds either."""
    found: dict[str, re.Pattern[str]] = {}
    for sa in pinned._eval_service_accounts(blocks):
        parts = [rf"google_service_account\.{re.escape(sa.name)}\b"]
        if sa.attr("account_id"):
            parts.append(re.escape((sa.attr("account_id") or "").strip('"')))
        base = re.compile("|".join(parts))
        aliases = [k for k, v in values.items() if base.search(v)]
        parts += [rf"local\.{re.escape(k)}\b" for k in aliases]
        found[sa.name] = re.compile("|".join(parts))
    return found


def _violations(root: pathlib.Path) -> list[str]:
    blocks = pinned._blocks(root)
    values = _local_values(blocks)
    idents = _identities(blocks, values)
    scheduler = pinned._scheduler_sa(root).name
    _kind, target = pinned._target(blocks, pinned._scheduler_job(root))
    out: list[str] = []

    for b in blocks:
        if b.kind in ("locals", "variable") or (b.kind == "resource" and b.labels[0] == "google_service_account"):
            continue
        code, rtype = _code(b.body), b.labels[0] if b.kind == "resource" else b.kind
        for sa, pattern in idents.items():
            if not pattern.search(code):
                continue
            if sa == scheduler and rtype in ("google_cloud_scheduler_job", "google_cloud_run_v2_job_iam_member"):
                continue
            hits = [ln for ln in code.splitlines() if pattern.search(ln)]
            if (
                sa != scheduler
                and rtype == "google_cloud_run_v2_job"
                and len(hits) == 1
                and "service_account" in hits[0]
            ):
                continue
            out.append(
                f"{rtype}.{b.name} names {sa}: only the scheduler job, the one invoker grant and the runtime account"
            )

    jobs = [b for b in pinned._of_type(blocks, "google_cloud_run_v2_job") if b.name == target]
    grants = [
        b
        for b in blocks
        if b.kind == "resource"
        and "_iam_" in b.labels[0]
        and re.search(rf"google_cloud_run_v2_job\.{re.escape(target)}\b|tilo-eval-nightly", _code(b.body))
    ]
    ok = [g for g in grants if g.labels[0] == "google_cloud_run_v2_job_iam_member"]
    if len(grants) != 1 or len(ok) != 1:
        out.append(f"the job must have exactly one IAM grant (a job_iam_member), found {[g.labels[0] for g in grants]}")
    for g in grants:
        text = _expand(_code(g.body), values)
        if PUBLIC.search(text):
            out.append(f"{g.name}: a public member on the job")
        if (g.attr("role") or "").strip() != '"roles/run.invoker"':
            out.append(f"{g.name}: role {g.attr('role')} on the job, only roles/run.invoker")
        member = _expand(g.attr("member") or "", values)
        if not idents[scheduler].search(member) or "serviceAccount:" not in member:
            out.append(f"{g.name}: the member is {member!r}, only the eval scheduler account")

    for job in jobs:
        code = _code(job.body)
        if SECRETISH.search(code):
            out.append("the job mounts or reads a secret (volumes, secret, secret_key_ref, value_source)")
        cpus, mems = re.findall(r'\bcpu\s*=\s*"([^"]+)"', code), re.findall(r'\bmemory\s*=\s*"([^"]+)"', code)
        if not cpus or not mems or any(_cpu(c) > 1 for c in cpus) or any(_mem(m) > 1024 for m in mems):
            out.append(f"the job asks for cpu {cpus} / memory {mems}: literal, at most 1 and 1Gi")
        images = [_expand(i.strip(), values).strip('"') for i in re.findall(r"^\s*image\s*=\s*(.+)$", code, re.M)]
        if not images or not all(IMAGE.match(i) for i in images):
            out.append(f"job image {images} is not the project's Artifact Registry tilo/evals package")
    if not jobs:
        out.append("the target job is missing")
    return out


def _cpu(text: str) -> float:
    return float(text[:-1]) / 1000 if text.endswith("m") else float(text)


def _mem(text: str) -> float:
    """Mebibytes; unparsable counts as huge."""
    m = re.fullmatch(r"(\d+)(Ki|Mi|Gi|K|M|G)", text)
    if not m:
        return float("inf")
    return (
        int(m.group(1))
        * {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024, "K": 1e3 / 2**20, "M": 1e6 / 2**20, "G": 1e9 / 2**20}[m.group(2)]
    )


def _copy_tf(root: pathlib.Path, dest: pathlib.Path) -> pathlib.Path:
    def skip(directory: str, names: list[str]) -> list[str]:
        return [
            n
            for n in names
            if n == ".terraform" or (not n.endswith(".tf") and not (pathlib.Path(directory) / n).is_dir())
        ]

    shutil.copytree(root / "infra", dest / "infra", ignore=skip)
    return dest / INFRA_DEV / "eval_nightly.tf"


def _res(kind: str, role: str, member: str, **extra: str) -> str:
    """A one-grant resource; `extra` are more attributes (an IAM target such as bucket or name)."""
    attrs = "".join(f"  {k} = {v}\n" for k, v in extra.items())
    return f'\nresource "{kind}" "m" {{\n{attrs}  role = "{role}"\n  member = {member}\n}}\n'


def _sa(ref: str) -> str:
    return f'"serviceAccount:${{google_service_account.{ref}.email}}"'


def _literal(account: str) -> str:
    return f'"serviceAccount:tilo-eval-{account}@essential-wares-510320-f0.iam.gserviceaccount.com"'


PRJ = {"project": "var.project_id"}
JOB = {"project": "var.project_id", "location": "var.region", "name": "google_cloud_run_v2_job.eval_nightly.name"}
JOB_IAM = "google_cloud_run_v2_job_iam_member"
GOOGLE_IMAGE = "${var.region}-docker.pkg.dev/${var.project_id}/tilo/evals:latest"
VOLUME = '      volumes {\n        name = "s"\n        secret {\n          secret = "x"\n        }\n      }\n'
ENV = '        env {\n          name = "K"\n          value_source {\n            secret_key_ref {\n'
ENV += '              secret = "x"\n            }\n          }\n        }\n'
MODULE = '\nmodule "x" {\n  source = "../../modules/service"\n  extra_invokers = [google_service_account.eval_runner.email]\n}\n'  # noqa: E501
POLICY = '\nresource "google_cloud_run_v2_job_iam_policy" "m" {\n  name = google_cloud_run_v2_job.eval_nightly.name\n  policy_data = "{}"\n}\n'  # noqa: E501
MUTANTS: dict[str, tuple[str, str]] = {
    # id: (text to replace in eval_nightly.tf, or "" to append, replacement or addition)
    "runner_project_aiplatform": (
        "",
        _res("google_project_iam_member", "roles/aiplatform.user", _sa("eval_runner"), **PRJ),
    ),
    "runner_secret_accessor": (
        "",
        _res(
            "google_secret_manager_secret_iam_member",
            "roles/secretmanager.secretAccessor",
            _sa("eval_runner"),
            secret_id='"s"',
        ),
    ),
    "scheduler_literal_project_run_admin": (
        "",
        _res("google_project_iam_member", "roles/run.admin", _literal("scheduler"), **PRJ),
    ),
    "runner_literal_bucket": (
        "",
        _res("google_storage_bucket_iam_member", "roles/storage.admin", _literal("runner"), bucket='"b"'),
    ),
    "runner_local_alias_editor": (
        "",
        "\nlocals {\n  r = google_service_account.eval_runner.email\n}\n"
        + _res("google_project_iam_member", "roles/editor", '"serviceAccount:${local.r}"', **PRJ),
    ),
    "runner_act_as": (
        "",
        _res(
            "google_service_account_iam_member",
            "roles/iam.serviceAccountUser",
            '"user:a@example.com"',
            service_account_id="google_service_account.eval_runner.name",
        ),
    ),
    "runner_module_invoker": ("", MODULE),
    "job_member_local_allusers": (
        "",
        '\nlocals {\n  pub = "allUsers"\n}\n' + _res(JOB_IAM, "roles/run.invoker", "local.pub", **JOB),
    ),
    "job_all_authenticated_literal": ("", _res(JOB_IAM, "roles/run.invoker", '"allAuthenticatedUsers"', **JOB)),
    "scheduler_extra_developer_on_job": ("", _res(JOB_IAM, "roles/run.developer", _sa("eval_scheduler"), **JOB)),
    "other_member_admin_on_job": ("", _res(JOB_IAM, "roles/run.admin", '"user:a@example.com"', **JOB)),
    "job_iam_policy": ("", POLICY),
    "secret_volume": ("      containers {", VOLUME + "      containers {"),
    "secret_env": ("        resources {", ENV + "        resources {"),
    "cpu_8": ('cpu    = "1"', 'cpu    = "8"'),
    "memory_32gi": ('memory = "1Gi"', 'memory = "32Gi"'),
    "image_docker_io": (f'"{GOOGLE_IMAGE}"', '"docker.io/library/python:3.12"'),
    "image_other_project": ("${var.project_id}/tilo/evals:latest", "attacker/tilo/evals:latest"),
    "image_other_repository": ("/tilo/evals:latest", "/other/evals:latest"),
}


def test_EFF_05c_the_real_tree_has_no_grant_or_job_violation(repo_root):
    assert _violations(repo_root) == []


@pytest.mark.parametrize("mutant", sorted(MUTANTS))
def test_EFF_05c_every_injected_runner_scheduler_or_job_mutant_is_reported(repo_root, tmp_path, mutant):
    old, new = MUTANTS[mutant]
    path = _copy_tf(repo_root, tmp_path)
    text = path.read_text(encoding="utf-8")
    if old:
        assert old in text, f"mutant {mutant} no longer applies"
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    else:
        path.write_text(text + new, encoding="utf-8")
    assert _violations(tmp_path), f"EFF-05c: mutant {mutant} survived the grant check"


# --- (1) failure alert ---------------------------------------------------------------------------------------


def test_EFF_05c_failed_nightly_executions_raise_an_email_alert(repo_root):
    module = (repo_root / "infra/modules/monitoring/main.tf").read_text(encoding="utf-8")
    policy = next(
        (
            b
            for b in pinned._blocks(repo_root)
            if b.labels[:1] == ["google_monitoring_alert_policy"] and "completed_execution_count" in b.body
        ),
        None,
    )
    assert policy is not None, "EFF-05c: no alert policy on run.googleapis.com/job/completed_execution_count"
    assert "infra/modules/monitoring" in policy.path.as_posix() and module
    body = _code(policy.body)
    assert 'resource.type=\\"cloud_run_job\\"' in body and re.search(r'metric\.labels\.result=\\"failed\\"', body)
    assert "var.eval_nightly_job_name" in body, "the policy watches the job named by the module variable"
    assert re.search(r"notification_channels\s*=\s*\[google_monitoring_notification_channel\.email\.id\]", body)
    assert re.search(r"threshold_value\s*=\s*0\b", body) and "EVALUATION_MISSING_DATA_INACTIVE" in body
    env = (repo_root / INFRA_DEV / "main.tf").read_text(encoding="utf-8")
    assert re.search(r"eval_nightly_job_name\s*=\s*google_cloud_run_v2_job\.eval_nightly\.name", env), (
        "the env passes the real job name to module.monitoring"
    )
    assert (repo_root / INFRA_DEV / "tests/eval_nightly_alert.tftest.hcl").is_file(), "plan-time pin for the alert"


# --- (3) docker ignore filters -------------------------------------------------------------------------------


def _ignored(lines: list[str], path: str) -> bool:
    ignored = False
    for line in lines:
        negate = line.startswith("!")
        pattern = line.lstrip("!").strip("/")
        regex = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*", "[^/]*")
        if re.fullmatch(regex, path) or re.fullmatch(regex + "/.*", path):
            ignored = not negate
    return ignored


@pytest.mark.parametrize("ignore_file", [".dockerignore", "evals/Dockerfile.dockerignore"])
def test_EFF_05c_docker_ignore_files_filter_credential_files_at_any_depth(repo_root, ignore_file):
    lines = [
        ln.strip()
        for ln in (repo_root / ignore_file).read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    for name in (
        "client_secret_123.apps.googleusercontent.com.json",
        "token.json",
        "credentials.json",
        "k.pem",
        ".env",
    ):
        for path in (name, f"services/api/{name}", f"packages/x/y/{name}"):
            assert _ignored(lines, path), f"EFF-05c: {ignore_file} must keep {path} out of the build context"
    assert not _ignored(lines, "services/api/pyproject.toml"), "the workspace files stay in"


# --- (4) Artifact Registry cleanup ---------------------------------------------------------------------------


def test_EFF_05c_artifact_registry_keeps_the_last_n_evals_images_and_touches_nothing_else(repo_root):
    repo = next(
        b
        for b in pinned._of_type(pinned._blocks(repo_root), "google_artifact_registry_repository")
        if b.name == "containers"
    )
    policies = repo.sub("cleanup_policies")
    assert len(policies) == 2, "one KEEP (most recent N) and one DELETE for the evals package"
    actions = sorted(re.search(r'action\s*=\s*"(\w+)"', p).group(1) for p in policies)
    assert actions == ["DELETE", "KEEP"]
    for p in policies:
        assert re.findall(r"package_name_prefixes\s*=\s*(\[[^\]]*\])", p) == ['["evals"]'], (
            "scoped to the evals package"
        )
        if '"KEEP"' in p:
            assert 2 <= int(re.search(r"keep_count\s*=\s*(\d+)", p).group(1)) <= 20
        else:
            assert re.search(r'older_than\s*=\s*"\d+s"', p), "never delete a fresh build"


# --- (5) terraform validate recipe ---------------------------------------------------------------------------


def test_EFF_05c_just_tf_validate_runs_init_without_backend_then_validate_and_the_runbook_names_it(repo_root):
    justfile = (repo_root / "justfile").read_text(encoding="utf-8")
    recipe = re.search(r"(?m)^tf-validate:\n((?:    .+\n?)+)", justfile)
    assert recipe, "EFF-05c: the justfile needs a `tf-validate` recipe"
    lines = [ln.strip() for ln in recipe.group(1).splitlines()]
    assert lines == [
        "terraform -chdir=infra/envs/dev init -backend=false -input=false",
        "terraform -chdir=infra/envs/dev validate",
    ]
    docs = (repo_root / "docs/deploy-dev.md").read_text(encoding="utf-8")
    section = docs[docs.index("## Nightly eval smoke") :]
    assert "just tf-validate" in section
    assert section.index("just tf-validate") < section.index("then plan and apply"), "validate comes before the apply"
