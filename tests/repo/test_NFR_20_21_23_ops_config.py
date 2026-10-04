"""NFR-20 and NFR-23 (PRD 17.2), the parts that are configuration in `infra/` and so checkable before the
deploy exists. Written from the PRD text before any builder touches it (tests/NFR-batch-1); the live numbers (99.5%
availability, a warm instance actually serving, an alert actually firing) need the deployed tilo-demo and are
planned in docs/open-questions.md.

- NFR-20: "checked every minute": an uptime check with a 60 s period on the public link.
- NFR-21 ("Min-instances = 1 ... during those windows") is about the tilo-demo environment, which is the user's
  call to create, so it has no test here; it is a plan line for after the deploy (issue #316).
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


ALERTS = {
    "uptime": r"uptime",
    "error rate above 2%": r"error[ _-]?rate|5xx",
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


def _threshold_is_two_percent(policy: str, text: str) -> bool:
    m = re.search(r"threshold_value\s*=\s*([^\n]+)", policy)
    if not m:
        return False
    value = m.group(1).strip()
    if re.fullmatch(r"(0\.02|2)", value):
        return True
    var = re.fullmatch(r"var\.(\w+)", value)  # a variable: its default is the threshold
    if not var:
        return False
    block = re.search(rf'variable\s+"{var.group(1)}"\s*\{{(.*?)\n\}}', text, re.S)
    return bool(block and re.search(r"default\s*=\s*(0\.02|2)\b", block.group(1)))


def test_NFR_23_the_error_rate_alert_fires_above_two_percent():
    text = _hcl(INFRA)
    policies = [
        p for p in _blocks(text, "google_monitoring_alert_policy") if re.search(ALERTS["error rate above 2%"], p, re.I)
    ]
    assert policies, "no error-rate alert policy exists"
    assert any(_threshold_is_two_percent(p, text) for p in policies), "the threshold is not 2%"
