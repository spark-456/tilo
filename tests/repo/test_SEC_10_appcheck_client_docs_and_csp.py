"""SEC-10 (PRD 16 "Rate limits, App Check and spend caps"): App Check client wiring, the static parts.

- infra/ACCESS.md section 7 (Console steps) records the Firebase web app id and the reCAPTCHA Enterprise
  score site key, and says enforcement stays off. Both ids are public values (the web client ships them), not
  secrets; they are the same two ids as `apps/web/src/appcheck/config.ts`.
- The Hosting CSP (firebase.json) lets the deployed page load reCAPTCHA Enterprise and reach the App Check
  exchange endpoint, and nothing wider: no wildcard, no 'unsafe-eval', no inline scripts.
- `apps/web` depends on the `firebase` package (the App Check SDK).
- No secret-looking content in the App Check sources or in section 7.

Static only: no network, no cloud credentials.

AMBIGUITY (documented, PRD 6.5 / SEC-02 give no origin list): the CSP additions pinned are Google's own
documented minimum for reCAPTCHA Enterprise and the App Check REST exchange;
`test_P0_07c_csp_forbids_framing_and_off_origin_loads` asserts "no off-origin source"
and will need a documented test change in the builder's branch, as P0-07e did for
`base-uri`, to allow exactly the origins pinned here and no others.
"""

from __future__ import annotations

import json
import pathlib
import re

FIREBASE_APP_ID = "1:379216745263:web:8cda5846cf882c2cefc7da"
RECAPTCHA_SITE_KEY = "6LdlsOItAAAAAEhO_aq9zmtbQue6Rni2ZDUDuRTe"

# Origins Google documents for reCAPTCHA Enterprise (script, frame) and the App Check token exchange (connect).
RECAPTCHA_SCRIPT_ORIGINS = {"https://www.google.com/recaptcha/", "https://www.gstatic.com/recaptcha/"}
RECAPTCHA_FRAME_ORIGIN = "https://www.google.com/recaptcha/"
APPCHECK_CONNECT_ORIGIN = "https://firebaseappcheck.googleapis.com"


def _section_7(repo_root: pathlib.Path) -> str:
    text = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    match = re.search(r"^## 7\..*?(?=^## 8\.)", text, flags=re.S | re.M)
    assert match, "infra/ACCESS.md has no '## 7.' section ending before '## 8.'"
    return match.group(0)


def _csp(repo_root: pathlib.Path) -> dict[str, list[str]]:
    hosting = json.loads((repo_root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
    hosting = hosting[0] if isinstance(hosting, list) else hosting
    value = ""
    for rule in hosting["headers"]:
        if rule.get("source") in ("**", "/**"):
            for h in rule["headers"]:
                if h["key"].lower() == "content-security-policy":
                    value = h["value"]
    assert value, "no site-wide Content-Security-Policy in firebase.json"
    result: dict[str, list[str]] = {}
    for part in value.split(";"):
        tokens = part.split()
        if tokens:
            result[tokens[0].lower()] = tokens[1:]
    return result


def test_SEC_10_access_md_section_7_records_the_web_app_id_and_the_site_key(repo_root: pathlib.Path) -> None:
    section = _section_7(repo_root)
    assert FIREBASE_APP_ID in section, "section 7 must record the Firebase web app id of 'tilo-web'"
    assert RECAPTCHA_SITE_KEY in section, "section 7 must record the reCAPTCHA Enterprise score site key"


def test_SEC_10_access_md_says_enforcement_stays_off(repo_root: pathlib.Path) -> None:
    section = _section_7(repo_root)
    assert re.search(r"enforcement[^.\n]*\boff\b|\boff\b[^.\n]*enforcement", section, flags=re.I), (
        "section 7 must say that App Check enforcement is off (and stays off until the owner switches it on)"
    )


def test_SEC_10_ids_in_access_md_and_in_the_web_config_are_the_same(repo_root: pathlib.Path) -> None:
    config = (repo_root / "apps" / "web" / "src" / "appcheck" / "config.ts").read_text(encoding="utf-8")
    section = _section_7(repo_root)
    for public_id in (FIREBASE_APP_ID, RECAPTCHA_SITE_KEY):
        assert public_id in config, f"apps/web/src/appcheck/config.ts must hold {public_id}"
        assert public_id in section


def test_SEC_10_hosting_csp_allows_recaptcha_enterprise_and_the_app_check_exchange(repo_root: pathlib.Path) -> None:
    csp = _csp(repo_root)
    assert RECAPTCHA_SCRIPT_ORIGINS <= set(csp["script-src"]), "script-src must allow the reCAPTCHA script origins"
    assert "'self'" in csp["script-src"]
    assert RECAPTCHA_FRAME_ORIGIN in csp.get("frame-src", []), "frame-src must allow the reCAPTCHA challenge frame"
    assert APPCHECK_CONNECT_ORIGIN in csp["connect-src"], "connect-src must allow the App Check token exchange"
    assert "'self'" in csp["connect-src"]


def test_SEC_10_hosting_csp_stays_tight(repo_root: pathlib.Path) -> None:
    csp = _csp(repo_root)
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["default-src"] == ["'self'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'none'"]
    for name, sources in csp.items():
        assert "*" not in sources, f"{name}: wildcard source"
        assert not any(s.startswith("*.") or "://*." in s for s in sources), f"{name}: wildcard host {sources}"
    assert "'unsafe-eval'" not in {s for sources in csp.values() for s in sources}
    assert "'unsafe-inline'" not in csp["script-src"]
    # Only the three documented origins are added beyond 'self' and the existing data:/blob: sources.
    off_origin = {s for name in ("script-src", "connect-src", "frame-src") for s in csp.get(name, []) if "://" in s}
    assert off_origin <= RECAPTCHA_SCRIPT_ORIGINS | {RECAPTCHA_FRAME_ORIGIN, APPCHECK_CONNECT_ORIGIN}, off_origin


def test_SEC_10_web_depends_on_the_firebase_sdk(repo_root: pathlib.Path) -> None:
    package = json.loads((repo_root / "apps" / "web" / "package.json").read_text(encoding="utf-8"))
    assert "firebase" in package.get("dependencies", {}), "apps/web needs the `firebase` package (App Check SDK)"
    # docs/licences.md must list it too (test_PRD_17_6 covers every package.json dependency; pinned by name here).
    licences = (repo_root / "docs" / "licences.md").read_text(encoding="utf-8")
    assert re.search(r"^\|\s*firebase\b(?!-tools)", licences, flags=re.M | re.I), "docs/licences.md must list firebase"


def test_SEC_10_no_secret_looking_content_in_the_app_check_files(repo_root: pathlib.Path) -> None:
    files = [repo_root / "infra" / "ACCESS.md", repo_root / "apps" / "web" / "src" / "api" / "http.ts"]
    folder = repo_root / "apps" / "web" / "src" / "appcheck"
    assert folder.is_dir(), "apps/web/src/appcheck/ must exist"
    files += [p for p in folder.glob("*.ts*") if ".test." not in p.name]
    assert any(p.name == "config.ts" for p in files)
    forbidden = re.compile(
        r"AIza[0-9A-Za-z_-]{30,}"  # Google API key
        r"|GOCSPX-[0-9A-Za-z_-]+"  # OAuth client secret
        r"|ya29\.[0-9A-Za-z_-]{10,}"  # OAuth access token
        r"|-----BEGIN [A-Z ]*PRIVATE KEY"
        r"|FIREBASE_APPCHECK_DEBUG_TOKEN\s*=\s*[\"'][0-9A-Za-z-]{16,}[\"']"  # a committed debug credential
    )
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"secret-looking content in {path.relative_to(repo_root)}"
