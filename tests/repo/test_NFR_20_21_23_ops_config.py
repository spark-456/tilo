"""NFR-20, NFR-21, NFR-23 (PRD 17.2), the parts that are configuration in `infra/` and so checkable before the
deploy exists. Written from the PRD text before any builder touches it (tests/NFR-batch-1); the live numbers (99.5%
availability, a warm instance actually serving, an alert actually firing) need the deployed tilo-demo and are
planned in docs/open-questions.md.

- NFR-20: "checked every minute": an uptime check with a 60 s period on the public link.
- NFR-21: "Min-instances = 1 for tilo-api, tilo-harness and tilo-channels" in the demo environment (infra/envs/demo).
- NFR-23: "Alerts on uptime, error rate > 2%, spend thresholds, quota errors, webhook failures and token-refresh
  failures": one alert policy for each, in infra/.
Plain text search of the HCL: the repo's tests run before any terraform tooling is installed.
"""

from __future__ import annotations

import pathlib
import re

import pytest

INFRA = pathlib.Path(__file__).resolve().parents[2] / "infra"


def _hcl(root: pathlib.Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(root.rglob("*.tf")))


def _blocks(text: str, resource: str) -> list[str]:
    """The body of every `resource "<type>" "<name>" { ... }` of this type (balanced braces)."""
    found = []
    for m in re.finditer(rf'resource\s+"{re.escape(resource)}"\s+"[^"]+"\s*\{{', text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        found.append(text[m.end() : i])
    return found


def test_NFR_20_an_uptime_check_runs_every_minute_on_the_public_link():
    checks = _blocks(_hcl(INFRA), "google_monitoring_uptime_check_config")
    assert checks, "infra/ defines no google_monitoring_uptime_check_config: nothing checks the demo link"
    assert any(re.search(r'period\s*=\s*"60s"', c) for c in checks), "no uptime check has a 60 s period"


@pytest.mark.parametrize("service", ["api", "harness", "channels"])
def test_NFR_21_the_demo_environment_keeps_one_instance_warm(service):
    demo = INFRA / "envs" / "demo"
    assert demo.is_dir(), "infra/envs/demo does not exist: the demo link has no environment definition"
    text = _hcl(demo)
    m = re.search(rf'"{service}"\s*=\s*\{{(.*?)\n\s*\}}', text, re.S)
    assert m, f"infra/envs/demo defines no cloud run service {service!r}"
    count = re.search(r"min_instance_count\s*=\s*(\d+)", m.group(1))
    assert count and int(count.group(1)) >= 1, f"{service}: min_instance_count must be at least 1"


ALERTS = {
    "uptime": r"uptime",
    "error rate above 2%": r"error[ _-]?rate",
    "spend thresholds": r"spend|budget",
    "quota errors": r"quota",
    "webhook failures": r"webhook",
    "token-refresh failures": r"token[ _-]?refresh",
}


@pytest.mark.parametrize("alert", ALERTS)
def test_NFR_23_there_is_an_alert_policy_for(alert):
    text = _hcl(INFRA)
    if alert == "spend thresholds" and any("threshold_rules" in b for b in _blocks(text, "google_billing_budget")):
        return  # a billing budget with threshold rules is the spend alert (modules/budget)
    policies = _blocks(text, "google_monitoring_alert_policy")
    assert policies, "infra/ defines no google_monitoring_alert_policy"
    named = [p for p in policies if re.search(ALERTS[alert], p, re.I)]
    assert named, f"no alert policy covers {alert}"


def test_NFR_23_the_error_rate_alert_fires_above_two_percent():
    policies = [
        p
        for p in _blocks(_hcl(INFRA), "google_monitoring_alert_policy")
        if re.search(ALERTS["error rate above 2%"], p, re.I)
    ]
    assert policies, "no error-rate alert policy exists"
    assert any(re.search(r"threshold_value\s*=\s*(0\.02|2)\b", p) for p in policies), "the threshold is not 2%"
