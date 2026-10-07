"""P0-07c: security response headers on Firebase Hosting (PRD 6.5, SEC-02).

Every route gets a Content-Security-Policy that forbids framing and any off-origin load, nosniff, and a strict
Referrer-Policy. The deployed web app loads Pixi's CSP-safe build, so the policy needs no 'unsafe-eval'.

Static only: no firebase, no network, no cloud credentials.
"""

from __future__ import annotations

import json
import pathlib
import re


def _rules(repo_root: pathlib.Path) -> list[dict]:
    hosting = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    hosting = hosting[0] if isinstance(hosting, list) else hosting
    return hosting["headers"]


def _site_wide(repo_root: pathlib.Path) -> dict[str, str]:
    """Headers from every rule whose source matches all routes, keyed by lower-cased header name."""
    out: dict[str, str] = {}
    for rule in _rules(repo_root):
        if rule.get("source") in ("**", "/**"):
            for h in rule["headers"]:
                out[h["key"].lower()] = h["value"]
    return out


def _directives(csp: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for part in csp.split(";"):
        tokens = part.split()
        if tokens:
            result[tokens[0].lower()] = tokens[1:]
    return result


def test_P0_07c_headers_apply_to_all_routes(repo_root: pathlib.Path) -> None:
    headers = _site_wide(repo_root)
    assert {"content-security-policy", "x-content-type-options", "referrer-policy"} <= set(headers)
    assert headers["x-content-type-options"].lower() == "nosniff"
    assert headers["referrer-policy"].lower() == "strict-origin-when-cross-origin"


# SEC-10 (documented test change, like P0-07e's base-uri): the web client's App Check loads reCAPTCHA Enterprise and
# exchanges its challenge at the App Check endpoint, so the policy names exactly these off-origin sources, per
# directive (Google's documented minimum; the Firebase SDK needs nothing else), and no other directive has any.
# tests/repo/test_SEC_10_appcheck_client_docs_and_csp.py pins the same set; everything else stays 'self' only.
OFF_ORIGIN_ALLOWED = {
    "script-src": ["https://www.google.com/recaptcha/", "https://www.gstatic.com/recaptcha/"],
    "frame-src": ["https://www.google.com/recaptcha/"],
    "connect-src": ["https://firebaseappcheck.googleapis.com"],
}


def test_P0_07c_csp_forbids_framing_and_off_origin_loads(repo_root: pathlib.Path) -> None:
    csp = _directives(_site_wide(repo_root)["content-security-policy"])
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["default-src"] == ["'self'"]
    assert csp["script-src"] == ["'self'", *OFF_ORIGIN_ALLOWED["script-src"]]  # SEC-10: was exactly 'self'
    assert csp["connect-src"] == ["'self'", *OFF_ORIGIN_ALLOWED["connect-src"]]  # SEC-10: was exactly 'self'
    assert csp["frame-src"] == OFF_ORIGIN_ALLOWED["frame-src"]  # SEC-10: new, the reCAPTCHA challenge frame only
    assert csp["object-src"] == ["'none'"]
    # P0-07e (documented test change): base-uri tightened from 'self' to 'none'; the app has no <base> tag.
    assert csp["base-uri"] == ["'none'"]
    for name, sources in csp.items():
        assert "*" not in sources, f"{name}: wildcard source"
        off_origin = [s for s in sources if re.match(r"https?:", s)]
        assert off_origin == OFF_ORIGIN_ALLOWED.get(name, []), f"{name}: off-origin source {sources}"


def test_P0_07c_csp_script_src_allows_neither_eval_nor_inline_scripts(repo_root: pathlib.Path) -> None:
    csp = _directives(_site_wide(repo_root)["content-security-policy"])
    assert "'unsafe-eval'" not in csp["script-src"]
    assert "'unsafe-inline'" not in csp["script-src"]
    assert not any("unsafe-eval" in s for sources in csp.values() for s in sources)


def test_P0_07c_web_stage_loads_pixi_unsafe_eval_build_so_the_csp_holds(repo_root: pathlib.Path) -> None:
    stage = (repo_root / "apps" / "web" / "src" / "stage" / "Stage.tsx").read_text(encoding="utf-8")
    assert 'import("pixi.js/unsafe-eval")' in stage, "Pixi needs its CSP-safe build when 'unsafe-eval' is forbidden"


def test_P0_07c_headers_keep_the_cache_rules(repo_root: pathlib.Path) -> None:
    by_source = {r["source"]: {h["key"].lower(): h["value"] for h in r["headers"]} for r in _rules(repo_root)}
    assert "immutable" in by_source["/assets/**"]["cache-control"]
    assert "no-cache" in by_source["/index.html"]["cache-control"]
