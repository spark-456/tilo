"""NFR-27 (docs/prd-supplement-2026-10-05.md): the Terraform half of the owner cost alerts.

"Owner alerts at 80% and 100% of a uid's cap and above a global daily threshold (alert-only), through a redacted
structured log wired to a Cloud Monitoring email alert." The application writes one JSON line per alert with
`"event": "cost_alert"` (see `packages/metering/tests/test_NFR_27_cost_alerts.py`); Terraform turns that line into a
log-based metric and an alert policy that emails the owner.

What these static checks pin (no terraform binary, no network, no credentials, nothing is planned or applied):
  * a `google_logging_metric` whose filter selects `jsonPayload.event="cost_alert"`;
  * a `google_monitoring_alert_policy` that reads that metric (or matches the same log line) and notifies an
    email `google_monitoring_notification_channel`;
  * the channel address comes from a variable with no default; no email address is written into any `.tf` file;
  * nothing applies itself: no provisioner, no `local-exec`, no apply step in CI or the justfile.

Where the implementation goes: `infra/modules/monitoring/main.tf` (it already owns the email channel
`google_monitoring_notification_channel.email`, `var.alert_email` and the NFR-23 policies). A PR only: the user
applies it.

Heads up for the builder (not asserted here): `infra/envs/dev/tests/monitoring.tftest.hcl` pins the module output
`alert_policies` to exactly the three NFR-23 keys, so expose the cost policy under a separate output, or update that
assertion deliberately.

Ambiguity resolved (PRD gives only "a Cloud Monitoring email alert"): the log event name is `cost_alert` (the
`COST_ALERT_EVENT` constant of `tilo_metering`), matched on `jsonPayload.event`.
"""

from __future__ import annotations

import pathlib
import re

import pytest

EVENT_FILTER = re.compile(r'jsonPayload\.event\s*=\s*\\?"cost_alert\\?"')
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[A-Za-z0-9.-]+")


def _tf_files(repo_root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in (repo_root / "infra").rglob("*.tf") if ".terraform" not in p.parts)


def _blocks(text: str, resource_type: str) -> list[tuple[str, str]]:
    """(name, body) of every `resource "<type>" "<name>" { ... }`, by brace matching."""
    out: list[tuple[str, str]] = []
    for head in re.finditer(rf'^resource\s+"{re.escape(resource_type)}"\s+"([^"]+)"\s*\{{', text, re.M):
        depth, i = 1, head.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append((head.group(1), text[head.end() : i - 1]))
    return out


def _all_blocks(repo_root: pathlib.Path, resource_type: str) -> list[tuple[pathlib.Path, str, str]]:
    found = []
    for path in _tf_files(repo_root):
        for name, body in _blocks(path.read_text(encoding="utf-8"), resource_type):
            found.append((path, name, body))
    return found


def _cost_metric(repo_root: pathlib.Path) -> tuple[pathlib.Path, str, str]:
    metrics = [m for m in _all_blocks(repo_root, "google_logging_metric") if EVENT_FILTER.search(m[2])]
    assert metrics, 'NFR-27: no google_logging_metric filters on jsonPayload.event="cost_alert" under infra/'
    return metrics[0]


def test_NFR_27_log_based_metric_counts_cost_alert_lines(repo_root):
    path, name, body = _cost_metric(repo_root)
    assert "infra/modules/monitoring" in path.as_posix(), "NFR-27: put the metric in the monitoring module"
    assert re.search(r'metric_kind\s*=\s*"DELTA"', body), "NFR-27: a log-based counter is metric_kind DELTA"
    assert re.search(r'value_type\s*=\s*"INT64"', body), "NFR-27: a log-based counter is value_type INT64"
    assert re.search(r"\bproject\s*=\s*var\.project_id", body), "NFR-27: the metric lives in var.project_id"


def test_NFR_27_alert_policy_reads_the_cost_alert_log_and_emails_the_owner(repo_root):
    _path, metric_name, metric_body = _cost_metric(repo_root)
    name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', metric_body, re.M)
    assert name_match, "NFR-27: the log-based metric needs a literal name"
    metric_type = f"logging.googleapis.com/user/{name_match.group(1)}"

    policies = [
        (p, n, b)
        for p, n, b in _all_blocks(repo_root, "google_monitoring_alert_policy")
        if metric_type in b
        or f"google_logging_metric.{metric_name}" in b
        or ("condition_matched_log" in b and EVENT_FILTER.search(b))
    ]
    assert policies, f"NFR-27: no google_monitoring_alert_policy reads {metric_type} or matches the cost_alert log"
    _p, _n, body = policies[0]

    email_channels = [
        n
        for _p2, n, b in _all_blocks(repo_root, "google_monitoring_notification_channel")
        if re.search(r'type\s*=\s*"email"', b)
    ]
    assert email_channels, "NFR-27: an email notification channel must exist"
    assert re.search(r"notification_channels\s*=\s*\[[^\]]*google_monitoring_notification_channel\.\w+\.id", body), (
        "NFR-27: the cost alert policy must notify an email notification channel"
    )
    referenced = re.findall(r"google_monitoring_notification_channel\.(\w+)\.id", body)
    assert set(referenced) & set(email_channels), "NFR-27: the policy's channel must be an email channel"


def test_NFR_27_alert_policy_documents_the_alert_and_stays_alert_only(repo_root):
    _path, metric_name, metric_body = _cost_metric(repo_root)
    name = re.search(r'^\s*name\s*=\s*"([^"]+)"', metric_body, re.M).group(1)
    policies = [b for _p, _n, b in _all_blocks(repo_root, "google_monitoring_alert_policy") if name in b]
    assert policies, "NFR-27: no alert policy for the cost metric"
    body = policies[0]
    assert "NFR-27" in body, "NFR-27: the policy's documentation names the requirement"
    assert re.search(r"documentation\s*\{", body)


def test_NFR_27_no_email_address_is_written_into_terraform(repo_root):
    channels = _all_blocks(repo_root, "google_monitoring_notification_channel")
    assert channels, "NFR-27: no notification channel resource found"
    for path, name, body in channels:
        match = re.search(r"email_address\s*=\s*(.+)", body)
        assert match, f"{path.name}:{name} has no email_address"
        assert match.group(1).strip().startswith("var."), (
            f"NFR-27: {path.name}:{name} email_address must come from a variable, got {match.group(1).strip()!r}"
        )
    for path in _tf_files(repo_root):
        for line in path.read_text(encoding="utf-8").splitlines():
            code = line.split("#", 1)[0]
            if "regex(" in code or "serviceAccount" in code or "iam.gserviceaccount.com" in code:
                continue  # the validation pattern and service-account member strings are not owner addresses
            assert not EMAIL.search(code), (
                f"NFR-27: a literal email address in {path.relative_to(repo_root)}: {line.strip()}"
            )


def test_NFR_27_alert_email_variable_has_no_default(repo_root):
    for rel in ("infra/modules/monitoring/variables.tf", "infra/envs/dev/variables.tf"):
        text = (repo_root / rel).read_text(encoding="utf-8")
        match = re.search(r'variable\s+"alert_email"\s*\{', text)
        assert match, f"{rel} must declare variable alert_email"
        depth, i = 1, match.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        assert not re.search(r"^\s*default\s*=", text[match.end() : i], re.M), (
            f"{rel}: alert_email must have no default"
        )


def test_NFR_27_nothing_in_the_cost_alert_change_applies_itself(repo_root):
    for path in _tf_files(repo_root):
        text = path.read_text(encoding="utf-8")
        for banned in ("provisioner", "local-exec", "remote-exec", "null_resource", "external_data"):
            assert banned not in text, (
                f"NFR-27: {path.relative_to(repo_root)} contains {banned!r}: Terraform must not apply itself"
            )
    for rel in (".github/workflows", "cloudbuild.yaml", "justfile"):
        target = repo_root / rel
        files = (
            [p for p in target.rglob("*") if p.is_file()] if target.is_dir() else ([target] if target.exists() else [])
        )
        for f in files:
            for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if re.search(r"terraform\s+(-chdir=\S+\s+)?apply\b", code) and "the user runs" not in code:
                    pytest.fail(
                        f"NFR-27: {f.relative_to(repo_root)}:{n} runs the infra apply step; the user applies it"
                    )


def test_NFR_27_docs_tell_the_owner_how_the_alert_is_wired(repo_root):
    """The runbook (docs/deploy-dev.md or infra/README.md) names the event, the metric and the email variable."""
    texts = [
        (repo_root / rel).read_text(encoding="utf-8")
        for rel in ("docs/deploy-dev.md", "infra/README.md")
        if (repo_root / rel).exists()
    ]
    assert any("NFR-27" in t and "cost_alert" in t and "alert_email" in t for t in texts), (
        "NFR-27: docs/deploy-dev.md or infra/README.md must mention NFR-27, the cost_alert event and alert_email"
    )


def test_NFR_27_metric_filter_is_scoped_to_cloud_run_stdout_and_the_three_kinds(repo_root):
    _path, _name, body = _cost_metric(repo_root)
    flt = re.search(r"^\s*filter\s*=\s*(.+)$", body, re.M).group(1)
    assert 'resource.type=\\"cloud_run_revision\\"' in flt, "NFR-27: scope the metric to Cloud Run revisions"
    assert "run.googleapis.com%2Fstdout" in flt, "NFR-27: scope the metric to stdout"
    for kind in ("uid_cap_80", "uid_cap_100", "global_daily"):
        assert f'\\"{kind}\\"' in flt, f"NFR-27: filter must name kind {kind}"


def test_NFR_27_policy_auto_closes_and_treats_missing_data_as_inactive(repo_root):
    _path, _name, metric = _cost_metric(repo_root)
    metric_name = re.search(r'^\s*name\s*=\s*"([^"]+)"', metric, re.M).group(1)
    body = next(b for _p, _n, b in _all_blocks(repo_root, "google_monitoring_alert_policy") if metric_name in b)
    assert re.search(r'auto_close\s*=\s*"1800s"', body), "NFR-27: an incident must auto-close (1800s)"
    assert re.search(r'evaluation_missing_data\s*=\s*"EVALUATION_MISSING_DATA_INACTIVE"', body)
