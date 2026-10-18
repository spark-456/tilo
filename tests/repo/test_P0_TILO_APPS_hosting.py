import json
from pathlib import Path


def test_P0_TILO_APPS_public_viewer_has_scoped_headers():
    hosting = json.loads((Path(__file__).parents[2] / "firebase.json").read_text())["hosting"]
    rules = [rule for rule in hosting["headers"] if rule.get("source") == "/u/**"]
    assert len(rules) == 1
    headers = {entry["key"]: entry["value"] for entry in rules[0]["headers"]}
    csp = headers["Content-Security-Policy"]
    assert "default-src 'none'" in csp
    assert "frame-src" in csp and "data:" in csp and "blob:" in csp
    assert headers["Referrer-Policy"] == "no-referrer"
    general = next(rule for rule in hosting["headers"] if rule.get("source") == "**")
    general_headers = {entry["key"]: entry["value"] for entry in general["headers"]}
    assert general_headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
