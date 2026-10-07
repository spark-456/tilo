"""SEC-15 / SIGNIN (PRD 6 platform row "Firebase Authentication: Google sign-in and anonymous demo sessions"; PRD R-06):
the user setup sheet, the Hosting CSP for Google sign-in, and the static rules of the web sign-in code.

- infra/ACCESS.md has a sign-in section (a numbered setup sheet, in order): enable the Google provider in Firebase
  Authentication, enable the Anonymous provider, check the authorized domains (the project's web.app and firebaseapp.com
  hosts), widen the web API key's API restriction to what the Auth SDK calls, and the OAuth consent screen with
  publishing status: the user chose In production (BQ-SIGNIN-1), with its consequences (the unverified-app warning and
  the 100-new-user cap on Gmail consent, until Google verifies the restricted scopes: a later owner step) and Testing as
  the fallback. docs/deploy-dev.md must not keep telling the user the key is "App Check API only", or sign-in breaks.
- The Gmail consent sheet (S-08) tells the person about Google's unverified-app warning before the redirect; the exact
  sentence is in services/api/tests/API_SIGNIN.md and in apps/web/src/screens/S_08.unverified.SIGNIN.test.tsx.
- The Hosting CSP (firebase.json) gets exactly what the Firebase Auth SDK needs for a popup / redirect Google sign-in,
  nothing wider. Found by reading @firebase/auth 12.x `dist/esm/index-*.js` (version in pnpm-lock): the gapi loader is
  `https://apis.google.com/js/api.js` (script-src), the sign-in iframe and handler live on the project's auth domain at
  `/__/auth/iframe` and `/__/auth/handler` (frame-src), and the REST hosts are
  `identitytoolkit.googleapis.com` (API_HOST)
  and `securetoken.googleapis.com` (TOKEN_API_HOST) (connect-src). The Google account chooser opens in the popup window
  or as a top-level navigation, which script-src, frame-src and connect-src do not govern, so `accounts.google.com` is
  NOT required (it may appear in frame-src only; BQ-SIGNIN-5). No wildcard, no 'unsafe-eval', no 'unsafe-inline' script.
  NOTE FOR THE BUILDER: `tests/repo/test_SEC_10_appcheck_client_docs_and_csp.py::test_SEC_10_hosting_csp_stays_tight`
  allows only the App Check origins off-origin and says in its header that it needs a documented edit when more
  origins are
  added (as P0-07e did for base-uri); extend its allowed set by exactly the origins pinned here and no more.
- `apps/web/src/auth/` imports the Firebase SDK only dynamically (NFR-01: the SDK stays off the landing bundle), and has
  no secret-looking content.

Static only: no network, no cloud credentials.
"""

from __future__ import annotations

import json
import pathlib
import re
from urllib.parse import urlparse

DEV_PROJECT = "essential-wares-510320-f0"  # the dev project (tests/repo/test_P0_07c_deploy_web.py)

AUTH_DOMAIN_FRAME = f"https://{DEV_PROJECT}.firebaseapp.com/__/auth/"
GAPI_SCRIPT = "https://apis.google.com"
IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com"
SECURE_TOKEN = "https://securetoken.googleapis.com"

APPCHECK_ORIGINS = {
    "https://www.google.com/recaptcha/",
    "https://www.gstatic.com/recaptcha/",
    "https://content-firebaseappcheck.googleapis.com",
}
SIGN_IN_SCRIPT = {GAPI_SCRIPT}
SIGN_IN_FRAME = {AUTH_DOMAIN_FRAME}
SIGN_IN_CONNECT = {IDENTITY_TOOLKIT, SECURE_TOKEN}
OPTIONAL_FRAME = {"https://accounts.google.com"}  # allowed, never required (BQ-SIGNIN-5)


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


def _sign_in_section(repo_root: pathlib.Path) -> str:
    text = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    match = re.search(r"^## \d+[a-z]?\.[^\n]*sign-?in[^\n]*\n.*?(?=^## |\Z)", text, flags=re.S | re.M | re.I)
    assert match, (
        "infra/ACCESS.md needs a '## N. ... sign-in ...' section: the user's setup sheet for Firebase Authentication"
    )
    return match.group(0)


def _steps(section: str) -> list[str]:
    """The numbered list items of the section, each with its continuation lines."""
    items = re.split(r"^\s{0,3}\d+\.\s", section, flags=re.M)
    return items[1:]


def _first_step(steps: list[str], pattern: str) -> int:
    for index, step in enumerate(steps):
        if re.search(pattern, step, flags=re.S | re.I):
            return index
    return -1


# --- the user setup sheet ---------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_access_md_has_a_numbered_setup_sheet(repo_root: pathlib.Path) -> None:
    section = _sign_in_section(repo_root)
    assert len(_steps(section)) >= 5, "the sign-in section is a numbered list of the user's console steps"
    assert DEV_PROJECT in section, "name the project id the steps are for"


def test_SEC_15_SIGNIN_access_md_steps_cover_provider_anonymous_domains_key_and_consent_in_order(
    repo_root: pathlib.Path,
) -> None:
    steps = _steps(_sign_in_section(repo_root))
    anchors = {
        "enable the Google provider in Firebase Authentication": r"Google.{0,80}provider",
        "enable the Anonymous provider": r"\banonymous\b",
        "authorized domains": r"authori[sz]ed domains",
        "the web API key's API restriction": r"Identity Toolkit API",
        "the OAuth consent screen": r"consent screen",
    }
    where = {name: _first_step(steps, pattern) for name, pattern in anchors.items()}
    assert all(i >= 0 for i in where.values()), f"missing steps: {[n for n, i in where.items() if i < 0]}"
    order = list(anchors)
    indexes = [where[name] for name in order]
    assert indexes == sorted(indexes), f"steps out of order (provider, anonymous, domains, API key, consent): {where}"


def test_SEC_15_SIGNIN_access_md_authorized_domains_name_both_hosting_hosts(repo_root: pathlib.Path) -> None:
    steps = _steps(_sign_in_section(repo_root))
    step = steps[_first_step(steps, r"authori[sz]ed domains")]
    assert f"{DEV_PROJECT}.web.app" in step
    assert f"{DEV_PROJECT}.firebaseapp.com" in step


def test_SEC_15_SIGNIN_access_md_says_never_enable_passwords_and_the_anonymous_provider_is_for_demo_sessions(
    repo_root: pathlib.Path,
) -> None:
    section = _sign_in_section(repo_root)
    assert re.search(r"(do not|never|don't)[^.\n]*(email|password)", section, flags=re.I), (
        "Tilo never handles passwords (PRD 16.1): the sheet says not to enable Email/Password"
    )
    assert re.search(r"demo", section, flags=re.I)


def test_SEC_15_SIGNIN_access_md_widens_the_web_key_to_the_apis_the_auth_sdk_calls(repo_root: pathlib.Path) -> None:
    section = _sign_in_section(repo_root)
    assert "Identity Toolkit API" in section, "the Auth SDK calls identitytoolkit.googleapis.com"
    assert re.search(r"Token Service API|securetoken", section, flags=re.I), "and securetoken.googleapis.com"
    assert re.search(r"App Check", section), "the App Check API stays on the list"
    assert re.search(r"referrer", section, flags=re.I), "the website (referrer) restrictions stay"
    assert re.search(r"generativelanguage", section), "and the key still must not reach the Gemini API"


def test_SEC_15_SIGNIN_access_md_says_the_consent_screen_goes_in_production_and_what_that_means(
    repo_root: pathlib.Path,
) -> None:
    section = _sign_in_section(repo_root)
    assert re.search(r"In production", section), "the consent screen publishing status is In production"
    assert re.search(
        r"(chosen|decided|decision|selected)[^.\n]{0,120}In production"
        r"|In production[^.\n]{0,120}(chosen|decided|decision|selected)",
        section,
        flags=re.I,
    ), "production is stated as the user's chosen status, not as one option among two"
    assert re.search(r"`?openid`?[^\n]*`?email`?[^\n]*`?profile`?", section), "the sign-in scopes are named"
    assert re.search(r"non-sensitive|basic", section, flags=re.I), (
        "the sign-in scopes are non-sensitive: anyone can sign in"
    )
    assert re.search(r"anyone|any Google account|every Google account", section, flags=re.I)
    assert re.search(r"restricted", section, flags=re.I) and re.search(r"gmail", section, flags=re.I)
    assert re.search(r"unverified", section, flags=re.I), "Gmail consent shows Google's unverified-app warning"
    assert re.search(r"\b100\b", section), "and is capped at 100 new users until Google verifies the scopes"
    assert re.search(r"100[^.\n]{0,60}(new )?users|users[^.\n]{0,60}\b100\b", section, flags=re.I)
    assert "BQ-SIGNIN-1" in section
    assert re.search(r"no code path|either (works|way)|does not depend", section, flags=re.I), (
        "says the build works with either status (nothing in the code depends on it)"
    )


def test_SEC_15_SIGNIN_access_md_keeps_testing_as_a_one_line_fallback(repo_root: pathlib.Path) -> None:
    section = _sign_in_section(repo_root)
    line = next((ln for ln in section.splitlines() if re.search(r"\bTesting\b", ln)), None)
    assert line is not None, "Testing is mentioned as the fallback"
    assert re.search(r"\b7[ -]days?\b|seven days", section, flags=re.I), (
        "Testing: sign-ins expire after about 7 days (R-06)"
    )
    assert re.search(r"test users?", section, flags=re.I), "Testing: only listed test users can sign in"
    assert re.search(r"fall ?back", section, flags=re.I)


def test_SEC_15_SIGNIN_access_md_lists_google_verification_of_the_restricted_scopes_as_a_later_owner_step(
    repo_root: pathlib.Path,
) -> None:
    steps = _steps(_sign_in_section(repo_root))
    consent = _first_step(steps, r"consent screen")
    later = _first_step(
        steps, r"(start|begin|submit|request)[^.\n]{0,60}(Google )?verification|verification[^.\n]{0,80}restricted"
    )
    assert later >= 0, "a step says to start Google verification for the restricted Gmail scopes"
    assert later >= consent, "it comes at or after the consent screen step"
    step = steps[later]
    assert re.search(r"later|after|once|when", step, flags=re.I), "it is marked as a later step, not needed to sign in"
    assert re.search(r"restricted", step, flags=re.I) and re.search(r"gmail", step, flags=re.I)
    assert re.search(r"owner", step, flags=re.I), "it is an owner step"


def test_SEC_15_SIGNIN_the_gmail_consent_sentence_in_the_spec_doc_is_the_one_the_web_test_pins(
    repo_root: pathlib.Path,
) -> None:
    spec = (repo_root / "services" / "api" / "tests" / "API_SIGNIN.md").read_text(encoding="utf-8")
    web = (repo_root / "apps" / "web" / "src" / "screens" / "S_08.unverified.SIGNIN.test.tsx").read_text(
        encoding="utf-8"
    )
    match = re.search(r'const UNVERIFIED_NOTE =\s*"([^"]+)"', web)
    assert match, "the web test pins the sentence in UNVERIFIED_NOTE"
    sentence = match.group(1)
    assert sentence in spec, "services/api/tests/API_SIGNIN.md must hold the exact sentence the web test pins"
    assert "not verified" in sentence and "Gmail" in sentence


def test_SEC_15_SIGNIN_access_md_keeps_the_app_check_key_instructions_consistent(repo_root: pathlib.Path) -> None:
    for relative in ("infra/ACCESS.md", "docs/deploy-dev.md"):
        text = (repo_root / relative).read_text(encoding="utf-8")
        assert "App Check API only" not in text, (
            f"{relative} still tells the user to restrict the web key to the App Check API only, which blocks sign-in"
        )


def test_SEC_15_SIGNIN_access_md_section_6_still_lists_the_basic_sign_in_scopes_and_no_new_ones(
    repo_root: pathlib.Path,
) -> None:
    text = (repo_root / "infra" / "ACCESS.md").read_text(encoding="utf-8")
    match = re.search(r"^## 6\..*?(?=^## 7\.)", text, flags=re.S | re.M)
    assert match
    assert re.search(r"`openid`, `email`, `profile`[^\n]*Google sign-in", match.group(0))


def test_SEC_15_SIGNIN_no_secret_looking_content_in_the_sign_in_section_or_the_web_auth_sources(
    repo_root: pathlib.Path,
) -> None:
    forbidden = re.compile(
        r"AIza[0-9A-Za-z_-]{30,}"
        r"|GOCSPX-[0-9A-Za-z_-]+"
        r"|ya29\.[0-9A-Za-z_-]{10,}"
        r"|eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{5,}"  # a JWT
        r"|-----BEGIN [A-Z ]*PRIVATE KEY"
    )
    assert not forbidden.search(_sign_in_section(repo_root))
    folder = repo_root / "apps" / "web" / "src" / "auth"
    assert folder.is_dir(), "apps/web/src/auth/ must exist"
    for path in folder.glob("*.ts*"):
        assert not forbidden.search(path.read_text(encoding="utf-8")), f"secret-looking content in {path.name}"


# --- the Hosting CSP --------------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_hosting_csp_allows_google_sign_in(repo_root: pathlib.Path) -> None:
    csp = _csp(repo_root)
    assert SIGN_IN_SCRIPT <= set(csp["script-src"]), "script-src must allow the gapi loader (apis.google.com)"
    assert SIGN_IN_FRAME <= set(csp.get("frame-src", [])), "frame-src must allow the project's /__/auth/ iframe"
    assert SIGN_IN_CONNECT <= set(csp["connect-src"]), "connect-src must allow identitytoolkit and securetoken"
    # App Check's own origins are still there (SEC-10)
    assert APPCHECK_ORIGINS <= set(csp["script-src"]) | set(csp["connect-src"]) | set(csp.get("frame-src", []))
    assert "'self'" in csp["script-src"] and "'self'" in csp["connect-src"]


def test_SEC_15_SIGNIN_hosting_csp_adds_exactly_the_sign_in_origins_and_nothing_wider(repo_root: pathlib.Path) -> None:
    csp = _csp(repo_root)
    off_origin = {
        name: {s for s in csp.get(name, []) if "://" in s} for name in ("script-src", "connect-src", "frame-src")
    }
    assert off_origin["script-src"] <= APPCHECK_ORIGINS | SIGN_IN_SCRIPT, off_origin["script-src"]
    assert off_origin["connect-src"] <= APPCHECK_ORIGINS | SIGN_IN_CONNECT, off_origin["connect-src"]
    assert off_origin["frame-src"] <= APPCHECK_ORIGINS | SIGN_IN_FRAME | OPTIONAL_FRAME, off_origin["frame-src"]
    # no other directive grows an off-origin source (img, font, style, worker, form-action, base-uri, object-src)
    for name, sources in csp.items():
        if name in ("script-src", "connect-src", "frame-src"):
            continue
        assert not [s for s in sources if "://" in s], f"{name} gained an off-origin source: {sources}"


def test_SEC_15_SIGNIN_hosting_csp_stays_tight(repo_root: pathlib.Path) -> None:
    csp = _csp(repo_root)
    assert csp["frame-ancestors"] == ["'none'"]
    assert csp["default-src"] == ["'self'"]
    assert csp["object-src"] == ["'none'"]
    assert csp["base-uri"] == ["'none'"]
    assert csp["form-action"] == ["'self'"]
    for name, sources in csp.items():
        assert "*" not in sources, f"{name}: wildcard source"
        assert not any(s.startswith("*.") or "://*." in s for s in sources), f"{name}: wildcard host {sources}"
    flat = {s for sources in csp.values() for s in sources}
    assert "'unsafe-eval'" not in flat
    assert "'unsafe-inline'" not in csp["script-src"]
    assert "data:" not in csp["script-src"] and "blob:" not in csp["script-src"]
    assert "https:" not in flat and "http:" not in flat


def test_SEC_15_SIGNIN_the_auth_frame_source_is_the_projects_own_auth_path_over_https(repo_root: pathlib.Path) -> None:
    for source in _csp(repo_root).get("frame-src", []):
        if "firebaseapp.com" in source:
            parsed = urlparse(source)
            assert parsed.scheme == "https"
            assert parsed.netloc == f"{DEV_PROJECT}.firebaseapp.com"
            assert parsed.path == "/__/auth/", "the iframe and handler live under /__/auth/ only"


def test_SEC_15_SIGNIN_the_pinned_hosts_are_the_ones_the_installed_auth_sdk_names(repo_root: pathlib.Path) -> None:
    """If @firebase/auth is installed here, every Google API host its source names is in the CSP's connect-src or one of
    the App Check / reCAPTCHA origins already allowed, and the gapi loader is the script origin pinned above."""
    candidates = sorted(
        repo_root.glob("node_modules/.pnpm/@firebase+auth@*/node_modules/@firebase/auth/dist/esm/index-*.js")
    )
    if not candidates:
        candidates = sorted(
            repo_root.glob("apps/web/node_modules/firebase/node_modules/@firebase/auth/dist/esm/index-*.js")
        )
    if not candidates:
        import pytest  # noqa: PLC0415

        pytest.skip("@firebase/auth is not installed in this checkout; the pins were read from 12.19.0")
    source = candidates[-1].read_text(encoding="utf-8")
    hosts = set(re.findall(r'"([a-z0-9.-]+\.googleapis\.com)" /\* DefaultConfig\.(?:API_HOST|TOKEN_API_HOST)', source))
    assert hosts, "could not find the SDK's API_HOST / TOKEN_API_HOST constants"
    connect = {urlparse(s).netloc for s in SIGN_IN_CONNECT}
    assert hosts <= connect, f"the SDK calls hosts the CSP does not allow: {hosts - connect}"
    assert "https://apis.google.com/js/api.js" in source


# --- the web sign-in code ---------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_the_web_auth_code_loads_the_firebase_sdk_only_dynamically(repo_root: pathlib.Path) -> None:
    folder = repo_root / "apps" / "web" / "src" / "auth"
    sources = [p for p in folder.glob("*.ts*") if ".test." not in p.name and ".SIGNIN." not in p.name]
    assert any(p.name == "auth.ts" for p in sources), "apps/web/src/auth/auth.ts is the controller"
    assert any(p.name == "session.ts" for p in sources), "apps/web/src/auth/session.ts holds the page's one controller"
    assert any(p.name.startswith("SignInGate") for p in sources)
    static_import = re.compile(r"^\s*import\s+(?!type\b)[^;]*?\bfrom\s+[\"']firebase/", flags=re.M)
    side_effect = re.compile(r"^\s*import\s+[\"']firebase/", flags=re.M)
    for path in sources:
        text = path.read_text(encoding="utf-8")
        assert not static_import.search(text), (
            f"{path.name}: a static import of the Firebase SDK (NFR-01: use import())"
        )
        assert not side_effect.search(text), f"{path.name}: a side-effect import of the Firebase SDK"
    assert re.search(r"import\(\s*[\"']firebase/auth[\"']\s*\)", (folder / "auth.ts").read_text(encoding="utf-8"))


def test_SEC_15_SIGNIN_the_web_auth_code_never_logs_tokens_or_touches_storage_itself(repo_root: pathlib.Path) -> None:
    folder = repo_root / "apps" / "web" / "src" / "auth"
    sources = [p for p in folder.glob("*.ts*") if ".test." not in p.name and ".SIGNIN." not in p.name]
    assert sources, "apps/web/src/auth/ has no sign-in sources yet"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if re.search(r"console\.(log|info|warn|error|debug)\(", line):
                assert not re.search(r"token|idToken|credential|email|user\b", line, flags=re.I), (
                    f"{path.name}: {line.strip()}"
                )
        assert "localStorage" not in text and "sessionStorage" not in text, (
            f"{path.name}: the SDK keeps the session; the app must not copy a token into web storage"
        )
        assert not re.search(r"document\.cookie", text)
        assert not re.search(r"location\.(href|search|hash)\s*=\s*[^;]*token", text, flags=re.I)


# --- the open questions -----------------------------------------------------------------------------------------


def test_SEC_15_SIGNIN_the_choices_made_for_the_ambiguities_are_in_open_questions(repo_root: pathlib.Path) -> None:
    text = (repo_root / "docs" / "open-questions.md").read_text(encoding="utf-8")
    for number in range(1, 8):
        assert re.search(rf"^\| BQ-SIGNIN-{number} \|", text, flags=re.M), (
            f"docs/open-questions.md lacks BQ-SIGNIN-{number}"
        )
