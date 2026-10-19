"""EFF-05 (PRD 6.6; user decision relayed 2026-10-06): the nightly eval smoke is triggered by Cloud Scheduler in
tilo-dev, not by a GitHub Actions cron. Static checks on the Terraform and the workflows; nothing is planned or
applied (the user runs the apply), no terraform binary, no network, no credentials.

The target may be either of the two shapes the user allowed, and the checks accept both but pin their own rules:
  * a Cloud Run JOB (`google_cloud_run_v2_job`), started by Scheduler calling the Cloud Run Admin API
    `https://run.googleapis.com/v2/projects/<p>/locations/<region>/jobs/<name>:run`. That is a call to a Google API,
    so Scheduler authenticates with an OAuth access token (`oauth_token`); OIDC is for calls to a service you own.
  * an authenticated HTTP endpoint on a Cloud Run SERVICE (the gmail renew/poll pattern, `module.service.uris[...]`),
    with `oidc_token`.
Either way: one dedicated service account for Scheduler that holds `roles/run.invoker` on that one job or service and
nothing else; no project-level role; no allUsers; region asia-southeast1; at most one running copy; nothing secret.

Rules pinned (each is a test below):
  * exactly one `google_cloud_scheduler_job` for the eval smoke; a daily cron; a time zone; `region` = var.region (whose
    default is asia-southeast1) or the literal; retries at most 1;
  * auth matches the target (see above), never both, never neither; the token's `service_account_email` is the
    dedicated eval Scheduler service account (account id contains "eval"), not the gmail, tasks, cloudbuild or runtime
    accounts, and that account is used for nothing but this trigger and its invoker grant;
  * `roles/run.invoker` for that account exists exactly once, on the target job or service (resource-scoped, a
    `google_cloud_run_v2_job_iam_*` / `_service_iam_*` resource or a `module.service` `extra_invokers` entry), and the
    account holds no other role anywhere (so no `roles/iam.serviceAccountUser` either: if Scheduler turns out to need
    it for a job, stop and report it, do not add it quietly); no `roles/run.invoker` in any `google_project_iam_*`
    resource, in `service_project_roles`, `project_bindings` or `deployer_project_roles`;
  * a Cloud Run job's runtime service account is a different account from Scheduler's;
  * scale: a job has `parallelism = 1`, `task_count = 1`, `max_retries` 0 or 1 and a timeout of at most 3600 s; a
    service target must be scale-to-zero with `max_instance_count = 1` (tilo-harness has 3, so a harness endpoint
    needs its own decision);
  * the job runs `python -m tilo_evals nightly`; no env var of the live switch, no credentials file, no secret
    reference, no `google_secret_manager_secret_version`, no `google_service_account_key`, no key-like literal;
  * no GitHub Actions workflow with a `schedule` trigger runs or names the evals; `infra/ACCESS.md` lists the identity.

Ambiguities resolved (PRD gives only "Cloud Scheduler"; listed in the ticket report to become BQ rows): the name rule
("eval" in the resource name or account id), daily rather than weekday-only, Scheduler retries at most 1, job timeout at
most 3600 s, `max_retries` at most 1, and "no secrets at all" for the replay job (a live run is a later, separate
decision of the user's).
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

DAILY_CRON = re.compile(r"^\s*\d{1,2}\s+\d{1,2}\s+\*\s+\*\s+\*\s*$")
KEY_LIKE = re.compile(
    r"AIza[0-9A-Za-z_-]{20,}|ghp_[0-9A-Za-z]{20,}|sk-[0-9A-Za-z]{20,}|-----BEGIN|Bearer\s+[0-9A-Za-z._-]{10,}"
)
PROJECT_IAM = ("google_project_iam_member", "google_project_iam_binding", "google_project_iam_policy")
RUN_IAM = (
    "google_cloud_run_v2_job_iam_member",
    "google_cloud_run_v2_job_iam_binding",
    "google_cloud_run_v2_service_iam_member",
    "google_cloud_run_v2_service_iam_binding",
)


# --- a tiny HCL reader: enough for top-level blocks, nested blocks and attributes ----------------------------


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _match(text: str, open_at: int) -> int:
    """Index just past the bracket that closes the one at `open_at` (strings are skipped)."""
    opener = text[open_at]
    closer = {"{": "}", "(": ")", "[": "]"}[opener]
    depth, i, in_string = 0, open_at, False
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "#" or text.startswith("//", i):
            i = text.find("\n", i)
            if i == -1:
                break
        elif c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return len(text)


class Block:
    def __init__(self, path: pathlib.Path, kind: str, labels: list[str], body: str) -> None:
        self.path, self.kind, self.labels, self.body = path, kind, labels, body

    @property
    def name(self) -> str:
        return self.labels[-1] if self.labels else ""

    def attr(self, key: str) -> str | None:
        """The text of a top-level attribute of this block (one line, or a bracketed value), else None."""
        for m in re.finditer(rf"^[ \t]*{re.escape(key)}[ \t]*=[ \t]*", self.body, re.M):
            if _depth_at(self.body, m.start()) != 0:
                continue
            start = m.end()
            if start < len(self.body) and self.body[start] in "{[(":
                return self.body[start : _match(self.body, start)]
            end = self.body.find("\n", start)
            return self.body[start : end if end != -1 else len(self.body)].strip()
        return None

    def sub(self, name: str) -> list[str]:
        """Bodies of nested `name { ... }` blocks at depth 0 of this block."""
        out = []
        for m in re.finditer(rf"^[ \t]*{re.escape(name)}[ \t]*\{{", self.body, re.M):
            if _depth_at(self.body, m.start()) == 0:
                end = _match(self.body, m.end() - 1)
                out.append(self.body[m.end() : end - 1])
        return out


def _depth_at(text: str, index: int) -> int:
    depth, in_string, i = 0, False, 0
    while i < index:
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "#":
            i = text.find("\n", i)
            if i == -1:
                break
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        i += 1
    return depth


def _blocks(repo_root: pathlib.Path) -> list[Block]:
    found: list[Block] = []
    head = re.compile(r'^(resource|module|variable|locals|data|output)((?:[ \t]+"[^"]+")*)[ \t]*\{', re.M)
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for m in head.finditer(text):
            end = _match(text, m.end() - 1)
            labels = re.findall(r'"([^"]+)"', m.group(2))
            found.append(Block(path, m.group(1), labels, text[m.end() : end - 1]))
    return found


def _of_type(blocks: list[Block], *types: str) -> list[Block]:
    return [b for b in blocks if b.kind == "resource" and b.labels[0] in types]


def _eval_jobs(blocks: list[Block]) -> list[Block]:
    jobs = _of_type(blocks, "google_cloud_scheduler_job")
    return [b for b in jobs if "eval" in b.name.lower() or "eval" in (b.attr("name") or "").lower()]


def _scheduler_job(repo_root: pathlib.Path) -> Block:
    jobs = _eval_jobs(_blocks(repo_root))
    assert len(jobs) == 1, (
        f"EFF-05: exactly one google_cloud_scheduler_job for the eval smoke must exist under infra/ (its resource name "
        f"or `name` contains 'eval'); found {[j.name for j in jobs]}"
    )
    return jobs[0]


def _resolve(blocks: list[Block], expr: str | None) -> str | None:
    """A quoted literal as-is; `var.x` -> the default of a variable named x anywhere under infra/; else None."""
    if expr is None:
        return None
    literal = re.fullmatch(r'"([^"$]*)"', expr.strip())
    if literal:
        return literal.group(1)
    ref = re.fullmatch(r"var\.(\w+)", expr.strip())
    if ref:
        for b in blocks:
            if b.kind == "variable" and b.name == ref.group(1):
                default = b.attr("default")
                lit = re.fullmatch(r'"([^"$]*)"', (default or "").strip())
                if lit:
                    return lit.group(1)
    return None


def _through_modules(blocks: list[Block], var_name: str) -> str:
    """What a module call passes for `var_name` (the first module that passes it), or ''."""
    for module in (b for b in blocks if b.kind == "module"):
        passed = module.attr(var_name)
        if passed:
            return passed
    return ""


def _target(blocks: list[Block], job: Block) -> tuple[str, str]:
    """('job' | 'service', the Cloud Run job resource name or the service key) from the scheduler job's uri."""
    http = job.sub("http_target")
    assert len(http) == 1, "EFF-05: the eval scheduler job needs exactly one http_target block"
    uri = Block(job.path, "http_target", [], http[0]).attr("uri") or ""
    for _ in range(2):  # a hop through a module variable: `var.target_uri` or `${var.target_uri}` inside a string
        bare = re.fullmatch(r"var\.(\w+)", uri.strip())
        if bare:
            uri = _through_modules(blocks, bare.group(1)) or uri
        uri = re.sub(r"\$\{var\.(\w+)\}", lambda m: _through_modules(blocks, m.group(1)) or m.group(0), uri)
    if "run.googleapis.com" in uri and "/jobs/" in uri and uri.rstrip('"').endswith(":run"):
        ref = re.search(r"google_cloud_run_v2_job\.(\w+)", uri)
        literal = re.search(r"/jobs/([\w-]+):run", uri)
        return "job", (ref.group(1) if ref else literal.group(1) if literal else "")
    service = re.search(r'uris\["([\w-]+)"\]|google_cloud_run_v2_service\.\w+\["([\w-]+)"\]', uri)
    assert service and "run.googleapis.com" not in uri, (
        "EFF-05: the eval scheduler job must call a Cloud Run job's `:run` URL on run.googleapis.com or an endpoint "
        f"on one of our Cloud Run services (module.service.uris[...]); its uri resolves to {uri!r}"
    )
    return "service", next(g for g in service.groups() if g)


def _http_block(job: Block) -> Block:
    return Block(job.path, "http_target", [], job.sub("http_target")[0])


def _eval_service_accounts(blocks: list[Block]) -> list[Block]:
    out = []
    for b in _of_type(blocks, "google_service_account"):
        if "eval" in b.name.lower() or "eval" in (b.attr("account_id") or "").lower():
            out.append(b)
    return out


def _scheduler_sa(repo_root: pathlib.Path) -> Block:
    """The dedicated eval Scheduler service account resource the job authenticates as (resolved through one module)."""
    blocks = _blocks(repo_root)
    job = _scheduler_job(repo_root)
    http = _http_block(job)
    auth = (http.sub("oidc_token") or http.sub("oauth_token") or [""])[0]
    email = Block(job.path, "auth", [], auth).attr("service_account_email") or ""
    accounts = {b.name: b for b in _eval_service_accounts(blocks)}
    assert accounts, (
        "EFF-05: a dedicated google_service_account for the eval Scheduler trigger (account id with 'eval') is missing"
    )
    direct = re.search(r"google_service_account\.(\w+)", email)
    if direct:
        assert direct.group(1) in accounts, (
            f"EFF-05: Scheduler must use the dedicated eval account, not {direct.group(1)!r}"
        )
        return accounts[direct.group(1)]
    var = re.fullmatch(r"var\.(\w+)", email.strip())
    assert var, f"EFF-05: the scheduler token's service_account_email must reference a service account, got {email!r}"
    for module in (b for b in blocks if b.kind == "module"):
        passed = module.attr(var.group(1)) or ""
        ref = re.search(r"google_service_account\.(\w+)", passed)
        if ref and ref.group(1) in accounts:
            return accounts[ref.group(1)]
    pytest.fail(f"EFF-05: no module call passes a dedicated eval service account as var.{var.group(1)}")


def _refs(blocks: list[Block], sa: Block) -> list[Block]:
    pattern = re.compile(rf"google_service_account\.{re.escape(sa.name)}\b")
    return [b for b in blocks if b is not sa and pattern.search(b.body)]


# --- the scheduler job ---------------------------------------------------------------------------------------


def test_EFF_05_one_scheduler_job_runs_the_eval_smoke_daily_in_asia_southeast1(repo_root):
    blocks = _blocks(repo_root)
    job = _scheduler_job(repo_root)

    schedule = _resolve(blocks, job.attr("schedule"))
    if schedule is None:  # the cron may be a module variable the env passes in; accept any literal cron near the job
        text = job.path.read_text(encoding="utf-8")
        schedule = next(iter(re.findall(r'"(\d{1,2} \d{1,2} \* \* \*)"', text)), None)
    assert schedule is not None, "EFF-05: the job's cron must resolve to a literal or a variable default"
    assert DAILY_CRON.match(schedule), f"EFF-05: 'nightly' means a daily cron like '0 19 * * *', got {schedule!r}"
    assert job.attr("time_zone"), "EFF-05: set time_zone explicitly (the gmail jobs use Etc/UTC)"

    region = job.attr("region") or ""
    assert region == "var.region" or region == '"asia-southeast1"', f"EFF-05: region must be var.region, got {region!r}"
    variables = [b for b in blocks if b.kind == "variable" and b.name == "region" and "envs/dev" in b.path.as_posix()]
    assert variables and '"asia-southeast1"' in (variables[0].attr("default") or ""), (
        "EFF-05: infra/envs/dev var.region must stay asia-southeast1 (PRD 6.5)"
    )

    retry = job.sub("retry_config")
    if retry:
        count = Block(job.path, "retry", [], retry[0]).attr("retry_count")
        assert count is not None and int(count) <= 1, f"EFF-05: Scheduler retry_count must be at most 1, got {count}"


def test_EFF_05_scheduler_authenticates_to_match_its_target_and_never_both_ways(repo_root):
    job = _scheduler_job(repo_root)
    kind, _name = _target(_blocks(repo_root), job)
    http = _http_block(job)
    oidc, oauth = http.sub("oidc_token"), http.sub("oauth_token")

    assert not (oidc and oauth), "EFF-05: oidc_token and oauth_token are mutually exclusive"
    if kind == "service":
        assert oidc, "EFF-05: an endpoint on our own Cloud Run service is called with an OIDC token"
        assert Block(job.path, "oidc", [], oidc[0]).attr("audience"), "EFF-05: the OIDC token needs an audience"
    else:
        assert oauth, "EFF-05: the Cloud Run Admin API (a Google API) needs an OAuth token, not OIDC, to run a job"
    assert http.attr("http_method") in ('"POST"', '"post"'), "EFF-05: the trigger is a POST"


def test_EFF_05_scheduler_uses_its_own_service_account_for_nothing_else(repo_root):
    blocks = _blocks(repo_root)
    sa = _scheduler_sa(repo_root)
    allowed = {"module", "locals", "output", "google_cloud_scheduler_job", *RUN_IAM}

    assert sa.attr("account_id") and "eval" in sa.attr("account_id").lower()
    for b in _refs(blocks, sa):
        kind = b.labels[0] if b.kind == "resource" else b.kind
        assert kind in allowed, (
            f"EFF-05: the eval Scheduler account may appear only in the scheduler job, a run.invoker grant on the "
            f"target, or the module call that passes it on; found it in {b.kind} {b.labels} ({b.path.name})"
        )
    for other in ("tilo-gmail-scheduler", "tilo-tasks-invoker", "tilo-cloudbuild", "tilo-gmail-push"):
        assert other not in (sa.attr("account_id") or ""), f"EFF-05: do not reuse {other}"


# --- IAM: invoker only on the target -------------------------------------------------------------------------


def _grants_for(blocks: list[Block], sa: Block) -> list[tuple[str, Block]]:
    """(role or 'run.invoker (extra_invokers)', block) for every IAM grant that names the eval Scheduler account."""
    pattern = re.compile(rf"google_service_account\.{re.escape(sa.name)}\b")
    grants: list[tuple[str, Block]] = []
    for b in blocks:
        if b.kind == "resource" and b.labels[0] in (
            *RUN_IAM,
            *PROJECT_IAM,
            "google_service_account_iam_member",
            "google_service_account_iam_binding",
            "google_storage_bucket_iam_member",
            "google_secret_manager_secret_iam_member",
            "google_pubsub_topic_iam_member",
            "google_kms_crypto_key_iam_member",
        ):
            if pattern.search(b.body):
                grants.append((b.attr("role") or "?", b))
        if b.kind == "module" and re.search(r"extra_invokers", b.body) and pattern.search(b.body):
            grants.append(("roles/run.invoker", b))
    return grants


def test_EFF_05_scheduler_account_holds_run_invoker_on_the_target_and_no_other_role(repo_root):
    blocks = _blocks(repo_root)
    sa = _scheduler_sa(repo_root)
    kind, target = _target(_blocks(repo_root), _scheduler_job(repo_root))

    grants = _grants_for(blocks, sa)

    assert len(grants) == 1, f"EFF-05: exactly one IAM grant for the eval Scheduler account, got {len(grants)}"
    role, block = grants[0]
    assert role.strip('"') == "roles/run.invoker", f"EFF-05: the only role is roles/run.invoker, got {role}"
    kinds = block.labels[0] if block.kind == "resource" else "module"
    assert kinds not in PROJECT_IAM, "EFF-05: no project-level invoker: scope the grant to the one job or service"
    if kind == "job":
        assert kinds in ("google_cloud_run_v2_job_iam_member", "google_cloud_run_v2_job_iam_binding"), (
            f"EFF-05: a job target takes a google_cloud_run_v2_job_iam_* grant, got {kinds}"
        )
        assert f"google_cloud_run_v2_job.{target}" in (block.attr("name") or ""), (
            "EFF-05: the invoker grant must name the same job Scheduler runs"
        )
        assert "allUsers" not in block.body and "allAuthenticatedUsers" not in block.body
    else:
        assert kinds in ("module", "google_cloud_run_v2_service_iam_member", "google_cloud_run_v2_service_iam_binding")
        assert f'"{target}"' in block.body or target in block.body, "EFF-05: the grant must name the target service"


def test_EFF_05_no_project_level_run_invoker_anywhere(repo_root):
    blocks = _blocks(repo_root)
    sa = _scheduler_sa(repo_root)

    for b in _of_type(blocks, *PROJECT_IAM):
        assert "run.invoker" not in b.body, f"EFF-05: {b.labels} in {b.path.name} grants run.invoker project-wide"
        assert not re.search(rf"google_service_account\.{re.escape(sa.name)}\b", b.body), (
            "EFF-05: the eval Scheduler account has no project-level role of any kind"
        )
    for b in blocks:
        if b.kind == "variable" and b.name == "deployer_project_roles":
            assert "run.invoker" not in b.body
        if b.kind == "locals":
            for key in ("service_project_roles", "project_bindings"):
                value = b.attr(key)
                if value is not None:
                    assert "run.invoker" not in value and "eval" not in value.lower(), (
                        f"EFF-05: locals.{key} must not carry the eval trigger or an invoker role"
                    )


def test_EFF_05_the_target_is_never_public(repo_root):
    blocks = _blocks(repo_root)
    kind, target = _target(_blocks(repo_root), _scheduler_job(repo_root))

    for b in _of_type(blocks, "google_cloud_run_v2_job_iam_member", "google_cloud_run_v2_job_iam_binding"):
        assert "allUsers" not in b.body and "allAuthenticatedUsers" not in b.body, (
            f"EFF-05: no public IAM on a Cloud Run job ({b.name})"
        )
    if kind == "service":
        services = next(
            (b.attr("cloud_run_services") for b in blocks if b.kind == "locals" and b.attr("cloud_run_services")), ""
        )
        entry = re.search(rf'"{re.escape(target)}"\s*=\s*\{{(.*?)\n    \}}', services or "", re.S)
        assert entry and re.search(r"public\s*=\s*false", entry.group(1)), (
            f"EFF-05: the target service {target!r} must be public = false (an authenticated endpoint)"
        )


# --- scale to zero, at most one copy -------------------------------------------------------------------------


def test_EFF_05_the_target_runs_at_most_one_copy_and_scales_to_zero(repo_root):
    blocks = _blocks(repo_root)
    kind, target = _target(_blocks(repo_root), _scheduler_job(repo_root))

    if kind == "job":
        jobs = [b for b in _of_type(blocks, "google_cloud_run_v2_job") if b.name == target]
        assert len(jobs) == 1, f"EFF-05: google_cloud_run_v2_job.{target} must be declared under infra/"
        job = jobs[0]
        job_template = Block(job.path, "template", [], job.sub("template")[0])
        assert job_template.attr("parallelism") == "1", "EFF-05: parallelism = 1"
        assert job_template.attr("task_count") == "1", "EFF-05: task_count = 1"
        task = Block(job.path, "task", [], job_template.sub("template")[0])
        assert task.attr("max_retries") in ("0", "1"), (
            "EFF-05: max_retries 0 or 1 (the idempotency key makes a retry safe)"
        )
        timeout = re.fullmatch(r'"(\d+)s"', (task.attr("timeout") or "").strip())
        assert timeout and int(timeout.group(1)) <= 3600, "EFF-05: set a task timeout of at most 3600s"
        assert job.attr("location") == "var.region", "EFF-05: the job lives in var.region"
    else:
        services = next(
            (b.attr("cloud_run_services") for b in blocks if b.kind == "locals" and b.attr("cloud_run_services")), ""
        )
        entry = re.search(rf'"{re.escape(target)}"\s*=\s*\{{(.*?)\n    \}}', services or "", re.S)
        assert entry, f"EFF-05: service {target!r} not found in cloud_run_services"
        assert re.search(r"min_instance_count\s*=\s*0\b", entry.group(1)), "EFF-05: scale to zero"
        assert re.search(r"max_instance_count\s*=\s*1\b", entry.group(1)), "EFF-05: max_instance_count = 1"


def test_EFF_05_a_job_runs_as_a_different_account_from_scheduler_and_runs_the_nightly_entrypoint(repo_root):
    blocks = _blocks(repo_root)
    kind, target = _target(_blocks(repo_root), _scheduler_job(repo_root))
    if kind != "job":
        pytest.skip("endpoint target: the entrypoint is the service's own route, pinned by its own ticket")
    sa = _scheduler_sa(repo_root)
    job = next(b for b in _of_type(blocks, "google_cloud_run_v2_job") if b.name == target)

    assert '"nightly"' in job.body and '"tilo_evals"' in job.body, (
        "EFF-05: the job's command/args must run `python -m tilo_evals nightly`"
    )
    runtime = re.search(r"service_account\s*=\s*(.+)", job.body)
    assert runtime, "EFF-05: the job names its own runtime service account (never the default compute account)"
    ref = re.search(r"google_service_account\.(\w+)", runtime.group(1))
    eval_accounts = {b.name for b in _eval_service_accounts(blocks)}
    assert ref and ref.group(1) in eval_accounts, "EFF-05: the job runs as its own dedicated eval service account"
    assert ref.group(1) != sa.name, "EFF-05: the account that triggers the job must not be the account the job runs as"


# --- no secrets, nothing live --------------------------------------------------------------------------------


def test_EFF_05_the_eval_infra_has_no_secrets_keys_or_live_switch(repo_root):
    blocks = _blocks(repo_root)
    assert not _of_type(blocks, "google_secret_manager_secret_version"), "PRD 16.1 rule 4: no secret values in code"
    assert not _of_type(blocks, "google_service_account_key"), "infra/CLAUDE.md: no service account keys anywhere"
    kind, target = _target(_blocks(repo_root), _scheduler_job(repo_root))
    scoped = [_scheduler_job(repo_root), *_eval_service_accounts(blocks)]
    if kind == "job":
        scoped += [b for b in _of_type(blocks, "google_cloud_run_v2_job") if b.name == target]
    for b in scoped:
        assert not KEY_LIKE.search(b.body), f"EFF-05: a key-like literal in {b.labels}"
        assert "secret_key_ref" not in b.body and "secret_environment_variables" not in b.body, (
            "EFF-05: the replay smoke needs no secret; a live run is a later, separate decision"
        )
        assert "GOOGLE_APPLICATION_CREDENTIALS" not in b.body
        assert not re.search(r'name\s*=\s*"(LIVE|TILO_RECORD)"', b.body), (
            "EFF-01: Terraform never sets the live or record switch; only the user does"
        )


# --- not GitHub Actions --------------------------------------------------------------------------------------


def test_EFF_05_no_github_actions_cron_runs_the_evals(repo_root):
    workflows = sorted((repo_root / ".github" / "workflows").glob("*.y*ml"))
    assert workflows, "the CI workflows exist"
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        triggers = data.get("on", data.get(True)) or {}
        scheduled = isinstance(triggers, dict) and "schedule" in triggers
        if scheduled:
            assert not re.search(r"(?i)tilo_evals|just eval|\beval\b|nightly", text), (
                f"EFF-05: {path.name} schedules a cron that touches the evals; the user chose Cloud Scheduler"
            )


def test_EFF_05_access_audit_lists_the_eval_scheduler_identity_and_its_one_grant(repo_root):
    sa = _scheduler_sa(repo_root)
    account_id = (sa.attr("account_id") or "").strip('"')
    access = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")

    assert account_id and account_id in access, f"EFF-05: infra/ACCESS.md must list {account_id}"
    row = next((line for line in access.splitlines() if account_id in line), "")
    assert "run.invoker" in row, "EFF-05: its ACCESS.md row names roles/run.invoker and the one target"
